"""Local, bounded evidence exchange with the separately distributed Studio application."""
import base64
import hashlib
import json
import os
import platform
from pathlib import Path
import tempfile

RECEIVER = "GroundSurf-Studio-Connector-Receiver.html"
DIGEST = "a459b91395de3b3c6747dc376baa5fcc90e3020a9ce7794c078438328582c9d3"
MARK = b'<meta name="groundsurf-connector" content="1"'
TERRAIN = ("manifest.json", "terrain/dem.tif", "imagery/orthophoto.tif", "metadata/preview.json",
           "metadata/provenance.json", "metadata/validation.json")
LIMIT = 64 * 1024**2


def desktop_installations():
    system = platform.system()
    if system == "Windows":
        for root in ("LOCALAPPDATA", "ProgramFiles"):
            if os.environ.get(root):
                for sub in ("GroundSurf Studio", "Programs/GroundSurf Studio"):
                    app = Path(os.environ[root]) / sub
                    yield app / "GroundSurf Studio.exe", app / "resources/app"
    elif system == "Darwin":
        for root in (Path("/Applications"), Path.home()/"Applications"):
            app = root/"GroundSurf Studio.app/Contents"
            yield app/"MacOS/GroundSurf Studio", app/"Resources/app"
    else:
        for prefix in (Path("/usr"), Path("/usr/local")):
            yield prefix/"bin/groundsurf-studio", prefix/"lib/groundsurf-studio/app"


def desktop():
    for exe, app in desktop_installations():
        try:
            if (exe.is_file() and os.access(exe, os.X_OK)
                    and MARK in (app/"dist/index.html").read_bytes()[:10000]
                    and b"'--groundsurf-transfer'" in (app/"desktop/main.cjs").read_bytes()):
                return exe
        except OSError:
            continue


def portable(paths):
    for path in paths:
        try:
            path = Path(path)
            if path.is_file() and path.stat().st_size <= 32*1024**2:
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() == DIGEST and MARK in data:
                    return data
        except OSError:
            continue


def prepare(folder, boreholes):
    from .package import validate
    root = Path(folder).resolve(strict=True)
    names = ("boreholes.geojson",) if boreholes else TERRAIN
    members = []
    total = 0
    for name in names:
        p = root/name
        if p.resolve(strict=True) != p or not p.is_file():
            raise ValueError("Transfer contains a linked or missing member.")
        size = p.stat().st_size
        total += size
        if total > LIMIT or (boreholes and size > 8*1024**2):
            raise ValueError("Transfer exceeds the automatic import limit. Use conventional import.")
        with p.open("rb") as f:
            data = f.read(size+1)
        if len(data) != size:
            raise ValueError("Evidence changed while preparing transfer.")
        if boreholes:
            obj = json.loads(data)
            if (obj.get("type") != "FeatureCollection" or not isinstance(obj.get("features"),list)
                    or not 1 <= len(obj["features"]) <= 2000):
                raise ValueError("Invalid borehole evidence collection.")
        members.append(dict(path=name,bytes=base64.b64encode(data).decode("ascii")))
    if not boreholes:
        validate(root)
    return json.dumps(dict(version=1,members=members),separators=(",",":")).encode("ascii")


def launch_file(parent, payload, html=None):
    folder = Path(tempfile.mkdtemp(dir=parent))
    p = folder / ("Studio.html" if html else "evidence.gstransfer")
    with p.open("xb") as f:
        if html:
            if html.count(b"</head>") != 1:
                raise ValueError("Unsupported browser application.")
            head, tail = html.split(b"</head>",1)
            f.write(head)
            f.write(b'<script type="application/json" id="groundsurf-local-transfer">')
            f.write(payload)
            f.write(b"</script></head>")
            f.write(tail)
        else:
            f.write(payload)
    return p


def installer_link(page, system, machine):
    """Resolve only installers explicitly linked by the official Studio landing page."""
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlsplit

    landing = "https://studio.groundsurf.net/"
    x64 = machine.lower() in ("amd64", "x86_64", "x64")
    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []

        def handle_starttag(self, tag, attrs):
            href = dict(attrs).get("href")
            if tag == "a" and href:
                self.urls.append(urljoin(landing, href))
    parser = Links()
    parser.feed(page)
    for url in parser.urls:
        u = urlsplit(url)
        if u.scheme != "https" or u.query or u.username or u.password:
            continue
        if not (u.netloc == "studio.groundsurf.net" or
                (u.netloc == "github.com" and u.path.startswith("/wtzet-eng/groundsurf-studio-web/releases/download/"))):
            continue
        name = u.path.split("/")[-1].lower()
        if system == "Windows" and x64 and "x64" in name and name.endswith(".exe"):
            return url
        if system == "Darwin" and name.endswith(".dmg") and (
            "universal" in name or machine.lower() in name):
            return url
        if system == "Linux" and x64:
            if Path("/etc/debian_version").exists() and name.endswith("_amd64.deb"):
                return url
            if name.endswith("x86_64.appimage"):
                return url
    return None

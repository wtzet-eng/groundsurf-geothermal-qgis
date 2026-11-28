import base64
import hashlib
import json
import math
import struct
import tempfile
from pathlib import Path

import numpy as np
from osgeo import gdal

from .raster import check, describe, metric, open_tif, prepare

FILES = {
    "terrain": "terrain/dem.tif",
    "imagery": "imagery/orthophoto.tif",
    "provenance": "metadata/provenance.json",
    "validation": "metadata/validation.json",
    "preview": "metadata/preview.json",
}
VERSION = "groundsurf-transfer/0.1"


def dump(path, obj):
    path.write_text(
        json.dumps(obj, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8"
    )


def digest(path, cancel=lambda: False):
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            check(cancel)
            sha.update(block)
    return sha.hexdigest()


def read_json(path, limit):
    if path.stat().st_size > limit:
        raise ValueError(f"{path.name} exceeds allowed size.")
    return json.loads(path.read_text(encoding="utf-8"))


def fixed_file(root, rel):
    path = root / rel
    if path.resolve() != root / rel or not path.is_file():
        raise ValueError(f"Missing or linked package member: {rel}")
    return path


def grid_match(dem, rgb):
    a, b = describe(dem), describe(rgb)
    if (
        a["dimensions"] != b["dimensions"]
        or a["geoTransform"] != b["geoTransform"]
        or not dem.GetSpatialRef().IsSame(rgb.GetSpatialRef())
    ):
        raise ValueError("Terrain and imagery must share the exact grid. Use Align rasters.")
    gt = a["geoTransform"]
    metric(a["crsWkt"])
    if gt[1] <= 0 or gt[5] >= 0 or gt[2] or gt[4]:
        raise ValueError("A north-up metric grid is required.")
    if dem.RasterCount != 1 or rgb.RasterCount not in (3, 4):
        raise ValueError("Expected one elevation band and RGB or RGBA imagery.")
    if dem.GetRasterBand(1).DataType == gdal.GDT_Byte or dem.GetRasterBand(1).GetColorTable():
        raise ValueError("Colour indices cannot be elevation.")
    if any(rgb.GetRasterBand(i).DataType != gdal.GDT_Byte for i in range(1, rgb.RasterCount + 1)):
        raise ValueError("Prepare imagery as 8-bit RGB.")
    if dem.GetRasterBand(1).GetUnitType().lower() not in ("m", "metre", "meter"):
        raise ValueError("Prepare terrain and confirm its elevation units.")
    if min(a["dimensions"]) < 2 or math.prod(a["dimensions"]) > 16000000:
        raise ValueError("Unsupported grid size.")


def frame(ds):
    x, dx, _, y, _, dy = ds.GetGeoTransform()
    X, Y = x + dx * ds.RasterXSize, y + dy * ds.RasterYSize
    return dict(
        extent=[x, Y, X, y],
        origin=[(x + X) / 2, (y + Y) / 2, 0],
        convention="local = projected XYZ minus origin; east,north,up",
        units="m",
    )


def make_preview(root, dem, rgb):
    w, h = dem.RasterXSize, dem.RasterYSize
    k = min(1, 160 / max(w, h))
    nx, ny = max(2, round(w * k)), max(2, round(h * k))
    band = dem.GetRasterBand(1)
    z = band.ReadAsArray(buf_xsize=nx, buf_ysize=ny).astype(float)
    valid = np.isfinite(z) & (band.GetMaskBand().ReadAsArray(buf_xsize=nx, buf_ysize=ny) != 0)
    if not valid.any():
        raise ValueError("No terrain samples in preview. Choose a smaller area.")
    k = min(1, 900 / max(w, h))
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "texture.png"
        tex = gdal.Translate(
            str(img),
            rgb,
            format="PNG",
            width=max(1, round(w * k)),
            height=max(1, round(h * k)),
            resampleAlg="bilinear",
        )
        if not tex:
            raise ValueError("Could not encode aerial texture.")
        tex = None
        texture = base64.b64encode(img.read_bytes()).decode("ascii")
    gt = dem.GetGeoTransform()
    # GDAL nearest reads the pixel under each target cell centre.
    xs = (np.floor((np.arange(nx) + 0.5) * w / nx) + 0.5) / w
    ys = (np.floor((np.arange(ny) + 0.5) * h / ny) + 0.5) / h
    return dict(
        nx=nx,
        ny=ny,
        width=w * gt[1],
        height=-h * gt[5],
        u=xs.tolist(),
        v=ys.tolist(),
        z=[float(v) if ok else None for v, ok in zip(z.flat, valid.flat)],
        texture=texture,
    )


def validate_preview(data, spatial):
    nx, ny = data["nx"], data["ny"]
    if not all(type(v) is int and 2 <= v <= 160 for v in (nx, ny)):
        raise ValueError("Invalid preview dimensions.")
    x, y, X, Y = spatial["extent"]
    if abs(data["width"] - (X - x)) > 1e-6 or abs(data["height"] - (Y - y)) > 1e-6:
        raise ValueError("Preview extent conflicts with terrain.")
    for name, n in (("u", nx), ("v", ny)):
        axis = data[name]
        if (
            len(axis) != n
            or not all(0 <= v <= 1 for v in axis)
            or any(a >= b for a, b in zip(axis, axis[1:]))
        ):
            raise ValueError("Invalid preview sampling positions.")
    z = data["z"]
    if (
        len(z) != nx * ny
        or not any(v is not None for v in z)
        or not all(v is None or (type(v) in (float, int) and math.isfinite(v)) for v in z)
    ):
        raise ValueError("Invalid preview elevations.")
    image = base64.b64decode(data["texture"], validate=True)
    if (
        image[:16] != bytes.fromhex("89504e470d0a1a0a0000000d49484452")
        or len(image) < 24
        or not all(0 < d <= 900 for d in struct.unpack(">II", image[16:24]))
    ):
        raise ValueError("Invalid preview texture.")


def validate(folder, cancel=lambda: False):
    root = Path(folder).resolve()
    m = read_json(fixed_file(root, "manifest.json"), 256000)
    if m.get("schema") != VERSION or set(m.get("files", {})) != set(FILES):
        raise ValueError("Unknown format or missing dataset.")
    for key, rel in FILES.items():
        rec = m["files"][key]
        path = fixed_file(root, rel)
        if (
            rec["path"] != rel
            or path.stat().st_size != rec["bytes"]
            or rec["bytes"] > 256 * 1024**2
        ):
            raise ValueError(f"Invalid path or size for {key}.")
        if digest(path, cancel) != rec["sha256"]:
            raise ValueError(f"Checksum mismatch: {rel}")
    dem, rgb = [open_tif(root / FILES[k]) for k in ("terrain", "imagery")]
    grid_match(dem, rgb)
    if m["frame"] != frame(dem) or m["terrainRole"] not in ("DTM", "DSM", "DEM"):
        raise ValueError("Invalid spatial frame or terrain role.")
    if m["grid"] != describe(dem) or m["imageGrid"] != describe(rgb):
        raise ValueError("Manifest conflicts with embedded GeoTIFF metadata.")
    if not isinstance(m.get("verticalDatum"), str) or not m["verticalDatum"].strip():
        raise ValueError("Missing vertical reference declaration.")
    validate_preview(read_json(root / FILES["preview"], 8 * 1024**2), m["frame"])
    audit = read_json(root / FILES["validation"], 64000)
    if audit.get("sameGrid") is not True or audit.get("metric") is not True:
        raise ValueError("Package grid validation was incomplete.")
    if not str(m.get("rights", "")).strip():
        raise ValueError("Source rights declaration is missing.")
    return m


def create_package(
    destination,
    dem_paths,
    rgb_paths,
    bounds,
    crs,
    step,
    role,
    datum,
    rights,
    history,
    cancel=lambda: False,
    progress=lambda p: None,
    cutline=None,
    bands=None,
):
    dest = Path(destination).absolute()
    if dest.exists() or not dest.parent.is_dir():
        raise ValueError("Choose a new package directory in an existing folder.")
    if not rights.strip() or not datum.strip():
        raise ValueError("Enter source rights and vertical datum, or explicitly enter unknown.")
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        root = Path(tmp) / "transfer"
        for sub in ("terrain", "imagery", "metadata"):
            (root / sub).mkdir(parents=True)
        provenance = {}
        for j, (key, paths, kind) in enumerate(
            [("terrain", dem_paths, role), ("imagery", rgb_paths, "imagery")]
        ):
            provenance[key] = prepare(
                paths,
                root / FILES[key],
                kind,
                bounds,
                crs,
                step,
                cancel,
                lambda p: progress(j * 35 + p * 0.35),
                cutline,
                bands,
            )
        dem, rgb = [open_tif(root / FILES[k]) for k in ("terrain", "imagery")]
        grid_match(dem, rgb)
        m = dict(
            schema=VERSION,
            terrainRole=role,
            verticalDatum=datum,
            elevationUnits="m",
            rights=rights,
            frame=frame(dem),
            grid=describe(dem),
            imageGrid=describe(rgb),
            files={},
        )
        warnings = (
            ["Vertical datum unknown. Review before comparing borehole elevations."]
            if datum.lower() == "unknown"
            else []
        )
        dump(root / FILES["validation"], dict(warnings=warnings, sameGrid=True, metric=True))
        dump(
            root / FILES["provenance"],
            dict(inputs=provenance, process=history, gdal=gdal.VersionInfo("--version")),
        )
        dump(root / FILES["preview"], make_preview(root, dem, rgb))
        dem = rgb = None
        for key, rel in FILES.items():
            path = root / rel
            m["files"][key] = dict(path=rel, bytes=path.stat().st_size, sha256=digest(path, cancel))
        dump(root / "manifest.json", m)
        validate(root, cancel)
        write_view(root, root / "preview.html")
        check(cancel)
        if dest.exists():
            raise ValueError("Package destination already exists.")
        root.rename(dest)
        progress(100)
    return m


def write_view(root, target):
    """Render trusted local code with a base64-encoded data envelope."""
    root, target = Path(root), Path(target)
    m = validate(root)
    data = read_json(root / FILES["preview"], 8 * 1024**2)
    data.update(
        rights=m["rights"], datum=m["verticalDatum"], role=m["terrainRole"], frame=m["frame"]
    )
    template = Path(__file__).with_name("viewer.html").read_text(encoding="utf-8")
    payload = base64.b64encode(json.dumps(data, allow_nan=False).encode()).decode("ascii")
    with target.open("x", encoding="utf-8") as f:
        f.write(template.replace("__PAYLOAD__", payload))
    return str(target)

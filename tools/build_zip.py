"""Build QGIS install-from-ZIP package. No dependency downloads."""
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
folder = root / "groundsurf_geothermal"
output = root / "GroundSurf-Studio-Connector-0.6.0-dev.zip"
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for path in sorted(folder.rglob("*")):
        if (not path.is_file() or "__pycache__" in path.parts
                or "web_studio" in path.parts
                or path.suffix in (".pyc", ".zip")):
            continue
        z.write(path, Path("groundsurf_geothermal") / path.relative_to(folder))
print(output)

"""Local-only QGIS browser edition ZIP. Do not publish without licence review."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

parser = argparse.ArgumentParser()
parser.add_argument('--studio-dist', required=True, type=Path,
                    help='Local static Vite build from the GroundSurf Studio source.')
a=parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = a.studio_dist.resolve()
dest = root / 'groundsurf_geothermal' / 'web_studio'
if not (source/'index.html').is_file():
    raise SystemExit('Missing prebuilt Studio static interface; run npm run build first.')
if source != dest.resolve():
    dest.mkdir(exist_ok=True)
    for filename in source.rglob('*'):
        if filename.is_file():
            target=dest / filename.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(filename.read_bytes())
assert (dest/'index.html').is_file()
out = root / 'Studio-by-GroundSurf-Browser-0.4.15-EXPERIMENTAL.zip'
with ZipFile(out,'w',ZIP_DEFLATED) as archive:
    for file in sorted((root/'groundsurf_geothermal').rglob('*')):
        if (file.is_file() and not file.is_symlink() and
                '__pycache__' not in file.parts and
                file.suffix not in ('.pyc','.zip')):
            archive.write(file, 'groundsurf_geothermal/' +
                          file.relative_to(root/'groundsurf_geothermal').as_posix())
with ZipFile(out) as archive:
    assert archive.testzip() is None
    names=set(archive.namelist())
    assert 'groundsurf_geothermal/metadata.txt' in names
    assert 'groundsurf_geothermal/LICENSE' in names
    assert 'groundsurf_geothermal/web_studio/index.html' in names
    assert any(name.endswith('.js') for name in names)
print('Experimental QGIS/browser ZIP:',out,'bytes:',out.stat().st_size)

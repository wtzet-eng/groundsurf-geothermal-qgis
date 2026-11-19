# GroundSurf Geothermal 0.4.5 — Clearer QGIS coordinate-system errors

Experimental QGIS 3.34–3.x maintenance release • 2026-11-19

## Fixed: “QGIS feature 2: latitude must be <= 90”

The QGIS grouped borehole importer could report a generic validation
error when source point geometry was incorrectly labelled as latitude
and longitude. The importer now explains the likely cause with an
actionable message showing the actual QGIS layer name, declared CRS,
feature ID and raw X/Y geometry coordinates.

Both **regular well copy** and **grouped interval import** use the same
new coordinate validation function, keeping their behaviour consistent.

### Example

A point geometry with `X=450000, Y=5800000` declared as geographic
`EPSG:4326` is invalid: latitude cannot exceed ±90 degrees. Such
numbers may instead be projected coordinates in metres.

Rather than guess the source CRS, silently swap coordinates or modify
input files, GroundSurf stops before writing anything and advises users
to inspect **QGIS layer Properties → Information → CRS**, verify the
geometry X/Y, assign the actual source *layer* CRS and retry.

Coordinates can also be stored in the wrong X/Y order. The importer
shows a specific suggestion when the numeric ranges make this plausible.

For layers correctly declared in a projected CRS, GroundSurf continues
to transform point geometry to EPSG:4326 automatically.

## Scope and tests

- New QGIS regression test: projected metre coordinates incorrectly
  tagged as EPSG:4326 cause a clear error and no import.
- Grouped and standard well import use identical checks.
- Correct EPSG:3857 projected geometries still import accurately.
- An example of apparently swapped coordinates produces a distinct hint.
- No source geometry or QGIS layer metadata is ever changed.
- Original Python and QGIS regression suites retained.

**This is a diagnostic and safety improvement, not automatic CRS
inference.** If the source reference system is unknown, it must be
identified from survey records or original GIS metadata before
using borehole coordinates for geological modelling.

Existing QGIS layer import, well grouping, lithological logs,
groundwater/temperature measurements, geological sections, preliminary
3D modelling, ParaView export and dark/light themes remain available.

## Feedback

Email: **tzuk.ls@outlook.com**
Videos: https://www.youtube.com/@Ground-Surf

GPL source: https://github.com/wtzet-eng/groundsurf-geothermal-qgis

The official QGIS repository security, code-quality and Qt6 static
scans must be run after uploading the new ZIP.

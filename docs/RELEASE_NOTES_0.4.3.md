# GroundSurf Geothermal 0.4.3 — Flake8 E731 cleanup

Experimental QGIS maintenance release · November 2026

## Corrected
The QGIS Plugin Repository code-quality report identified two Flake8 **E731**
warnings in `groundsurf_geothermal/section_canvas.py`, previously at lines
82 and 83. The assigned lambda functions used for horizontal and vertical
cross-section plot coordinates are now ordinary local `def` functions.

This is a **non-functional style correction**. Cross-section geometry,
dark/light presentation, geological well records, 3D modelling and the new
**Import from QGIS** workflow from 0.4.2 remain unchanged.

The plugin version and generated model manifest version were updated to
`0.4.3` to permit submission as a new QGIS repository version.

## Checks
- Python AST check confirms no lambda assignments remain in
  `section_canvas.py`.
- The original Python unit tests and QGIS integration smoke tests are
  retained, including direct point-well import and GeoPackage/GeoTIFF links.
- Official QGIS Flake8, security and Qt6 static scanners must still be run
  on the uploaded 0.4.3 ZIP. QGIS 4 runtime remains untested.

## Contact

Feedback: **tzuk.ls@outlook.com**
Video demonstrations: https://www.youtube.com/@Ground-Surf

Public GPL source:
https://github.com/wtzet-eng/groundsurf-geothermal-qgis

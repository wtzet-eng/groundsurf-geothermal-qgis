# GroundSurf Geothermal 0.4.7 — Local XYZ geology without a known map CRS

Experimental QGIS 3.34–3.x plugin • Free local data and ParaView export

## User problem addressed

A QGIS `BH_logs` layer uses `ID/X/Y/Z/Strata` records with metre-like
XY coordinate values, but the layer declares EPSG:4326 (degrees). The
georeferenced importer correctly refuses to assign impossible geographic
locations. This is not a limitation of ParaView, which accepts ordinary
Cartesian XYZ scene coordinates without a GIS CRS.

## New: Unlocated engineering XYZ import

**Import from QGIS → Import local XYZ metres (NO map CRS; usable in ParaView)**

- Reads original point geometry XY or attribute X/Y, and Z from attribute
  or true 3D PointZ geometry.
- Requires the user to explicitly confirm that all X, Y and Z values
  use **metres in one common local coordinate system**. GroundSurf
  cannot verify that unit assumption automatically.
- Preserves raw X/Y/Z, borehole IDs and source unit labels in a **separate
  GeoPackage local-XYZ contact store**, grouped by dataset and borehole.
- Shows the observations in the new **Local XYZ** dock tab.
- Keeps the original QGIS layer intact; never invents WGS84 coordinates
  or assigns a false EPSG value to a geological contact.
- Auto-suggests local XYZ when a QGIS layer claims a geographic CRS but
  contains impossible coordinate values.
- Flags repeated/conflicting horizons (such as a duplicated Cretaceous Z
  at one well); raw observations are preserved.

## New: Local XYZ → ParaView 3D

Under **3D Models**, choose
**LOCAL XYZ (metres, NO geographic CRS) → ParaView**.

The local model is built from common, unambiguous contact elevations
within the input-well footprint. Each input X/Y is translated using
a shared recorded local origin to keep scene numbers small:

`X_scene = X_source - X_origin`,
`Y_scene = Y_source - Y_origin`,
`Z_scene = Z_source`.

The original coordinates and origin are saved in `model.json`,
which contains `georeferenced: false` and a local-coordinate label.
This does not turn the local data into geographic points.

Unspecified vertical datum may be used for **conceptual local
visualisation**, but it is flagged as unverified and cannot be treated
as a national-height elevation or combined with independently located
GIS constraints without further evidence.

### Critical projection distinction

The XY values may be metres in a known projection or a private local
engineering frame. A **coordinate translation** preserves local
coordinate differences but does not determine the original map CRS or
correct projection scale. In particular, if the original X/Y were Web
Mercator, the numeric coordinate differences can differ from real
ground distances significantly.

For geographically located borehole reporting and overlays, use the
existing **source CRS picker** in the PointZ/contacts import mode, after
the actual source CRS has been independently identified.

## Verification

- 20 Python database, geology and numerical tests retained.
- Previous QGIS 3.34/Qt5 smoke tests retained.
- New synthetic 50-record QGIS `PointZ` layer incorrectly declaring
  EPSG:4326 imports to 10 local boreholes/50 contact observations,
  without registering false WGS84 well points.
- Existing QGIS layer and geometry remain unchanged.
- Local contact table survives project reload; conceptual 3D model
  excludes conflicting horizon labels.
- Real 3D Model UI produces a ParaView VTK multiblock scene, registers
  the model in GroundSurf and saves the reversible local XY origin in
  `model.json`.
- All tests use fabricated XY/Z values, not private user records.

Official QGIS Plugin Repository security, quality and Qt6 scans must be
run after upload. QGIS 4 runtime has not been tested.

Feedback: tzuk.ls@outlook.com
GroundSurf demos: https://www.youtube.com/@Ground-Surf

GPL-2.0-or-later QGIS plugin source:
https://github.com/wtzet-eng/groundsurf-geothermal-qgis

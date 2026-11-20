# GroundSurf Geothermal 0.4.11 — clearer QGIS import and geological ParaView styling

Experimental offline QGIS 3.34–3.x plugin • 20 November 2026

## More readable QGIS import

Following user feedback about the small import mapping dialog:

- Resizable dialog with a wider default, fitted to available screen space.
- Mapping controls have a scrollable region; **Preview / OK / Cancel remain accessible** even on small screens.
- Shorter operation notes and no unused CRS field label in local-metre mode.
- Mapping/preview errors are displayed in the dialog as well as the error message box.
- Local XYZ confirmation is concise but still explains assumed metre units,
  no geographic CRS, and warns of ambiguous repeated formation contacts.
- **Separate batches are counted separately** in the Project Explorer and
  project status. Two imports each containing ten BH IDs are not presented as
  twenty unique boreholes. Original GeoPackage records remain untouched.

## GroundSurf geological studio look for ParaView

**3D Models → Scene look…** allows a new model to have:

- Default muted geological unit colours, or an optional vivid,
  high-contrast palette; formation names stay consistent across runs.
- Always **#212121** charcoal background with soft, matte surfaces.
- Optional **formation boundary outlines** using ParaView's
  ExtractSurface/FeatureEdges, avoiding the near-black dense per-facet
  wireframe appearance.
- Optional XYZ orientation triad (on by default), and labelled local
  XYZ axes/bounds box (off by default). This is not a geographic grid.
- Existing independent geological unit visibility, source borehole
  contact markers and adjustable display-only vertical exaggeration.

The model's `appearance.json` records the palette and individual
`bands[].color` HEX values. Users can edit unit colours manually
and reload `view_in_paraview.py` without changing model geometry.
The original `model.vtm` opens as before, and the script launched
through **Open in ParaView** prepares the new appearance.

The visual language uses common geological modelling conventions,
not proprietary software skins, icons or copied artwork.

## Scientific and compatibility limits

- Existing coordinates, formation interpretations, vertical datums,
  IDW interpolation, original QGIS layers and output VTK files remain
  unchanged. No new georeferencing is claimed.
- Local XYZ batches stay separate: the same ID may appear in multiple
  imports, but independent batches are not merged automatically.
- Data coverage distance is **not a validated confidence or
  geostatistical uncertainty estimate**.
- Borehole vertical sticks are schematic source constraints, not
  surveyed deviated trajectories.
- Conceptual model only: no calibrated geothermal, groundwater or
  structural simulation.

## Verification

- QGIS 3.34/Qt5 offscreen test checks small-screen import sizing and
  field-scroll accessibility, fixed Preview/OK controls, field mapping,
  palette persistence, clean dark background, and no changes to Z.
- ParaView 6.2.0 `pvpython` executed and rendered a synthetic model
  with high-contrast geological colours, formation boundary outlines,
  optional XYZ orientation and labelled source-coordinate bounds.
- Existing well/PointZ/CRS/grouped import tests, 3D model and scene
  generation tests, static scanning and ZIP integrity run for release.
- Official QGIS repository static security/style/Qt6 scans and
  QGIS 4 runtime remain separate pending checks.

Feedback: tzuk.ls@outlook.com
Source and installation ZIP:
https://github.com/wtzet-eng/groundsurf-geothermal-qgis

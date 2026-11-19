# GroundSurf Geothermal 0.4.0 — Preliminary 3D Developer Preview

An experimental **local-first QGIS plugin** for managing wells, map layers and a
versioned geological project database. Version 0.4 adds a **preliminary 3D
interpolation engine** for shared geological contacts. It is not a validated
geothermal simulator or professional structural modelling replacement.

## What works in 0.4

- Create/open a local **GeoPackage (.gpkg)** project.
- Store well point geometries (EPSG:4326 WGS84), depths and elevations.
- Import wells from CSV, or add wells from a dialog.
- Display wells and add local raster/vector map layers to QGIS.
- Keep local map-file references in the project database.
- Project explorer, wells list, map list and well details; click a well to zoom.
- Dark (#212121, green accents) / light appearance, remembered across sessions.
- Well Manager for geological formations, lithological intervals,
  observed/interpreted formation tops, and dated hydrothermal measurements.
- All-depth well log CSV import; duplicate/overlap checks and atomic writes.
- Local map inventory, relative paths, missing-source detection and relinking.
- Explicit v0.1-to-v0.2 database migration with a full SQLite backup.
- Saved geological section lines and corridor selection, using local metre CRS.
- Automatic section from wells or a selected QGIS polyline feature.
- Well log cross-section viewer with labelled tentative correlations.
- Editable section-only formation contact interpretations, separate from well data.
- Cross-section PNG export and map preview of the section trace.
- **Help & feedback:** tzuk.ls@outlook.com, YouTube @Ground-Surf.
- Preliminary local **3D geological contact surfaces** from common wells.
- Triangulated IDW horizon geometry and wedge-shaped rock volumes,
  clipped to input-well triangulation (no extrapolation).
- Versioned local 3D model catalogue with VTK/ParaView scene exports,
  manifest, provenance, vertical datum and reproducibility hash.
- No remote service, account, uploaded site data or GitHub runtime required.

## Important data conventions

- Imported well point coordinates must be WGS84 longitude and latitude
  in degrees. QGIS can reproject the layer for display.
- `total_depth_m` is **metres below ground**, positive downward.
- `ground_elev_m` is in **metres**, using the datum that the **user must state**
  in `vertical_datum`. Do not mix elevations from different vertical datums.
- Storing a measurement is not the same as calculating groundwater head.
  Future analysis must distinguish elevations, depths and measurement dates.
- Faulted geology, heat-flow and groundwater simulations are **not**
  present in 0.4. Preliminary 3D surfaces are inferred, not observed. Do not make engineering decisions based on this preview.

## Install in QGIS 3.34+

1. Download/clone this repository and copy `groundsurf_geothermal` into
   your QGIS profile `python/plugins` directory, or use the generated ZIP
   from the release preparation command below.
2. In QGIS, open **Plugins > Manage and Install Plugins** and enable
   **GroundSurf Geothermal**.
3. Click **GroundSurf Geothermal** in the toolbar or Plugins menu.
4. Click **New project**, choose a fresh `.gpkg` filename.
5. Add wells or import the sample CSV from `examples/sample_wells.csv`.
6. Under **Well log**, create formation codes (e.g. Q, C, B).
7. Add lithological intervals manually or import `examples/sample_intervals.csv`.
8. Under **Formation tops**, mark observed or interpreted contacts.
9. Under **Measurements**, record water-level, head, pressure and temperature readings.
10. In **Cross-sections**, click **Auto from wells** or select one line feature
    on a QGIS line layer and click **Selected QGIS line**. Give it a name and
    choose the perpendicular corridor width in metres.
11. Click **Open cross-section** to see the schematic log panel. Use
    **Add / edit interpreted contact** to adjust a *section-only* tie point;
    **Export PNG** to save an image. The original well log is unchanged.
12. Click **Show section line on QGIS map** to preview the section trace.
13. Add local maps; select a map row then **Relink map** if needed.
14. Open **3D Models → Build model**, give it a name and choose the
    surface subdivisions (default: 10). Confirm the well count, common
    horizons, projection and vertical datum. Select a local output folder.
15. Select the saved model and click **Open in ParaView** (if installed)
    or **Open selected model folder**. Read `model.json` before interpreting.
16. Save the QGIS .qgz project separately to preserve map layout and styles.

The GeoPackage is the source of truth for wells and the app tables. External
map layers are referenced by relative path when possible, with an absolute
fallback; use Relink map when the source is no longer available.

### CSV columns

Mandatory: `well_id,name,latitude,longitude`

Optional: `total_depth_m,ground_elev_m,vertical_datum,source,notes`

Duplicate well IDs and invalid coordinates are rejected. Maximum 10,000 wells
per import. The test data are synthetic for software testing only.

### Lithology CSV columns

Mandatory: `well_id,formation_code,top_depth_m,base_depth_m`

Optional: `description`. Define the referenced formation codes first.
Depths are metres below ground (positive down). Intervals must not overlap
within the same well. The entire CSV is rejected if any row is invalid.

### Measurements

Store a dated ISO 8601 timestamp with explicit UTC offset and select:

- `water_depth_bgl_m`: depth to water, m below ground.
- `water_head_elev_m`: water level as elevation, m; vertical datum required.
- `temperature_c`: temperature in degrees Celsius at an explicit depth.
- `pressure_kpa`: pressure in kPa, with explicit absolute/gauge basis.

Source names, measurement depth and interpretation basis remain distinct.
Do not infer groundwater head from total well depth.

### Migrating existing projects

Opening an old project prompts for a one-time upgrade. A `.backup-v1-*`
SQLite copy is saved beside the original GeoPackage *before* the v1-to-v2
upgrade. When older v0.2 projects gain the new sections module, another
backup is saved before installing its additive tables. Keep these backups
until the upgraded project is checked.

### Cross-section safeguards

- Section lines are stored as WGS84 coordinate lists and measured in a
  **local UTM coordinate system** when displayed. Initial sections must be
  within one suitable UTM area, shorter than 100 km, with up to 80 logged
  wells intersecting the selected corridor.
- Elevation-based correlations require that all plotted wells have
  ground-level elevations in the same explicitly labelled vertical datum.
  Inconsistent or missing datums switch to depth-below-ground display and
  **disable correlations**.
- Coloured lithology bars represent input log intervals, not interpolated
  3D geology. Dashed lines join only *adjacent* wells sharing formation
  contacts and are labelled as tentative interpretations.
- Section-only interpreted contact depths may be replaced or removed.
  Source borehole logs and formation-top tables are not altered by edits.
- A section is a cross-sectional **diagram**, not terrain measured between
  wells, and vertical/horizontal plot scales differ.

### Preliminary 3D modelling

The modelling prototype works **offline** and uses only Python's standard
library and QGIS. It does not import GemPy, PyVista, SciPy or ParaView.
ParaView is an *optional independent viewer* for exported `model.vtm`.

A model needs **three or more non-collinear wells** with ground elevations
in a **single explicitly labelled vertical datum** and at least one
shared formation contact below local ground level. The tool recognises
formation tops and lithological interval tops in the local database.

At each well, the tool honours the supplied contact elevations. Between
wells it uses inverse-distance weighting (power 2) and a subdivided
Delaunay mesh. **This is preliminary interpolation**, not geological
structural interpretation, geostatistical uncertainty quantification or
geothermal reservoir simulation.

- Surface meshes are `surface-*.vtp` files; volumes between consecutive
  horizons are VTK triangular wedges in `unit-*.vtu`.
- The scene index is `model.vtm`; modelling inputs, warnings and output
  filenames are in `model.json`.
- Output coordinates use a local metre-based UTM CRS (`EPSG:326xx` or
  `EPSG:327xx`), with user-supplied ground elevations as the Z coordinate.
- No extrapolation is performed beyond the input well triangulation.
- If well datums conflict, the tool refuses the 3D model.
- Incomplete wells may be excluded **with an explicit warning**. Only
  contacts shared by the included wells are modelled.
- A layer's modelled thickness must be positive at every contributing well.
- Model spans are limited to 50 km in this experimental release, at most
  150 contributing wells and 80,000 mesh cells.
- These early surfaces do not honour faults, folds, deviated wells or
  geological surfaces from seismic interpretations. Do not use them
  as checked engineering or reservoir models.

The basic **QGIS plugin code** is GPL-2.0-or-later and publicly reviewable at
https://github.com/wtzet-eng/groundsurf-geothermal-qgis. Experimental
future modelling research can remain separate and private. The software
uploads no geological project data.

### Feedback and demonstrations

Your suggestions are welcome. Contact the GroundSurf project directly:

- **Feedback email:** [tzuk.ls@outlook.com](mailto:tzuk.ls@outlook.com)
- **YouTube:** [GroundSurf — tutorials and demonstrations](https://www.youtube.com/@Ground-Surf)

The QGIS plugin includes buttons for both under **Help & feedback**. Neither
link opens automatically, and no geological project data is transferred.

## Check the code

No internet access or Python downloads are needed for these tests:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q groundsurf_geothermal
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_qgis.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_v02.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_v03.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_v04.py
python3 tools/build_zip.py
```

The source uses Python standard library, QGIS 3 and Qt as shipped with QGIS.
QGIS runtime compatibility beyond the tested installation is not guaranteed.

## Architecture

- `groundsurf_geothermal/plugin.py` — UI and QGIS actions only.
- `groundsurf_geothermal/db.py` — schema and CSV/input validation (pure Python).
- `groundsurf_geothermal/storage.py` — QGIS well geometry storage.
- `groundsurf_geothermal/well_manager.py` — well-log, tops and observation UI.
- `groundsurf_geothermal/sections.py` — saved sections and interpreted contacts.
- `groundsurf_geothermal/section_math.py` — pure metric geometry calculations.
- `groundsurf_geothermal/section_geo.py` — QGIS CRS and well projection.
- `groundsurf_geothermal/section_canvas.py` — original QPainter diagram.
- `groundsurf_geothermal/section_ui.py` — section and contact editor.
- `groundsurf_geothermal/model_core.py` — original NumPy-free numerical kernel.
- `groundsurf_geothermal/model_adapter.py` — QGIS well and CRS validation.
- `groundsurf_geothermal/models.py` — local model catalogue and backup.
- `groundsurf_geothermal/model_ui.py` — 3D modelling UI and ParaView launch.
- `docs/ARCHITECTURE.md` — extensible module boundaries.

**Local geological data and large files do not belong in GitHub.** Keep
GeoPackages, real wells, seismic SEG-Y, grids and simulator results off Git.
The .gitignore deliberately excludes them.

## Licensing and distribution

The **QGIS plugin** is GPL-2.0-or-later, with full licence text in its folder.
A separate standalone modelling engine could have a different licence subject
to legal compatibility review. This repository may be kept private during
development; publication through the official QGIS plugin catalogue requires
publicly accessible source and other review conditions.

Copyright 2026 GroundSurf contributors. Experimental, no warranty.

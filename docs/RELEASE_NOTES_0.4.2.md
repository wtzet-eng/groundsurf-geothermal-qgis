# GroundSurf Geothermal 0.4.2 — Import from open QGIS projects

Experimental QGIS 3.34–3.x release • Native QGIS tools, local-first

## Main improvement

The new **Import from QGIS** button reads the existing layer tree.

### Copy existing point wells into GroundSurf

- Choose any open QGIS point layer, including memory layers.
- Optionally import selected features only.
- Automatically suggest field mappings for Well ID, name, total depth,
  ground elevation, vertical datum, data source and notes.
- Review or change the mapping in the dialog.
- Coordinates come from **point geometry**. QGIS transforms the points
  from the source CRS to EPSG:4326; no manual X/Y columns are needed.
- A missing name defaults to the Well ID. A Well ID field is required.
- Depth and elevation values are assumed to be **metres** and are not
  automatically converted between unit systems or elevation datums.
- All records are validated before writing. Duplicate IDs, missing CRS,
  invalid geometries or bad values abort the batch without partially
  importing it.
- Original QGIS features and source files remain untouched.
- Copied wells become available to the existing well-log, cross-section
  and preliminary 3D modelling workflows.

### Link existing maps without duplicating layers

- Choose an open file-based vector or raster source in QGIS.
- Supported persistent sources: GeoPackage, shapefile, GeoJSON and GeoTIFF.
- Register a relative/absolute file reference in the GroundSurf GeoPackage,
  without loading a second copy or changing the original QGIS style.
- When reopening a GroundSurf project, reuse the already-open QGIS map
  layer if its file and GeoPackage sublayer match.
- Memory layers, WMS/WFS or other network map services are **not yet
  persistently linked**. Export them to a supported local format.
- Linked maps are reference layers, **not automatically geological
  modelling constraints**. Structural interpretation tools are later work.

## Tested

- A QGIS memory well layer in EPSG:3857 was imported as WGS84 wells using
  non-standard names (BH_ID, WellName, Depth, RL, Datum).
- Import selected-only and full feature sets, with duplicate batch rollback.
- Source QGIS feature geometries remained unchanged.
- Directly imported wells drove a valid preliminary 3D geological model.
- Already-open GeoPackage line and GeoTIFF raster layers linked without
  duplication; their QGIS identities survived reloading GroundSurf.
- Existing QGIS 3.34/Qt5 smoke tests and Python unit tests retained.
- The Qt6 enum and Bandit source-pattern corrections from version 0.4.1
  are preserved. Official QGIS security and Qt6 scanning is still required.

## Unchanged limitation

GroundSurf Geothermal is an experimental, preliminary geology workbench.
The IDW 3D interpolator is not a calibrated geological/geothermal solver,
and current links to fault maps are not automatic fault geometry inputs.

## Support

Feedback: **tzuk.ls@outlook.com**
Video demonstrations: **https://www.youtube.com/@Ground-Surf**

Public QGIS plugin source (GPL-2.0-or-later):
https://github.com/wtzet-eng/groundsurf-geothermal-qgis

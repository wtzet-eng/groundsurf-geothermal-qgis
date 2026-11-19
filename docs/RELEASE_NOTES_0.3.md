# GroundSurf Geothermal 0.3.0 — Cross-Sections developer preview

## New in 0.3

- Create a saved geological cross-section automatically from imported wells,
  or from **one selected QGIS line feature**.
- Use a local UTM projection to calculate well chainage and perpendicular
  offsets; choose the width of the well-selection corridor.
- Display coloured well intervals and formation tops in a resizable, separate
  2D cross-section window.
- Draw **dashed correlation hypotheses** only where neighbouring wells have
  matching formation contacts and share the same explicit vertical datum.
- Create or revise **section-specific interpreted formation contacts**.
  Original well logs and source formation tops are not changed.
- Export a 1800 × 950 PNG section diagram and show the section trace on the
  QGIS map as a removable, transient preview layer.
- Save sections and interpretations inside the local project GeoPackage.
  Existing 0.2 project databases receive a one-time additive schema upgrade,
  automatically backed up before writing.
- The original dark (#212121) and light themes remain.
- **Help & feedback** is now part of the plugin:
  - **Email:** tzuk.ls@outlook.com
  - **YouTube tutorials and demonstrations:**
    https://www.youtube.com/@Ground-Surf

## How to try

1. Install the `GroundSurf-Geothermal-0.3.0.zip` through QGIS Plugin Manager.
2. Create a new local GeoPackage project.
3. Import synthetic wells from `examples/sample_wells.csv` and define
   three formation codes **Q**, **C** and **B**.
4. Import `examples/sample_intervals.csv` from the **Well log** tab.
5. Open **Cross-sections** and choose **Auto from wells**.
6. Inspect the section, change a contact depth using **Add / edit interpreted
   contact**, and export PNG.
7. Alternatively, draw a line in QGIS, select exactly one feature, and choose
   **Selected QGIS line** in the plugin.
8. Use **Help & feedback** to email ideas or open the GroundSurf YouTube page.

## Important limits

These are schematic well-log correlations, **not a 3D geological model**,
a geologically validated interpolation or a numerical groundwater/geothermal
simulation. Sections use straight, vertical boreholes at their mapped well
locations. Deviated well paths, surface DEM profiles, faults, true-scale
sections and uncertainty envelopes are future work.

Do not mix vertical datums. If any plotted well lacks a reliable datum/elevation,
the viewer switches to depth-only mode and suppresses elevation correlations.
A shared datum label is not proof that a height reference is correct. Synthetic
demonstration measurements are not site evidence.

Keep geological project databases off GitHub; all modelling data remain local.

## Tests

- 15 automated pure-Python tests for database, section picks and geometry.
- QGIS 3.34.4 offscreen integration: GeoPackage, saved sections, WGS84 line
  selection, automatic section orientation, edits, PNG export, and Help tab.
- Existing QGIS v0.1/v0.2 smoke tests also remain in the repository.
- No GitHub Actions workflows or hosted inference services are required.

**Status:** Private experimental developer preview. Feedback welcome.

# GroundSurf Geothermal 0.4.8 — Clearer QGIS dock and prominent 3D modelling

Experimental free QGIS 3.34–3.x plugin • November 20, 2026

## Changes suggested by user screenshot

The original QGIS dock had nine large buttons in five rows. The vertical
Project Explorer became too small to show its last entries, and the
**3D Models** tab could be hidden behind the tab-bar scroll arrows.

### Cleaner everyday controls

- **Import from QGIS** and **3D MODELS →** are now equally prominent
  primary actions. One click on 3D MODELS opens the modeller, even
  when its tab was not previously selected.
- **New project** and **Open project** remain immediately visible.
- A compact **More tools ▼** button holds six secondary operations:
  Import wells CSV, Add well, Add map layer, Relink map, Switch theme,
  and Help & feedback. The expanded/collapsed choice is remembered.
  No command or plugin function was removed.

### Room for the actual geological data

- The **3D Models** tab is first in the scrolling tab strip.
- Clicking a heading in **Project Explorer** now opens its view:
  Wells, Maps, Z Contacts, Local XYZ or 3D Models.
- The explorer cannot collapse accidentally below a readable minimum.
- The 3D modelling page moves **Model folder** next to
  **Build model / Open in ParaView**, freeing height for the saved-model
  table. A real saved model row now fits below its header.
- Concise on-screen text and full model warnings in the existing
  confirmation and model.json keep the modelling limitations clear.

## Unchanged

- Source XYZ, original QGIS layers and saved GroundSurf GeoPackages.
- Grouped borehole and contact-elevation imports, source CRS checks,
  local ungeoreferenced XYZ, WGS84 storage for truly mapped wells.
- Preliminary IDW geological surface construction and ParaView VTK output.
- Offline, non-commercial operation and existing dark/light themes.

## Test coverage

- QGIS 3.34.4/Qt5 offscreen UI tested at a dock size of 640×900.
- The Project Explorer displayed all five headings at about 154px height;
  clicking each heading opened the matching workspace.
- 3D Models visible as first tab and accessible through the new
  top shortcut.
- All optional actions open under **More tools** and can be collapsed.
- The model table has space for one full saved-model row and header.
- Earlier Python tests and QGIS integration tests retained and rerun.
- Official QGIS repository security, Flake8, Qt6/Qt compatibility scanning
  remains pending after upload; QGIS 4 runtime not verified locally.

Feedback: tzuk.ls@outlook.com
Videos: https://www.youtube.com/@Ground-Surf
Source: https://github.com/wtzet-eng/groundsurf-geothermal-qgis

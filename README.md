# GroundSurf Studio Connector — 0.5.0 development preview

One QGIS plugin (existing identifier groundsurf_geothermal), one dock. Discover embeds GroundSurf Connect 0.2.6; Model & visualise retains the established local geological modelling workspace. Existing standalone Studio remains separate. Both workspaces follow the current QGIS palette. Disable the separate GroundSurf Connect plugin before upgrading to avoid a Processing provider collision. The combined plugin is distributed under GPL-3.0-or-later, using the GPL-2.0-or-later option in the legacy code; its original licence notice remains included. This is a local development branch, not a public release. See docs/CONNECTOR_050.md. The older documentation describes the historical plugin versions.

# Studio by GroundSurf 0.4.14 — Separate modelling Studio and reliable ParaView opening

An experimental **local-first QGIS plugin** for managing wells, map layers and a
versioned geological project database. Version 0.4 adds a **preliminary 3D
interpolation engine** for shared geological contacts. It is not a validated
geothermal simulator or professional structural modelling replacement.

## Naming and optional desktop companion (0.4.14)

**Studio by GroundSurf** is the user-facing QGIS plugin name. The
`groundsurf_geothermal` plugin directory, existing settings keys, GeoPackage
schemas, model catalogue and original ParaView exports stay the same, so
existing projects and QGIS plugin installations remain compatible.

The existing **OPEN STUDIO** button still detaches the *same* QGIS
editor/widgets into a bigger window; this is not the standalone desktop
application. Under **More tools → Open desktop Studio**, you can launch the
separate GroundSurf Studio app with the currently open local GeoPackage
path. On the first use, choose its executable launcher if it is not already
on your PATH. The Python app is a separate installation and is not bundled
inside the QGIS plugin ZIP. No data are uploaded, and source QGIS layers
are not modified by launching the app.

The desktop app is called **GroundSurf Studio**, while the website and
Site Intelligence plugin retain their existing names. Previous
`GroundSurf Geothermal` references embedded in model manifests and
database checks are intentionally preserved for backward compatibility.

## What works in 0.4.14

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
- **Import from QGIS:** Copy one point per well, or **group repeated borehole
  rows** into one well and its geological intervals. Link local maps without
  duplication. Coordinate conversion and field mapping are automatic.
- **PointZ / X-Y-Z / Strata importer** for repeated geological contact
  elevations: one point per borehole, every Z contact saved in a dedicated
  GroundSurf database, shown in the **Z Contacts** tab, with ambiguous
  duplicate unit labels flagged rather than erased.
- **Import-only CRS selector** for QGIS geometry or source X/Y fields.
  The QGIS source layer and its original CRS are never changed.
- Preliminary 3D models can explicitly use original Z contact elevations
  rather than well-log depths, if a common vertical reference is supplied.
- **Local XYZ in metres, no verified geographic CRS:** keep arbitrary
  engineering XY and Z data separately in the GroundSurf GeoPackage.
  View 10 unlocated boreholes/50 stratigraphic contacts in **Local XYZ**
  without creating false WGS84 well locations.
- **3D Models → LOCAL XYZ (metres, NO geographic CRS):** interpolate
  geological horizons inside the source coordinate frame, centred around a
  reversible local XY origin, and open the resulting model in ParaView.
- No remote service, account, uploaded site data or GitHub runtime required.

## Important data conventions

- GroundSurf **stores** well point coordinates as EPSG:4326 longitude/latitude.
  Existing QGIS source coordinates may use any correctly identified CRS;
  the importer transforms them to EPSG:4326 without changing the source.
- `total_depth_m` is **metres below ground**, positive downward.
- `ground_elev_m` is in **metres**, using the datum that the **user must state**
  in `vertical_datum`. Do not mix elevations from different vertical datums.
- Storing a measurement is not the same as calculating groundwater head.
  Future analysis must distinguish elevations, depths and measurement dates.
- Imported raw contact **Z** is an elevation relative to the named source
  vertical basis, **not** drilled depth, interval base or necessarily ground.
  An unspecified vertical reference allows storage but blocks 3D modelling.
- Faulted geology, heat-flow and groundwater simulations are **not**
  present in 0.4. Preliminary 3D surfaces are inferred, not observed. Do not make engineering decisions based on this preview.

## Separate modelling Studio and ParaView Shell fix (new in 0.4.13)

QGIS remains the compact launch and import environment. Clicking
**OPEN STUDIO** opens a larger independent, non-modal GroundSurf
Modelling Studio window with the same Project Explorer, boreholes,
Local XYZ/contacts, cross-sections, 3D models and ParaView controls.

**Import from QGIS** automatically opens Studio on the imported-data
tab after a successful import, so the results are immediately visible.
The existing splitter and all its tabs are moved, NOT cloned; both
interfaces share the same single local GeoPackage and source QGIS
layers. Closing the Studio window returns all tools to the QGIS dock.
The plugin remains hosted within QGIS (not a standalone EXE).

**ParaView 6.2 NameError: __file__ is not defined** is fixed.
The Open in ParaView button now launches a tiny runpy-based wrapper
that supplies the required filename even for previously exported
0.4.9–0.4.12 conceptual models. Their original VTK geometry, scene
settings and manifest are unchanged. New 0.4.13 viewer scripts also
know how to find their folder if ParaView runs them as Python text
without __file__ and outside the model directory.

For an old model opened manually through ParaView Python Shell,
the equivalent workaround is:

    import runpy
    runpy.run_path("/absolute/path/to/view_in_paraview.py",
                   run_name="__main__")

Prefer GroundSurf 3D Models > Open in ParaView after installing this
update. Importing the same geological data again is not necessary.

## Delete selected conceptual models (new in 0.4.12)

Open **3D Models**, click one saved model row, then click
**Delete model…** beside **Model folder**.

A confirmation dialogue identifies the selected model and uses
**Cancel by default**. The main action **Remove selected model**
removes exactly that model's catalogue entry in the project's
GeoPackage, identified by its unique ID even if several models
have the same name. By default, **all output files remain on disk**.

To clean up space as well, explicitly check
**Also move this model's generated files to Trash**. Qt moves the
verified GroundSurf-generated model folder to the *system Trash*,
where files can normally be recovered. This is not an immediate
permanent wipe. GroundSurf will not offer file removal when the
folder is missing, symlinked, custom/unrecognised, shared by
another model entry or fails validation against the GroundSurf
`model.json` manifest. If moving to Trash fails, the catalogue
entry is preserved.

**Crucially:** no operation removes imported boreholes, geological
intervals, local XYZ contacts, well observations, maps or QGIS source
layers. The project database is never deleted. A removed catalogue
entry cannot be automatically restored by GroundSurf if only the
listing is removed; the export files can still be opened manually.
The model deletion action does not modify the active ParaView
session; close or hide the corresponding source there if necessary.

## Roomier import and ParaView scene styling (0.4.11)

**Import from QGIS** now opens a wider, resizable window. The mapping
fields have their own scroll area, so **Preview / OK / Cancel** stay
visible even when the QGIS screen is small. Source-mode notes are
shorter and the CRS label disappears in local-metre mode, where a CRS
transform must not be attempted. Preview failures show the actual
error. The final local XYZ confirmation is shorter but still flags
duplicate conflicting horizons (e.g. two Cretaceous contact heights).
For multiple imports, the explorer says **2 separate imports** rather
than implying 20 necessarily distinct boreholes. Previously stored
datasets are unchanged and are modelled one batch at a time.

**3D Models → Scene look…** configures the next ParaView export:

- **Geological · muted earth tones** (default): consistent colours
  assigned to formation labels.
- **Geological · high contrast**: vivid, distinct formation colours
  for presentations and interpretation.
- Optional **formation outlines**, *not all triangle mesh edges*;
  these accent major geological boundaries without hiding colours.
- Optional XYZ orientation triad (default on) and labelled **local
  X/Y/Z bounds box** (default off); local coordinates are not a
  georeferenced map.
- Consistent **#212121** charcoal scene, soft matte lighting and an
  oblique geological camera. Existing source-contact markers, single-
  unit visibility toggles and vertical display exaggeration remain.

These are ordinary geological-visualisation conventions, not a copy
of any vendor's proprietary interface or artwork.

The two palettes and scene toggles are stored in local QSettings.
New model folders save the complete choices in `appearance.json`.
For per-formation custom colours, change a
`bands[].color` field to a six-digit hex string (e.g. `#39b9b1`)
and rerun `view_in_paraview.py` via the ParaView Python Shell.
No re-export or modification of the geological XYZ is needed.
Original VTK geometry, contact elevations, IDW interpolation and
source CRS handling remain identical.

## Where did my QGIS data go? (0.4.10)

For your source `BH_logs` with repeated `ID`, metre X/Y,
`Z` and `Strata`, **Import local XYZ metres (NO map CRS)** saves a
distinct dataset to `gs_local_xyz_batches` and its contact rows to
`gs_local_xyz_contacts`. They appear in **Local XYZ**, not in the
geographic **Wells** tab. This is deliberate: a 3D model can use
unlocated, consistent metre XYZ without inventing latitude/longitude.

When opening a project with imported local data, GroundSurf now
reports the number of datasets, individual local boreholes and contacts
at the bottom of the dock. The Project Explorer displays the count,
for example `Local XYZ · 10 boreholes / 50 contacts (unlocated)`.
Click that heading to inspect source data, or open **3D Models**
to use it for a new conceptual ParaView export. Previously saved
local datasets are preserved.

Also corrected after the 0.4.8 tab reorder:

- Copying ordinary **georeferenced wells** now opens the **Wells** tab.
- Grouping **well-log intervals** now opens the **Wells** tab.
- Linking an existing QGIS **map** now opens the **Maps** tab.
- GroundSurf will show a useful error dialog and write to the local
  QGIS Message Log under `GroundSurf Geothermal` if the import
  dialog itself cannot open. Source layers with empty or multipart
  first geometry no longer raise unhandled errors during CRS-mode
  suggestion.

The earlier QGIS message `Python error: See message log (Python Error)`
**does not itself identify a cause**; the exact Python traceback in
the **Python Error** log may still be needed to identify an unrelated
QGIS or plugin problem.

## Geological presentation in ParaView (new in 0.4.9)

GroundSurf now generates **two complementary ParaView opening paths**:

- `model.vtm` — the original, unmodified geometric multiblock model for
  manual review, numerical attribute checks and backwards compatibility.
- `view_in_paraview.py` + `appearance.json` — a new **prepared scene**
  with consistent geological unit colours, readable stratigraphic
  labels, a dark `#212121` background, a useful oblique camera
  perspective, and **source-contact well markers**.

After building a model, select it in **3D Models** and click
**Open in ParaView**. For newly exported models, GroundSurf uses
ParaView's documented `--script` argument so unit colours and
borehole overlays appear automatically. Models created before
0.4.9 continue to open their original `model.vtm` file normally.

### Display controls

In **3D Models** in QGIS, choose a **ParaView display Z ×** value
from 0.5× to 10× (default **1×**, no exaggeration). Tick **Boreholes**
(default on) to include observed or source-derived contact markers
and schematic vertical well sticks in the scene. The choice is stored
in `appearance.json`.

This changes **display only**. Original X/Y/Z, geological contact
elevations, model grids, thickness values and source CRS metadata
are not scaled or modified. To change the display after export,
adjust the `vertical_exaggeration`, `show_boreholes`, or
`show_contacts` fields in `appearance.json` and run the ParaView
script again (or create a new model with other QGIS display settings).
The script can also be run in an existing ParaView session through
**Tools → Python Shell → Run Script**.

In ParaView's Pipeline Browser, the geological volumes are separate
toggleable pipeline items. This makes it easy to hide Quaternary,
Pleistocene, Palaeogene, Cretaceous and other units independently.
Source contacts are points; white schematic borehole sticks are
vertical connectors between the modelled contact elevations, **not
measured deviated well trajectories**. Interpolated surfaces remain
available in the folder but are hidden by default to avoid visual
flicker where coincident surfaces overlap volume faces.

### Transparent evidence coverage (NOT confidence)

Each interpolated surface carries `Distance_to_nearest_well_m` as a
point array, and each volume carries it as a cell array. You can
choose this quantity from ParaView's **Color By** menu to see where
the geological model is close to, or remote from, borehole input.
This is a **spatial proximity measure only**. It does NOT quantify
geological uncertainty, produce calibrated confidence intervals, or
make IDW interpolation a geostatistical prediction.

Legend colours identify **source formation names**, not geological
certainty or temperature. Any source units or inferred contacts
must still be checked against the original survey/borehole records.

## Easier navigation in 0.4.8

The narrow QGIS dock gives more of the window to the actual geological
data. The main toolbar now shows only two important workflows and
project controls:

- **Import from QGIS** — use a layer already open in QGIS.
- **3D MODELS →** — one-click entry into the 3D modeller and ParaView
  scene exporter, even if the tab strip has scrolled.
- **New project / Open project** — always visible.
- **More tools ▼** — expands the well CSV, manual well editing, map
  source management, theme and Help/feedback actions. The setting is
  remembered; no existing operation has been removed.

The **3D Models** tab is now first in the tab strip. Clicking any
heading in the **Project Explorer** jumps to its tab. The explorer
retains enough height to show the important categories instead of
hiding the last row.

Within the 3D Models page, **Build model / Open in ParaView / Model
folder** occupy one toolbar row. The saved-model table has sufficient
height to display both its column headings and actual model records.
The compact notes still flag conceptual IDW limitations; detailed
warnings remain in the modelling confirmation and `model.json`.

These are QGIS UI-only changes: source data, modelling calculations,
existing local GeoPackages, coordinate reference handling, geological
uncertainty flags and ParaView outputs are unchanged.

## Install in QGIS 3.34+

1. Download/clone this repository and copy `groundsurf_geothermal` into
   your QGIS profile `python/plugins` directory, or use the generated ZIP
   from the release preparation command below.
2. In QGIS, open **Plugins > Manage and Install Plugins** and enable
   **GroundSurf Geothermal**.
3. Click **GroundSurf Geothermal** in the toolbar or Plugins menu.
4. Click **New project**, choose a fresh `.gpkg` filename.
   For existing data, click **Import from QGIS** to use open project layers.
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

### Import from open QGIS projects (new in 0.4.2)

**No intermediate CSV is needed** if the well layer already appears in your
QGIS Layers panel.

1. Open the well or geological map layer in QGIS as usual.
2. In GroundSurf Geothermal, create/open a local GroundSurf GeoPackage.
3. Click **Import from QGIS**. The active QGIS layer is selected by default.
4. For well points, choose **Copy point features as GroundSurf wells**.
   Review the proposed mapping of `well_id`, `name`, `total_depth_m`,
   `ground_elev_m`, `vertical_datum`, `source` and `notes`.
   Typical source names such as `BH_ID`, `WellName`, `Depth`, `RL`
   and `Datum` are suggested automatically.
5. Tick **Import selected features only** if you want only your QGIS
   selection. Otherwise import every point in that layer.
6. The source CRS is used to convert geometry to WGS84. Depth and elevation
   values are **not** converted between metres and feet, nor are vertical
   datums transformed. Check the original measurement units.
7. For maps, choose **Link existing map source (no data copied)**.
   GeoPackage, shapefile, GeoJSON and GeoTIFF links are supported. The
   original QGIS layer, including its styling, is kept in place.
8. If the source is an in-memory, virtual or remote service map, save it
   to GeoPackage or GeoTIFF before linking permanently. Well point features
   from memory layers can still be copied directly.

Linked maps are reference data, **not automatic fault surfaces or other 3D
modelling constraints**. Real wells copied into the GroundSurf GeoPackage
can immediately be used in well logs, section interpretation and preliminary
3D modelling. Existing input layers are never modified by the importer.

### Group repeated borehole rows into complete well logs (new in 0.4.4)

Use **Import from QGIS** when your existing QGIS **point layer** has
more than one record for the same borehole (typically one row per lithological
interval). GroundSurf detects repeated well IDs and preselects:

**Group repeated borehole rows into individual well logs**

1. Choose the loaded QGIS point layer. The active QGIS layer is preselected.
2. Check the suggested **Well identity** field mappings: borehole ID, name,
   surveyed ground elevation, total depth, vertical datum and provenance.
3. Open the **Geological intervals** tab. Review the proposed formation,
   interval top and interval base fields. The values must be metres below
   ground; interval base must be deeper than its top.
4. Choose **Import selected features only**, or import the entire layer.
5. Click **Preview grouped boreholes** to see how many records will become
   individual wells and intervals. Check warnings and a sample by-well count.
6. Confirm the import. Each unique borehole ID becomes exactly one
   GroundSurf well. Its lithological intervals appear under **Well log**.
7. Original QGIS rows and their geometry are never edited or deleted.

Example: 30 rows representing five boreholes, each with six lithological
intervals, become **five wells and 30 log intervals** in GroundSurf.

- The importer accepts 50,000 source rows and at most 10,000 distinct wells.
- Matching borehole IDs must have consistent ground elevations, total
  depths, names, vertical datums and map locations (within 5 metres).
- Overlapping intervals, reversed depths and inconsistent attributes are
  rejected *before* the original copy is changed.
- The attribute `Depth` alone is deliberately **not** assumed to represent
  drilled total depth in grouped mode. Set total-depth mapping explicitly
  if it truly refers to the completed hole depth.
- If no drilled total depth is supplied, it remains **unknown**. The base
  of the deepest logged interval is not silently treated as drilled depth.
- Grouped formation labels are copied as source labels and marked for
  geological verification; they are not independently validated stratigraphy.
- The importer refuses existing GroundSurf well IDs rather than silently
  replacing or merging existing logs.
- If no interval columns are present, leave all three formation/top/base
  fields unmapped to import grouped well locations only.
- This first release reads QGIS **point-geometry layers**. Standalone
  relational tables, AGS files, and well-path/deviation tables will require
  separate import adapters.

### When QGIS reports an invalid latitude (new diagnostic in 0.4.5)

If a source feature has a coordinate such as `X=450000, Y=5800000`
but the layer is *declared* `EPSG:4326` (degrees), GroundSurf cannot
safely interpret its location as longitude/latitude. It will stop and show:

- the source layer name and QGIS feature ID;
- the source layer CRS, plus raw geometry X and Y;
- whether the values resemble projected coordinates or swapped X/Y;
- the step required in QGIS: identify and **assign the actual source
  LAYER CRS**, not just the QGIS project CRS, then retry.

For projected layer coordinates in metres, the proper source CRS could be
a local UTM, national grid or other engineering system. It cannot be
determined safely from two numbers alone. GroundSurf therefore never
auto-guesses CRS, silently swaps latitude/longitude, or modifies the
original QGIS input layer.

See QGIS **right-click layer → Properties → Information** for its CRS.
Compare that with the geometry coordinate values shown by QGIS's feature
inspection tools. Once the real layer CRS is correctly assigned,
the importer uses QGIS's transformation to EPSG:4326 automatically.
This applies to both single-well and grouped-interval importing.

### Import geological PointZ contacts from a QGIS layer (new in 0.4.6)

This is the right option for records such as:

```text
wkt_geom                         ID   X       Y       Z     Strata
PointZ(503200 5840100 -145)       BH9  503200  5840100 -145  Base
PointZ(503200 5840100 -112)       BH9  503200  5840100 -112  Cretaceous
PointZ(503200 5840100 22)         BH9  503200  5840100 22    Quaternary
```

Each row represents a **geological contact at a source Z elevation**.
The importer does **not** treat Z as a drilled depth below ground.

1. Open the source `BH_logs` layer in the QGIS Layers panel.
2. Create or open a **GroundSurf project** (its own local GeoPackage).
3. Click **Import from QGIS** and choose that source layer.
4. Select **Import PointZ geological contact elevations**. GroundSurf
   should preselect this format when it sees ID/Strata/Z fields.
5. Check the **Source X/Y CRS** picker. Select the actual coordinate
   system of the *source numbers*, not simply the project CRS. For example,
   X around 1,400,000 and Y around 7,000,000 are **not EPSG:4326 degrees**.
   The correct source projection must be established from the original data;
   do **not** assume EPSG:3857 merely because it produces plausible results.
   The CRS choice affects this import only; the original QGIS layer is not edited.
6. Open **PointZ / contact elevations**. Verify ID, Strata and Z mappings.
   By default, horizontal X/Y comes from point geometry. If the source
   attributes are authoritative, tick **Use attribute X and Y**.
   Choose **Use PointZ geometry height** to use the geometry's third
   coordinate rather than the Z attribute.
7. Enter a **vertical reference or elevation datum** only if it is known
   from the original dataset. Leaving it blank stores `UNSPECIFIED` and
   keeps the contacts available for inspection, but stops 3D modelling.
8. Click **Preview contact elevations**. Review recognised boreholes,
   all source elevations and any conflicting/missing unit labels.
9. Confirm. GroundSurf now displays unique wells in **Wells** and all
   contact elevations in **Z Contacts** within the plugin dock.
10. Optionally choose **3D Models → Imported contact Z elevations** and
    create a preliminary model. This requires at least three spatially
    separate, unambiguous wells and a common user-declared vertical basis.
    The model retains source provenance and explicitly excludes ambiguous
    well/unit combinations.

In the synthetic 10-borehole test example, **50 rows** map to **10 distinct
well records and 50 stored Z contacts**. BH8 has **two different
Cretaceous elevations** and **no Base contact**. Both records are
preserved and flagged; BH8 is excluded from any preliminary model that
requires a single Cretaceous contact. No contact value is fabricated.

Source Z elevations remain independent from well-log depth intervals.
The uppermost observed contact is not assumed to be terrain, ground
elevation or completed well depth.

### When source XY are metres but the CRS is unknown (new in 0.4.7)

**You do not need to pretend that source XY are EPSG:4326 to make a
preliminary 3D scene in ParaView.**

For a dataset whose point geometry contains numbers like
`X=600200, Y=5840100, Z=-145`, the X/Y values are not geographic
longitude and latitude. If these represent distances **in metres** in
one local engineering frame, you can build a local model *without*
knowing where that frame sits on the Earth.

1. Open your existing `BH_logs` layer in QGIS.
2. Open a local GroundSurf GeoPackage project.
3. Select **Import from QGIS → BH_logs** and choose
   **Import local XYZ metres (NO map CRS; usable in ParaView)**.
   For a layer declaring a geographic CRS with invalid coordinate
   magnitudes, this option is suggested automatically.
4. Review the field mappings: `ID` (well), `Strata` (unit),
   `X`, `Y` (horizontal), and `Z` (source contact height).
   Select either point geometry or attribute X/Y and Z.
5. **Explicitly check that X, Y and Z are in metres and share a
   consistent local coordinate basis.** This is an input requirement,
   not something GroundSurf can infer from the numbers alone.
6. Optionally enter the source's vertical reference name.
   If unknown, leave it unverified; the scene remains a conceptual
   local model and cannot be tied to a surveyed ground elevation.
7. Click **Preview LOCAL XYZ**. Review the number of unique
   boreholes and all geological units; ambiguous duplicate unit Z
   values are flagged, not silently replaced.
8. Confirm. The records appear in GroundSurf's **Local XYZ** tab
   (with source X, Y and Z preserved), *not* the worldwide map Wells
   layer or the georeferenced Z Contacts tab.
9. Open **3D Models**, select **LOCAL XYZ (metres, NO geographic CRS)**,
   then click **Build model**. Review the source warnings and save the
   resulting `model.vtm` and `model.json`.
10. Use **Open in ParaView**. Coordinates use a locally centred
    scene: `X_local = X_source - X_origin` and
    `Y_local = Y_source - Y_origin`, while `Z_local = Z_source`.
    All scene coordinates remain in the user-confirmed metre units.
    `model.json` preserves the origin offset, provenance, original
    XY values and the **ungrounded/ungeoreferenced** coordinate label.

**What this does NOT do:** establish where the boreholes are on the
world map, turn a false layer CRS into a true one, perform a Web
Mercator scale correction, or make the source Z an independently
surveyed elevation. A later GIS overlay still requires identifying the
actual source CRS from survey metadata and performing a real CRS
transformation. Do **not** invent a plausible EPSG code.

Caution: source values expressed in metres need not correspond to
undistorted ground metres. For example, Web Mercator has variable
ground-scale distortion. A local translation preserves distances
in the source coordinate system; it does not remove map projection
distortion. Use appropriate verified metric/projected coordinates
for engineering interpretation.

This separation is intentional. A **local 3D geological model** can be
visually useful before a site's geographic position is available;
**GIS-referenced reports and overlays** cannot.

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
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_qgis_import_v042.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_grouped_v044.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_crs_v045.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_pointz_v046.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_local_xyz_v047.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_layout_v048.py
PYTHONPATH=. /usr/bin/python3 tools/smoke_paraview_scene_v049.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_paraview_ui_v049.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_import_visibility_v0410.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_scene_look_v0411.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_delete_model_v0412.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. /usr/bin/python3 tools/smoke_studio_v0413.py
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
- `groundsurf_geothermal/qgis_import.py` — live QGIS layer import and mapping UI.
- `groundsurf_geothermal/grouped_import.py` — grouped well/interval validation
  and import with rollback if metadata writing fails.
- `groundsurf_geothermal/elevation_contacts.py` — raw elevation Z store.
- `groundsurf_geothermal/elevation_import.py` — PointZ/XYZ input validation.
- `groundsurf_geothermal/contact_ui.py` — in-plugin Z Contacts table.
- `groundsurf_geothermal/contact_adapter.py` — Z-based 3D surface input.
- `groundsurf_geothermal/local_xyz.py` — separate local-metre XYZ store
  (no assigned map CRS), preview and 3D model input.
- `groundsurf_geothermal/scene_style.py` — stable categorical palettes
  and model presentation settings.
- `groundsurf_geothermal/paraview_scene.py` — stand-alone ParaView
  GUI Python script copied into each exported model folder.
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

## Security and Qt6 maintenance (0.4.1)

The QGIS plugin security scan identified three patterns in 0.4.0. All were
replaced in 0.4.1: literal SQL DELETE statements, safely escaped XML output
without the xml.sax helper, and the Qt-native QProcess launcher for optional
ParaView viewing. The 57 reported deprecated/unscoped Qt symbols and exec_
calls were updated to scoped enum values and exec(), compatible with the
tested QGIS 3.34.4/Qt5 runtime. QGIS 4/Qt6 runtime validation is still
pending; static Qt6 scanner warnings should be rechecked after upload.

## v0.4.3 quality fix

Two assigned lambda expressions in the cross-section drawing panel were
replaced by ordinary named functions to resolve Flake8 E731. Behaviour,
visualisation and direct QGIS import workflows are unchanged.

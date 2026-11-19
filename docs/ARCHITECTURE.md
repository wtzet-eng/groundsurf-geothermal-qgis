# GroundSurf Geothermal architecture — v0.4.4

## Stable boundaries

```
QGIS 3 user interface / map canvas
       |
       | UI actions, project_id, model tasks (future)
       v
local project store: one GeoPackage
       |-- gs_wells: native WGS84 point geometry
       |-- gs_meta: schema + project metadata
       |-- gs_formations: formation catalogue
       |-- gs_intervals: borehole geology intervals
       |-- gs_observations: dated hydro/thermal observations
       |-- gs_formation_tops: observed or interpreted stratigraphic tops
       |-- gs_map_layers: local map source references
       |-- gs_maps: legacy v1 catalogue kept for compatibility
       |-- gs_sections: named WGS84 polylines + section corridor widths
       |-- gs_section_picks: interpreted contact overrides by well/formation
       '-- gs_model_runs: independent, source-tracked local 3D model runs
       |
       +-- future separate modelling-core process / versioned API
                 |-- geometry modelling
                 |-- groundwater solvers
                 |-- geothermal solvers
                 '-- optional ParaView export
```

QGIS owns map rendering and GIS coordinate conversion. The GeoPackage stores
local data. The future independent modelling core does NOT run inside QGIS's
Python interpreter and will expose a versioned, documented task interface.
Avoid forcing heavy dependencies into the QGIS plugin.

### Schema and migration policy

Base project schema remains v2. Cross-sections use independent additive
module schema gs_meta.section_schema_version = 1, backed up on first open
of an existing v0.2 project. This avoids destructive changes to the well tables.
Schema version stored as gs_meta.schema_version = 2. Future updates must
provide an explicit backed-up migration path and never silently overwrite
unknown schema versions. The v0.3 plugin preserves the backed-up v1-to-v2 upgrade, adds an optional section module backup, and refuses unknown versions.

### Geological conventions

- Well point: longitude/latitude WGS84 EPSG:4326.
- Depths: positive downward from reported ground level, in metres.
- Ground elevations: metres in source-specific vertical datum, never silently
  mixed or converted.
- Time-dependent measurements store observation date and measurement units.
- Source and method provenance should be captured for every derived property.
- Modelled surfaces must not be presented as observed boundaries.

### Next iterations

1. Extend 2D well correlation to inclined/deviated boreholes and terrain DEM.
2. Explicit vertical datum conversion and geology measurement provenance.
3. Better QGIS .qgz project persistence and map-source diagnostics.
4. Optional standalone geology/thermal modelling process with tests.
5. Import/export AGS, LAS, SEG-Y via separately tested adapters.

### Development safety

No runtime cloud dependencies; no Github Actions workflows by default.
Do not add real project data, binary solvers, generated videos or packages
to the source repository. Keep production GroundSurf/ParaView/SGeMS plugins
separate. The initial dark/light interface is an original design, not a copy
of any proprietary application's assets.

## Preliminary 3D pipeline (v0.4)

QGIS well GeoPackage → explicit contact elevations and vertical datum →
local UTM coordinates → original Python IDW interpolator and subdivision
triangulation → VTP horizon surfaces + VTU wedge volumes → VTM scene
index and JSON provenance manifest → optional independent desktop ParaView.

The QGIS plugin (including its small modelling kernel) is GPL-licensed
and public; experimental future standalone simulation services can have
independent codebases and licences subject to legal review. The model output,
well logs and user project files remain local.

The new `gs_model_runs` catalogue and `gs_meta.model_schema_version = 1`
are additive to the existing GeoPackage version 2 schema. Existing projects
receive a backup before the first model module migration.


## Importing from an existing QGIS project (0.4.2)

The QGIS plug-in enumerates QgsProject.instance().mapLayers(), excluding
GroundSurf's own wells and transient section preview layers. Point wells
can be copied into the GroundSurf GeoPackage through preflight attribute
validation and QGIS CRS transformation (EPSG:4326). All records are
validated first, then committed in one GroundSurf well-layer edit transaction.
The original layer is not edited and its geometry is not transformed in place.

For local vector/raster maps, the plug-in registers the existing file URI
(and named GeoPackage sublayer) in the gs_map_layers catalogue without
copying data or adding a duplicate QGIS layer. On subsequent project loads,
file-backed links are resolved relative to the GroundSurf project and any
already-open QGIS layer is reused. The plug-in tracks ownership separately,
so relinking cannot remove an existing user-owned QGIS source.

These registered maps remain *context layers*, not automatically structural
geological constraints. Memory and service layers cannot be persistently
linked until a separate source-URI preservation feature is designed.


## Grouped borehole import from long-form QGIS point data (0.4.4)

Long-form source rows are grouped by a selected borehole ID field.
The importer first validates every row's coordinates (converted to WGS84),
attributes, geological interval depths and repeated-well consistency.
An automatically suggested mapping is user-editable, with a preview of
individual well and interval counts.

Repeated rows within 5 metres are treated as one well location, provided
depth, name, elevation and vertical datum also agree. Overlapping or
reversed intervals reject the batch. Unmapped or unknown total well depths
are left unknown rather than being inferred from the longest log.
Source geological unit codes are imported as provenance-marked labels.

After preflight, one QGIS well-layer edit transaction copies the unique
wells. A second, all-or-nothing SQLite transaction installs any new
formation labels and geological intervals in the same GeoPackage. On
the unlikely event of an interval transaction failure, the importer
performs a compensating deletion of the freshly added wells. This two-stage
process is **not claimed to be a single database transaction**; unrecoverable
rollback failures are explicitly reported for manual review.

Only QGIS point layers with attribute rows are accepted in this initial
version. Importing a separate nonspatial AGS or relational borehole log
table is a different adapter to be implemented later.

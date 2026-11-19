# GroundSurf Geothermal 0.2.0 — Well Manager (development preview)

## New functionality

- Create and select geological formations (code, name, lithology).
- Add and remove lithological intervals per well, with depths in metres below
  ground and conflict checks.
- Import interval CSV atomically. Failed imports do not leave partial logs.
- Add observed or interpreted formation-top depths; retain source attribution.
- Store dated groundwater-depth, water-head-elevation, temperature and
  pressure observations with explicit units, depth and datum fields.
- Show well logs, formation tops and measurements in dedicated tabs.
- Local map inventory now stores relative paths; report missing map sources,
  select a map record and relink to a moved source file.
- Allow selection of a sublayer in a multi-table GeoPackage.
- Backward compatibility: offer migration from GeoPackage schema v1 to v2;
  create a SQLite backup before updating the original.

## Important limitations

This is a **well database and map-management workbench**, not a validated
geothermal or groundwater flow simulator. Geological interval data are
stored as observations/interpretations, not yet rendered in geological
cross-sections. The initial log editing supports adding and deleting records;
editing means deleting and re-adding a corrected entry.

Vertical datum conversion and wellbore deviation are not yet implemented.
Well positions are WGS84 lon/lat, vertical measurements in metres. Absolute
file paths remain as a fallback when relative map links cannot resolve.

## Demonstration

Create a project, import `examples/sample_wells.csv`. Use **Formation**
three times to define Q (Sand), C (Clay), B (Sandstone). Import
`examples/sample_intervals.csv` using the **Well log** tab. Select a well,
explore its log and add a dated groundwater or temperature observation.

All example data are synthetic and are not evidence about a real site.

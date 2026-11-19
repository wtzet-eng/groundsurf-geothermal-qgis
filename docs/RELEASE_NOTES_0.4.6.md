# GroundSurf Geothermal 0.4.6 — PointZ geological contacts from QGIS

Experimental QGIS 3.34–3.x plugin • local-first, GPL-2.0-or-later

## New: Import XYZ contact elevations from an open QGIS project

Supports source layers like `BH_logs` with fields `ID, X, Y, Z, Strata`
and 3D point geometry `PointZ (X Y Z)`.

- Read and group repeated IDs into **individual GroundSurf wells**.
- Preserve **every** raw geological contact observation, including
  stratigraphic unit label and its original Z elevation. This is not a
  drilled-depth interval or calculated ground elevation.
- Automatically map common `ID`, `Strata`, `Z`, `X` and `Y` fields.
- Read horizontal X/Y from source geometry or user-selected X/Y
  attributes. Read height from the `Z` attribute or PointZ geometry.
- Native QGIS **Source X/Y CRS** picker chooses the actual coordinate
  system used by source values, *per import*, without modifying the
  original QGIS layer or the QGIS project CRS.
- Import preview shows unique boreholes, source contacts, repeated unit
  labels, missing units and whether the vertical elevation basis is known.
- A new **Z Contacts** tab in the GroundSurf dock displays the persisted
  observations by borehole/unit. This resolves the confusion between a
  layer visible in QGIS and records registered in GroundSurf.
- Existing well-log depth intervals and raw contact elevations remain
  separate in the GeoPackage. Existing layers and records are not modified.

### Verified with a synthetic PointZ dataset matching the source schema

The 50 fabricated records representing BH1 through BH10 produced
**10 unique well records and 50 saved contact-elevation observations**.

BH8 is ambiguous: `Cretaceous` occurs twice with differing Z values
and `Base` is missing. GroundSurf **preserves both Cretaceous records**
and flags the missing/ambiguous source geology rather than filling it in.

## New: Preliminary 3D model from contact Z elevations

Under **3D Models**, select either:

- **Well-log depths** — original depth interval workflow; or
- **Imported contact Z elevations** — interpolate source contact
  elevations at the known well locations.

Raw contact Z surfaces need a common user-provided vertical reference
to be modelled. Missing or unverified vertical basis is never inferred
from the top of a lithological log. The contact model excludes ambiguous
duplicate-unit wells (such as BH8) and warns which wells/horizons
were omitted. Interpolation is an IDW *conceptual visualisation only*,
not a validated structural, geothermal or groundwater model.

## Coordinate safety

Source points such as `X=503200,Y=5840100` are **not EPSG:4326
longitude/latitude degrees**. Users must identify their real original
projected CRS (if any) from survey/GIS documentation and choose it in
the import dialog. A plausible result under EPSG:3857 alone does not
prove that EPSG:3857 is the correct CRS.

The importer never guesses a CRS or silently changes the input layer.
A wrong CRS still blocks import, with an actionable coordinate error.

## Quality checks

- Test using 50 fully synthetic rows with the same field schema and an
  BH8 ambiguous geological unit.
- Verify native CRS selector, original source layer safety,
  exact 10-well/50-contact persistence in local GeoPackage,
  live GroundSurf **Z Contacts** panel and plugin import button.
- Check explicit user-provided height reference, unknown-datum
  rejection for modelling, and preliminary 3D surface generation
  from unambiguous wells only.
- Retain all 20 pure-Python tests and prior QGIS integration tests.
- The official QGIS security, code-quality and Qt6 static scans must
  be rerun following the new version upload. Qt6 runtime remains untested.

Feedback: **tzuk.ls@outlook.com**
Video demonstrations: https://www.youtube.com/@Ground-Surf

Public source: https://github.com/wtzet-eng/groundsurf-geothermal-qgis

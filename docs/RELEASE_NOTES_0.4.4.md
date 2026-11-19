# GroundSurf Geothermal 0.4.4 — Automatic grouped borehole importer

Experimental QGIS 3.34–3.x plugin • 2026-11-19

## New: One QGIS layer → Individual boreholes

A single point layer can contain multiple attribute rows for each borehole,
for instance one feature per lithological interval. GroundSurf now
automatically recognises repeated IDs and offers **Group repeated borehole
rows into individual well logs** in **Import from QGIS**.

- Groups rows by the mapped borehole ID, creating **one GroundSurf well**
  per unique ID, rather than treating duplicate IDs as import errors.
- User-editable automatic mappings for borehole ID/name, ground elevation,
  drilled depth, vertical datum and separate formation/top/base/description
  columns. Common aliases include BH_ID, WellName, RL, TD, VDatum,
  Formation, From_m, To_m and Geology.
- Preview unique well count, source row count, interval count and
  representative per-well interval counts before importing.
- Imported intervals are accessible from each well's **Well log** tab;
  imported unit labels are marked as source data needing interpretation.
- Selected-only importing, WGS84 geometry transformations and original
  input layer ownership are retained from v0.4.2.
- Does not create unnecessary separate QGIS map layers per well.
- Does not claim a drilled depth from the deepest logged interval.

## Safety and data validation

- Repeated features for the same ID must be within five metres of one
  another and have consistent ground elevation, total depth, name and
  vertical datum.
- Reject missing IDs, nonnumeric or inverted interval depths, overlapping
  intervals, conflicting metadata and duplicate IDs already stored in
  GroundSurf before writing the import.
- Verify a preview before confirming each grouped import.
- The importer writes new wells through the QGIS transaction and
  geological log intervals through a separate SQLite transaction, with
  best-effort automatic compensation on failure and explicit error reporting.
- Original QGIS layer data, coordinate geometry and styles remain unchanged.

## Scope and limits

The initial importer works with **point layers already loaded in QGIS**
whose attributes include a unique borehole identity. Separate non-spatial
AGS databases or relational contact tables are not yet joined automatically.
Wellbore trajectories are not modelled from per-record point offsets.
Formation code mapping is not a replacement for professional geological
correlation.

Existing direct single-feature-per-well import, QGIS map linking,
groundwater/temperature measurements, 2D sections, preliminary 3D
interpolation, ParaView export and dark/light themes remain available.

## Verification

- Headless QGIS test turns six source records into three wells, each with
  two intervals, and checks automatic column detection, selected-only
  grouping, coordinate conversion, original layer integrity, rejection
  of duplicate IDs/inconsistent coordinates, and rollback after simulated
  metadata failure.
- Earlier Python and QGIS integration tests retained.
- Official QGIS security, Qt6 compatibility and Flake8 scans still need
  to be rerun after the new ZIP is uploaded.

Feedback: tzuk.ls@outlook.com
Videos: https://www.youtube.com/@Ground-Surf

Public GPL plugin source:
https://github.com/wtzet-eng/groundsurf-geothermal-qgis

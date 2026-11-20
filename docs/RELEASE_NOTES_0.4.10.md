# GroundSurf Geothermal 0.4.10 — Correct import navigation and saved XYZ visibility

Experimental QGIS 3.34–3.x plugin • November 20, 2026

## Why this update

An import could have succeeded while its results remained hidden by
unhelpful tab navigation. A local XYZ project containing **10 boreholes
and 50 source contact elevations** can have an empty geographic Wells
table. Such records belong in **Local XYZ**, not in a map-based well
list, because their geographic coordinate reference is unverified.

Their geographic `gs_wells` and `gs_elevation_contacts` tables were
empty. This is **expected and correct** for an unlocated metre-based
dataset. Imported points appear in **Local XYZ**, not geographic
**Wells**. A real source CRS is still unknown; GroundSurf will not
invent one.

There was also a definite UI routing error from v0.4.8:
moving 3D Models to first tab left legacy numeric tab indexes
in the ordinary well and map import handlers. Data could be
stored correctly while the interface switched to an unrelated tab.

## Changes

- The **Local XYZ** heading in Project Explorer now shows saved
  dataset counts, e.g. **10 boreholes / 50 contacts (unlocated)**.
  Clicking it opens the in-plugin contact records.
- Project reopening explains the difference between unlocated local
  XYZ and verified, geographically referenced Wells.
- Ordinary well, grouped well-log and map imports now navigate to
  the **correct** view using stable widget objects, not tab numbers.
- The QGIS import-dialog construction/execution is now inside a
  user-facing exception handler. Errors are written to QGIS
  **Message Log → GroundSurf Geothermal** and shown in a dialog.
- Empty or multipart first source geometry cannot crash the initial
  automatic local XYZ mode suggestion.

### Interpreting generic QGIS Python errors

`Python error: See message log (Python Error)` is **not the
traceback** and does not prove which plugin or operation failed.
The original 20:49–20:50 Python exceptions have **not been
individually attributed** to GroundSurf or diagnosed without
their tracebacks. This update fixes confirmed navigation bugs and
improves future error reporting; it makes no unverified claim
about the original generic QGIS notification.

The earlier QGIS temporary-ZIP and Open Sans font warnings may be
unrelated to data import; the plugin source and installed 0.4.9
files were checked and matched.

## Safety and verification

- Previously stored data and any source QGIS layers remain unchanged.
- Synthetic offscreen regression test reproduces georeferenced well
  import, file-backed map linking, import-dialog constructor failure,
  first source feature without geometry, and reopening a synthetic
  project holding ten unlocated boreholes with 50 source contacts.
- Existing unit and QGIS integration tests, ParaView 6.2 scene export,
  versioned ZIP and static scans retained.

Official QGIS repository scanner/Qt6 runtime status must be checked
separately after upload.

Public source: https://github.com/wtzet-eng/groundsurf-geothermal-qgis
Feedback: tzuk.ls@outlook.com

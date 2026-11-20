# GroundSurf Geothermal 0.4.12 — Delete conceptual models in the QGIS dock

Experimental free QGIS 3.34–3.x plugin • 20 November 2026

## User-requested model removal

The **3D Models** view now has a **Delete model…** button next to
**Model folder**.

1. Select one saved conceptual model row in the list.
2. Click **Delete model…**.
3. In the confirmation, choose **Remove selected model**, or **Cancel**
   (the default).
4. By default, only that one catalogue entry is removed from the
   GroundSurf project's `gs_model_runs` table. The generated VTK and
   ParaView files remain on disk.
5. To also remove the generated outputs, explicitly check
   **Also move this model's generated files to Trash**. The chosen
   output folder goes to the operating system's Trash, not through a
   permanent deletion command. The Trash option is disabled unless
   the directory is a verified GroundSurf-generated model folder.

Model IDs uniquely identify output even when several entries have
identical display names, dates or borehole counts.

## Data protections

- **No change to source geology:** imported georeferenced wells, local
  XYZ batches, contact elevations, geological intervals, observations,
  maps, QGIS source layers and the project GeoPackage remain intact.
- A generated output folder is eligible for Trash only when it uses
  the generated `gsmodel-` prefix, contains GroundSurf's own
  `model.vtm` and a `model.json` with matching application and model
  name, and is not a shared/linked model directory.
- Symlinked, missing, renamed, ambiguous or unrecognised folders are
  not offered for automatic Trash. Their model list entry can still
  be removed separately, leaving their files untouched.
- If the Trash move fails, the model entry stays in the catalogue.
  Cancel makes no changes.
- Removing a list entry does not close or change models already
  open in the separate ParaView application.

## Verification

- 20 Python unit tests plus the existing QGIS integration/smoke
  suite retained.
- Added synthetic QGIS 3.34/Qt5 workflow test at 640 × 900:
  user selection, Cancel, duplicate model names, list-only deletion,
  optional Trash, failed file move, unsafe folder rejection,
  symlink/duplicate-output safety and unchanged geological records.
- Confirmed Qt 5.15 `QFile.moveToTrash` supports model folders.
- Installer ZIP integrity, GPL licence, metadata and prior Qt6,
  Bandit and Flake8 flagged patterns checked.
- Official QGIS plugin repository code-quality/security/Qt6 scanner
  and QGIS4 runtime must be verified separately after upload.

Public source and ZIP:
https://github.com/wtzet-eng/groundsurf-geothermal-qgis
Feedback: tzuk.ls@outlook.com

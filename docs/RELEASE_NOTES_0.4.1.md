# GroundSurf Geothermal 0.4.1 — Security and Qt6 source compatibility

Experimental maintenance release • November 2026 • QGIS 3.34–3.x

This release addresses all **three critical Bandit patterns** and **57 Qt6
static compatibility findings** reported for 0.4.0 by the QGIS Plugin
Repository scanner.

## Security corrections

1. **SQL deletion** (formerly `db.py` around line 396): removed
   f-string SQL table interpolation. Each supported record type has its own
   fixed SQL statement and parameterised values. Unknown record types
   are rejected before any deletion.
2. **XML output** (formerly `model_core.py` line 14): removed the
   `xml.sax.saxutils.quoteattr` import that the QGIS scanner flagged.
   For writing the VTK XML scene, use `html.escape(..., quote=True)` to
   escape attributes safely. No untrusted XML parsing is introduced.
3. **ParaView launch** (formerly `model_ui.py` around line 215):
   removed `subprocess.Popen` and replaced it with the native Qt
   `QProcess.startDetached` API with an explicit argument list and a
   system-discovered executable. Never invokes a shell.

## Qt6 compatibility clean-up

All 57 flagged enum accesses and the `exec_()` methods were migrated
to fully scoped Qt enum names and `exec()`. This preserves runtime
support for the installed QGIS 3.34.4/Qt5 environment.

**Important:** These changes address the static scan findings. QGIS 4
runtime testing has not yet been completed. The official QGIS repository
must scan the *new version* before it can be approved.

## Checks

- 20 Python unit tests passed, including VTK output and interval data.
- Legacy QGIS 0.1, 0.2 and 0.3 offscreen smoke tests passed on Qt5.
- QGIS 0.4 offscreen test passed with three wells, 100 surface faces
  and two valid 3D geological volumes.
- ZIP archive integrity and original source-to-public mirror equality
  are checked before publication.
- Static source review confirmed none of the reported pattern strings
  remain in the 14 Python source files.
- The official Bandit, detect-secrets and Qt6 scanners must be rerun on the
  QGIS website after upload; no local Bandit installation was available.

## Unchanged functionality and limitations

Wells, lithological intervals, formation tops, groundwater and
temperature observations, 2D section interpretation, local preliminary
3D interpolation, independent ParaView export, dark/light themes and the
feedback links remain available.

This is still a **conceptual geological modelling prototype**, not
a validated engineering or geothermal reservoir simulator.

Feedback: **tzuk.ls@outlook.com**
Videos: **https://www.youtube.com/@Ground-Surf**

Public GPL plugin source:
https://github.com/wtzet-eng/groundsurf-geothermal-qgis

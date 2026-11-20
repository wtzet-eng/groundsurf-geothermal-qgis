# GroundSurf Geothermal 0.4.13 — Separate Modelling Studio and ParaView Python Shell fix

Experimental free QGIS 3.34–3.x plugin • 20 November 2026

## A simpler QGIS dock and a proper geological modelling window

The QGIS dock continues to offer **Import from QGIS**, **New/Open project**,
optional additional tools and a short project status. Its main action
**OPEN STUDIO ↗** now opens a separate, larger, resizable, non-modal
**GroundSurf Modelling Studio** window.

The Studio contains the existing live Project Explorer, geographic
Wells/Maps, Local XYZ boreholes and contacts, formations, cross-sections,
saved conceptual 3D models, ParaView display controls and safe model
deletion.

A successful **Import from QGIS** opens Studio automatically on the
corresponding imported-data tab. Closing Studio moves all the same
widgets back into the original QGIS dock. The project database and
source layers are **not duplicated**, and Studio requires no new
web/backend service. QGIS remains the host application.

## Fix: ParaView NameError — __file__ is not defined

In some ParaView 6.2 GUI Python Shell and --script execution contexts,
the viewer script is evaluated as Python text without defining
__file__. Previously, this produced a Python NameError even though
the geological model and VTK files had exported successfully.

- The GroundSurf **Open in ParaView** action now creates a small local
  open_with_groundsurf.py wrapper that calls runpy.run_path with the
  selected scene's absolute filename, supplying __file__ to even older
  0.4.9–0.4.12 exported viewer scripts.
- New model exports also embed a source-folder fallback. The scene
  script can locate model.json and appearance.json using its own
  filename, the active working directory or the embedded folder.
- Older model.vtm files and source geological data are **not rewritten**.
  Models without a styled script continue to open as VTK files.

### Manual workaround

If you are using an older viewer script through ParaView's Python Shell,
run:

    import runpy
    runpy.run_path("/absolute/path/to/view_in_paraview.py",
                   run_name="__main__")

Replace the example with the actual path. With 0.4.13, prefer the
GroundSurf **Open in ParaView** button.

## Verification

- Synthetic QGIS 3.34/Qt5 test checks Studio open/reuse, shared widgets,
  theme, close/reparent/reopen and plugin unload without any change to
  the GeoPackage's local XYZ records.
- Existing QGIS import and 3D model launch tests updated for the
  automatic Studio and runpy launcher.
- **Actual ParaView 6.2.0 pvpython** tested both a newly generated scene
  and an older 0.4.12 scene with caller __file__ undefined, including
  an unrelated current working directory.
- Full Python unit/QGIS integration suite and ZIP validation run for
  release; official QGIS repository static, security and Qt6 scans
  are still required separately after upload.

Scientific limits remain unchanged: conceptual IDW model only, no
verified geographical CRS for local XYZ and no calibrated heat-flow or
geostatistical uncertainty simulation.

Source: https://github.com/wtzet-eng/groundsurf-geothermal-qgis
Feedback: tzuk.ls@outlook.com

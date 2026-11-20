# GroundSurf Geothermal 0.4.9 — Geology-first ParaView presentation

Experimental, offline QGIS 3.34–3.x plugin • November 20, 2026

## A more readable 3D geological model

GroundSurf now exports a **prepared ParaView scene** alongside the
original VTK multiblock model:

- **Consistent geological colours** for Quaternary, Pleistocene,
  Palaeogene, Cretaceous and other formations (stable fallback palette
  for unfamiliar labels).
- **Separate, selectable geological unit sources** in the ParaView
  Pipeline Browser. Toggle individual formations using eye icons.
- **Source borehole/contact overlays**: observed/source-derived contact
  points and schematic vertical well sticks are exported as separate
  PolyData. These are not surveyed deviated well paths.
- **Compact, colour-coded geological legend**, dark `#212121` scene
  and **oblique geological camera** instead of the initial plan view.
- Interpolated horizon overlays are retained but hidden by default
  to prevent coincident volume faces causing visual flicker.
- **Optional display-only vertical exaggeration**, 0.5–10×
  (default 1×), chosen in QGIS before building the model.
  Source borehole markers can be enabled/disabled.

Click **3D Models → Open in ParaView** to open the styled scene.
New models launch the official ParaView GUI `--script` option.
Previously exported models (without this file) continue to load
their original `model.vtm` as before.

The original `model.vtm`, volume wedges, geological surface elevations,
thickness data, input XYZ and source CRS are preserved. For full
reproducibility, `model.json` lists all observations and warnings;
`appearance.json` records palette, Z display scale and overlays.

### Data support is not statistical uncertainty

Each surface has a `Distance_to_nearest_well_m` point field and each
volume has a corresponding cell field. Select this field in
ParaView's **Color By** menu to review where interpolation is
well-supported by nearby inputs and where it is more distant.

**Important:** This is spatial proximity only—not a confidence
percentage, probability, standard error or validated geological
uncertainty. No modelled 3D surface should be interpreted as observed
ground truth between boreholes.

### ParaView script details

GroundSurf includes a self-contained `view_in_paraview.py` in each
new output folder. It uses ParaView's own Python API and can also be
run from **Tools → Python Shell → Run Script** in an existing ParaView
session. A separate `appearance.json` allows subsequent adjustment
of display exaggeration or borehole visibility without changing the
model files.

## Verification

- Original 20 Python unit tests and 10 QGIS 3.34/Qt5 smoke tests retained.
- New synthetic display regression validates stable colours, true
  observed marker geometry, all VTK XML arrays, saved presentation
  settings and original unchanged multiblock wedge geometries.
- New QGIS UI test confirms Z exaggeration settings, borings toggle
  and the command line `--script` launch with fallback for old models.
- Full ParaView **6.2.0** Python engine ran the generated script and
  produced a 1350×870 offscreen screenshot; the previously clipped
  plan view was corrected to an oblique camera.
- All fixtures are synthetic; no exact user project coordinates are
  published in tests.
- Official QGIS code quality, security and Qt6 static scanning is
  still required after uploading 0.4.9; QGIS 4 runtime not validated.

## Limits

Preliminary geological IDW interpolation only. Source strata labels
are not independently correlated, and source point/derived contact
observations may contain uncertainty. No faults, folds, anisotropic
geostatistics, calibrated uncertainty quantification, groundwater
flow or geothermal heat-transport simulation.

Feedback: tzuk.ls@outlook.com
Video demos: https://www.youtube.com/@Ground-Surf
Public GPL-2.0-or-later repository:
https://github.com/wtzet-eng/groundsurf-geothermal-qgis

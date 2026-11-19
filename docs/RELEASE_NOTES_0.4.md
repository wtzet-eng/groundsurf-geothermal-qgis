# GroundSurf Geothermal 0.4.0 — Preliminary 3D Modelling

Experimental developer release • QGIS 3.34–3.x • GPL-2.0-or-later

## First actual 3D geometry

- Build terrain and formation-top surfaces from **3 or more spatially separate
  boreholes**, using only horizons shared by the contributing wells.
- Produce volume blocks between consecutive contact surfaces as real VTK
  triangular-wedge cells, and save surface meshes as ParaView-readable VTP.
- Generate a model.vtm scene file and model.json manifest documenting
  contributing wells, depth constraints, CRS, elevation datum, method,
  warnings, input provenance, generated output and limitations.
- Register model runs in the existing local GeoPackage with a reproducibility
  hash and relative path.
- Open a model in ParaView (optional independent desktop installation), or
  inspect its local results folder.
- Keep the existing well manager, cross-sections, ground measurements,
  dark/light themes and feedback/tour links.

## Model method

An original, small IDW interpolation routine in Python (power=2) smooths
horizon elevation between observed/interpreted formation contacts.
Planar Delaunay triangulation and face subdivision define the 3D surface
mesh. Wedge cells connect successive surfaces into preliminary geological
volume units. The method honours contact elevations at the wells and
does not extrapolate beyond their footprint.

This is **not a structural modeller, a groundwater or geothermal flow solver,
or a validated subsurface reservoir interpretation**. Do not use results for
engineering decisions without appropriate professional verification.

## Well and spatial restrictions

- Three or more non-collinear wells, all with surveyed or explicitly
  labelled ground elevations in one vertical datum.
- At least one matching subsurface formation contact across included wells.
- Formation contacts consistently ordered down each contributing well.
- No fault offsets or deviated wells; vertical well paths only.
- Maximum 50 km span, 150 wells and 80,000 mesh cells per preliminary model.
- Incomplete well constraints are listed as excluded, rather than invented.
- Synthetic data from the examples use `DEMO-UNDEFINED` vertical datum,
  with a prominent warning. They must not be treated as real survey heights.

## Testing

- Pure Python numerical tests confirm input validation, contact honouring,
  positive unit thickness, triangulation and VTK XML structure.
- QGIS 3.34.4 offscreen test generates a complete three-well, two-volume
  example and saves/reopens the model catalogue.
- ParaView 6.2.0 on Ubuntu successfully reads the resulting multiblock
  VTM scene, with 3 surfaces and 2 unstructured volume datasets.
- The existing versions 0.1, 0.2 and 0.3 regression tests are retained.

## Contact and tutorials

Feedback: **tzuk.ls@outlook.com**
Video demonstrations: **https://www.youtube.com/@Ground-Surf**

## QGIS publication

The QGIS plugin and the numerical code distributed inside it are open source
under GPL-2.0-or-later. Public source repository:
https://github.com/wtzet-eng/groundsurf-geothermal-qgis

Separate future research components and unreleased simulation modules may be
developed privately, subject to the licences of any libraries actually used.
All user geological data remain on their own computer.

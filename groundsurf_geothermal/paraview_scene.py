"""GroundSurf ParaView interactive geology scene — Python Shell compatible.

A COPY of this file is placed beside model.vtm and appearance.json. ParaView
loads this file with --script, or via View > Python Shell > Run Script.

The original VTK point coordinates and scalars remain unchanged. For unit
display we load each .vtu as a distinct togglable pipeline source and apply
user-picked colours (not Thickness_m). Observations load as separate overlays.
"""
import json
import os
from pathlib import Path

from paraview import simple as pvs


def _rgb(text):
    return [int(text[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]


def _safe_property(proxy, name, value):
    """Cope with optional ParaView properties across 5.12–6.2."""
    try:
        setattr(proxy, name, value)
        return True
    except Exception as exc:
        # ParaView may throw NotSupportedException (rather than
        # AttributeError) when a property is removed in a newer GUI.
        print("[GroundSurf] Optional display property", name, ":", exc)
        return False


def _colour(display, hex_code):
    rgb = _rgb(hex_code)
    try:
        pvs.ColorBy(display, None)
    except RuntimeError:
        # ParaView 6.2 rejects a NONE association for vtkPolyData with
        # no active scalar field (observed well sticks, etc.).
        _safe_property(display, "ColorArrayName", [None, ""])
    _safe_property(display, "DiffuseColor", rgb)
    _safe_property(display, "AmbientColor", rgb)
    _safe_property(display, "Specular", 0.1)


def _vis_source(path, label, view, factor, colour, kind="unit"):
    reader = pvs.OpenDataFile(str(path))
    if reader is None:
        raise RuntimeError("ParaView could not read " + str(path))
    pvs.RenameSource(label, reader)
    upstream = reader
    if abs(factor - 1.0) > 1e-8:
        scaled = pvs.Transform(Input=reader)
        scaled.Transform = "Transform"
        scaled.Transform.Scale = [1.0, 1.0, factor]
        pvs.RenameSource(label + " · display Z×" + str(factor), scaled)
        upstream = scaled
    display = pvs.Show(upstream, view)
    _colour(display, colour)
    if kind == "borehole":
        _safe_property(display, "Representation", "Wireframe")
        _safe_property(display, "LineWidth", 3.5)
    elif kind == "contact":
        _safe_property(display, "Representation", "Points")
        _safe_property(display, "PointSize", 9)
    else:
        _safe_property(display, "Representation", "Surface")
        _safe_property(display, "Opacity", 1.0)
    return upstream, display


def _legend_item(view, line, colour, index, count):
    # Text objects can be toggled as well, using the pipeline eye icon.
    try:
        source = pvs.Text()
        source.Text = str(line)
        pvs.RenameSource("Legend · " + str(line), source)
        rep = pvs.Show(source, view)
        _safe_property(rep, "WindowLocation", "Any Location")
        _safe_property(rep, "Position", [0.025, 0.92 - index * 0.039])
        _safe_property(rep, "Color", _rgb(colour))
        _safe_property(rep, "FontSize", 12)
        _safe_property(rep, "Bold", 0)
    except (AttributeError, RuntimeError, ValueError, TypeError) as exc:
        print("[GroundSurf] Legend text unavailable:", exc)


def main():
    here = Path(__file__).resolve().parent
    scene = json.loads((here / "appearance.json").read_text(encoding="utf-8"))
    model = json.loads((here / "model.json").read_text(encoding="utf-8"))
    by_label = {
        item["label"]: item["file"] for item in model["outputs"]
    }
    factor = float(scene.get("vertical_exaggeration", 1.0))
    if not 0.5 <= factor <= 10.0:
        raise ValueError("Unsupported vertical exaggeration")
    view = pvs.GetActiveViewOrCreate("RenderView")
    _safe_property(view, "UseColorPaletteForBackground", 0)
    _safe_property(view, "BackgroundColorMode", "Single Color")
    _safe_property(view, "Background", _rgb(scene.get("background", "#212121")))
    _safe_property(view, "ViewSize", [1300, 850])

    shown = []
    for index, band in enumerate(scene["bands"]):
        top, lower = band["unit_between"]
        label = "Unit " + top + " to " + lower
        fname = by_label[label]
        if Path(fname).name != fname:
            raise ValueError("Model references an unsafe output path")
        geom = here / fname
        if not geom.is_file():
            raise ValueError("Missing geological geometry: " + str(geom))
        colour = band["color"]
        source, display = _vis_source(
            geom, "GroundSurf | " + label, view, factor, colour
        )
        shown.append((source, display))
        _legend_item(view, str(top), colour, index, len(scene["bands"]))

    observations = scene.get("observations", {})
    if scene.get("show_boreholes", True):
        _vis_source(
            here / observations.get(
                "boreholes_file", "observed-boreholes.vtp"
            ),
            "OBSERVED | Borehole locations · schematic vertical sticks",
            view, factor, "#d8e8e2", "borehole",
        )
    if scene.get("show_contacts", True):
        _vis_source(
            here / observations.get(
                "contact_points_file", "observed-contacts.vtp"
            ),
            "OBSERVED | Source contact elevations (points)",
            view, factor, "#f3f2d8", "contact",
        )
    # Leave interpolation surfaces in the pipeline but hidden by default.
    # Overlapping transparent horizons with opaque unit volumes otherwise
    # produce pixel-fighting artefacts in the viewer.
    if scene.get("load_interpolated_surfaces", True):
        for item in model["outputs"]:
            if not item["label"].startswith("Surface "):
                continue
            geom = here / item["file"]
            name = item["label"]
            reader = pvs.OpenDataFile(str(geom))
            if reader is None:
                continue
            pvs.RenameSource("INTERPOLATED | " + name + " (hidden)", reader)
            if scene.get("show_interpolated_surfaces", False):
                # To avoid z-fighting, these should generally be used
                # INSTEAD OF visible unit volume tops.
                _source, disp = _vis_source(
                    geom, "INTERPOLATED | " + name,
                    view, factor, "#b0b8b0", "unit"
                )
                _safe_property(disp, "Opacity", 0.25)

    # Keep the on-screen legend brief; audit warnings remain in model.json.
    pvs.SetActiveView(view)
    if shown:
        pvs.SetActiveSource(shown[0][0])
    view.ResetCamera()
    # ParaView normally starts from plan (looking down Z). Geological
    # layers need an OBLIQUE perspective, otherwise all four units hide
    # behind the top surface. Use all visible unit bounding boxes.
    import math
    boundaries = []
    for source, _display in shown:
        bounds = source.GetDataInformation().GetBounds()
        if bounds and len(bounds) == 6 and all(math.isfinite(v) for v in bounds):
            boundaries.append(bounds)
    if boundaries:
        x0=min(b[0] for b in boundaries); x1=max(b[1] for b in boundaries)
        y0=min(b[2] for b in boundaries); y1=max(b[3] for b in boundaries)
        z0=min(b[4] for b in boundaries); z1=max(b[5] for b in boundaries)
        cx=(x0+x1)/2; cy=(y0+y1)/2; cz=(z0+z1)/2
        span=max(x1-x0, y1-y0, z1-z0, 1.0)
        _safe_property(view, "CameraFocalPoint", [cx,cy,cz])
        _safe_property(view, "CameraPosition", [
            cx+2.05*span, cy-2.30*span, cz+1.75*span
        ])
        _safe_property(view, "CameraViewUp", [0.,0.,1.])
        _safe_property(view, "CameraParallelScale", 1.10*span)
    # Skipping rendering supports headless integration testing with pvpython.
    if os.environ.get("GROUNDSURF_PV_TEST") != "1":
        pvs.Render(view)
    print(
        "[GroundSurf] Prepared %d geological volume units, with independent "
        "observed contact overlays and Z display ×%g." % (
            len(scene["bands"]), factor
        )
    )
    print(
        "[GroundSurf] Toggle units/observations with the Pipeline Browser eye "
        "icons. Distance_to_nearest_well_m is coverage, NOT uncertainty."
    )
    return view


if __name__ == "__main__" or (
    __name__ == "paraview_scene" and os.environ.get("GROUNDSURF_PV_TEST") == "1"
):
    main()

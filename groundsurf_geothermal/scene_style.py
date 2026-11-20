"""Portable, auditable ParaView geological display styling.

Colours are semantic and stable: the same source unit gets the same colour
across independent exports. Other unit labels use a deterministic palette.
No external packages are required in QGIS or for JSON generation.
"""
import hashlib
import json
from pathlib import Path

BACKGROUND_HEX = "#212121"
DEFAULT_VERTICAL_EXAGGERATION = 1.0

# Interpret colour as a *visual identity*, not confirmed material properties.
# 'Ground' is a bounding horizon, not automatically a geological formation.
NAMED_COLORS = {
    "quaternary": "#6ea9a2",
    "pleistocene": "#d8b989",
    "holocene": "#7dbbb0",
    "palaeogene": "#b98756",
    "paleogene": "#b98756",
    "cretaceous": "#a96750",
    "jurassic": "#527b66",
    "triassic": "#9e7185",
    "base": "#4e5a68",
    "ground": "#97b6a4",
    "soil": "#b9a177",
    "peat": "#80685a",
    "clay": "#9f8269",
    "sand": "#cead6c",
    "sandstone": "#c59f69",
    "limestone": "#7c9b99",
    "granite": "#a17d85",
}
FALLBACK_PALETTE = (
    "#5d9d94", "#d1af78", "#a47c64", "#6f85a3",
    "#aa819a", "#8cab73", "#c47e67", "#779c9f",
    "#b7a078", "#a086a8", "#6b987d", "#ad8d7a",
)


def geology_color(label):
    """Return a stable hex colour for a source geological unit name."""
    text = str(label).strip().casefold()
    for name, colour in NAMED_COLORS.items():
        if text == name or (name not in ("base", "ground")
                           and name in text.split()):
            return colour
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return FALLBACK_PALETTE[int.from_bytes(digest[:4], "big")
                            % len(FALLBACK_PALETTE)]


def rgb01(value):
    h = value.lstrip("#")
    if len(h) != 6:
        raise ValueError("Colours must be six-digit hex values")
    return [int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4)]


def appearance(mesh, vertical_exaggeration=1.0, show_boreholes=True):
    scale = float(vertical_exaggeration)
    if not (0.5 <= scale <= 10.0):
        raise ValueError("Vertical exaggeration must be 0.5–10×")
    if not mesh.get("input_points"):
        raise ValueError("Input well markers are required for this display")
    bands = []
    for top, lower in zip(mesh["horizons"], mesh["horizons"][1:]):
        bands.append({
            "label": str(top),
            "unit_between": [top, lower],
            "color": geology_color(top),
            "description": "Interpreted volume between source contact horizons",
        })
    return {
        "schema": "groundsurf-paraview-appearance-v1",
        "background": BACKGROUND_HEX,
        "vertical_exaggeration": scale,
        "show_boreholes": bool(show_boreholes),
        "show_contacts": bool(show_boreholes),
        "show_interpolated_surfaces": False,
        "show_distance_to_well_by_default": False,
        "colour_meaning": "Categorical unit identity, not thickness or confidence",
        "bands": bands,
        "observations": {
            "boreholes_file": "observed-boreholes.vtp",
            "contact_points_file": "observed-contacts.vtp",
            "meaning": "Schematic vertical sticks joining observed elevation "
                       "contacts; not surveyed trajectories or drilled depths.",
        },
        "interpretation": [
            "Units and contact labels are taken from source data.",
            "Observed contact markers are evidence points; coloured volumes "
            "and surfaces between them are IDW interpolation.",
            "Distance_to_nearest_well_m measures coverage only. It is NOT "
            "a probability or calibrated geostatistical uncertainty.",
            "Vertical exaggeration changes display only, not input XYZ.",
        ],
    }


def save_appearance(folder, mesh, vertical_exaggeration=1.0,
                    show_boreholes=True):
    data = appearance(mesh, vertical_exaggeration, show_boreholes)
    output = Path(folder) / "appearance.json"
    output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output, data

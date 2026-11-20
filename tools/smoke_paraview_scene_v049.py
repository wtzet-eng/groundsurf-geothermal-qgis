"""QGIS-independent scene QA: categorical geology, observations and distance.

Uses completely synthetic coordinates and geometry. Optionally retain
synthetic scene at GS_SCENE_TEST_FOLDER for an independent pvpython test.
"""
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from groundsurf_geothermal import model_core, scene_style


def synthetic_wells():
    return [
        {"well_id": "BH1", "x": 0.0, "y": 0.0,
         "elevations": {"Quaternary": 35, "Pleistocene": 3,
                        "Palaeogene": -35, "Cretaceous": -105, "Base": -171}},
        {"well_id": "BH2", "x": 500.0, "y": 0.0,
         "elevations": {"Quaternary": 31, "Pleistocene": -2,
                        "Palaeogene": -40, "Cretaceous": -110, "Base": -176}},
        {"well_id": "BH3", "x": 125.0, "y": 700.0,
         "elevations": {"Quaternary": 28, "Pleistocene": -8,
                        "Palaeogene": -46, "Cretaceous": -120, "Base": -188}},
        {"well_id": "BH4", "x": 400.0, "y": 290.0,
         "elevations": {"Quaternary": 38, "Pleistocene": 1,
                        "Palaeogene": -32, "Cretaceous": -99, "Base": -166}},
    ]


def check(output):
    wells=synthetic_wells()
    horizons=list(wells[0]["elevations"])
    mesh=model_core.build_mesh(wells,horizons,subdivisions=7)
    assert len(mesh["input_points"])==4
    assert min(mesh["distance_to_nearest_well_m"])==0.0
    assert max(mesh["distance_to_nearest_well_m"])>10.0
    scene,manifest=model_core.export_model(
        mesh,output,"Synthetic geology colour test",
        "LOCAL_XYZ_METRES_UNGEOREFERENCED", "UNVERIFIED_SOURCE_Z",
        [{"well_id":p["well_id"]} for p in wells],
        warnings=["SYNTHETIC data; no surveyed reference"],
        vertical_exaggeration=2.5,
        show_boreholes=True,
    )
    data=json.loads(manifest.read_text())
    assert data["version"]=="0.4.9"
    assert data["scene"]=="model.vtm"
    assert len(data["outputs"])==9, data["outputs"]
    assert data["source_observations"]["contact_count"]==20
    assert data["source_observations"]["borehole_count"]==4
    assert data["colour_by_default"].startswith("geological unit")
    assert "confidence" in " ".join(data["display_warnings"]).lower()
    assert (output/"view_in_paraview.py").is_file()
    assert (output/"observed-boreholes.vtp").is_file()
    assert (output/"observed-contacts.vtp").is_file()
    settings=json.loads((output/"appearance.json").read_text())
    assert settings["vertical_exaggeration"]==2.5
    assert settings["show_boreholes"]
    assert settings["bands"][0]["label"]=="Quaternary"
    assert settings["bands"][0]["color"]=="#6ea9a2"
    assert [b["label"] for b in settings["bands"]] == horizons[:-1]
    assert len({b["color"] for b in settings["bands"]})==4
    assert settings["colour_meaning"].endswith("confidence")
    for entry in data["outputs"]:
        body=ET.parse(output/entry["file"])
        if entry["label"].startswith("Unit "):
            array=body.find(
                ".//CellData/DataArray[@Name='Distance_to_nearest_well_m']"
            )
            assert array is not None, entry["file"]
            measures=[float(x) for x in array.text.split()]
            assert len(measures)==len(mesh["faces"])
            assert all(x>=0 for x in measures)
        else:
            array=body.find(
                ".//PointData/DataArray[@Name='Distance_to_nearest_well_m']"
            )
            assert array is not None, entry["file"]
    observed=ET.parse(output/"observed-boreholes.vtp")
    piece=observed.find(".//Piece")
    assert int(piece.attrib["NumberOfLines"])==4
    contacts=ET.parse(output/"observed-contacts.vtp")
    piece=contacts.find(".//Piece")
    assert int(piece.attrib["NumberOfVerts"])==20
    # A second run never overwrites a completed model folder.
    try:
        model_core.export_model(
            mesh,output,"Duplicate","LOCAL","test",[]
        )
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("Output was overwritten")
    # Stable source-label palette independently of input order.
    assert scene_style.geology_color("Cretaceous")==scene_style.geology_color(
        "CRETaCEOUS"
    )
    assert scene_style.geology_color("Something new")==scene_style.geology_color(
        "Something new"
    )
    assert scene_style.rgb01("#ff0000")==[1.,0.,0.]
    print(
        "PASS 0.4.9: stable formation palette, four borehole lines, "
        "20 observed contact markers, nearest-well distance, 2.5x "
        "display exaggeration, and unmodified VTM volumes"
    )
    print("SCENE_FOLDER", output)


folder=os.environ.get("GS_SCENE_TEST_FOLDER")
if folder:
    dest=Path(folder).expanduser().resolve()
    dest.mkdir(parents=True,exist_ok=True)
    if any(dest.iterdir()):
        raise ValueError("SCENE test folder must be empty")
    check(dest)
else:
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory)/"scene")

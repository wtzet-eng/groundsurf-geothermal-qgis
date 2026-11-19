"""Dependency-free numerical tests for the preliminary 3D modelling kernel."""
import json
import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from groundsurf_geothermal import model_core as mc


def wells():
    return [
        dict(well_id="A",x=0.,y=0.,elevations={"ground":105.,"C":90.,"B":60.}),
        dict(well_id="B",x=100.,y=0.,elevations={"ground":110.,"C":92.,"B":51.}),
        dict(well_id="C",x=15.,y=85.,elevations={"ground":103.,"C":88.,"B":48.}),
        dict(well_id="D",x=40.,y=35.,elevations={"ground":106.,"C":94.,"B":52.}),
    ]


class PreliminaryModelTests(unittest.TestCase):
    def test_idw_honours_well_and_positive_thickness(self):
        w=wells()
        mesh=mc.build_mesh(w,["ground","C","B"],subdivisions=8)
        self.assertGreater(len(mesh["faces"]),30)
        self.assertGreater(len(mesh["vertices"]),30)
        self.assertTrue(all(v>0 for v in mesh["min_thickness_by_unit_m"].values()))
        for well in w:
            match=[h for x,y,h in mesh["vertices"] if math.hypot(x-well["x"],y-well["y"])<1e-6]
            self.assertEqual(len(match),1)
            for code,z in well["elevations"].items():
                self.assertAlmostEqual(match[0][code],z,places=7)

    def test_vtk_label_escaping(self):
        names=["ground", "C\"<&"]
        inputs=wells()
        for well in inputs:
            well["elevations"][names[1]]=well["elevations"].pop("C")
        mesh=mc.build_mesh(inputs,names,3)
        with tempfile.TemporaryDirectory() as tmp:
            scene,_=mc.export_model(mesh,Path(tmp)/"special","Labels",
                                    "EPSG:32633","test",[])
            self.assertEqual(len(ET.parse(scene).findall(
                "vtkMultiBlockDataSet/DataSet")),3)

    def test_invalid_or_inconsistent(self):
        with self.assertRaisesRegex(ValueError,"3"):
            mc.build_mesh(wells()[:2],["ground","C"])
        wrong=wells()
        wrong[0]["elevations"]["B"]=150
        with self.assertRaisesRegex(ValueError,"thickness"):
            mc.build_mesh(wrong,["ground","C","B"])
        with self.assertRaisesRegex(ValueError,"Subdivisions"):
            mc.build_mesh(wells(),["ground","C"],subdivisions=0)
        w=wells()
        w[2]["x"]=w[0]["x"]
        w[2]["y"]=w[0]["y"]
        with self.assertRaisesRegex(ValueError,"coincide"):
            mc.build_mesh(w,["ground","C","B"])

    def test_collinear_rejected(self):
        collinear=[
            dict(well_id=str(i), x=i*200.,y=0.,elevations={"ground":0.,"C":-20.})
            for i in range(3)
        ]
        with self.assertRaisesRegex(ValueError,"Non-collinear"):
            mc.build_mesh(collinear,["ground","C"])

    def test_vtk_export_readable(self):
        mesh=mc.build_mesh(wells(),["ground","C","B"],6)
        with tempfile.TemporaryDirectory() as root:
            scene,manifest=mc.export_model(
                mesh,Path(root)/"run", "Synthetic", "EPSG:32633",
                "synthetic-m", [{"well_id":w["well_id"]} for w in wells()],
                warnings=["Synthetic only"],
            )
            self.assertTrue(scene.is_file())
            self.assertEqual(ET.parse(scene).getroot().attrib["type"],
                             "vtkMultiBlockDataSet")
            details=json.loads(manifest.read_text())
            self.assertEqual(details["triangle_count"],len(mesh["faces"]))
            self.assertEqual(len(details["outputs"]),5) # 3 surfaces, 2 volumes
            for result in details["outputs"]:
                rootxml=ET.parse(scene.parent/result["file"]).getroot()
                self.assertIn(rootxml.attrib["type"],["PolyData","UnstructuredGrid"])
            # VTK wedge cells: one per triangle, six vertices per cell.
            wedges=ET.parse(scene.parent/"unit-ground-to-c.vtu")
            piece=wedges.find("UnstructuredGrid/Piece")
            self.assertEqual(int(piece.attrib["NumberOfCells"]),len(mesh["faces"]))
            self.assertEqual(int(piece.attrib["NumberOfPoints"]),
                             2*len(mesh["vertices"]))
            with self.assertRaisesRegex(ValueError,"empty"):
                mc.export_model(mesh,scene.parent,"Again","EPSG:32633","datum",[])


if __name__=="__main__":
    unittest.main()

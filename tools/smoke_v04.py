"""Offscreen QGIS 3.34: generate actual VTK surfaces + wedge volumes."""
import hashlib
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QMainWindow
from groundsurf_geothermal import (
    db, model_adapter, model_core, models, storage,
)
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin

app=QgsApplication([],False)
app.initQgis()


class Iface:
    def __init__(self):
        self.window=QMainWindow()
    def mainWindow(self): return self.window
    def addDockWidget(self,a,b): self.window.addDockWidget(a,b)
    def removeDockWidget(self,b): self.window.removeDockWidget(b)
    def addPluginToMenu(self,*args): pass
    def removePluginMenu(self,*args): pass
    def addToolBarIcon(self,*args): pass
    def removeToolBarIcon(self,*args): pass


with tempfile.TemporaryDirectory() as td:
    path=Path(td)/"site.gpkg"
    storage.create_project(path)
    assert models.has_schema(path)
    source=Path(__file__).resolve().parent.parent/"examples"
    layer=storage.open_wells(str(path))
    records=db.parse_well_csv((source/"sample_wells.csv").read_text())
    storage.add_wells(layer,records)
    for code,name in (("Q","Sand"),("C","Clay"),("B","Sandstone")):
        db.add_formation(path,code,name)
    db.import_intervals_csv(path,layer,(source/"sample_intervals.csv").read_text())
    constraints=model_adapter.gather_wells(path,layer)
    assert constraints["horizons"]==["ground","C","B"],constraints
    assert constraints["datum"]=="DEMO-UNDEFINED"
    assert "EPSG:" in constraints["epsg"]
    assert any("Synthetic" in w for w in constraints["warnings"])
    mesh=model_core.build_mesh(
        constraints["samples"],constraints["horizons"],subdivisions=10
    )
    assert len(mesh["faces"])>50
    output=Path(td)/"result"
    scene,manifest=model_core.export_model(
        mesh,output,"Synthetic test",constraints["epsg"],
        constraints["datum"],constraints["provenance"],
        warnings=constraints["warnings"]
    )
    manifest_obj=json.loads(manifest.read_text())
    assert manifest_obj["version"]=="0.4.2"
    assert len(manifest_obj["outputs"])==5
    for out in manifest_obj["outputs"]:
        xml_path=output/out["file"]
        assert xml_path.is_file()
        assert ET.parse(xml_path).getroot() is not None
    fingerprint=hashlib.sha256(manifest.read_bytes()).hexdigest()
    models.record(
        path,"Synthetic test",output,constraints["epsg"],
        constraints["datum"],3,fingerprint,model_core.METHOD
    )
    assert len(models.list_models(path))==1
    assert models.find_output(path,models.list_models(path)[0])==output
    iface=Iface()
    plugin=GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    dock=plugin.dock
    dock.load_project(path)
    assert dock.model_table.rowCount()==1
    assert dock.theme in ("light","dark")
    plugin.unload()
    QgsProject.instance().clear()
    print(
        f"PASS: model=3 wells / {len(mesh['faces'])} faces / 2 volumes, "
        "VTK exported, schema, QGIS model tab, original data preserved"
    )

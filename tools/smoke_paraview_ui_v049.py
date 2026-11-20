"""QGIS 3 presentation UI smoke test without launching GUI ParaView."""
import json
import os
from pathlib import Path
import tempfile
from qgis.core import QgsApplication,QgsProject
from qgis.PyQt.QtWidgets import QMainWindow
from groundsurf_geothermal import model_core, models, storage
from groundsurf_geothermal import model_ui as ui_module
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
app=QgsApplication([],False)
app.initQgis()


class Iface:
    def __init__(self): self.window=QMainWindow()
    def mainWindow(self): return self.window
    def addDockWidget(self, area, widget): self.window.addDockWidget(area,widget)
    def removeDockWidget(self, widget): self.window.removeDockWidget(widget)
    def addPluginToMenu(self,*args): pass
    def removePluginMenu(self,*args): pass
    def addToolBarIcon(self,*args): pass
    def removeToolBarIcon(self,*args): pass


def wells():
    return [
        {"well_id":"A","x":0.,"y":0.,"elevations":{"Quaternary":30,"Cretaceous":-20,"Base":-100}},
        {"well_id":"B","x":200.,"y":0.,"elevations":{"Quaternary":33,"Cretaceous":-22,"Base":-106}},
        {"well_id":"C","x":80.,"y":300.,"elevations":{"Quaternary":32,"Cretaceous":-15,"Base":-90}},
    ]


with tempfile.TemporaryDirectory() as folder:
    gpkg=Path(folder)/"model_ui.gpkg"
    storage.create_project(gpkg)
    mesh=model_core.build_mesh(
        wells(),["Quaternary","Cretaceous","Base"],6
    )
    scene_folder=Path(folder)/"styled"
    scene,meta=model_core.export_model(
        mesh,scene_folder,"Styled model","LOCAL_XYZ_METRES_UNGEOREFERENCED",
        "UNVERIFIED",[{"well_id":p["well_id"]} for p in wells()],
        vertical_exaggeration=1.5,show_boreholes=True
    )
    models.record(
        gpkg,"Styled model",scene_folder,"LOCAL_XYZ_METRES_UNGEOREFERENCED",
        "UNVERIFIED",3,"synthetic","IDW test"
    )
    iface=Iface(); plugin=GroundSurfGeothermalPlugin(iface)
    plugin.initGui();plugin.open_dock()
    dock=plugin.dock;dock.load_project(str(gpkg))
    assert dock.model_table.rowCount()==1
    assert dock.scene_vertical.minimum()==0.5
    assert dock.scene_vertical.maximum()==10.0
    dock.scene_vertical.setValue(3.5)
    assert float(dock.settings.value("3d_vertical_exaggeration"))==3.5
    assert dock.show_boreholes.isChecked()
    assert dock.model_source.count()==3
    dock.model_table.selectRow(0)
    fake_calls=[]
    class QStd:
        @staticmethod
        def findExecutable(name):
            assert name=="paraview"
            return "/usr/bin/fake-test-paraview"
    class QProc:
        @staticmethod
        def startDetached(executable,args,workdir):
            fake_calls.append((executable,list(args),workdir))
            return True,123
    oldpath=ui_module.QStandardPaths
    oldproc=ui_module.QProcess
    ui_module.QStandardPaths=QStd
    ui_module.QProcess=QProc
    try:
        dock.open_in_paraview()
        assert len(fake_calls)==1
        executable,args,workdir=fake_calls[-1]
        assert args==["--script",str(scene_folder/"view_in_paraview.py")],args
        assert workdir==str(scene_folder)
        # A legacy saved model without a new style script falls back
        # to its original VTM reader without changing the file.
        (scene_folder/"view_in_paraview.py").rename(
            scene_folder/"preserved-script-for-test.py"
        )
        dock.open_in_paraview()
        assert fake_calls[-1][1]==[str(scene_folder/"model.vtm")]
    finally:
        ui_module.QStandardPaths=oldpath
        ui_module.QProcess=oldproc
    dock.scene_vertical.setValue(1.0)  # return to default for other tests
    plugin.unload()
    QgsProject.instance().clear()
    print(
        "PASS v0.4.9: QGIS vertical exaggeration range and settings; "
        "Open in ParaView --script, preserved backward-compatible VTM fallback"
    )

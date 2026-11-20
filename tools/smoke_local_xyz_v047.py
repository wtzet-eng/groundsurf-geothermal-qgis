"""QGIS 3 integration: import local engineering XYZ WITHOUT falsely assigning CRS.

Fully fabricated 50 record / ten borehole PointZ test, consistent with
the user's field layout but deliberately not publishing user coordinates.
"""
import json
import tempfile
from pathlib import Path

from qgis.core import (
    QgsApplication, QgsFeature, QgsField, QgsGeometry, QgsPoint,
    QgsProject, QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QDialog, QMessageBox, QMainWindow

from groundsurf_geothermal import (
    elevation_import, local_xyz, model_core, models, storage,
)
from groundsurf_geothermal import plugin as plugin_module
from groundsurf_geothermal import model_ui as model_ui_module
from groundsurf_geothermal.qgis_import import ImportFromQGISDialog

app=QgsApplication([], False)
app.initQgis()

def sample_layer():
    layer=QgsVectorLayer("PointZ?crs=EPSG:4326","Invented local XYZ","memory")
    layer.dataProvider().addAttributes([
        QgsField("ID", QVariant.String), QgsField("X", QVariant.Double),
        QgsField("Y", QVariant.Double), QgsField("Z", QVariant.Double),
        QgsField("Strata", QVariant.String),
    ])
    layer.updateFields()
    units=["Base","Cretaceous","Palaeogene","Pleistocene","Quaternary"]
    for i in range(10):
        well=f"BH{i+1}"
        x,y = 600200.+i*240, 5800100.+(i*i%13)*125
        # realistic thickness ordering, with one ambiguous unit as a test.
        heights=[-185.-i,-150.-i,-90.-i,-30.+i,25.+i]
        for j,(code,z) in enumerate(zip(units,heights)):
            if well=="BH8" and j==0:
                code="Cretaceous"
            feature=QgsFeature(layer.fields())
            feature.setAttributes([well,x,y,z,code])
            feature.setGeometry(QgsGeometry(QgsPoint(x,y,z)))
            assert layer.dataProvider().addFeatures([feature])[0]
    layer.updateExtents()
    assert layer.featureCount()==50
    return layer

class Iface:
    def __init__(self,active):
        self.active=active;self.window=QMainWindow()
    def mainWindow(self): return self.window
    def activeLayer(self): return self.active
    def addDockWidget(self,area,dock): self.window.addDockWidget(area,dock)
    def removeDockWidget(self,dock): self.window.removeDockWidget(dock)
    def addPluginToMenu(self,*args): pass
    def removePluginMenu(self,*args): pass
    def addToolBarIcon(self,*args): pass
    def removeToolBarIcon(self,*args): pass

with tempfile.TemporaryDirectory() as folder:
    original=sample_layer()
    QgsProject.instance().addMapLayer(original)
    before=[(f.id(),f.geometry().asWkt(),f.attributes())
            for f in original.getFeatures()]
    suggested=elevation_import.detect_fields(
        [field.name() for field in original.fields()]
    )
    assert suggested == {
        "well_id":"ID","formation_code":"Strata","elevation_m":"Z",
        "x":"X","y":"Y"
    }
    dialog=ImportFromQGISDialog(preferred_layer_id=original.id())
    assert dialog.mode_combo.currentData()=="local_xyz",dialog.mode_combo.currentData()
    assert not dialog.local_confirm.isChecked()
    assert not dialog.source_crs.isVisible() or dialog.mode_combo.currentData()=="local_xyz"
    dialog.local_confirm.setChecked(True)
    dialog.vertical_reference.setText("")
    dialog.use_xy_fields.setChecked(True)
    dialog.accept()
    selection=dialog.selection()
    assert selection["mode"]=="local_xyz"
    assert selection["local_metre_confirmed"]
    staged=local_xyz.prepare_local(
        original,selection["fields"],
        use_xy_fields=selection["use_xy_fields"],
        use_geometry_z=selection["use_geometry_z"],
        selected_only=selection["selected_only"],
        vertical_reference=selection["vertical_datum"],
    )
    assert staged["well_count"]==10 and staged["contact_count"]==50
    assert staged["source_layer_crs_claim"]=="EPSG:4326"
    assert len(staged["ambiguous"])==1
    assert staged["ambiguous"][0][0]=="BH8"
    assert "UNVERIFIED" in staged["vertical_reference"]

    project=Path(folder)/"local_project.gpkg"
    storage.create_project(project)
    assert local_xyz.has_schema(project)
    well_layer=storage.open_wells(project)
    before_well_count=well_layer.featureCount()
    assert before_well_count==0
    batch_id=local_xyz.store_batch(project,staged)
    assert len(local_xyz.list_batches(project))==1
    rows=local_xyz.list_contacts(project,batch_id)
    assert len(rows)==50
    assert any(r[1]=="BH1" and r[3]==600200. for r in rows)
    assert any(r[1]=="BH8" and r[2]=="Cretaceous" for r in rows)
    assert well_layer.featureCount()==0, "Unlocated XY must NOT become fake WGS84!"
    inputs=local_xyz.model_inputs(project,batch_id)
    assert inputs["epsg"]==local_xyz.BASIS
    assert len(inputs["samples"])==9
    assert len(inputs["horizons"])==5
    assert len(inputs["excluded_wells"])==1
    assert inputs["excluded_wells"][0].startswith("BH8:")
    assert inputs["datum"]=="UNVERIFIED_SOURCE_Z"
    assert inputs["local_origin_m"]["x"]>600200
    mesh=model_core.build_mesh(inputs["samples"],inputs["horizons"],4)
    assert mesh["input_wells"]==9
    output=Path(folder)/"paraview_local"
    scene,manifest=model_core.export_model(
        mesh,output,"Test LOCAL XYZ",inputs["epsg"],inputs["datum"],
        inputs["provenance"],warnings=inputs["warnings"]
    )
    assert scene.is_file() and manifest.is_file()
    assert all(abs(v[0])<3000 and abs(v[1])<3000
               for v in mesh["vertices"])
    original_coords=[(r[3],r[4]) for r in rows]
    assert min(x for x,y in original_coords)>600000
    assert len(list(output.glob("surface-*.vtp")))==5
    print("PASS local XYZ: original metre coordinates preserved, centred 3D mesh exported")

    iface=Iface(original)
    plugin=plugin_module.GroundSurfGeothermalPlugin(iface)
    plugin.initGui();plugin.open_dock()
    dock=plugin.dock
    dock.load_project(str(project))
    assert dock.wells_table.rowCount()==0
    assert dock.local_table.rowCount()==50
    assert dock.local_batch_combo.currentData()==batch_id
    assert "50 records" in dock.local_summary.text()
    dock.model_source.setCurrentIndex(
        dock.model_source.findData("local_xyz")
    )
    assert dock.model_source.currentData()=="local_xyz"

    # Trigger actual plugin import path into second GeoPackage.
    second=Path(folder)/"action_project.gpkg"
    storage.create_project(second)
    dock.load_project(str(second))
    class FakeDialog:
        def __init__(self,**kwargs):
            self.layers=[original]
            assert kwargs["preferred_layer_id"]==original.id()
        def exec(self): return QDialog.DialogCode.Accepted
        def selection(self): return selection
    class Confirm:
        StandardButton=QMessageBox.StandardButton
        @staticmethod
        def question(*args,**kwargs):return QMessageBox.StandardButton.Yes
    previous_dialog=plugin_module.ImportFromQGISDialog
    previous_box=plugin_module.QMessageBox
    plugin_module.ImportFromQGISDialog=FakeDialog
    plugin_module.QMessageBox=Confirm
    try:
        dock.import_from_qgis()
    finally:
        plugin_module.ImportFromQGISDialog=previous_dialog
        plugin_module.QMessageBox=previous_box
    assert dock.local_table.rowCount()==50
    assert dock.wells_table.rowCount()==0
    assert dock.tabs.currentWidget()==dock.local_xyz_tab
    assert dock.model_source.currentData()=="local_xyz"
    assert "NO" not in dock.status.text() or "No geographic" in dock.status.text()
    assert "No geographic CRS assigned" in dock.status.text()

    # Actual GroundSurf 3D Models UI creates a ParaView scene, registers
    # it and writes the reversible X/Y origin to model.json.
    class TestInputs:
        @staticmethod
        def getText(*args, **kwargs): return ("Local XYZ surface", True)
        @staticmethod
        def getInt(*args, **kwargs): return (4, True)
    class TestFileDialogs:
        @staticmethod
        def getExistingDirectory(*args, **kwargs):
            return str(Path(folder)/"model_exports")
    class TestMessages:
        StandardButton=QMessageBox.StandardButton
        @staticmethod
        def question(*args, **kwargs): return QMessageBox.StandardButton.Yes
        @staticmethod
        def information(*args, **kwargs): return None
    Path(folder,"model_exports").mkdir()
    old_inputs=model_ui_module.QInputDialog
    old_file=model_ui_module.QFileDialog
    old_model_box=model_ui_module.QMessageBox
    model_ui_module.QInputDialog=TestInputs
    model_ui_module.QFileDialog=TestFileDialogs
    model_ui_module.QMessageBox=TestMessages
    try:
        dock.build_model()
    finally:
        model_ui_module.QInputDialog=old_inputs
        model_ui_module.QFileDialog=old_file
        model_ui_module.QMessageBox=old_model_box
    saved_models=models.list_models(second)
    assert len(saved_models)==1,saved_models
    assert saved_models[0][5]==local_xyz.BASIS
    output_dir=Path(saved_models[0][3])
    assert (output_dir/"model.vtm").is_file()
    manifest_data=json.loads((output_dir/"model.json").read_text())
    assert manifest_data["georeferenced"] is False
    assert manifest_data["crs"]==local_xyz.BASIS
    assert manifest_data["local_origin_m"]==inputs["local_origin_m"]
    assert manifest_data["input_batch_id"]==1
    assert manifest_data["source_coordinates"]=="local Cartesian, no EPSG"
    assert len(manifest_data["outputs"])>=5
    print("PASS GroundSurf dock 3D Models → actual local scene and auditable origin")

    saved=local_xyz.list_batches(second)
    assert len(saved)==1 and saved[0][7]==50
    assert len(local_xyz.list_contacts(second,saved[0][0]))==50
    assert original.featureCount()==50
    assert [(f.id(),f.geometry().asWkt(),f.attributes())
            for f in original.getFeatures()]==before
    # Existing project reload preserves local XYZ but still no map-located wells.
    dock.load_project(str(second))
    assert dock.local_table.rowCount()==50
    assert dock.wells_table.rowCount()==0
    plugin.unload()
    QgsProject.instance().clear()
    print("PASS v0.4.7: wrong EPSG:4326 source → 10 local boreholes, 50 saved local XYZ contacts")
    print("PASS v0.4.7: no fake WGS84; input unchanged; plugin Local XYZ tab and ParaView model")

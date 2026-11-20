"""QGIS 3 model removal safety tests on an isolated synthetic GeoPackage.

No original GroundSurf project file or user model is opened or touched.
"""
import json
from pathlib import Path
import tempfile
import shutil

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QMainWindow, QMessageBox

from groundsurf_geothermal import db, model_core, models, local_xyz, storage
from groundsurf_geothermal import model_ui, plugin as plugin_module
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin


app=QgsApplication([], False)
app.initQgis()


class Iface:
    def __init__(self):
        self.window=QMainWindow()
    def mainWindow(self): return self.window
    def addDockWidget(self,area,dock):self.window.addDockWidget(area,dock)
    def removeDockWidget(self,dock):self.window.removeDockWidget(dock)
    def addPluginToMenu(self,*args):pass
    def removePluginMenu(self,*args):pass
    def addToolBarIcon(self,*args):pass
    def removeToolBarIcon(self,*args):pass


class Confirm:
    Icon=QMessageBox.Icon
    ButtonRole=QMessageBox.ButtonRole
    next_response="remove"
    trash_checked=False
    last_message=""
    last_checkbox=None
    last_cancel_default=False
    warnings=[]
    def __init__(self,parent):
        self.buttons={}
        self.clicked=None
    def setIcon(self,icon):pass
    def setWindowTitle(self,title):pass
    def setText(self,text):self.last_message=text;Confirm.last_message=text
    def setInformativeText(self,text):self.informative=text
    def setCheckBox(self,checkbox):
        self.checkbox=checkbox
        Confirm.last_checkbox=checkbox
    def addButton(self,label,role):
        button=object()
        self.buttons[label]=button
        return button
    def setDefaultButton(self,button):
        Confirm.last_cancel_default=(
            button==self.buttons.get("Cancel")
        )
    def exec(self):
        assert Confirm.last_cancel_default
        self.clicked=self.buttons.get(
            "Cancel" if Confirm.next_response=="cancel"
            else "Remove selected model"
        )
        self.checkbox.setChecked(Confirm.trash_checked)
        return 1
    def clickedButton(self):return self.clicked
    @staticmethod
    def information(*args,**kwargs):pass
    @staticmethod
    def warning(_parent,title,message):
        Confirm.warnings.append((title,str(message)))


with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)
    project=root/"geology.gpkg"
    storage.create_project(project)
    QgsProject.instance().clear()
    with db.connect(project) as con:
        formation_before=con.execute(
            "SELECT count(*) FROM gs_formations"
        ).fetchone()[0]
        con.execute(
            "INSERT INTO gs_formations(code,name) VALUES(?,?)",
            ("Quaternary","Quaternary")
        )
    local_xyz.store_batch(project, {
        "source_layer":"Synthetic BH logs",
        "vertical_reference":"UNVERIFIED_SOURCE_Z",
        "source_layer_crs_claim":"EPSG:4326",
        "records":[
            {
                "well_id":f"BH{i}","unit_label":unit,
                "x_m":500000.+i*80,"y_m":5800000.+i*70,
                "z_m":float(30.-j*55.),
                "source_feature_id":f"{i}_{j}",
            }
            for i in range(1,11)
            for j,unit in enumerate(("Quaternary","Cretaceous","Base"))
        ],
    })
    rows_original=local_xyz.list_contacts(project)
    source_file=root/"original borehole layer.xyz"
    source_file.write_text("NOT MODEL DATA — DO NOT DELETE")

    wells=[
        {"well_id":"BH1","x":0.,"y":0.,
         "elevations":{"Quaternary":35.,"Cretaceous":-15.,"Base":-100.}},
        {"well_id":"BH2","x":200.,"y":0.,
         "elevations":{"Quaternary":39.,"Cretaceous":-25.,"Base":-110.}},
        {"well_id":"BH3","x":70.,"y":130.,
         "elevations":{"Quaternary":36.,"Cretaceous":-20.,"Base":-105.}},
    ]
    mesh=model_core.build_mesh(
        wells,["Quaternary","Cretaceous","Base"],5
    )
    folders={}
    ids={}
    for iteration in (1,2,3):
        name="Conceptual model (same name)"  # intentional duplicate
        folder=root/f"gsmodel-test-{iteration:02d}"
        scene,manifest=model_core.export_model(
            mesh,folder,name,"LOCAL_XYZ_METRES_UNGEOREFERENCED",
            "UNVERIFIED_SOURCE_Z",[],
        )
        model_id=models.record(
            project,name,folder,"LOCAL_XYZ_METRES_UNGEOREFERENCED",
            "UNVERIFIED_SOURCE_Z",3,f"hash-{iteration}","IDW"
        )
        folders[iteration]=folder
        ids[iteration]=model_id
        record=models.find_record(project,model_id)
        assert models.safe_trash_folder(project,record)==folder.resolve()

    # Unrelated folders must never qualify for automatic trashing.
    unrelated=root/"source-geology"
    unrelated.mkdir()
    (unrelated/"model.vtm").write_text("synthetic")
    (unrelated/"model.json").write_text(
        json.dumps({
            "application":"GroundSurf Geothermal",
            "name":"Conceptual model (same name)"
        })
    )
    unrelated_id=models.record(
        project,"Conceptual model (same name)",unrelated,
        "LOCAL","UNKNOWN",3,"hash-unclear","IDW"
    )
    assert models.safe_trash_folder(
        project,models.find_record(project,unrelated_id)
    ) is None
    # Never mistake a malicious/moved symlink for a generated source.
    wrong=root/"gsmodel-test-wrong"
    wrong.mkdir()
    (wrong/"model.vtm").write_text("synthetic")
    (wrong/"model.json").write_text(
        json.dumps({
            "application":"Another Program",
            "name":"Conceptual model (same name)"
        })
    )
    wrong_id=models.record(project,"Conceptual model (same name)",
                           wrong,"LOCAL","UNKNOWN",3,"hash-wrong","IDW")
    assert models.safe_trash_folder(
        project,models.find_record(project,wrong_id)
    ) is None

    # An output symlink must never authorize moving the target to Trash.
    link=root/"gsmodel-linked-dataset"
    link.symlink_to(folders[3],target_is_directory=True)
    link_id=models.record(
        project,"Conceptual model (same name)",link,
        "LOCAL","UNKNOWN",3,"symlink","IDW"
    )
    assert models.safe_trash_folder(
        project,models.find_record(project,link_id)
    ) is None
    models.remove_model(project,link_id)
    # An output shared by two catalogue rows cannot be trashed until
    # the duplicate is removed; other models must remain usable.
    duplicated_id=models.record(
        project,"Conceptual model (same name)",folders[3],
        "LOCAL","UNKNOWN",3,"duplicate","IDW"
    )
    assert models.safe_trash_folder(
        project,models.find_record(project,ids[3])
    ) is None
    models.remove_model(project,duplicated_id)
    assert models.safe_trash_folder(
        project,models.find_record(project,ids[3])
    ) == folders[3].resolve()

    iface=Iface()
    plugin=GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    dock=plugin.dock
    dock.load_project(str(project))
    iface.window.resize(640,900)
    iface.window.show()
    dock.show()
    dock.tabs.setCurrentWidget(dock.model_tab)
    app.processEvents()
    assert dock.delete_model_button.isVisible()
    assert dock.delete_model_button.geometry().width() >= 80
    assert dock.model_table.height() >= 92
    assert dock.model_table.rowCount()==5
    assert dock.delete_model_button.text()=="Delete model…"
    previous_box=model_ui.QMessageBox
    previous_file=model_ui.QFile
    previous_plugin_box=plugin_module.QMessageBox
    plugin_module.QMessageBox=Confirm
    model_ui.QMessageBox=Confirm
    moved=[]
    class Trash:
        succeed=True
        @staticmethod
        def moveToTrash(path):
            if not Trash.succeed:return False, ""
            src=Path(path)
            destination=root/"test_trash"/src.name
            destination.parent.mkdir(exist_ok=True)
            shutil.move(str(src),str(destination))
            moved.append((src,destination))
            return True,str(destination)
    model_ui.QFile=Trash
    try:
        # A selected row should be addressed by immutable id, not label.
        dock.model_table.selectRow(0)
        assert dock.model_table.item(0,0).data(0x0100)==wrong_id
        Confirm.next_response="cancel"
        Confirm.trash_checked=True
        dock.delete_selected_model()
        assert len(models.list_models(project))==5
        assert unrelated.is_dir()
        assert wrong.is_dir()
        assert not moved

        # Remove only one catalogue row, *without touching files*.
        idx=next(
            i for i,r in enumerate(models.list_models(project))
            if r[0]==ids[2]
        )
        dock.refresh_models()
        dock.model_table.selectRow(idx)
        Confirm.next_response="remove"
        Confirm.trash_checked=False
        dock.delete_selected_model()
        assert models.find_record(project,ids[2]) is None
        assert folders[2].is_dir()
        assert folders[1].is_dir() and folders[3].is_dir()
        assert len(models.list_models(project))==4
        assert "Generated files remain" in dock.status.text()

        # Simulate failed Trash operation: catalogue entry survives.
        dock.refresh_models()
        dock.model_table.selectRow(3)  # generated id 1 after two unsafe
        assert dock.model_table.item(3,0).data(0x0100)==ids[1]
        Confirm.trash_checked=True
        Trash.succeed=False
        print("ATTEMPT FAILED TRASH",flush=True)
        dock.delete_selected_model()
        print("FAIL HANDLED",flush=True)
        assert models.find_record(project,ids[1])
        assert folders[1].is_dir()
        assert "could not be moved" in Confirm.warnings[-1][1]

        # Move one generated folder to Trash then remove exactly its row.
        dock.refresh_models()
        dock.model_table.selectRow(3)
        Confirm.trash_checked=True
        Trash.succeed=True
        dock.delete_selected_model()
        assert models.find_record(project,ids[1]) is None
        assert not folders[1].exists()
        assert (root/"test_trash"/folders[1].name/"model.vtm").is_file()
        assert folders[3].is_dir() and folders[2].is_dir()
        assert not unrelated.is_symlink() and unrelated.is_dir()
        assert source_file.read_text()=="NOT MODEL DATA — DO NOT DELETE"
        assert local_xyz.list_contacts(project)==rows_original
        with db.connect(project) as con:
            count=con.execute(
                "SELECT count(*) FROM gs_formations"
            ).fetchone()[0]
            assert count==formation_before+1
        assert "Boreholes, geological contacts" in dock.status.text()

        # Unsafe directory is catalogue-removable only.
        dock.refresh_models()
        dock.model_table.selectRow(0)
        assert dock.model_table.item(0,0).data(0x0100)==wrong_id
        Confirm.trash_checked=False
        dock.delete_selected_model()
        assert models.find_record(project,wrong_id) is None
        assert wrong.is_dir()  # deliberately never trashed
        assert unrelated.is_dir()
    finally:
        model_ui.QMessageBox=previous_box
        plugin_module.QMessageBox=previous_plugin_box
        model_ui.QFile=previous_file
        plugin.unload()
        iface.window.close()
        QgsProject.instance().clear()
    print(
        "PASS 0.4.12: explicit Cancel, one-row catalogue removal, "
        "optional guarded Trash, failed-trash no mutation; "
        "original boreholes, local contact records and other output folders intact"
    )

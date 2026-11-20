"""QGIS 3 visual import and geology-scene controls, synthetic only."""
import json
from pathlib import Path
import tempfile

from qgis.core import (
    QgsApplication, QgsFeature, QgsField, QgsGeometry, QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QTimer, QVariant
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QMainWindow, QScrollArea,
)

from groundsurf_geothermal import model_core, scene_style, storage
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin
from groundsurf_geothermal.qgis_import import ImportFromQGISDialog


app=QgsApplication([],False)
app.initQgis()


class Iface:
    def __init__(self):self.window=QMainWindow()
    def mainWindow(self):return self.window
    def addDockWidget(self, area, widget):self.window.addDockWidget(area,widget)
    def removeDockWidget(self, widget):self.window.removeDockWidget(widget)
    def addPluginToMenu(self,*a):pass
    def removePluginMenu(self,*a):pass
    def addToolBarIcon(self,*a):pass
    def removeToolBarIcon(self,*a):pass


QgsProject.instance().clear()
source=QgsVectorLayer("PointZ?crs=EPSG:4326", "Synthetic BH_logs", "memory")
assert source.isValid()
source.dataProvider().addAttributes([
    QgsField("ID",QVariant.String),QgsField("X",QVariant.Double),
    QgsField("Y",QVariant.Double),QgsField("Z",QVariant.Double),
    QgsField("Strata",QVariant.String),
])
source.updateFields()
for i in range(10):
    for j,name in enumerate(("Quaternary","Pleistocene","Palaeogene",
                              "Cretaceous","Base")):
        feat=QgsFeature(source.fields())
        x,y=1_400_000.0+i*170.0,7_000_000.0+i*90.0
        z=22.0-30.0*j
        feat.setGeometry(QgsGeometry.fromWkt(
            f"POINT Z ({x} {y} {z})"
        ))
        feat.setAttributes([f"BH{i+1}",x,y,z,name])
        assert source.dataProvider().addFeatures([feat])[0]
source.updateExtents()
QgsProject.instance().addMapLayer(source)
dialog=ImportFromQGISDialog(preferred_layer_id=source.id())
assert dialog.mode_combo.currentData()=="local_xyz",dialog.mode_combo.currentData()
assert dialog.contact_fields["well_id"].currentData()=="ID"
assert dialog.contact_fields["formation_code"].currentData()=="Strata"
assert dialog.contact_fields["elevation_m"].currentData()=="Z"
assert dialog.contact_fields["x"].currentData()=="X"
assert dialog.contact_fields["y"].currentData()=="Y"
assert not dialog.source_crs.isVisible()
assert len(dialog.findChildren(QScrollArea))>=3
dialog.show()
app.processEvents()
assert dialog.height()>=510
assert dialog.width()>=560
assert dialog.preview_button.isVisible()
assert dialog.findChild(QDialogButtonBox).isVisible()
assert dialog.well_tabs.widget(2).verticalScrollBar() is not None
assert dialog.local_confirm.isChecked() is False
dialog.local_confirm.setChecked(True)
assert dialog._contact_selection()["local_metre_confirmed"]
assert dialog._contact_selection()["mode"]=="local_xyz"
preview_path=Path("/tmp/groundsurf_import_v0411.png")
assert dialog.grab().save(str(preview_path))
print("DIALOG",dialog.width(),dialog.height(),
      "SCROLL MAX",dialog.well_tabs.widget(2).verticalScrollBar().maximum(),
      "PREVIEW",preview_path)
dialog.close()

with tempfile.TemporaryDirectory() as tmp:
    gpkg=Path(tmp)/"geology.gpkg"
    storage.create_project(gpkg)
    iface=Iface()
    plugin=GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    dock=plugin.dock
    dock.load_project(str(gpkg))
    assert dock.scene_look_button.text()=="Scene look…"
    saved={
        key:dock.settings.value(key,None)
        for key in ("3d_palette","3d_edges","3d_orientation","3d_bounds")
    }
    try:
        def choose_settings():
            modal=QApplication.activeModalWidget()
            assert modal and isinstance(modal,QDialog)
            chooser=modal.findChild(QComboBox)
            assert chooser is not None
            ix=chooser.findData("contrast")
            assert ix>=0
            chooser.setCurrentIndex(ix)
            checks=modal.findChildren(QCheckBox)
            assert len(checks)==3,len(checks)
            # Edges YES, orientation YES, bounds YES
            for box in checks:
                box.setChecked(True)
            modal.accept()
        QTimer.singleShot(60,choose_settings)
        dock._edit_scene_look()
        assert dock._scene_palette=="contrast"
        assert dock._scene_edges
        assert dock._scene_orientation
        assert dock._scene_bounds
        assert "#212121" in dock.status.text()
        assert dock.settings.value("3d_palette")=="contrast"
        assert scene_style.geology_color("Quaternary","contrast")=="#39b9b1"
        assert scene_style.geology_color("Cretaceous","contrast")=="#d96666"
        assert scene_style.geology_color("Quaternary","earth")=="#6ea9a2"

        wells=[
            {"well_id":"BH1","x":0.,"y":0.,"elevations":{
                "Quaternary":18.,"Cretaceous":-50.,"Base":-140.}},
            {"well_id":"BH2","x":230.,"y":0.,"elevations":{
                "Quaternary":26.,"Cretaceous":-55.,"Base":-151.}},
            {"well_id":"BH3","x":100.,"y":210.,"elevations":{
                "Quaternary":24.,"Cretaceous":-60.,"Base":-162.}},
        ]
        mesh=model_core.build_mesh(wells,
            ["Quaternary","Cretaceous","Base"],subdivisions=5)
        destination=Path(tmp)/"scene"
        model_core.export_model(mesh,destination,"synthetic",
            "LOCAL_XYZ_METRES_UNGEOREFERENCED","unverified",
            [], palette=dock._scene_palette, show_edges=dock._scene_edges,
            show_orientation=dock._scene_orientation,
            show_bounds=dock._scene_bounds)
        appearance=json.loads((destination/"appearance.json").read_text())
        assert appearance["background"]=="#212121"
        assert appearance["palette"]=="contrast"
        assert appearance["show_unit_edges"] is True
        assert appearance["show_orientation_axes"] is True
        assert appearance["show_bounds_box"] is True
        assert appearance["bands"][0]["color"]=="#39b9b1"
        assert mesh["input_points"][0]["elevations"]["Base"]==-140.
    finally:
        for key,value in saved.items():
            if value is None: dock.settings.remove(key)
            else: dock.settings.setValue(key,value)
        plugin.unload()
        iface.window.close()
        QgsProject.instance().clear()
print("PASS 0.4.11: wide scrollable mapping, fixed Preview/OK, "
      "user-selectable palette/outlines/axes/bounds, charcoal background "
      "and unchanged input Z")

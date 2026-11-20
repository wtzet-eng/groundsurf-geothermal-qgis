"""QGIS 3 UI regression: import actually navigates to the saved data view.

No user data are read or modified; all inputs are synthetic and local.
"""
import tempfile
from pathlib import Path

from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsField,
    QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer,
    QgsVectorFileWriter,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QDialog, QMainWindow, QMessageBox

from groundsurf_geothermal import storage, local_xyz
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin
from groundsurf_geothermal import plugin as plugin_module
from groundsurf_geothermal.qgis_import import ImportFromQGISDialog


app=QgsApplication([],False)
app.initQgis()


class Iface:
    def __init__(self):
        self.window=QMainWindow()
        self.active=None
    def mainWindow(self): return self.window
    def activeLayer(self): return self.active
    def addDockWidget(self,area,widget): self.window.addDockWidget(area,widget)
    def removeDockWidget(self,widget): self.window.removeDockWidget(widget)
    def addPluginToMenu(self,*args): pass
    def removePluginMenu(self,*args): pass
    def addToolBarIcon(self,*args): pass
    def removeToolBarIcon(self,*args): pass


class Confirm:
    StandardButton=QMessageBox.StandardButton
    messages=[]
    @staticmethod
    def warning(_parent,title,message):
        Confirm.messages.append((title,str(message)))
        return QMessageBox.StandardButton.Ok
    @staticmethod
    def question(*args,**kwargs): return QMessageBox.StandardButton.Yes
    @staticmethod
    def information(*args,**kwargs):return QMessageBox.StandardButton.Ok


with tempfile.TemporaryDirectory() as folder:
    project=Path(folder)/"site.gpkg"
    storage.create_project(project)
    QgsProject.instance().clear()
    source=QgsVectorLayer("Point?crs=EPSG:4326","Synthetic wells","memory")
    source.dataProvider().addAttributes([
        QgsField("ID",QVariant.String), QgsField("Name",QVariant.String),
        QgsField("Depth",QVariant.Double),
    ])
    source.updateFields()
    for i in range(3):
        ft=QgsFeature(source.fields())
        ft.setGeometry(QgsGeometry.fromPointXY(
            QgsPointXY(12.+i*.01,51.+i*.01)))
        ft.setAttributes([f"BH{i+1}", f"Borehole {i+1}", 150.])
        assert source.dataProvider().addFeatures([ft])[0]
    source.updateExtents()
    QgsProject.instance().addMapLayer(source)

    map_path=Path(folder)/"map.geojson"
    options=QgsVectorFileWriter.SaveVectorOptions()
    options.driverName="GeoJSON"
    result=QgsVectorFileWriter.writeAsVectorFormatV3(
        source,str(map_path),QgsProject.instance().transformContext(),options
    )
    assert int(result[0])==0,result
    map_layer=QgsVectorLayer(str(map_path),"Synthetic map","ogr")
    assert map_layer.isValid()
    QgsProject.instance().addMapLayer(map_layer)

    # Dialog guards: CRS diagnostic should not crash when the first
    # feature is missing geometry (a common real-world source issue).
    bad=QgsVectorLayer("Point?crs=EPSG:4326","Empty geometry","memory")
    bad.dataProvider().addAttributes([
        QgsField("ID",QVariant.String),QgsField("Strata",QVariant.String),
        QgsField("Z",QVariant.Double),
    ])
    bad.updateFields()
    feature=QgsFeature(bad.fields())
    feature.setAttributes(["BH0","Quaternary",10.])
    assert bad.dataProvider().addFeatures([feature])[0]
    QgsProject.instance().addMapLayer(bad)
    dialog=ImportFromQGISDialog(preferred_layer_id=bad.id())
    assert dialog.mode_combo.currentData()=="contacts"
    dialog.close()

    iface=Iface()
    iface.active=source
    plugin=GroundSurfGeothermalPlugin(iface)
    plugin.initGui();plugin.open_dock()
    dock=plugin.dock
    dock.load_project(str(project))

    class FakeDialog:
        selection_data=None
        def __init__(self,**kwargs):
            self.layers=[source]
        def exec(self): return QDialog.DialogCode.Accepted
        def selection(self): return FakeDialog.selection_data

    old_dialog=plugin_module.ImportFromQGISDialog
    old_box=plugin_module.QMessageBox
    plugin_module.ImportFromQGISDialog=FakeDialog
    plugin_module.QMessageBox=Confirm
    try:
        FakeDialog.selection_data={
            "mode":"wells","layer":source,"selected_only":False,
            "mapping":{
                "well_id":"ID","name":"Name","total_depth_m":"Depth",
                "ground_elev_m":None,"vertical_datum":None,
                "source":None,"notes":None,
            },
            "source_crs":QgsCoordinateReferenceSystem("EPSG:4326"),
        }
        dock.import_from_qgis()
        assert dock.wells_table.rowCount()==3
        assert dock.tabs.currentWidget() is dock.wells_table, (
            "Successful well import unexpectedly opened another tab"
        )
        assert "Copied 3" in dock.status.text()
        FakeDialog.selection_data={"mode":"map","layer":map_layer}
        dock.import_from_qgis()
        assert dock.maps_table.rowCount()==1
        assert dock.tabs.currentWidget() is dock.maps_table, (
            "Successful map link unexpectedly opened another tab"
        )
        assert not Confirm.messages,Confirm.messages
        # A failure in dialog creation must now be user-facing (and
        # recorded under GroundSurf in the QGIS Message Log), not an
        # uncaught generic "Python error" notification.
        class BrokenDialog:
            def __init__(self,**kwargs):
                raise RuntimeError("synthetic bad dialog setup")
        plugin_module.ImportFromQGISDialog=BrokenDialog
        dock.import_from_qgis()
        assert Confirm.messages
        assert "synthetic bad dialog" in Confirm.messages[-1][1]
        assert "synthetic bad dialog" in dock.status.text()
    finally:
        plugin_module.ImportFromQGISDialog=old_dialog
        plugin_module.QMessageBox=old_box

    # Prior LOCAL XYZ imports are visible at project open, not confused
    # with the zero rows of the WGS84 Wells table.
    fresh=Path(folder)/"local.gpkg"
    storage.create_project(fresh)
    local_xyz.store_batch(fresh,{
        "source_layer":"Synthetic BH_logs",
        "vertical_reference":"UNVERIFIED_SOURCE_Z",
        "source_layer_crs_claim":"EPSG:4326",
        "records":[
            {
                "well_id":f"BH{i+1}", "unit_label":unit,
                "x_m":500000.+i*200, "y_m":5800000.+i*200,
                "z_m":float(-i*10-j*30),
                "source_feature_id":str(i*5+j)
            }
            for i in range(10)
            for j,unit in enumerate(
                ("Quaternary","Pleistocene","Palaeogene",
                 "Cretaceous","Base")
            )
        ]
    })
    dock.load_project(str(fresh))
    assert dock.wells_table.rowCount()==0
    assert dock.local_table.rowCount()==50
    assert "50 saved contacts" in dock.status.text()
    headings=[
        dock.tree.topLevelItem(i)
        for i in range(dock.tree.topLevelItemCount())
    ]
    local_head=next(x for x in headings if x.text(0).startswith("Local XYZ"))
    assert "10 boreholes / 50 contacts" in local_head.text(0)
    dock._tree_selected(local_head,0)
    assert dock.tabs.currentWidget() is dock.local_xyz_tab
    assert dock.local_batch_combo.count()==1

    plugin.unload()
    iface.window.close()
    QgsProject.instance().clear()
    print("PASS 0.4.10: new wells open Wells tab, map import opens Maps; "
          "import-dialog errors handled; existing 10/50 local XYZ "
          "contacts visible in Project Explorer and status")

"""QGIS 3 detachable Studio: one workspace, no duplicate data or widgets."""
import json
import tempfile
from pathlib import Path

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication, QDialog, QMainWindow

from groundsurf_geothermal import storage, models, local_xyz
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin

app=QgsApplication([],False)
app.initQgis()

class Iface:
    def __init__(self): self.window=QMainWindow()
    def mainWindow(self): return self.window
    def addDockWidget(self,area,widget): self.window.addDockWidget(area,widget)
    def removeDockWidget(self,widget): self.window.removeDockWidget(widget)
    def addPluginToMenu(self,*args): pass
    def removePluginMenu(self,*args): pass
    def addToolBarIcon(self,*args): pass
    def removeToolBarIcon(self,*args): pass

with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/"synthetic.gpkg"
    storage.create_project(path)
    local_xyz.store_batch(path, {
        "source_layer":"Synthetic geology", "source_layer_crs_claim":"EPSG:4326",
        "vertical_reference":"UNVERIFIED_SOURCE_Z",
        "records":[
            {
                "well_id":f"BH{i+1}", "unit_label":label,
                "x_m":600000.+i*130, "y_m":5200000.+i*120,
                "z_m":-45.-j*60,
                "source_feature_id":str(i*3+j),
            }
            for i in range(3)
            for j,label in enumerate(("Quaternary","Cretaceous","Base"))
        ]
    })
    iface=Iface()
    plugin=GroundSurfGeothermalPlugin(iface)
    plugin.initGui();plugin.open_dock()
    dock=plugin.dock
    dock.load_project(str(path))
    iface.window.resize(620,850);iface.window.show();dock.show()
    app.processEvents()
    original_splitter=dock.explorer_splitter
    original_tab=dock.model_tab
    original_xyz=dock.local_xyz_tab
    expected_record_count=dock.local_table.rowCount()
    assert expected_record_count==9
    assert dock._studio_window is None
    assert original_splitter.parent() is dock.widget()
    assert "STUDIO" in dock.models_shortcut.text()

    # Existing QGIS dock button opens an independent, non-modal window.
    dock.models_shortcut.click()
    app.processEvents()
    studio=dock._studio_window
    assert isinstance(studio,QDialog)
    assert studio.isVisible()
    assert studio.isModal() is False
    assert studio is not dock
    assert original_splitter.parent() is studio
    assert dock.tabs.currentWidget() is original_tab
    assert dock.local_table.rowCount()==expected_record_count
    assert "Studio" in studio.windowTitle()
    assert studio.width()>=690 and studio.height()>=465

    # Clicking again must reuse the same window and same original tabs.
    dock.models_shortcut.click()
    app.processEvents()
    assert dock._studio_window is studio
    assert dock.explorer_splitter is original_splitter
    assert dock.local_xyz_tab is original_xyz

    # Changing tab in Studio is applied to the one shared workspace.
    dock.tabs.setCurrentWidget(dock.local_xyz_tab)
    assert dock.tabs.currentWidget() is original_xyz
    app.processEvents()
    preview = Path("/tmp/GroundSurf-Geothermal-0.4.13-Studio-Preview.png")
    assert studio.grab().save(str(preview))
    print("STUDIO_PREVIEW", preview)
    dock.toggle_theme()
    assert studio.styleSheet()==dock.widget().styleSheet()
    dock.toggle_theme()

    studio.close()
    app.processEvents()
    assert dock._studio_window is None
    assert original_splitter.parent() is dock.widget()
    assert dock.main_layout.indexOf(original_splitter)==dock.workspace_home_index
    assert dock.local_table.rowCount()==expected_record_count
    assert original_splitter.isVisible()
    assert dock.tabs.currentWidget() is original_xyz

    # Reopen after closing still uses same live widgets.
    dock.models_shortcut.click()
    app.processEvents()
    another=dock._studio_window
    assert another is not None
    assert dock.tabs.currentWidget() is original_tab
    assert dock.local_table.rowCount()==expected_record_count
    assert dock.explorer_splitter is original_splitter

    # Unloading plugin while Studio open returns workspace safely.
    plugin.unload()
    app.processEvents()
    assert dock._studio_window is None
    assert len(local_xyz.list_contacts(path))==9
    assert len(models.list_models(path))==0
    assert len(QgsProject.instance().mapLayers())>=1  # Existing QGIS layers stay
    iface.window.close()
    QgsProject.instance().clear()
    print(
        "PASS v0.4.13: compact QGIS dock opens independent Studio; "
        "single shared explorer/tabs, theme, full model workspace, "
        "close/restore/reopen/unload; local XYZ GeoPackage unchanged"
    )

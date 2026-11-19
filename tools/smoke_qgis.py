"""Offscreen functional test using the system QGIS Python runtime."""
import os
import tempfile
from pathlib import Path
from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QMainWindow
from groundsurf_geothermal import db, storage
from groundsurf_geothermal.plugin import GeothermalDock, GroundSurfGeothermalPlugin

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app = QgsApplication([], False)
app.initQgis()


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self._canvas = None

    def mainWindow(self):
        return self.window

    def addDockWidget(self, area, dock):
        self.window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self.window.removeDockWidget(dock)

    def addPluginToMenu(self, *args): pass
    def removePluginMenu(self, *args): pass
    def addToolBarIcon(self, *args): pass
    def removeToolBarIcon(self, *args): pass

    def mapCanvas(self):
        if self._canvas is None:
            from qgis.gui import QgsMapCanvas
            self._canvas = QgsMapCanvas()
        return self._canvas


with tempfile.TemporaryDirectory() as tmp:
    path = str(Path(tmp) / "sample.gpkg")
    storage.create_project(path)
    assert db.valid_project(path), "Failed to initialise project"
    layer = storage.open_wells(path)
    records = db.parse_well_csv(
        "well_id,name,latitude,longitude,total_depth_m\n"
        "S1,Synthetic,52.50,13.35,125\n"
        "S2,Test,52.51,13.36,240\n"
    )
    storage.add_wells(layer, records)
    assert layer.featureCount() == 2
    iface = FakeIface()
    plugin = GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    plugin.dock.load_project(path)
    assert plugin.dock.wells_table.rowCount() == 2
    assert plugin.dock.theme in ("dark", "light")
    plugin.dock.toggle_theme()
    plugin.unload()
    QgsProject.instance().clear()
    print("PASS: GeoPackage, wells, UI, theme and plugin lifecycle")
# QgsApplication teardown is intentionally left to interpreter exit.

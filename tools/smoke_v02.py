"""Full QGIS 3.34 offscreen integration smoke for v0.2."""
import sqlite3
import tempfile
from pathlib import Path

from qgis.PyQt.QtWidgets import QMainWindow
from qgis.core import QgsApplication, QgsProject, QgsProviderRegistry
from groundsurf_geothermal import db, storage
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin

app = QgsApplication([], False)
app.initQgis()


class Iface:
    def __init__(self):
        self.window = QMainWindow()
        self._canvas = None

    def mainWindow(self): return self.window
    def addDockWidget(self, area, widget): self.window.addDockWidget(area, widget)
    def removeDockWidget(self, widget): self.window.removeDockWidget(widget)
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
    project_file = Path(tmp) / "aquifer.gpkg"
    storage.create_project(project_file)
    wells = storage.open_wells(str(project_file))
    source = Path(__file__).resolve().parent.parent / "examples/sample_wells.csv"
    records = db.parse_well_csv(source.read_text())
    assert storage.add_wells(wells, records) == 3

    for code, name in (("Q", "Sand"), ("C", "Clay"), ("B", "Sandstone")):
        db.add_formation(project_file, code, name)

    intervals = (Path(__file__).resolve().parent.parent /
                 "examples/sample_intervals.csv").read_text()
    assert db.import_intervals_csv(project_file, wells, intervals) == 9
    db.add_formation_top(project_file, wells, "SIM-01", "B", 62,
                         interpretation="observed", source="synthetic log")
    db.add_observation(project_file, wells, "SIM-01", db.utcnow(),
                       "water_depth_bgl_m", 3.4, source="synthetic")
    db.add_observation(project_file, wells, "SIM-01", db.utcnow(),
                       "temperature_c", 14.2, depth_bgl_m=35, source="synthetic")

    # Check the browser can read a GeoPackage sublayer by name.
    sources = QgsProviderRegistry.instance().querySublayers(str(project_file))
    assert any(x.name() == "gs_wells" for x in sources), [
        (x.name(), x.providerKey()) for x in sources
    ]
    db.record_map(project_file, project_file, "Wells map 1", "vector", "gs_wells")
    # v2 allows more than one named map from the same GeoPackage.
    db.record_map(project_file, project_file, "Wells map 2", "vector", "additional")
    assert len(db.maps(project_file)) == 2

    iface = Iface()
    plugin = GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    dock = plugin.dock
    dock.load_project(str(project_file))
    assert dock.wells_table.rowCount() == 3
    assert dock.well_select.count() == 3
    dock.well_select.setCurrentIndex(dock.well_select.findData("SIM-01"))
    assert dock.intervals_table.rowCount() == 3
    assert dock.tops_table.rowCount() == 1
    assert dock.observations_table.rowCount() == 2
    assert dock.maps_table.rowCount() == 2
    assert dock.theme in ("dark", "light")
    dock.toggle_theme()

    # Models can't be faked; this preview is a well-log database + map viewer.
    assert len(db.formations(project_file)) == 3
    plugin.unload()
    QgsProject.instance().clear()
    print("PASS: QGIS 3.34, formations, logs, tops, measurements, maps, UI")

# Leave Qt runtime teardown to interpreter exit.

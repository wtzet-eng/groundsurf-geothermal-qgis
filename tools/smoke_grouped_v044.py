"""Headless QGIS 3 smoke: one long-form layer becomes separate well logs."""
from pathlib import Path
import tempfile
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QDialog, QMessageBox, QMainWindow

from groundsurf_geothermal import db, storage, grouped_import
from groundsurf_geothermal.qgis_import import ImportFromQGISDialog
from groundsurf_geothermal import plugin as plugin_module

app = QgsApplication([], False)
app.initQgis()


def source_layer():
    layer = QgsVectorLayer(
        "Point?crs=EPSG:3857", "Long-form boreholes", "memory"
    )
    layer.dataProvider().addAttributes([
        QgsField("BH_ID", QVariant.String),
        QgsField("WellName", QVariant.String),
        QgsField("RL", QVariant.Double),
        QgsField("TD", QVariant.Double),
        QgsField("VDatum", QVariant.String),
        QgsField("Formation", QVariant.String),
        QgsField("From_m", QVariant.Double),
        QgsField("To_m", QVariant.Double),
        QgsField("Geology", QVariant.String),
    ])
    layer.updateFields()
    transform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:4326"), layer.crs(),
        QgsProject.instance(),
    )
    rows = [
        ("BH-1", "Site well 1", 48., 70., "DHHN2016", "SAND", 0., 20., "Fine sand"),
        ("BH-1", "Site well 1", 48., 70., "DHHN2016", "CLAY", 20., 70., "Clay"),
        ("BH-2", "Site well 2", 50., 80., "DHHN2016", "SAND", 0., 35., "Sand"),
        ("BH-2", "Site well 2", 50., 80., "DHHN2016", "CLAY", 35., 80., "Clay"),
        ("BH-3", "Site well 3", 49., 90., "DHHN2016", "SAND", 0., 40., "Sand"),
        ("BH-3", "Site well 3", 49., 90., "DHHN2016", "CLAY", 40., 90., "Clay"),
    ]
    coords = {
        "BH-1": (13.35, 52.50),
        "BH-2": (13.36, 52.505),
        "BH-3": (13.355, 52.512),
    }
    for row in rows:
        f = QgsFeature(layer.fields())
        x, y = coords[row[0]]
        point = transform.transform(QgsPointXY(x, y))
        f.setGeometry(QgsGeometry.fromPointXY(point))
        f.setAttributes(list(row))
        assert layer.dataProvider().addFeatures([f])[0]
    layer.updateExtents()
    return layer


with tempfile.TemporaryDirectory() as temp:
    project_path = Path(temp) / "geothermal.gpkg"
    storage.create_project(project_path)
    target = storage.open_wells(project_path)
    source = source_layer()
    QgsProject.instance().addMapLayer(source)
    original = [(f.id(), f.attributes(), f.geometry().asWkt()) for f in source.getFeatures()]

    dialog = ImportFromQGISDialog(preferred_layer_id=source.id())
    assert dialog.mode_combo.currentData() == "grouped"  # duplicate BH IDs detected
    assert dialog.mapping_combo["well_id"].currentData() == "BH_ID"
    assert dialog.mapping_combo["total_depth_m"].currentData() == "TD"
    assert dialog.interval_combo["formation_code"].currentData() == "Formation"
    assert dialog.interval_combo["top_depth_m"].currentData() == "From_m"
    assert dialog.interval_combo["base_depth_m"].currentData() == "To_m"
    # Less common common vertical-datum aliases are now recognised.
    assert dialog.mapping_combo["vertical_datum"].currentData() == "VDatum"
    dialog.accept()
    selection = dialog.selection()
    assert selection["mode"] == "grouped"

    prepared = grouped_import.prepare_groups(
        source, selection["mapping"], selection["interval_mapping"]
    )
    assert prepared["source_rows"] == 6
    assert prepared["well_count"] == 3
    assert prepared["interval_count"] == 6
    assert prepared["counts"] == {"BH-1": 2, "BH-2": 2, "BH-3": 2}
    assert len(prepared["warnings"]) == 1

    imported = grouped_import.import_groups(project_path, target, prepared)
    assert imported == (3, 6)
    assert target.featureCount() == 3
    for well in ("BH-1", "BH-2", "BH-3"):
        log = db.intervals(project_path, well)
        assert len(log) == 2
        assert log[0][2] == 0.
        assert log[0][3] == log[1][2]
    assert {f[0] for f in db.formations(project_path)} == {"SAND", "CLAY"}
    assert source.featureCount() == 6
    assert original == [
        (f.id(), f.attributes(), f.geometry().asWkt())
        for f in source.getFeatures()
    ]
    assert abs(next(f for f in target.getFeatures() if f["well_id"] == "BH-1").geometry().asPoint().y() - 52.50) < 1e-4

    # Existing IDs cannot be overwritten or silently merged.
    try:
        grouped_import.import_groups(project_path, target, prepared)
    except ValueError as exc:
        assert "already exist" in str(exc)
    else:
        raise AssertionError("Existing wells were overwritten")

    # Selected subset remains a group, not an individual well per feature.
    features = list(source.getFeatures())
    source.selectByIds([features[0].id(), features[1].id()])
    subset = grouped_import.prepare_groups(
        source, selection["mapping"], selection["interval_mapping"], True
    )
    assert subset["well_count"] == 1 and subset["interval_count"] == 2

    # A conflicting repeated position must be rejected before any write.
    assert source.startEditing()
    f = next(f for f in source.getFeatures() if f.id() == features[1].id())
    geometry = QgsGeometry(f.geometry())
    point = geometry.asPoint()
    geometry = QgsGeometry.fromPointXY(QgsPointXY(point.x()+100.,point.y()))
    assert source.changeGeometry(f.id(), geometry)
    assert source.commitChanges()
    try:
        grouped_import.prepare_groups(
            source, selection["mapping"], selection["interval_mapping"], True
        )
    except ValueError as exc:
        assert "positions differ" in str(exc)
    else:
        raise AssertionError("Conflicting borehole positions were ignored")
    # The GroundSurf copy remains unchanged despite source changes.
    assert target.featureCount() == 3
    assert len(db.intervals(project_path, "BH-1")) == 2
    # A database write error after well creation must compensate by
    # removing any freshly imported well records.
    rollback_file = Path(temp) / "rollback_test.gpkg"
    storage.create_project(rollback_file)
    rollback_target = storage.open_wells(rollback_file)
    intact_source = source_layer()
    staged = grouped_import.prepare_groups(
        intact_source, selection["mapping"], selection["interval_mapping"]
    )
    original_connect = grouped_import.db.connect
    calls = [0]

    def fail_on_second_sql_connection(path):
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError("Simulated interruption before interval insert")
        return original_connect(path)

    grouped_import.db.connect = fail_on_second_sql_connection
    try:
        try:
            grouped_import.import_groups(rollback_file, rollback_target, staged)
        except RuntimeError as error:
            assert "Simulated interruption" in str(error)
        else:
            raise AssertionError("SQL failure was ignored")
    finally:
        grouped_import.db.connect = original_connect
    assert rollback_target.featureCount() == 0
    assert db.formations(rollback_file) == []
    assert db.intervals(rollback_file, "BH-1") == []

    # Exercise the actual QGIS dock command with a confirmed grouped import.
    action_file = Path(temp) / "dialog_action.gpkg"
    storage.create_project(action_file)
    QgsProject.instance().addMapLayer(intact_source)

    class TestIface:
        def __init__(self):
            self.window = QMainWindow()
            self._canvas = None
        def mainWindow(self): return self.window
        def addDockWidget(self, area, dock): self.window.addDockWidget(area, dock)
        def removeDockWidget(self, dock): self.window.removeDockWidget(dock)
        def addPluginToMenu(self, *args): pass
        def removePluginMenu(self, *args): pass
        def addToolBarIcon(self, *args): pass
        def removeToolBarIcon(self, *args): pass
        def activeLayer(self): return intact_source
        def mapCanvas(self):
            if self._canvas is None:
                from qgis.gui import QgsMapCanvas
                self._canvas = QgsMapCanvas()
            return self._canvas

    class AcceptedGroupDialog:
        def __init__(self, **kwargs):
            self.layers = [intact_source]
            assert kwargs["preferred_layer_id"] == intact_source.id()
        def exec(self): return QDialog.DialogCode.Accepted
        def selection(self):
            return {
                "mode": "grouped", "layer": intact_source,
                "mapping": selection["mapping"],
                "interval_mapping": selection["interval_mapping"],
                "selected_only": False,
            }

    class ConfirmingMessageBox:
        StandardButton = QMessageBox.StandardButton
        @staticmethod
        def question(*args, **kwargs): return QMessageBox.StandardButton.Yes
        @staticmethod
        def warning(*args, **kwargs):
            raise AssertionError("Unexpected error dialog: " + str(args))
        @staticmethod
        def information(*args, **kwargs):
            raise AssertionError("Unexpected information dialog: " + str(args))

    iface = TestIface()
    plugin = plugin_module.GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    plugin.dock.load_project(action_file)
    previous_dialog = plugin_module.ImportFromQGISDialog
    previous_box = plugin_module.QMessageBox
    plugin_module.ImportFromQGISDialog = AcceptedGroupDialog
    plugin_module.QMessageBox = ConfirmingMessageBox
    try:
        plugin.dock.import_from_qgis()
    finally:
        plugin_module.QMessageBox = previous_box
        plugin_module.ImportFromQGISDialog = previous_dialog
    assert plugin.dock.wells_table.rowCount() == 3
    assert len(db.intervals(action_file, "BH-1")) == 2
    assert "3 individual boreholes" in plugin.dock.status.text()
    plugin.unload()

    QgsProject.instance().clear()
    print("PASS v0.4.4: 6 source records → 3 boreholes / 6 log intervals")
    print("PASS v0.4.4: selected subset, CRS, QGIS source safety, validation, duplicate protection")

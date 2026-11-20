"""End-to-end QGIS test with fully synthetic XYZ contact points.

The coordinates are intentionally declared as EPSG:4326 by the source but
contain projected-looking values; only an explicit per-import CRS override
permits conversion. EPSG:3857 is used as a synthetic TEST CRS only.
"""
import tempfile
from pathlib import Path

from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsField,
    QgsGeometry, QgsPoint, QgsProject, QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QMainWindow, QMessageBox, QDialog

from groundsurf_geothermal import (
    db, elevation_contacts, elevation_import, contact_adapter,
    model_core, storage,
)
from groundsurf_geothermal import plugin as plugin_module
from groundsurf_geothermal.qgis_import import ImportFromQGISDialog

app = QgsApplication([], False)
app.initQgis()

# Fabricated boreholes, coords and Z: reproduce data FORMAT, not source records.
BH = {
    "BH9": (503200, 5840100, [-145, -112, -55, -15, 22]),
    "BH8": (500750, 5840450, [-148, -182, -67, -9, 19]),
    "BH7": (500220, 5840530, [-170, -131, -62, -19, 8]),
    "BH6": (501810, 5840780, [-176, -126, -80, -25, 14]),
    "BH5": (500940, 5840910, [-162, -117, -59, -7, 26]),
    "BH4": (502110, 5841100, [-171, -119, -69, -27, 11]),
    "BH3": (502670, 5841370, [-180, -148, -93, -35, 23]),
    "BH2": (501140, 5841590, [-169, -121, -73, -28, 18]),
    "BH10":(503340, 5839860, [-188, -139, -74, -24, 29]),
    "BH1": (500040, 5841820, [-153, -114, -64, -14, 15]),
}
UNIT_NAMES = ["Base", "Cretaceous", "Palaeogene", "Pleistocene", "Quaternary"]


def make_source():
    layer = QgsVectorLayer("PointZ?crs=EPSG:4326", "BH_logs", "memory")
    layer.dataProvider().addAttributes([
        QgsField("ID", QVariant.String),
        QgsField("X", QVariant.Double),
        QgsField("Y", QVariant.Double),
        QgsField("Z", QVariant.Double),
        QgsField("Strata", QVariant.String),
    ])
    layer.updateFields()
    for well, (x, y, zs) in BH.items():
        for unit_index, z in enumerate(zs):
            f = QgsFeature(layer.fields())
            f.setAttributes([
                well, float(x), float(y), float(z),
                ("Cretaceous" if well == "BH8" and unit_index == 0
                 else UNIT_NAMES[unit_index]),
            ])
            f.setGeometry(QgsGeometry(QgsPoint(float(x), float(y), float(z))))
            assert layer.dataProvider().addFeatures([f])[0]
    layer.updateExtents()
    assert layer.featureCount() == 50
    return layer


class Iface:
    def __init__(self):
        self.window = QMainWindow()
        self.current = None
    def mainWindow(self): return self.window
    def activeLayer(self): return self.current
    def addDockWidget(self, area, dock): self.window.addDockWidget(area, dock)
    def removeDockWidget(self, dock): self.window.removeDockWidget(dock)
    def addPluginToMenu(self, *args): pass
    def removePluginMenu(self, *args): pass
    def addToolBarIcon(self, *args): pass
    def removeToolBarIcon(self, *args): pass


with tempfile.TemporaryDirectory() as td:
    source = make_source()
    QgsProject.instance().addMapLayer(source)
    snapshot = [
        (f.id(), f.attributes(), f.geometry().asWkt())
        for f in source.getFeatures()
    ]
    actual_fieldnames = [field.name() for field in source.fields()]
    guessed = elevation_import.detect_fields(actual_fieldnames)
    assert guessed == {
        "well_id":"ID", "x":"X", "y":"Y", "elevation_m":"Z",
        "formation_code":"Strata",
    }, guessed

    # The original layer claims WGS84, but its geometry X/Y is invalid.
    try:
        elevation_import.prepare_contacts(source, guessed)
    except ValueError as error:
        assert "EPSG:4326" in str(error), str(error)
        assert "503200" in str(error) or "500040" in str(error)
    else:
        raise AssertionError("Invalid geographical location accepted")

    # The user must select the true CRS (EPSG:3857 here only as test data).
    test_crs = QgsCoordinateReferenceSystem("EPSG:3857")
    dialog = ImportFromQGISDialog(preferred_layer_id=source.id())
    # v0.4.7 now proposes local-metre mode for misleading EPSG:4326
    # source coordinates. Explicitly choose original geographic import
    # for this older regression test of a known source-CRS override.
    assert dialog.mode_combo.currentData() == "local_xyz"
    dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData("contacts"))
    assert dialog.mode_combo.currentData() == "contacts"
    assert dialog.contact_fields["formation_code"].currentData() == "Strata"
    assert dialog.contact_fields["well_id"].currentData() == "ID"
    assert dialog.contact_fields["elevation_m"].currentData() == "Z"
    assert dialog.source_crs.crs().authid() == "EPSG:4326"
    dialog.source_crs.setCrs(test_crs)
    assert dialog.source_crs.crs().authid() == "EPSG:3857"
    dialog.vertical_reference.setText("LOCAL TEST Z BASIS")
    dialog.accept()
    opts = dialog.selection()
    assert opts["mode"] == "contacts"
    staged = elevation_import.prepare_contacts(
        source, opts["fields"], source_crs=opts["source_crs"],
        use_xy_fields=opts["use_xy_fields"],
        use_geometry_z=opts["use_geometry_z"],
        vertical_datum=opts["vertical_datum"],
        selected_only=opts["selected_only"],
    )
    assert staged["well_count"] == 10
    assert staged["contact_count"] == 50
    assert staged["source_crs"] == "EPSG:3857"
    assert staged["counts"]["BH8"] == 5
    as_fields = elevation_import.prepare_contacts(
        source, guessed, source_crs=test_crs, use_xy_fields=True,
        use_geometry_z=False, vertical_datum="LOCAL TEST Z BASIS"
    )
    assert [r["elevation_m"] for r in as_fields["contacts"]] == [
        r["elevation_m"] for r in staged["contacts"]
    ]
    from_point_z = elevation_import.prepare_contacts(
        source, guessed, source_crs=test_crs, use_geometry_z=True,
        vertical_datum="LOCAL TEST Z BASIS"
    )
    assert [r["elevation_m"] for r in from_point_z["contacts"]] == [
        r["elevation_m"] for r in staged["contacts"]
    ]
    assert any(
        item[0] == "BH8" and item[1] == "Cretaceous"
        for item in staged["ambiguous"]
    )
    assert not any(
        item["well_id"] == "BH8" and item["formation_code"] == "Base"
        for item in staged["contacts"]
    )

    project = Path(td)/"site.gpkg"
    storage.create_project(project)
    assert elevation_contacts.has_schema(project)
    wells_layer = storage.open_wells(project)
    result = elevation_import.import_contacts(project, wells_layer, staged)
    assert result == (10, 50)
    assert wells_layer.featureCount() == 10
    rows = elevation_contacts.list_contacts(project)
    assert len(rows) == 50
    bh9_rows = elevation_contacts.list_contacts(project, "BH9")
    assert len(bh9_rows) == 5
    assert any(r[1] == "Quaternary" and r[2] == 22. for r in bh9_rows)
    assert any(r[1] == "Base" and r[2] == -145. for r in bh9_rows)
    assert len([r for r in elevation_contacts.list_contacts(project, "BH8")
                if r[1] == "Cretaceous"]) == 2
    assert source.featureCount() == 50
    assert [
        (f.id(), f.attributes(), f.geometry().asWkt())
        for f in source.getFeatures()
    ] == snapshot

    # These synthetic elevation horizons (not borehole depths) create a
    # conceptual model from raw source-Z contact elevations. BH8 has
    # inconsistent Cretaceous Z and is therefore excluded explicitly.
    model_source = contact_adapter.gather_contacts(project, wells_layer)
    assert len(model_source["samples"]) == 9, model_source["warnings"]
    assert model_source["horizons"] == [
        "Quaternary", "Pleistocene", "Palaeogene", "Cretaceous", "Base"
    ], model_source["horizons"]
    assert model_source["datum"] == "LOCAL TEST Z BASIS"
    assert any("BH8" in warning for warning in model_source["warnings"])
    assert "ground" not in model_source["horizons"]
    mesh = model_core.build_mesh(
        model_source["samples"], model_source["horizons"], 4
    )
    assert mesh["input_wells"] == 9
    assert len(mesh["horizons"]) == 5
    output = Path(td)/"pointz_model"
    scene, manifest = model_core.export_model(
        mesh, output, "Raw PointZ contacts test",
        model_source["epsg"], model_source["datum"],
        model_source["provenance"], warnings=model_source["warnings"]
    )
    assert scene.is_file() and manifest.is_file()
    assert (output/"model.vtm").is_file()

    # Test that unknown vertical datum is never silently accepted for
    # 3D interpolation, while raw observations remain importable.
    unknown_project = Path(td)/"unknown_datum.gpkg"
    storage.create_project(unknown_project)
    unknown_layer = storage.open_wells(unknown_project)
    unknown_staged = elevation_import.prepare_contacts(
        source, guessed, source_crs=test_crs
    )
    assert unknown_staged["vertical_datum"] == "UNSPECIFIED"
    assert elevation_import.import_contacts(
        unknown_project, unknown_layer, unknown_staged
    ) == (10, 50)
    try:
        contact_adapter.gather_contacts(unknown_project, unknown_layer)
    except ValueError as exc:
        assert "vertical" in str(exc).lower()
    else:
        raise AssertionError(
            "3D model unexpectedly accepted an unspecified vertical datum"
        )

    # Selected QGIS rows may be imported without pulling in all ten wells.
    selection_ids = [f.id() for f in source.getFeatures() if f["ID"] == "BH9"]
    source.selectByIds(selection_ids)
    selected = elevation_import.prepare_contacts(
        source, guessed, source_crs=test_crs, selected_only=True
    )
    assert selected["well_count"] == 1 and selected["contact_count"] == 5
    source.removeSelection()

    # Imported data are visible INSIDE the plugin, not only in QGIS layers.
    iface = Iface()
    iface.current = source
    plugin = plugin_module.GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    dock = plugin.dock
    dock.load_project(project)
    assert dock.wells_table.rowCount() == 10
    assert dock.contact_table.rowCount() == 50
    assert "50 saved contact" in dock.contact_summary.text()
    dock.contact_filter.setText("BH9")
    visible = [
        not dock.contact_table.isRowHidden(i)
        for i in range(dock.contact_table.rowCount())
    ]
    assert sum(visible) == 5
    dock.contact_filter.setText("")

    # Trigger the real QGIS import button workflow in a NEW project.
    action_project = Path(td)/"new_import.gpkg"
    storage.create_project(action_project)
    dock.load_project(action_project)
    class AcceptedDialog:
        def __init__(self, **kwargs):
            self.layers = [source]
            assert kwargs["preferred_layer_id"] == source.id()
        def exec(self): return QDialog.DialogCode.Accepted
        def selection(self): return opts
    class ConfirmedBox:
        StandardButton=QMessageBox.StandardButton
        @staticmethod
        def question(*args, **kwargs): return QMessageBox.StandardButton.Yes
    old_dialog = plugin_module.ImportFromQGISDialog
    old_box = plugin_module.QMessageBox
    plugin_module.ImportFromQGISDialog = AcceptedDialog
    plugin_module.QMessageBox = ConfirmedBox
    try:
        dock.import_from_qgis()
    finally:
        plugin_module.ImportFromQGISDialog = old_dialog
        plugin_module.QMessageBox = old_box
    assert dock.wells_table.rowCount() == 10
    assert dock.contact_table.rowCount() == 50
    assert dock.tabs.currentWidget() == dock.contact_tab
    assert "10 boreholes and 50" in dock.status.text()
    plugin.unload()
    QgsProject.instance().clear()
    print(
        "PASS v0.4.6: synthetic 50 PointZ records -> 10 GroundSurf wells, "
        "50 Z contacts, BH8 ambiguity preserved and visible in plugin"
    )
    print(
        "PASS v0.4.6: per-import CRS override, input unchanged, "
        "PointZ/Strata mapping, actual QGIS action and Z Contacts panel"
    )

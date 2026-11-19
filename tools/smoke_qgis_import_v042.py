"""Offscreen end-to-end check: import wells and link existing QGIS layers.

No network. Creates its own synthetic input, protects source QGIS layers,
checks WGS84 coordinate transforms, selected-features filter, record
rollback on duplicate IDs, map links and QGIS workspace persistence.
"""
from pathlib import Path
import tempfile

from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorFileWriter,
    QgsVectorLayer, QgsRasterLayer,
)
from qgis.PyQt.QtCore import QVariant
from osgeo import gdal, osr
gdal.UseExceptions()
from qgis.PyQt.QtWidgets import QDialog, QMainWindow, QPushButton

from groundsurf_geothermal import db, storage, model_adapter, model_core
from groundsurf_geothermal.qgis_import import (
    ImportFromQGISDialog, eligible_layers, file_backed_map,
    guess_mapping, import_wells, prepare_well_records,
)
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin
from groundsurf_geothermal import plugin as plugin_module

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


with tempfile.TemporaryDirectory() as temp:
    project = Path(temp) / "well_project.gpkg"
    storage.create_project(project)
    imported = storage.open_wells(project)
    QgsProject.instance().clear()

    # Project source: memory point layer in Web Mercator with non-standard field
    # names. Geometry must transform to EPSG:4326 without mutating the layer.
    source = QgsVectorLayer("Point?crs=EPSG:3857", "QGIS existing boreholes", "memory")
    provider = source.dataProvider()
    provider.addAttributes([
        QgsField("BH_ID", QVariant.String), QgsField("WellName", QVariant.String),
        QgsField("Depth", QVariant.Double), QgsField("RL", QVariant.Double),
        QgsField("Datum", QVariant.String),
    ])
    source.updateFields()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    mercator = source.crs()
    transform = QgsCoordinateTransform(wgs84, mercator, QgsProject.instance())
    for number in range(3):
        lon, lat = 13.3500 + 0.006 * number, 52.4950 + 0.004 * number + (0.005 if number == 2 else 0)
        centre = transform.transform(QgsPointXY(lon, lat))
        feature = QgsFeature(source.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(centre))
        feature.setAttributes([
            f"BH-{number+1}", f"Existing well {number+1}",
            120 + 30*number, 50+number, "DHHN2016",
        ])
        assert provider.addFeatures([feature])[0]
    source.updateExtents()
    QgsProject.instance().addMapLayer(source)
    initial_geometries = {
        f["BH_ID"]: f.geometry().asWkt() for f in source.getFeatures()
    }

    mapping = guess_mapping([field.name() for field in source.fields()])
    assert mapping["well_id"] == "BH_ID", mapping
    assert mapping["name"] == "WellName", mapping
    assert mapping["total_depth_m"] == "Depth", mapping
    assert mapping["ground_elev_m"] == "RL", mapping
    assert mapping["vertical_datum"] == "Datum", mapping

    selected_ids = [f.id() for f in list(source.getFeatures())[1:]]
    source.selectByIds(selected_ids)
    dialog = ImportFromQGISDialog()
    index = dialog.layer_combo.findData(source.id())
    assert index >= 0
    dialog.layer_combo.setCurrentIndex(index)
    assert dialog.mode_combo.currentData() == "wells"
    assert dialog.selected_only.isChecked()
    assert dialog.mapping_combo["well_id"].currentData() == "BH_ID"
    dialog.accept()
    selection = dialog.selection()
    assert selection["selected_only"] is True
    records = prepare_well_records(
        selection["layer"], selection["mapping"],
        selection["selected_only"]
    )
    assert len(records) == 2
    assert {r["well_id"] for r in records} == {"BH-2", "BH-3"}
    imported_bh2 = next(r for r in records if r["well_id"] == "BH-2")
    assert abs(imported_bh2["latitude"] - 52.4990) < 1e-5
    assert abs(imported_bh2["longitude"] - 13.3560) < 1e-5
    count = import_wells(
        source, imported, selection["mapping"], selected_only=True
    )
    assert count == 2 and imported.featureCount() == 2
    assert source.featureCount() == 3
    assert initial_geometries == {
        f["BH_ID"]: f.geometry().asWkt() for f in source.getFeatures()
    }

    # Duplicate IDs are rejected before applying any partial edit to the
    # GroundSurf GeoPackage. The already-copied two stay unchanged.
    try:
        import_wells(source, imported, mapping, selected_only=False)
    except ValueError as exc:
        assert "Existing well IDs" in str(exc), str(exc)
    else:
        raise AssertionError("Duplicate IDs were incorrectly accepted")
    assert imported.featureCount() == 2

    # Copy ALL source wells into a separate GroundSurf GPKG and demonstrate
    # that direct imported well geometry can drive a real conceptual 3D model.
    model_project = Path(temp) / "model_after_qgis_import.gpkg"
    storage.create_project(model_project)
    model_wells = storage.open_wells(model_project)
    assert import_wells(source, model_wells, mapping, selected_only=False) == 3
    for formation, description in (("C", "Clay"), ("B", "Sandstone")):
        db.add_formation(model_project, formation, description)
    for well_id, c_depth, b_depth in (
        ("BH-1", 20, 70), ("BH-2", 18, 80), ("BH-3", 25, 90)
    ):
        db.add_interval(
            model_project, model_wells, well_id, "C", c_depth, b_depth
        )
        db.add_formation_top(
            model_project, model_wells, well_id, "B", b_depth,
            "observed", "synthetic"
        )
    constraints = model_adapter.gather_wells(model_project, model_wells)
    assert len(constraints["samples"]) == 3
    assert constraints["datum"] == "DHHN2016"
    mesh = model_core.build_mesh(
        constraints["samples"], constraints["horizons"], 4
    )
    assert len(mesh["faces"]) >= 16 and len(mesh["horizons"]) == 3

    # Existing file-based map in QGIS should stay the *same* instance and be
    # referenced in GroundSurf's map table, not cloned or restyled.
    polygon = QgsVectorLayer("LineString?crs=EPSG:4326", "Fault traces", "memory")
    line_feature = QgsFeature()
    line_feature.setGeometry(QgsGeometry.fromPolylineXY([
        QgsPointXY(13.34,52.49), QgsPointXY(13.38,52.52)
    ]))
    assert polygon.dataProvider().addFeatures([line_feature])[0]
    polygon.updateExtents()
    settings = QgsVectorFileWriter.SaveVectorOptions()
    settings.driverName = "GPKG"
    settings.fileEncoding = "UTF-8"
    settings.layerName = "mapped_faults"
    file_path = str(Path(temp) / "existing_maps.gpkg")
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        polygon, file_path, QgsProject.instance().transformContext(), settings
    )
    assert result[0] == QgsVectorFileWriter.WriterError.NoError, result
    existing_map = QgsVectorLayer(
        file_path + "|layername=mapped_faults", "Imported fault traces", "ogr"
    )
    assert existing_map.isValid()
    QgsProject.instance().addMapLayer(existing_map)
    original_id = existing_map.id()
    original_uri = existing_map.source()
    initial_count = len(QgsProject.instance().mapLayers())

    linked, sublayer, kind = file_backed_map(existing_map)
    assert linked == file_path, linked
    assert sublayer == "mapped_faults" and kind == "vector"

    iface = Iface()
    plugin = GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    dock = plugin.dock
    dock.load_project(str(project))
    assert dock.wells_table.rowCount() == 2
    # Button discoverability: source needs no intermediate CSV.
    buttons = [
        widget.text()
        for widget in dock.findChildren(QPushButton)
    ]
    assert "Import from QGIS" in buttons, buttons

    # Exercise the dock's actual Import from QGIS action with a test dialog,
    # without requiring manual clicks in the headless QGIS environment.
    one_well = QgsVectorLayer(
        "Point?crs=EPSG:3857", "Open QGIS point source", "memory"
    )
    one_well.dataProvider().addAttributes([
        QgsField("BH_ID", QVariant.String), QgsField("WellName", QVariant.String)
    ])
    one_well.updateFields()
    imported_feature = QgsFeature(one_well.fields())
    imported_feature.setGeometry(QgsGeometry.fromPointXY(
        transform.transform(QgsPointXY(13.365, 52.51))
    ))
    imported_feature.setAttributes(["BH-ACTION", "Test action well"])
    assert one_well.dataProvider().addFeatures([imported_feature])[0]
    one_well.updateExtents()
    QgsProject.instance().addMapLayer(one_well)
    action_mapping = guess_mapping([field.name() for field in one_well.fields()])
    class AcceptedImportDialog:
        def __init__(self, **kwargs):
            self.layers = [one_well]
            assert "preferred_layer_id" in kwargs
        def exec(self):
            return QDialog.DialogCode.Accepted
        def selection(self):
            return {
                "mode": "wells", "layer": one_well,
                "mapping": action_mapping, "selected_only": False,
            }
    prior_dialog = plugin_module.ImportFromQGISDialog
    plugin_module.ImportFromQGISDialog = AcceptedImportDialog
    try:
        dock.import_from_qgis()
    finally:
        plugin_module.ImportFromQGISDialog = prior_dialog
    assert dock.wells_table.rowCount() == 3
    assert any(f["well_id"] == "BH-ACTION" for f in dock.well_layer.getFeatures())
    assert one_well.featureCount() == 1

    before_link = len(QgsProject.instance().mapLayers())
    chosen = dock._load_map(
        linked, existing_map.name(), kind,
        record=True, source_layer=sublayer, existing_layer=existing_map
    )
    assert chosen.id() == original_id
    assert len(QgsProject.instance().mapLayers()) == before_link
    assert dock.map_layer_ids == []
    assert len(db.maps(project)) == 1
    assert existing_map.source() == original_uri

    # A GeoTIFF *already loaded in QGIS* is linked without creating a copy
    # or changing the user-owned raster layer.
    tif_file = str(Path(temp) / "terrain.tif")
    driver = gdal.GetDriverByName("GTiff")
    raster = driver.Create(tif_file, 3, 3, 1, gdal.GDT_Float32)
    raster.SetGeoTransform((13.3, 0.001, 0, 52.5, 0, -0.001))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    raster.SetProjection(srs.ExportToWkt())
    raster.GetRasterBand(1).Fill(31)
    raster.FlushCache()
    raster = None
    existing_raster = QgsRasterLayer(tif_file, "Existing QGIS terrain", "gdal")
    assert existing_raster.isValid()
    QgsProject.instance().addMapLayer(existing_raster)
    raster_id = existing_raster.id()
    file_raster, sublayer_raster, raster_kind = file_backed_map(existing_raster)
    assert file_raster == tif_file and sublayer_raster is None
    assert raster_kind == "raster"
    before_raster_link = len(QgsProject.instance().mapLayers())
    dock._load_map(
        file_raster, existing_raster.name(), raster_kind, record=True,
        source_layer=sublayer_raster, existing_layer=existing_raster
    )
    assert len(QgsProject.instance().mapLayers()) == before_raster_link
    assert dock.map_layer_ids == []
    assert len(db.maps(project)) == 2

    dock.refresh()
    assert dock.maps_table.rowCount() == 2
    # Reload the GroundSurf project while *keeping* the existing QGIS map.
    dock.load_project(str(project))
    assert len(QgsProject.instance().mapLayers()) == before_raster_link
    assert QgsProject.instance().mapLayer(original_id) is not None
    assert dock.map_registry[db.maps(project)[0][0]] == original_id
    assert QgsProject.instance().mapLayer(raster_id) is not None
    assert dock.map_layer_ids == []

    # Nonpersistent memory map references should be rejected with clear help.
    try:
        file_backed_map(source)
    except ValueError as exc:
        assert "file" in str(exc).lower() or "export" in str(exc).lower()
    else:
        raise AssertionError("Memory layer was linked as persistent map")

    plugin.unload()
    assert QgsProject.instance().mapLayer(original_id) is not None
    QgsProject.instance().clear()
    print(
        "PASS v0.4.2: QGIS point mapping, selected-only copy, CRS conversion, "
        "duplicate rollback, source unchanged, working 3D model from imported "
        "wells, GeoPackage and GeoTIFF existing maps linked without duplication, "
        "restart and Help buttons"
    )

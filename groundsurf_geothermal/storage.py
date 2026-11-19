"""QGIS-specific GeoPackage creation and well feature writes."""
from pathlib import Path
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject,
    QgsVectorFileWriter, QgsVectorLayer,
)
from . import db, sections, models

LAYER_NAME = "gs_wells"
FIELDS = (
    ("well_id", QVariant.String), ("name", QVariant.String),
    ("total_depth_m", QVariant.Double), ("ground_elev_m", QVariant.Double),
    ("vertical_datum", QVariant.String), ("source", QVariant.String),
    ("notes", QVariant.String),
)


def create_project(path):
    path = str(Path(path).resolve())
    if Path(path).exists():
        raise ValueError("Choose a new filename: existing projects are not overwritten")
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "Wells", "memory")
    if not layer.isValid():
        raise RuntimeError("Cannot create memory well layer")
    layer.dataProvider().addAttributes([QgsField(name, kind) for name, kind in FIELDS])
    layer.updateFields()
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = LAYER_NAME
    options.fileEncoding = "UTF-8"
    outcome = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsProject.instance().transformContext(), options
    )
    if outcome[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError("Cannot create GeoPackage: " + str(outcome))
    db.bootstrap(path)
    sections.ensure_schema(path, backup_existing=False)
    models.ensure_schema(path, backup_existing=False)
    if not db.valid_project(path):
        raise RuntimeError("GeoPackage schema verification failed")
    return path


def open_wells(path):
    layer = QgsVectorLayer(f"{path}|layername={LAYER_NAME}", "Wells", "ogr")
    if not layer.isValid():
        raise RuntimeError("Cannot open wells layer")
    return layer


def add_wells(layer, records):
    existing = {str(f["well_id"]) for f in layer.getFeatures()}
    overlap = existing & {r["well_id"] for r in records}
    if overlap:
        raise ValueError("Existing well IDs: " + ", ".join(sorted(overlap)[:8]))
    if not layer.startEditing():
        raise RuntimeError("Cannot open well layer for editing")
    try:
        for record in records:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(
                QgsPointXY(record["longitude"], record["latitude"])
            ))
            for field_name, _ in FIELDS:
                feature[field_name] = record.get(field_name)
            if not layer.addFeature(feature):
                raise RuntimeError("Could not add well: " + record["well_id"])
        if not layer.commitChanges():
            message = "; ".join(layer.commitErrors())
            layer.rollBack()
            raise RuntimeError("Could not save wells: " + message)
    except Exception:
        if layer.isEditable():
            layer.rollBack()
        raise
    layer.reload()
    return len(records)

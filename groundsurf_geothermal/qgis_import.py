"""Import well points or link file-backed maps from the *open* QGIS project.

Operations are deliberately separate:
- Wells: copy feature coordinates and mapped attributes into GroundSurf GPKG.
- Map: add a persistent file reference, without changing or duplicating
  an existing QGIS layer. Linked maps do not automatically become geological
  constraints in the 3D modelling engine.

No network, data alteration to input layers, or external Python packages.
"""
from pathlib import Path
import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QLabel, QMessageBox, QVBoxLayout,
)
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry,
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsWkbTypes,
)

from . import db, storage

FIELD_OPTIONS = (
    ("well_id", "Well ID *"),
    ("name", "Well name (defaults to ID)"),
    ("total_depth_m", "Total depth (metres below ground)"),
    ("ground_elev_m", "Ground elevation (metres)"),
    ("vertical_datum", "Vertical elevation datum"),
    ("source", "Data source / provenance"),
    ("notes", "Notes"),
)
ALIASES = {
    "well_id": (
        "well_id", "wellid", "borehole_id", "boreholeid", "bh_id",
        "hole_id", "holeid", "well_no", "well_number", "uwi", "id",
    ),
    "name": ("name", "well_name", "wellname", "borehole_name", "bh_name",
             "description", "well"),
    "total_depth_m": (
        "total_depth_m", "totaldepth", "depth_m", "depth", "td",
        "well_depth", "bh_depth", "borehole_depth",
    ),
    "ground_elev_m": (
        "ground_elev_m", "ground_elevation", "ground_level", "surface_elev",
        "surface_elevation", "elevation", "elev", "rl",
    ),
    "vertical_datum": ("vertical_datum", "verticaldatum", "height_datum",
                       "elevation_datum", "datum"),
    "source": ("source", "data_source", "origin", "provenance"),
    "notes": ("notes", "comments", "remark", "remarks"),
}
MAX_WELLS = db.MAX_CSV_WELLS


def normalised_field(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def guess_mapping(field_names):
    """Conservative case/spacing-insensitive mapping, no field reused."""
    chosen = set()
    result = {}
    for target, _ in FIELD_OPTIONS:
        matches = {
            normalised_field(alias): priority
            for priority, alias in enumerate(ALIASES.get(target, (target,)))
        }
        candidates = [
            (matches[normalised_field(name)], index, name)
            for index, name in enumerate(field_names)
            if normalised_field(name) in matches and name not in chosen
        ]
        if candidates:
            _, _, name = min(candidates)
            chosen.add(name)
            result[target] = name
        else:
            result[target] = None
    return result


def is_point_layer(layer):
    return (
        isinstance(layer, QgsVectorLayer)
        and layer.isValid()
        and layer.geometryType() == QgsWkbTypes.GeometryType.PointGeometry
    )


def eligible_layers(excluded_ids=()):
    """Enumerate open user layers only; no need to read file paths or catalogues."""
    exclude = set(excluded_ids)
    return sorted(
        (
            layer for layer in QgsProject.instance().mapLayers().values()
            if layer.isValid() and layer.id() not in exclude
            and isinstance(layer, (QgsVectorLayer, QgsRasterLayer))
        ),
        key=lambda layer: layer.name().casefold(),
    )


def _source_value(feature, key):
    if key is None:
        return None
    value = feature[key]
    if value is None or str(value) == "NULL":
        return None
    value = str(value).strip()
    return value if value else None


def prepare_well_records(layer, mapping, selected_only=False):
    """Validate all features and transform geometry before any GPKG write.

    Caller should use storage.add_wells() only after this function succeeds.
    """
    if not is_point_layer(layer):
        raise ValueError("Only QGIS point layers can be copied as wells")
    if not layer.crs().isValid():
        raise ValueError("The source QGIS layer has no valid CRS")
    declared = {field.name() for field in layer.fields()}
    for target, source_field in mapping.items():
        if source_field and source_field not in declared:
            raise ValueError(f"Field {source_field!r} no longer exists")
    if not mapping.get("well_id"):
        raise ValueError("Map a source field to Well ID first")
    if selected_only:
        if layer.selectedFeatureCount() == 0:
            raise ValueError("No QGIS features are selected")
        features = layer.getSelectedFeatures()
    else:
        features = layer.getFeatures()

    to_wgs84 = QgsCoordinateTransform(
        layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance()
    )
    records, ids = [], set()
    for feature in features:
        if len(records) >= MAX_WELLS:
            raise ValueError(f"Import maximum: {MAX_WELLS} well features")
        label = f"Feature {feature.id()}"
        try:
            geometry = QgsGeometry(feature.geometry())  # never edit source geometry
            if geometry.isEmpty():
                raise ValueError("missing point geometry")
            if geometry.isMultipart():
                points = geometry.asMultiPoint()
                if len(points) != 1:
                    raise ValueError("multipoint well must contain exactly one point")
            geometry.transform(to_wgs84)
            if geometry.isMultipart():
                transformed = geometry.asMultiPoint()[0]
            else:
                transformed = geometry.asPoint()
            mapped = {
                target: _source_value(feature, mapping.get(target))
                for target, _ in FIELD_OPTIONS
            }
            well_id = mapped["well_id"]
            if well_id is None:
                raise ValueError("missing Well ID")
            mapped["name"] = mapped["name"] or well_id
            mapped["longitude"] = transformed.x()
            mapped["latitude"] = transformed.y()
            mapped["source"] = mapped["source"] or f"QGIS layer: {layer.name()}"
            item = db.validate_well(mapped)
        except Exception as exc:
            raise ValueError(f"{label}: {exc}") from exc
        if item["well_id"] in ids:
            raise ValueError(f"{label}: duplicate well ID {item['well_id']!r} in source")
        ids.add(item["well_id"])
        records.append(item)
    if not records:
        raise ValueError("No well features available for import")
    return records


def import_wells(layer, groundsurf_wells, mapping, selected_only=False):
    """All-or-nothing copy into the GroundSurf GeoPackage."""
    records = prepare_well_records(layer, mapping, selected_only)
    count = storage.add_wells(groundsurf_wells, records)
    return count


def file_backed_map(layer):
    """Return (absolute filepath, layer name in container, type).

    Prevent storing web service credentials, unstable memory layer URIs or
    unaudited datasource strings in the local project.
    """
    if not isinstance(layer, (QgsVectorLayer, QgsRasterLayer)) or not layer.isValid():
        raise ValueError("Select a valid QGIS map layer")
    kind = "raster" if isinstance(layer, QgsRasterLayer) else "vector"
    if kind == "vector" and layer.providerType() != "ogr":
        raise ValueError(
            "Only file-based OGR maps can be linked permanently. "
            "Copy wells directly, or export this map to a GeoPackage first."
        )
    if kind == "raster" and layer.providerType() != "gdal":
        raise ValueError(
            "Only local GDAL raster files can be linked permanently. "
            "Export the source to GeoTIFF first."
        )
    uri = str(layer.source())
    # QGIS OGR file sources may add |layername= or |layerid= .
    base = uri.split("|", 1)[0]
    if not base or base.startswith(("http:", "https:", "file:", "/vsicurl/")):
        raise ValueError("Only plain local file paths can be linked")
    path = Path(base).expanduser()
    if not path.is_file():
        raise ValueError(
            "Source is not an accessible local file. Save the QGIS layer "
            "as a GeoPackage or GeoTIFF, then try again."
        )
    suffix = path.suffix.casefold()
    if kind == "raster" and suffix not in (".tif", ".tiff"):
        raise ValueError("Raster links currently support local GeoTIFF files")
    if kind == "vector" and suffix not in (".gpkg", ".shp", ".geojson", ".json"):
        raise ValueError("Vector links support GeoPackage, shapefile or GeoJSON")
    sublayer = None
    if kind == "vector" and suffix == ".gpkg":
        match = re.search(r"(?:^|\|)layername=([^|]+)", uri)
        if match:
            sublayer = match.group(1)
        else:
            # Without a named sublayer, only an unambiguous single-table
            # GeoPackage can be safely reloaded.
            from qgis.core import QgsProviderRegistry
            matches = [
                item.name()
                for item in QgsProviderRegistry.instance().querySublayers(str(path))
                if item.providerKey() == "ogr"
            ]
            matches = list(dict.fromkeys(matches))
            if len(matches) != 1:
                raise ValueError(
                    "Multi-layer GeoPackage needs an explicit layername. "
                    "Use Add map layer to select the precise sublayer."
                )
            sublayer = matches[0]
    return str(path.resolve()), sublayer, kind


class ImportFromQGISDialog(QDialog):
    """Field-mapping preview of sources already in the QGIS layer tree."""

    def __init__(self, excluded_ids=(), preferred_layer_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import from open QGIS project")
        self.setMinimumWidth(485)
        self.layers = eligible_layers(excluded_ids)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose an existing QGIS layer. Copy well points into the local "
            "GroundSurf GeoPackage, or link a map without copying it."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.layer_combo = QComboBox()
        for layer in self.layers:
            cls = "raster" if isinstance(layer, QgsRasterLayer) else (
                "points" if is_point_layer(layer) else "vector"
            )
            self.layer_combo.addItem(
                f"{layer.name()}  [{cls} · {layer.providerType()}]", layer.id()
            )
        form.addRow("Open QGIS layer", self.layer_combo)
        self.mode_combo = QComboBox()
        form.addRow("Operation", self.mode_combo)
        layout.addLayout(form)

        self.details = QLabel("")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)

        self.mapping_box = QGroupBox("Well attribute mapping")
        mapping_layout = QFormLayout(self.mapping_box)
        self.mapping_combo = {}
        for target, caption in FIELD_OPTIONS:
            combo = QComboBox()
            self.mapping_combo[target] = combo
            mapping_layout.addRow(caption, combo)
        self.selected_only = QCheckBox("Import selected features only")
        mapping_layout.addRow(self.selected_only)
        explanation = QLabel(
            "Coordinates come from point geometry, not X/Y fields. "
            "GroundSurf converts to WGS84 automatically. Depths and "
            "elevations must already be in metres; vertical datum is not converted."
        )
        explanation.setWordWrap(True)
        mapping_layout.addRow(explanation)
        layout.addWidget(self.mapping_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.layer_combo.currentIndexChanged.connect(self._update_layer)
        self.mode_combo.currentIndexChanged.connect(self._update_mode)
        if preferred_layer_id:
            index = self.layer_combo.findData(preferred_layer_id)
            if index >= 0:
                self.layer_combo.setCurrentIndex(index)
        self._update_layer()

    def selected_layer(self):
        return QgsProject.instance().mapLayer(self.layer_combo.currentData())

    def _update_layer(self, *_):
        layer = self.selected_layer()
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        if layer is not None and is_point_layer(layer):
            self.mode_combo.addItem("Copy point features as GroundSurf wells", "wells")
        self.mode_combo.addItem("Link existing map source (no data copied)", "map")
        self.mode_combo.blockSignals(False)
        self._update_mode()

    def _update_mode(self, *_):
        layer = self.selected_layer()
        if layer is None:
            self.mapping_box.setVisible(False)
            self.details.setText("No layers are open in the QGIS project.")
            return
        is_wells = self.mode_combo.currentData() == "wells"
        self.mapping_box.setVisible(is_wells)
        if is_wells:
            names = [f.name() for f in layer.fields()]
            suggested = guess_mapping(names)
            for target, _caption in FIELD_OPTIONS:
                combo = self.mapping_combo[target]
                combo.clear()
                combo.addItem("(not mapped)", None)
                for field_name in names:
                    combo.addItem(field_name, field_name)
                chosen = suggested.get(target)
                if chosen is not None:
                    combo.setCurrentIndex(combo.findData(chosen))
            self.selected_only.setEnabled(layer.selectedFeatureCount() > 0)
            self.selected_only.setChecked(layer.selectedFeatureCount() > 0)
            self.details.setText(
                f"{layer.featureCount()} point features, "
                f"{layer.selectedFeatureCount()} selected. "
                f"Source CRS: {layer.crs().authid() or 'UNDEFINED'}. "
                "Mapped wells are COPIED; the QGIS source stays unchanged."
            )
        else:
            self.details.setText(
                "Map link: keep the layer's existing file on disk. "
                "This will register it as a map in GroundSurf without "
                "duplicating its QGIS layer or importing it as a 3D model constraint. "
                "Only local file-backed maps are supported."
            )

    def selection(self):
        if self.result() != QDialog.DialogCode.Accepted:
            return None
        layer = self.selected_layer()
        if layer is None or not layer.isValid():
            raise ValueError("Selected QGIS layer is no longer available")
        if self.mode_combo.currentData() == "wells":
            return dict(
                mode="wells",
                layer=layer,
                mapping={
                    target: combo.currentData()
                    for target, combo in self.mapping_combo.items()
                },
                selected_only=self.selected_only.isChecked(),
            )
        return dict(mode="map", layer=layer)

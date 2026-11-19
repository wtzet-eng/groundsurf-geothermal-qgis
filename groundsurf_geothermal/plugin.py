"""GroundSurf Geothermal 0.4: wells, maps and local project workspace."""
import os
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, Qt, QUrl
from qgis.PyQt.QtGui import QIcon, QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAction, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsCoordinateTransform, QgsMarkerSymbol, QgsProject, QgsProviderRegistry, QgsRasterLayer,
    QgsVectorLayer,
)
from . import db, storage
from .well_manager import WellManagerMixin
from .section_ui import SectionToolsMixin
from .model_ui import ModelToolsMixin
from . import sections, models


class GroundSurfGeothermalPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None

    def initGui(self):
        self.action = QAction(
            QIcon.fromTheme("applications-science"), "GroundSurf Geothermal",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.open_dock)
        self.iface.addPluginToMenu("&GroundSurf Geothermal", self.action)
        self.iface.addToolBarIcon(self.action)

    def open_dock(self):
        if self.dock is None:
            self.dock = GeothermalDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()

    def unload(self):
        if self.dock is not None:
            if getattr(self.dock, "_section_window", None):
                self.dock._section_window.close()
            for layer_id in getattr(self.dock, "_preview_line_ids", {}).values():
                QgsProject.instance().removeMapLayer(layer_id)
        if self.action is not None:
            self.iface.removePluginMenu("&GroundSurf Geothermal", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None


class GeothermalDock(ModelToolsMixin, SectionToolsMixin, WellManagerMixin, QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("GroundSurf Geothermal", parent)
        self.iface = iface
        self.path = None
        self.well_layer = None
        self.map_layer_ids = []
        self.map_registry = {}
        self._preview_line_ids = {}
        self.settings = QSettings("GroundSurf", "Geothermal")
        self.theme = self.settings.value("theme", "dark")
        self.setObjectName("GroundSurfGeothermalDock")
        self.setMinimumWidth(360)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self._build_ui()
        self._set_theme()
        last = self.settings.value("last_project", "")
        if last and db.project_version(last) in ('1', '2'):
            try:
                self.load_project(last)
            except Exception:
                self.status.setText("Previous project unavailable; create or open a project.")

    def _build_ui(self):
        content = QWidget()
        self.setWidget(content)
        outer = QVBoxLayout(content)
        outer.setSpacing(9)
        heading = QLabel("GroundSurf  /  GEOTHERMAL")
        heading.setObjectName("gsHeading")
        outer.addWidget(heading)
        description = QLabel("Wells · Logs · 3D Models · Maps")
        description.setObjectName("gsDescription")
        outer.addWidget(description)

        actions = QGridLayout()
        entries = (
            ("New project", self.new_project),
            ("Open project", self.open_project),
            ("Add well", self.add_well),
            ("Import wells CSV", self.import_csv),
            ("Add map layer", self.add_map),
            ("Relink map", self.relink_map),
            ("Switch theme", self.toggle_theme),
            ("Help & feedback", self.open_help),
        )
        for index, (caption, handler) in enumerate(entries):
            button = QPushButton(caption)
            button.clicked.connect(handler)
            actions.addWidget(button, index // 2, index % 2)
        outer.addLayout(actions)

        self.project_label = QLabel("No project loaded")
        self.project_label.setWordWrap(True)
        outer.addWidget(self.project_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("PROJECT EXPLORER")
        self.tree.itemClicked.connect(self._tree_selected)
        splitter.addWidget(self.tree)

        tabs = QTabWidget()
        self.tabs = tabs
        self.wells_table = QTableWidget(0, 4)
        self.wells_table.setHorizontalHeaderLabels(
            ["Well ID", "Name", "Depth (m)", "Elevation (m)"]
        )
        self.wells_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.wells_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.wells_table.cellClicked.connect(self._zoom_well)
        tabs.addTab(self.wells_table, "Wells")

        self.maps_table = QTableWidget(0, 3)
        self.maps_table.setHorizontalHeaderLabels(["Layer", "Type", "Source"])
        self.maps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tabs.addTab(self.maps_table, "Maps")
        self.setup_well_manager(outer, tabs)
        self.setup_section_tools(tabs)
        self.setup_model_tools(tabs)

        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlainText(
            "GroundSurf Geothermal 0.4\n\n"
            "Local GeoPackage projects and WGS84 well locations.\n"
            "Depths: metres, positive downward.\n"
            "Elevations: metres, datum supplied by user.\n\n"
            "Cross-sections are illustrative interpretations based on wells.\n"
            "Preliminary 3D horizons are now available. Flow/heat simulation "
            "and validated structural modelling remain future modules."
        )
        tabs.addTab(self.info, "Details")
        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)
        contact_header = QLabel("Questions or suggestions for GroundSurf Geothermal?")
        contact_header.setWordWrap(True)
        help_layout.addWidget(contact_header)
        email_label = QLabel("Feedback: tzuk.ls@outlook.com")
        email_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        help_layout.addWidget(email_label)
        contact = QPushButton("Email feedback")
        contact.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("mailto:tzuk.ls@outlook.com?subject=GroundSurf%20Geothermal%20feedback")
            )
        )
        help_layout.addWidget(contact)
        video_label = QLabel("Videos and demonstrations: YouTube @Ground-Surf")
        video_label.setWordWrap(True)
        help_layout.addWidget(video_label)
        youtube = QPushButton("Open GroundSurf YouTube channel")
        youtube.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://www.youtube.com/@Ground-Surf")
            )
        )
        help_layout.addWidget(youtube)
        caution = QLabel(
            "Experimental free tool. No cloud upload by default. "
            "Cross-section correlations are interpreted, not proven geology."
        )
        caution.setWordWrap(True)
        help_layout.addWidget(caution)
        help_layout.addStretch()
        self.help_tab_index = tabs.addTab(help_tab, "Help")
        splitter.addWidget(tabs)
        splitter.setSizes([170, 360])
        outer.addWidget(splitter, 1)

        self.status = QLabel("Offline by design · No cloud data transfer")
        self.status.setObjectName("gsStatus")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.refresh()

    def _set_theme(self):
        if self.theme == "dark":
            self.widget().setStyleSheet("""
                QWidget { background:#212121; color:#e6e9e7; }
                QLabel#gsHeading { color:#8db99a; font-size:16px; font-weight:700; }
                QLabel#gsDescription, QLabel#gsStatus { color:#a1aca7; }
                QPushButton { background:#303b34; border:1px solid #536957;
                              padding:8px; border-radius:3px; }
                QPushButton:hover { background:#405847; }
                QTreeWidget, QTableWidget, QTextEdit {
                    background:#252c28; alternate-background-color:#303732;
                    selection-background-color:#395e45; border:1px solid #4b574f;
                }
                QTabWidget::pane { border:1px solid #4b574f; }
                QTabBar::tab { background:#303732; padding:7px; }
                QTabBar::tab:selected { background:#395e45; }
            """)
        else:
            self.widget().setStyleSheet("""
                QWidget { background:#f7f9f7; color:#222b26; }
                QLabel#gsHeading { color:#225b39; font-size:16px; font-weight:700; }
                QLabel#gsDescription, QLabel#gsStatus { color:#56695e; }
                QPushButton { background:#e8f1eb; border:1px solid #afc6b5;
                              padding:8px; border-radius:3px; }
                QPushButton:hover { background:#d2e7d8; }
                QTreeWidget, QTableWidget, QTextEdit {
                    background:#fff; selection-background-color:#b3dbc1;
                    border:1px solid #bccbc0;
                }
                QTabBar::tab { background:#e8f1eb; padding:7px; }
                QTabBar::tab:selected { background:#c2dfca; }
            """)

    def open_help(self):
        self.tabs.setCurrentIndex(self.help_tab_index)

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.settings.setValue("theme", self.theme)
        self._set_theme()

    def _error(self, title, exc):
        self.status.setText(f"{title}: {exc}")
        QMessageBox.warning(self, title, str(exc))

    def _require_project(self):
        if not self.path or not self.well_layer:
            QMessageBox.information(self, "Create a project",
                                    "Create or open a local GeoPackage project first.")
            return False
        return True

    def new_project(self):
        name, _ = QFileDialog.getSaveFileName(
            self, "Create local GroundSurf project", str(Path.home() / "groundsurf_project.gpkg"),
            "GeoPackage (*.gpkg)"
        )
        if not name:
            return
        if not name.lower().endswith(".gpkg"):
            name += ".gpkg"
        try:
            storage.create_project(name)
            self.load_project(name)
            self.status.setText("New GeoPackage project created locally.")
        except Exception as exc:
            self._error("Cannot create project", exc)

    def open_project(self):
        name, _ = QFileDialog.getOpenFileName(
            self, "Open GroundSurf project", str(Path.home()), "GeoPackage (*.gpkg)"
        )
        if name:
            try:
                self.load_project(name)
            except Exception as exc:
                self._error("Cannot open project", exc)

    def load_project(self, path):
        path = str(Path(path).resolve())
        version = db.project_version(path)
        if version == "1":
            answer = QMessageBox.question(
                self, "Upgrade project database?",
                "This is a version 0.1 project. Upgrade to v0.2?\n"
                "An automatic SQLite backup is created beside the GeoPackage.\n"
                "Cancel to leave the original project untouched.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            db.migrate_v1(path)
        elif version != db.SCHEMA_VERSION:
            raise ValueError("Not a supported GroundSurf Geothermal project")

        backup = sections.ensure_schema(path, backup_existing=True)
        model_backup = models.ensure_schema(path, backup_existing=True)
        if self._section_window is not None:
            self._section_window.close()
            self._section_window = None
        if self.well_layer is not None:
            QgsProject.instance().removeMapLayer(self.well_layer.id())
        for layer_id in self.map_layer_ids:
            QgsProject.instance().removeMapLayer(layer_id)
        for layer_id in self._preview_line_ids.values():
            QgsProject.instance().removeMapLayer(layer_id)
        self._preview_line_ids = {}
        self.map_layer_ids = []
        self.map_registry = {}

        layer = storage.open_wells(path)
        layer.setName("GroundSurf · Wells")
        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle", "color": "55,129,79,255",
            "outline_color": "22,51,30,255", "size": "2.8"
        })
        layer.renderer().setSymbol(symbol)
        QgsProject.instance().addMapLayer(layer)
        self.well_layer = layer
        self.path = path
        self.settings.setValue("last_project", path)
        self.project_label.setText("Project: " + Path(path).name)

        missing = 0
        for row in db.maps(path):
            target, source_layer = db.resolve_map(path, row)
            if target is None:
                missing += 1
                continue
            try:
                loaded = self._load_map(str(target), row[2], row[3],
                                        record=False, source_layer=source_layer)
                self.map_registry[row[0]] = loaded.id()
            except Exception:
                missing += 1
        self.refresh()
        if backup or model_backup:
            self.status.setText(
                "New modelling tables installed; database backups saved locally."
            )
        self.status.setText(
            f"Project opened. {missing} map source(s) missing or unreadable. "
            "Select a map row and use Relink map." if missing else
            "Project opened. Local geology and observation tables are ready."
        )

    def add_well(self):
        if not self._require_project():
            return
        labels = (
            ("well_id", "Well ID *"), ("name", "Name *"),
            ("latitude", "Latitude (WGS84) *"),
            ("longitude", "Longitude (WGS84) *"),
            ("total_depth_m", "Total depth (m)"),
            ("ground_elev_m", "Ground elevation (m)"),
            ("vertical_datum", "Elevation datum"),
            ("source", "Source"),
            ("notes", "Notes"),
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("Add well")
        form = QFormLayout(dialog)
        widgets = {}
        for key, caption in labels:
            entry = QLineEdit()
            form.addRow(caption, entry)
            widgets[key] = entry
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            well = db.validate_well({k: v.text() for k, v in widgets.items()})
            storage.add_wells(self.well_layer, [well])
            self.refresh()
            self.status.setText("Saved well " + well["well_id"])
        except Exception as exc:
            self._error("Could not save well", exc)

    def import_csv(self):
        if not self._require_project():
            return
        name, _ = QFileDialog.getOpenFileName(
            self, "Import well locations", str(Path.home()), "CSV files (*.csv)"
        )
        if not name:
            return
        try:
            with open(name, "r", encoding="utf-8-sig", newline="") as handle:
                rows = db.parse_well_csv(handle.read())
            count = storage.add_wells(self.well_layer, rows)
            self.refresh()
            self.status.setText(f"Imported {count} wells. Coordinates interpreted as WGS84.")
        except Exception as exc:
            self._error("Well import failed", exc)

    def _make_map_layer(self, file_path, name, kind, source_layer=None):
        uri = str(file_path)
        if kind == "vector" and source_layer:
            uri += "|layername=" + source_layer
        layer = (QgsRasterLayer(uri, name) if kind == "raster"
                 else QgsVectorLayer(uri, name, "ogr"))
        if not layer.isValid():
            raise ValueError("Cannot read map layer: " + file_path)
        return layer

    def _load_map(self, file_path, name, kind, record, source_layer=None):
        layer = self._make_map_layer(file_path, name, kind, source_layer)
        if record:
            db.record_map(self.path, file_path, name, kind, source_layer)
            for record_id, abs_path, _name, _kind, _rel, source in db.maps(self.path):
                if (abs_path == str(Path(file_path).resolve()) and
                        source == (source_layer or "")):
                    previous = self.map_registry.pop(record_id, None)
                    if previous is not None:
                        QgsProject.instance().removeMapLayer(previous)
                        if previous in self.map_layer_ids:
                            self.map_layer_ids.remove(previous)
                    self.map_registry[record_id] = layer.id()
                    break
        QgsProject.instance().addMapLayer(layer)
        self.map_layer_ids.append(layer.id())
        return layer

    def _choose_map_sublayer(self, file_path):
        if Path(file_path).suffix.lower() != ".gpkg":
            return None
        candidates = QgsProviderRegistry.instance().querySublayers(file_path)
        vector_names = [item.name() for item in candidates
                        if item.providerKey() == "ogr" and item.name() != "gs_wells"]
        # If gs_wells is the only vector table in a GeoPackage, allow it.
        if not vector_names:
            vector_names = [item.name() for item in candidates
                            if item.providerKey() == "ogr"]
        vector_names = list(dict.fromkeys(vector_names))
        if len(vector_names) == 1:
            return vector_names[0]
        if len(vector_names) > 1:
            name, ok = QInputDialog.getItem(
                self, "Select GeoPackage layer", "Map layer", vector_names, 0, False
            )
            if not ok:
                return ""
            return name
        raise ValueError("No readable vector layers in selected GeoPackage")

    def add_map(self):
        if not self._require_project():
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Add local map", str(Path.home()),
            "Map layers (*.gpkg *.shp *.geojson *.tif *.tiff);;All files (*)"
        )
        if not file_path:
            return
        kind = "raster" if file_path.lower().endswith((".tif", ".tiff")) else "vector"
        try:
            source_layer = self._choose_map_sublayer(file_path)
            if source_layer == "":
                return
            name = source_layer or Path(file_path).stem
            self._load_map(file_path, name, kind, record=True,
                           source_layer=source_layer)
            self.refresh()
            self.status.setText("Map added locally; relative path stored for portability.")
        except Exception as exc:
            self._error("Cannot add map", exc)

    def relink_map(self):
        if not self._require_project():
            return
        selected = self.maps_table.currentRow()
        if selected < 0:
            QMessageBox.information(
                self, "Select map", "Select a map row before choosing its replacement."
            )
            return
        record_id = self.maps_table.item(selected, 0).data(Qt.ItemDataRole.UserRole)
        rows = [r for r in db.maps(self.path) if r[0] == record_id]
        if not rows:
            return
        record = rows[0]
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Locate missing map source", str(Path(self.path).parent),
            "Map layers (*.gpkg *.shp *.geojson *.tif *.tiff);;All files (*)"
        )
        if not file_path:
            return
        try:
            kind = "raster" if file_path.lower().endswith((".tif", ".tiff")) else "vector"
            if kind != record[3]:
                raise ValueError("Replacement map type must match original map type")
            source_layer = self._choose_map_sublayer(file_path)
            if source_layer == "":
                return
            # Verify the provider can read the replacement before changing
            # its database reference or removing the previous QGIS layer.
            layer = self._make_map_layer(
                file_path, record[2], kind, source_layer
            )
            db.relink_map(self.path, record_id, file_path, source_layer)
            old_layer_id = self.map_registry.pop(record_id, None)
            if old_layer_id is not None:
                QgsProject.instance().removeMapLayer(old_layer_id)
                if old_layer_id in self.map_layer_ids:
                    self.map_layer_ids.remove(old_layer_id)
            QgsProject.instance().addMapLayer(layer)
            self.map_registry[record_id] = layer.id()
            self.map_layer_ids.append(layer.id())
            self.refresh()
            self.status.setText("Map source repaired.")
        except Exception as exc:
            self._error("Cannot relink map", exc)

    def refresh(self):
        self.tree.clear()
        well_root = QTreeWidgetItem(self.tree, ["Wells"])
        map_root = QTreeWidgetItem(self.tree, ["Maps"])
        QTreeWidgetItem(self.tree, ["3D Models · preliminary"])
        self.wells_table.setRowCount(0)
        self.maps_table.setRowCount(0)
        if not self.path or not self.well_layer:
            self.tree.expandAll()
            self.refresh_well_details()
            self.refresh_sections()
            self.refresh_models()
            return
        for well in self.well_layer.getFeatures():
            code = str(well["well_id"])
            QTreeWidgetItem(well_root, [code + " · " + str(well["name"])])
            row = self.wells_table.rowCount()
            self.wells_table.insertRow(row)
            for col, key in enumerate(("well_id", "name", "total_depth_m", "ground_elev_m")):
                value = well[key]
                cell = QTableWidgetItem(
                    "" if value is None or str(value) == "NULL" else str(value)
                )
                self.wells_table.setItem(row, col, cell)
        for map_row in db.maps(self.path):
            identifier, absolute, layer_name, kind, relative, source_layer = map_row
            target, _ = db.resolve_map(self.path, map_row)
            state = "Available" if target else "Missing — relink required"
            QTreeWidgetItem(map_root, [layer_name + (" ⚠" if not target else "")])
            row = self.maps_table.rowCount()
            self.maps_table.insertRow(row)
            item = QTableWidgetItem(layer_name)
            item.setData(Qt.ItemDataRole.UserRole, identifier)
            self.maps_table.setItem(row, 0, item)
            self.maps_table.setItem(row, 1, QTableWidgetItem(kind))
            self.maps_table.setItem(row, 2, QTableWidgetItem(state))
        self.tree.expandAll()
        self.wells_table.resizeColumnsToContents()
        self.refresh_well_details()
        self.refresh_sections()
        self.refresh_models()

    def _tree_selected(self, item, column):
        self.status.setText("Selected: " + item.text(0))

    def _zoom_well(self, row, column):
        if not self.well_layer:
            return
        item = self.wells_table.item(row, 0)
        if item is None:
            return
        for feature in self.well_layer.getFeatures():
            if str(feature["well_id"]) != item.text():
                continue
            index = self.well_select.findData(item.text())
            if index >= 0:
                self.well_select.setCurrentIndex(index)
            point = feature.geometry().asPoint()
            canvas = self.iface.mapCanvas()
            transformer = QgsCoordinateTransform(
                self.well_layer.crs(), canvas.mapSettings().destinationCrs(),
                QgsProject.instance()
            )
            canvas.setCenter(transformer.transform(point))
            canvas.zoomScale(10000)
            canvas.refresh()
            self.info.setPlainText(
                "Well: " + str(feature["name"]) + "\n"
                + "ID: " + str(feature["well_id"]) + "\n"
                + "Total depth: " + str(feature["total_depth_m"]) + " m\n"
                + "Ground elevation: " + str(feature["ground_elev_m"]) + " m\n"
                + "Vertical datum: " + str(feature["vertical_datum"]) + "\n"
                + "Source: " + str(feature["source"]) + "\n"
                + "Notes: " + str(feature["notes"])
            )
            self.status.setText("Centered map on " + item.text())
            break

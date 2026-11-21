"""Studio by GroundSurf: QGIS geological modelling workspace."""
import os
from shutil import which
from pathlib import Path

from qgis.PyQt.QtCore import QProcess, QProcessEnvironment, QSettings, Qt, QUrl
from qgis.PyQt.QtGui import QIcon, QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAction, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import (
    Qgis, QgsCoordinateTransform, QgsMarkerSymbol, QgsMessageLog, QgsProject,
    QgsProviderRegistry, QgsRasterLayer, QgsVectorLayer,
)
from . import db, storage
from .browser_studio import BrowserStudio
from .well_manager import WellManagerMixin
from .section_ui import SectionToolsMixin
from .model_ui import ModelToolsMixin
from .contact_ui import ContactToolsMixin
from . import sections, models, elevation_contacts, elevation_import, local_xyz
from .qgis_import import ImportFromQGISDialog, file_backed_map, import_wells
from . import grouped_import


class GroundSurfGeothermalPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None

    def initGui(self):
        self.action = QAction(
            QIcon.fromTheme("applications-science"), "Studio by GroundSurf",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.open_dock)
        self.iface.addPluginToMenu("&Studio by GroundSurf", self.action)
        self.iface.addToolBarIcon(self.action)

    def open_dock(self):
        if self.dock is None:
            self.dock = GeothermalDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()

    def unload(self):
        if self.dock is not None:
            self.dock.close_studio()
            if getattr(self.dock, "_browser_studio", None):
                self.dock._browser_studio.stop()
            if getattr(self.dock, "_section_window", None):
                self.dock._section_window.close()
            for layer_id in getattr(self.dock, "_preview_line_ids", {}).values():
                QgsProject.instance().removeMapLayer(layer_id)
        if self.action is not None:
            self.iface.removePluginMenu("&Studio by GroundSurf", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None


class _GeothermalStudioWindow(QDialog):
    """One independent modelling window, using the dock's live widgets.

    We reparent the existing splitter rather than cloning state. Imported
    source data and all tab connections belong to one GeothermalDock.
    Closing the window returns the unchanged workspace to that dock.
    """

    def __init__(self, owner):
        super().__init__(owner.iface.mainWindow(), Qt.WindowType.Window)
        self.owner = owner
        self.setWindowTitle("Studio by GroundSurf · QGIS workspace")
        self.setObjectName("GroundSurfGeothermalStudio")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(690, 465)
        self.resize(1080, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.heading = QLabel("GROUNDSURF  /  GEOLOGICAL STUDIO")
        self.heading.setObjectName("gsHeading")
        layout.addWidget(self.heading)
        subtitle = QLabel(
            "Your QGIS layers remain in QGIS. Import, model and inspect "
            "the same local GroundSurf project here."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        # The live splitter is inserted by GeothermalDock.open_studio().
        self.workspace_layout = layout

    def closeEvent(self, event):
        self.owner._restore_studio_workspace()
        super().closeEvent(event)


class GeothermalDock(ContactToolsMixin, ModelToolsMixin,
                     SectionToolsMixin, WellManagerMixin, QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("Studio by GroundSurf · Geology", parent)
        self.iface = iface
        self.path = None
        self.well_layer = None
        self.map_layer_ids = []
        self.map_registry = {}
        self._preview_line_ids = {}
        self._studio_window = None
        self._browser_studio = None
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
        self.main_layout = outer
        outer.setContentsMargins(9, 8, 9, 8)
        outer.setSpacing(5)
        heading = QLabel("STUDIO BY GROUNDSURF  /  GEOLOGY")
        heading.setObjectName("gsHeading")
        outer.addWidget(heading)
        description = QLabel("Wells · Logs · 3D Models · Maps")
        description.setObjectName("gsDescription")
        outer.addWidget(description)

        # Keep the two most frequent workflows visible without forcing a
        # small QGIS dock to show nine large buttons at all times.
        primary = QGridLayout()
        primary.setHorizontalSpacing(6)
        primary.setVerticalSpacing(5)
        self.import_qgis_button = QPushButton("Import from QGIS")
        self.import_qgis_button.clicked.connect(self.import_from_qgis)
        primary.addWidget(self.import_qgis_button, 0, 0)
        self.models_shortcut = QPushButton("OPEN STUDIO  ↗")
        self.models_shortcut.setObjectName("gsModelsShortcut")
        self.models_shortcut.setToolTip(
            "Open a separate, resizable modelling window. Your "
            "source layers, imported records and QGIS project stay intact."
        )
        self.models_shortcut.clicked.connect(self.open_models)
        primary.addWidget(self.models_shortcut, 0, 1)
        for col, (name, handler) in enumerate((
            ("New project", self.new_project),
            ("Open project", self.open_project),
        )):
            button = QPushButton(name)
            button.clicked.connect(handler)
            primary.addWidget(button, 1, col)
        outer.addLayout(primary)

        # Optional commands stay one click away, but no longer squeeze
        # the Project Explorer and tables on a standard laptop screen.
        self.more_tools_button = QPushButton()
        self.more_tools_button.setObjectName("gsMoreTools")
        self.more_tools_button.setCheckable(True)
        self.more_tools_button.setToolTip(
            "Show or hide well CSV, manual editing, maps and settings"
        )
        outer.addWidget(self.more_tools_button)
        self.extra_actions = QWidget()
        extras = QGridLayout(self.extra_actions)
        extras.setContentsMargins(0, 0, 0, 0)
        extras.setHorizontalSpacing(6)
        extras.setVerticalSpacing(5)
        for index, (name, handler) in enumerate((
            ("Import wells CSV", self.import_csv),
            ("Add well", self.add_well),
            ("Add map layer", self.add_map),
            ("Relink map", self.relink_map),
            ("Switch theme", self.toggle_theme),
            ("Help & feedback", self.open_help),
            ("Open desktop Studio", self.launch_desktop_studio),
            ("Open Studio in browser (preview)", self.open_browser_studio),
        )):
            button = QPushButton(name)
            button.clicked.connect(handler)
            extras.addWidget(button, index // 2, index % 2)
        outer.addWidget(self.extra_actions)
        self.more_tools_button.toggled.connect(self._toggle_more_tools)
        saved_more = str(self.settings.value(
            "show_more_tools", "false"
        )).strip().lower() in ("true", "1", "yes")
        self.more_tools_button.setChecked(saved_more)
        self._toggle_more_tools(saved_more)

        self.project_label = QLabel("No project loaded")
        self.project_label.setWordWrap(True)
        outer.addWidget(self.project_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.explorer_splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)
        self.tree = QTreeWidget()
        # A squeezed splitter previously hid lower explorer entries.
        self.tree.setMinimumHeight(135)
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
        self.setup_contact_tab(tabs)
        self.setup_well_manager(outer, tabs)
        self.setup_section_tools(tabs)
        self.setup_model_tools(tabs)
        # 3D Models is also the FIRST visible tab, not an off-screen tab
        # accessible only after scrolling through the tab bar.
        tabs.tabBar().setUsesScrollButtons(True)
        tabs.tabBar().setExpanding(False)
        tabs.setDocumentMode(True)

        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlainText(
            "Studio by GroundSurf 0.4.14\n\n"
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
        contact_header = QLabel("Questions or suggestions for Studio by GroundSurf?")
        contact_header.setWordWrap(True)
        help_layout.addWidget(contact_header)
        email_label = QLabel("Feedback: tzuk.ls@outlook.com")
        email_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        help_layout.addWidget(email_label)
        contact = QPushButton("Email feedback")
        contact.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("mailto:tzuk.ls@outlook.com?subject=Studio%20by%20GroundSurf%20feedback")
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
        tabs.setMinimumHeight(220)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([170, 420])
        self.workspace_home_index = outer.count()
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
                QPushButton#gsModelsShortcut {
                    background:#234f35; border:1px solid #72a888;
                    color:#effaf0; font-weight:700; padding:7px;
                }
                QPushButton#gsModelsShortcut:hover { background:#326c49; }
                QPushButton#gsMoreTools {
                    background:#252b27; border:1px solid #3c5143;
                    color:#afc8b8; padding:4px;
                }
                QSplitter::handle { background:#374c3e; }
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
                QPushButton#gsModelsShortcut {
                    background:#d3e9da; border:1px solid #398158;
                    color:#1b4e30; font-weight:700; padding:7px;
                }
                QPushButton#gsModelsShortcut:hover { background:#bfe0cb; }
                QPushButton#gsMoreTools {
                    background:#f1f6f2; border:1px solid #c1d3c6;
                    color:#416650; padding:4px;
                }
                QSplitter::handle { background:#d1ded4; }
                QTreeWidget, QTableWidget, QTextEdit {
                    background:#fff; selection-background-color:#b3dbc1;
                    border:1px solid #bccbc0;
                }
                QTabBar::tab { background:#e8f1eb; padding:7px; }
                QTabBar::tab:selected { background:#c2dfca; }
            """)
        if self._studio_window is not None:
            # The workspace is detached and no longer inherits dock CSS.
            self._studio_window.setStyleSheet(self.widget().styleSheet())

    def _toggle_more_tools(self, shown):
        self.extra_actions.setVisible(bool(shown))
        self.more_tools_button.setText(
            "More tools  ▲" if shown else "More tools  ▼"
        )
        self.settings.setValue("show_more_tools", bool(shown))

    def open_studio(self):
        """Detach the *same* explorer and tabs into a larger window."""
        if self._studio_window is not None:
            self._studio_window.show()
            self._studio_window.raise_()
            self._studio_window.activateWindow()
            return
        studio = _GeothermalStudioWindow(self)
        self._studio_window = studio
        self.explorer_splitter.setParent(studio)
        studio.workspace_layout.addWidget(self.explorer_splitter, 1)
        self.explorer_splitter.show()
        studio.setStyleSheet(self.widget().styleSheet())
        studio.show()
        studio.raise_()
        studio.activateWindow()
        # Preserve the preceding import/model status text. The Studio
        # opens without replacing the success message in the QGIS dock.

    def _restore_studio_workspace(self):
        """Put the real QGIS tabs back; never create duplicate editors."""
        studio = self._studio_window
        if studio is None:
            return
        self._studio_window = None
        self.explorer_splitter.setParent(self.widget())
        self.main_layout.insertWidget(
            self.workspace_home_index, self.explorer_splitter, 1
        )
        self.explorer_splitter.show()

    def close_studio(self):
        """Called on QGIS plugin unload and by the normal close button."""
        if self._studio_window is not None:
            self._studio_window.close()

    def open_models(self):
        """Direct shortcut to the 3D tab in independent Studio window."""
        self.tabs.setCurrentWidget(self.model_tab)
        self.open_studio()

    def open_help(self):
        self.tabs.setCurrentIndex(self.help_tab_index)
        self.open_studio()

    def open_browser_studio(self):
        """Open bundled Studio assets locally, without a desktop installation.

        This initial experiment intentionally does NOT expose GeoPackages or
        arbitrary project directories to the browser server. Users explicitly
        select their exported VTP/VTU files from the local file chooser.
        """
        try:
            if self._browser_studio is None:
                assets = Path(__file__).resolve().parent / "web_studio"
                self._browser_studio = BrowserStudio(assets)
            url = self._browser_studio.start()
            if not QDesktopServices.openUrl(QUrl(url)):
                raise RuntimeError("Could not open the default browser")
            self.status.setText(
                "Local Studio browser preview opened. Import VTP/VTU files "
                "through QGIS Scene; no project files are hosted.")
        except Exception as error:
            self._error("Cannot open Studio browser preview", error)

    def launch_desktop_studio(self):
        """Launch an independent, opt-in Studio process, not another Qt window.

        The QGIS project file is passed only as an explicit local path.
        Preserve the existing plugin ID/settings and do not import the desktop
        application's Python or Qt modules into the QGIS process.
        """
        launcher = str(self.settings.value("desktop_studio_launcher", "") or "").strip()
        if not launcher or not (Path(launcher).is_file() and os.access(launcher, os.X_OK)):
            launcher = which("groundsurf-studio") or which("groundsurf-ai-studio") or ""
        if not launcher:
            launcher, _ = QFileDialog.getOpenFileName(
                self, "Choose GroundSurf Studio desktop launcher",
                str(Path.home()), "Executable files (*.sh *.AppImage);;All files (*)",
            )
            if not launcher:
                return
        launcher_path = Path(launcher).expanduser()
        if not (launcher_path.is_file() and os.access(launcher_path, os.X_OK)):
            self._error("Cannot launch GroundSurf Studio",
                        ValueError("Choose an executable GroundSurf Studio launcher or AppImage."))
            return

        process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        # A separate PyQt runtime should not inherit QGIS's Qt/Python plugin paths.
        for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                    "PYTHONPATH", "PYTHONHOME", "QGIS_PREFIX_PATH"):
            env.remove(key)
        process.setProcessEnvironment(env)
        process.setProgram(str(launcher_path.resolve()))
        process.setArguments(["--project", str(self.path)] if self.path else [])
        launched = process.startDetached()
        if isinstance(launched, tuple):
            launched = launched[0]
        if not launched:
            self._error("Cannot launch GroundSurf Studio",
                        RuntimeError("Desktop process did not start. Check the launcher path."))
            return
        self.settings.setValue("desktop_studio_launcher", str(launcher_path.resolve()))
        self.status.setText("GroundSurf Studio opened separately. QGIS data remains unchanged.")

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.settings.setValue("theme", self.theme)
        self._set_theme()

    def _error(self, title, exc):
        message = f"{title}: {exc}"
        self.status.setText(message)
        # GroundSurf's own diagnostics persist in QGIS's Message Log,
        # instead of leaving only the unhelpful generic "Python error".
        QgsMessageLog.logMessage(message, "Studio by GroundSurf", Qgis.MessageLevel.Warning)
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
        contact_backup = elevation_contacts.ensure_schema(
            path, backup_existing=True
        )
        local_backup = local_xyz.ensure_schema(
            path, backup_existing=True
        )
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
        if backup or model_backup or contact_backup or local_backup:
            self.status.setText(
                "New modelling tables installed; database backups saved locally."
            )
        batches = local_xyz.list_batches(path)
        if batches:
            count_contacts = sum(record[7] for record in batches)
            count_wells = sum(record[8] for record in batches)
            self.status.setText(
                f"Project opened: {len(batches)} separate LOCAL XYZ import(s), "
                f"{count_wells} borehole entries and "
                f"{count_contacts} saved contact rows in total. "
                "The same borehole can occur in multiple imports. "
                "Choose a batch in Local XYZ; batches are not combined."
                + (f" {missing} map source(s) missing." if missing else "")
            )
        else:
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

    def import_from_qgis(self):
        """Import already-open QGIS point layers or link existing map files."""
        if not self._require_project():
            return
        active_layer_getter = getattr(self.iface, "activeLayer", None)
        active_layer = active_layer_getter() if callable(active_layer_getter) else None
        try:
            dialog = ImportFromQGISDialog(
                excluded_ids=(
                    self.well_layer.id(), *self._preview_line_ids.values()
                ),
                preferred_layer_id=(
                    active_layer.id() if active_layer else None
                ),
                parent=self,
            )
            if not dialog.layers:
                QMessageBox.information(
                    self, "No QGIS layers",
                    "Open a well point layer or map in QGIS first, then try again."
                )
                return
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selection = dialog.selection()
            if not selection:
                return
            layer = selection["layer"]
            if selection["mode"] == "wells":
                count = import_wells(
                    layer,
                    self.well_layer,
                    selection["mapping"],
                    selected_only=selection["selected_only"],
                    source_crs=selection.get("source_crs"),
                )
                self.refresh()
                self.tabs.setCurrentWidget(self.wells_table)
                self.status.setText(
                    f"Copied {count} well features from QGIS layer "
                    f"'{layer.name()}'. Source layer was not modified."
                )
            elif selection["mode"] == "grouped":
                staged = grouped_import.prepare_groups(
                    layer,
                    selection["mapping"],
                    selection["interval_mapping"],
                    selection["selected_only"],
                    source_crs=selection.get("source_crs"),
                )
                warnings = "\n".join(staged["warnings"])
                prompt = (
                    f"Import {staged['source_rows']} QGIS records as "
                    f"{staged['well_count']} boreholes with "
                    f"{staged['interval_count']} geological intervals?\n\n"
                    "Original QGIS layer will remain unchanged.\n"
                    "Formation labels are copied as source labels, not "
                    "independently verified geology."
                )
                if warnings:
                    prompt += "\n\n" + warnings
                if QMessageBox.question(
                    self, "Confirm grouped borehole import", prompt,
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                ) != QMessageBox.StandardButton.Yes:
                    return
                well_count, interval_count = grouped_import.import_groups(
                    self.path, self.well_layer, staged
                )
                self.refresh()
                self.tabs.setCurrentWidget(self.wells_table)
                self.status.setText(
                    f"Imported {well_count} individual boreholes "
                    f"and {interval_count} log intervals from "
                    f"{staged['source_rows']} source records. "
                    "Original QGIS layer unchanged."
                )
            elif selection["mode"] == "local_xyz":
                if not selection.get("local_metre_confirmed"):
                    raise ValueError(
                        "Confirm X, Y and Z metre units first. "
                        "A local Cartesian model has NO geographic location."
                    )
                staged = local_xyz.prepare_local(
                    layer, selection["fields"],
                    use_xy_fields=selection["use_xy_fields"],
                    use_geometry_z=selection["use_geometry_z"],
                    vertical_reference=selection["vertical_datum"],
                    selected_only=selection["selected_only"],
                )
                # Make the final decision readable; the Preview dialogue
                # still presents all geological and coordinate cautions.
                ambiguities = [
                    issue for issue in staged["warnings"]
                    if "multiple heights" in issue
                ]
                prompt=(
                    f"Import {staged['contact_count']} XYZ contacts as "
                    f"{staged['well_count']} local boreholes?\n\n"
                    "Coordinates are assumed metres; no map CRS is "
                    "assigned. Z means elevation, not drilling depth.\n"
                    "The original QGIS layer will not be changed.\n"
                    "Results appear under Local XYZ (not Wells).\n"
                    "Vertical reference is unverified unless provided.\n"
                    + (
                        "\nData cautions:\n"
                        + "\n".join(ambiguities[:5])
                        if ambiguities else ""
                    )
                )
                if QMessageBox.question(
                    self, "Confirm UNLOCATED local XYZ import", prompt,
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                ) != QMessageBox.StandardButton.Yes:
                    return
                batch_id=local_xyz.store_batch(self.path,staged)
                self.refresh()
                index=self.local_batch_combo.findData(batch_id)
                if index >= 0:
                    self.local_batch_combo.setCurrentIndex(index)
                self.model_source.setCurrentIndex(
                    self.model_source.findData("local_xyz")
                )
                self.tabs.setCurrentWidget(self.local_xyz_tab)
                self.status.setText(
                    f"LOCAL XYZ dataset {batch_id}: "
                    f"{staged['well_count']} unlocated boreholes, "
                    f"{staged['contact_count']} source contacts saved. "
                    "No geographic CRS assigned. Use 3D Models to "
                    "export a local-metre ParaView scene."
                )
            elif selection["mode"] == "contacts":
                staged = elevation_import.prepare_contacts(
                    layer, selection["fields"],
                    source_crs=selection["source_crs"],
                    use_xy_fields=selection["use_xy_fields"],
                    use_geometry_z=selection["use_geometry_z"],
                    vertical_datum=selection["vertical_datum"],
                    selected_only=selection["selected_only"],
                )
                warnings = "\n".join(staged["warnings"][:10])
                prompt = (
                    f"Copy {staged['source_rows']} geological Z records as "
                    f"{staged['well_count']} GroundSurf boreholes and "
                    f"{staged['contact_count']} contact elevations?\n\n"
                    f"Horizontal source CRS: {staged['source_crs']}\n"
                    f"Vertical elevation basis: {staged['vertical_datum']}\n\n"
                    "Z is retained as a raw contact ELEVATION, not converted "
                    "to depth below ground. Existing QGIS layers stay unchanged."
                )
                if warnings:
                    prompt += "\n\nData issues / cautions:\n" + warnings
                if QMessageBox.question(
                    self, "Confirm 3D contact import", prompt,
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                ) != QMessageBox.StandardButton.Yes:
                    return
                count, contacts = elevation_import.import_contacts(
                    self.path, self.well_layer, staged
                )
                self.refresh()
                self.model_source.setCurrentIndex(
                    self.model_source.findData("z_contacts")
                )
                self.tabs.setCurrentWidget(self.contact_tab)
                self.status.setText(
                    f"GroundSurf imported {count} boreholes and {contacts} "
                    f"Z contact elevations. Open Z Contacts to review. "
                    f"{len(staged['ambiguous'])} ambiguous duplicate unit(s) "
                    "preserved for review."
                )
            else:
                file_path, source_layer, kind = file_backed_map(layer)
                self._load_map(
                    file_path, layer.name(), kind, record=True,
                    source_layer=source_layer, existing_layer=layer,
                )
                self.refresh()
                self.tabs.setCurrentWidget(self.maps_table)
                self.status.setText(
                    f"Linked QGIS map '{layer.name()}' without duplicating "
                    "or changing the original layer."
                )
            # After a successful QGIS import/link, show the result in a
            # dedicated, larger window (already on the selected tab).
            # No duplicate storage is created by this UI operation.
            self.open_studio()
        except Exception as exc:
            self._error("Import from QGIS failed", exc)

    def _make_map_layer(self, file_path, name, kind, source_layer=None):
        uri = str(file_path)
        if kind == "vector" and source_layer:
            uri += "|layername=" + source_layer
        layer = (QgsRasterLayer(uri, name) if kind == "raster"
                 else QgsVectorLayer(uri, name, "ogr"))
        if not layer.isValid():
            raise ValueError("Cannot read map layer: " + file_path)
        return layer

    def _existing_map_layer(self, file_path, kind, source_layer=None):
        """Find an existing QGIS file source, preserving the user's layer/style."""
        wanted = str(Path(file_path).resolve())
        for layer in QgsProject.instance().mapLayers().values():
            if not layer.isValid() or (
                self.well_layer is not None and layer.id() == self.well_layer.id()
            ):
                continue
            if kind == "raster" and not isinstance(layer, QgsRasterLayer):
                continue
            if kind == "vector" and not isinstance(layer, QgsVectorLayer):
                continue
            uri = str(layer.source())
            base, _, options = uri.partition("|")
            if str(Path(base).resolve()) != wanted:
                continue
            if kind == "vector" and Path(file_path).suffix.casefold() == ".gpkg":
                if "layername=" + str(source_layer or "") not in options.split("|"):
                    continue
            return layer
        return None

    def _load_map(
        self, file_path, name, kind, record, source_layer=None, existing_layer=None
    ):
        """Use existing user layer when possible; do not remove their layer."""
        layer = existing_layer or self._existing_map_layer(
            file_path, kind, source_layer
        )
        is_new = layer is None
        if is_new:
            layer = self._make_map_layer(file_path, name, kind, source_layer)
        if record:
            db.record_map(self.path, file_path, name, kind, source_layer)
            for record_id, abs_path, _name, _kind, _rel, source in db.maps(self.path):
                if (abs_path == str(Path(file_path).resolve()) and
                        source == (source_layer or "")):
                    previous = self.map_registry.pop(record_id, None)
                    # Crucial: never remove a layer that existed before GroundSurf.
                    if previous is not None and previous in self.map_layer_ids:
                        QgsProject.instance().removeMapLayer(previous)
                        self.map_layer_ids.remove(previous)
                    self.map_registry[record_id] = layer.id()
                    break
        if is_new:
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
            # Keep user-owned QGIS layers untouched during source relinking.
            if old_layer_id is not None and old_layer_id in self.map_layer_ids:
                QgsProject.instance().removeMapLayer(old_layer_id)
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
        QTreeWidgetItem(self.tree, ["Z Contacts · geological elevations"])
        local_batches = local_xyz.list_batches(self.path) if self.path else []
        if local_batches:
            local_wells = sum(row[8] for row in local_batches)
            local_contacts = sum(row[7] for row in local_batches)
            if len(local_batches) == 1:
                local_label = (
                    f"Local XYZ · {local_wells} boreholes / "
                    f"{local_contacts} contacts (unlocated)"
                )
            else:
                local_label = (
                    f"Local XYZ · {len(local_batches)} separate imports / "
                    f"{local_contacts} contact rows"
                )
        else:
            local_label = "Local XYZ · unlocated metre data"
        QTreeWidgetItem(self.tree, [local_label])
        QTreeWidgetItem(self.tree, ["3D Models · preliminary"])
        self.wells_table.setRowCount(0)
        self.maps_table.setRowCount(0)
        if not self.path or not self.well_layer:
            self.tree.expandAll()
            self.refresh_well_details()
            self.refresh_sections()
            self.refresh_models()
            self.refresh_contacts()
            self.refresh_local_xyz()
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
        self.refresh_contacts()
        self.refresh_local_xyz()

    def _tree_selected(self, item, column):
        """Project Explorer headings open their corresponding workspace."""
        label = item.text(0)
        destinations = {
            "Wells": self.wells_table,
            "Maps": self.maps_table,
            "Z Contacts · geological elevations": self.contact_tab,
            "Local XYZ · unlocated metre data": self.local_xyz_tab,
            "3D Models · preliminary": self.model_tab,
        }
        target = destinations.get(label)
        if target is None and label.startswith("Local XYZ · "):
            target = self.local_xyz_tab
        if target is None and item.parent() is not None:
            target = destinations.get(item.parent().text(0))
        if target is not None:
            self.tabs.setCurrentWidget(target)
        self.status.setText("Selected: " + label)

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

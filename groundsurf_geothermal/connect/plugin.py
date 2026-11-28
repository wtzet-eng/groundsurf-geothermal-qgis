import json
import subprocess
import tempfile
from pathlib import Path
from shutil import which

import processing
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsSettings,
    QgsTask,
    QgsWkbTypes,
)
from qgis.gui import QgsExtentWidget
from qgis.PyQt.QtCore import Qt, QUrl, QStandardPaths
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QApplication,
    QLabel,
    QTabWidget,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import handoff
from .appearance import RequestEdit, scroll_page, stylesheet, text_palette
from .catalogue import acquisition_adapter, discover, source_groups
from .package import create_package, validate, write_view
from .provider import Provider, box, mask_file
from .raster import grid


class BrowserDownload(QgsTask):
    def __init__(self, callback):
        super().__init__("Retrieve compatible browser Studio", QgsTask.CanCancel)
        self.callback = callback
        self.html = None

    def run(self):
        import hashlib
        from urllib.request import build_opener
        from .catalogue import NoRedirect
        try:
            url = "https://studio.groundsurf.net/connector/060/" + handoff.RECEIVER
            with build_opener(NoRedirect()).open(url, timeout=10) as reply:
                data = reply.read(4*1024**2 + 1)
            if self.isCanceled() or hashlib.sha256(data).hexdigest() != handoff.DIGEST:
                return False
            self.html = data
            return True
        except OSError:
            return False

    def finished(self, ok):
        if self.callback:
            self.callback(self, self.html if ok else None)


class LandscapeTask(QgsTask):
    def __init__(self, destination, bounds, step, polygon_json, provider, adapter, done):
        super().__init__("GroundSurf landscape transfer", QgsTask.CanCancel)
        self.destination, self.bounds, self.step = destination, bounds, step
        self.polygon_json, self.done, self.error = polygon_json, done, ""
        self.source_provider, self.adapter = provider, adapter

    def run(self):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dems, photos = self.adapter.acquire(
                    self.bounds, tmp, self.isCanceled, lambda p: self.setProgress(p * 0.55)
                )
                mask = Path(tmp) / "area.geojson"
                mask.write_text(self.polygon_json, encoding="utf-8")
                create_package(
                    self.destination,
                    dems,
                    photos,
                    self.bounds,
                    self.adapter.crs,
                    self.step,
                    "DTM",
                    self.adapter.datum,
                    self.adapter.rights,
                    dict(
                        provider=self.source_provider,
                        tiles=self.adapter.plan(self.bounds),
                        acquisitionDate=None,
                        licence=self.adapter.licence,
                        cutline=json.loads(self.polygon_json),
                    ),
                    self.isCanceled,
                    lambda p: self.setProgress(55 + p * 0.45),
                    str(mask),
                )
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    def finished(self, ok):
        if self.done:
            self.done(ok, self.destination, self.error)


class Connect:
    def __init__(self, iface):
        self.iface = iface
        self.dock = self.task = self.assistant_dock = None
        self.provider = Provider()
        self.package = None
        self.preview_tmp = tempfile.TemporaryDirectory()
        self.browser_jobs = []
        self.embedded = False
        self.select_discovery = None
        self.registered = False

    def register(self):
        if QgsApplication.processingRegistry().providerById("groundsurf"):
            return False
        self.registered = QgsApplication.processingRegistry().addProvider(self.provider)
        return self.registered

    def initGui(self):
        if not self.register():
            raise RuntimeError("The Processing provider ID groundsurf is already in use.")
        self.action = QAction("GroundSurf Connect", self.iface.mainWindow())
        self.action.triggered.connect(self.show)
        self.iface.addPluginToMenu("GroundSurf Connect", self.action)

        self.assistant_action = QAction("GroundSurf Assistant", self.iface.mainWindow())
        self.assistant_action.triggered.connect(self.assistant)
        self.iface.addPluginToMenu("GroundSurf Connect", self.assistant_action)

    def unload(self):
        for job in self.browser_jobs:
            job.callback = None
            job.cancel()
        self.browser_jobs.clear()
        if not self.embedded and hasattr(self, "assistant_action"):
            self.iface.removePluginMenu("GroundSurf Connect", self.assistant_action)
            self.iface.removePluginMenu("GroundSurf Connect", self.action)
        if self.assistant_dock:
            self.assistant_dock.shutdown()
        if self.task:
            self.task.done = None
            self.task.cancel()
        if self.dock:
            QApplication.instance().paletteChanged.disconnect(self.update_appearance)
            if not self.embedded:
                self.iface.removeDockWidget(self.dock)
                self.dock.deleteLater()
        if self.registered:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.registered = False
        self.preview_tmp.cleanup()

    def show(self):
        if self.dock:
            if self.select_discovery:
                self.select_discovery()
            self.dock.show()
            self.dock.raise_()
            return
        self.dock = QDockWidget("GroundSurf Connect", self.iface.mainWindow())
        self.dock.setObjectName("GroundSurfConnectDock")
        self.build_widget()

    def embed(self, dock, select_discovery):
        self.embedded = True
        self.dock = dock
        self.select_discovery = select_discovery
        return self.build_widget()

    def build_widget(self):
        widget = QWidget()
        widget.setObjectName("GroundSurfConnect")
        widget.setStyleSheet(stylesheet())
        self.theme_widget = widget
        QApplication.instance().paletteChanged.connect(self.update_appearance)
        lay = QVBoxLayout(widget)
        lay.setSpacing(6)
        lay.setContentsMargins(8, 6, 8, 6)
        title = QLabel("What would you like to investigate?")
        title.setWordWrap(True)
        lay.addWidget(title)
        self.extent = QgsExtentWidget()
        self.extent.setMapCanvas(self.iface.mapCanvas(), True)
        project_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.extent.setOutputCrs(project_crs)
        self.extent.setCurrentExtent(
            self.iface.mapCanvas().extent(), self.iface.mapCanvas().mapSettings().destinationCrs()
        )
        self.extent.setOutputExtentFromCurrent()
        form = QFormLayout()
        lay.addLayout(form)
        self.mode = QComboBox()
        self.mode.addItems(
            [
                "Custom extent",
                "Current map extent",
                "Selected polygon or parcel",
                "Active layer extent",
            ]
        )
        self.mode.setCurrentIndex(1)
        form.addRow("Area", self.mode)
        lay.addWidget(self.extent)
        self.extent.setVisible(False)
        self.mode.currentIndexChanged.connect(lambda i: self.extent.setVisible(i == 0))
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0.4, 1000)
        self.spacing.setValue(2)
        self.spacing.setSuffix(" m")
        self.buffer = QDoubleSpinBox()
        self.buffer.setRange(0, 10000)
        self.buffer.setSuffix(" m")
        self.advanced = QPushButton("Area and source settings")
        self.advanced.setCheckable(True)
        self.advanced_panel = QWidget()
        advanced_form = QFormLayout(self.advanced_panel)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.addRow("Grid spacing", self.spacing)
        advanced_form.addRow("Buffer", self.buffer)
        self.advanced_panel.hide()
        self.advanced.toggled.connect(self.advanced_panel.setVisible)
        self.request = RequestEdit()
        lay.addWidget(self.request, 1)
        self.find_button = QPushButton("Find data")
        self.find_button.setObjectName("GroundSurfPrimary")
        actions = QHBoxLayout()
        actions.addWidget(self.find_button, 1)
        lay.addLayout(actions)
        self.source = QComboBox()
        self.source.addItem("Automatic (recommended)", "auto")
        advanced_form.addRow("Source", self.source)
        self.tabs = QTabWidget()

        manual = QWidget()
        manual.setObjectName("GroundSurfManual")
        manual_lay = QVBoxLayout(manual)
        manual_lay.setContentsMargins(2, 4, 2, 4)

        def button(label, fn):
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            manual_lay.addWidget(btn)
            return btn

        button("Discover terrain and imagery", self.discover)
        self.report = QTextBrowser()
        self.report.setOpenExternalLinks(False)
        manual_lay.addWidget(self.report, 1)
        self.download = button("Prepare from selected source", self.download_area)
        button(
            "Prepare from local layers…",
            lambda: processing.execAlgorithmDialog("groundsurf:create_transfer_package", {}),
        )
        button("Preview terrain…", self.preview)
        button("Send existing terrain to Studio…", self.studio)
        self.studio_mode = QComboBox()
        self.studio_mode.addItems(["Automatic (recommended)", "Always use browser Studio", "Always use desktop Studio"])
        mode = QgsSettings().value("GroundSurfConnect/studioMode", 0, type=int)
        self.studio_mode.setCurrentIndex(mode if mode in (0,1,2) else 0)
        self.studio_mode.currentIndexChanged.connect(lambda i: QgsSettings().setValue("GroundSurfConnect/studioMode", i))
        manual_lay.addWidget(QLabel("Studio preference"))
        manual_lay.addWidget(self.studio_mode)
        button("Change Studio application…", self.choose_studio)
        import platform
        os_label = {"Linux":"Linux", "Windows":"Windows", "Darwin":"macOS"}.get(platform.system(),"desktop")
        button("Desktop downloads · " + os_label, self.desktop_download)
        button("Check my setup", self.check_setup)
        from .assistant_dock import AssistantDock

        self.assistant_dock = AssistantDock(self)
        self.assistant_scroll = scroll_page(self.assistant_dock)
        self.manual_scroll = scroll_page(manual)
        self.tabs.addTab(self.assistant_scroll, "Workflow")
        self.tabs.addTab(self.manual_scroll, "Advanced tools")
        self.tabs.tabBar().hide()
        actions.addWidget(self.assistant_dock.ai_plan, 1)
        self.tools_toggle = QPushButton("More tools")
        self.tools_toggle.setCheckable(True)
        self.import_local = QPushButton("Add my own data…")
        self.import_local.clicked.connect(self.add_local_files)
        secondary = QHBoxLayout()
        secondary.addWidget(self.import_local, 1)
        secondary.addWidget(self.tools_toggle, 1)
        lay.addLayout(secondary)
        lay.addWidget(self.tabs, 3)
        manual_lay.insertWidget(0, self.advanced)
        manual_lay.insertWidget(1, self.advanced_panel)
        self.advanced.hide()
        self.assistant_dock.connection.toggled.connect(self.reveal_ai_settings)
        self.tools_toggle.toggled.connect(lambda checked: self.tabs.setCurrentIndex(int(checked)))
        self.tabs.currentChanged.connect(self.sync_tools)
        self.find_button.clicked.connect(self.find_data)

        self.page_scroll = scroll_page(widget)
        if not self.embedded:
            self.dock.setWidget(self.page_scroll)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.set_workflow_busy(False)
        self.update_appearance()
        return self.page_scroll

    def reveal_ai_settings(self, opened):
        if opened:
            self.tabs.setCurrentIndex(0)
            from qgis.PyQt.QtCore import QTimer

            QTimer.singleShot(
                0,
                lambda: (
                    self.assistant_scroll.ensureWidgetVisible(self.assistant_dock.connection, 0, 8)
                    if self.assistant_dock.connection.isChecked()
                    else None
                ),
            )

    def update_appearance(self, *_):
        if self.dock:
            self.theme_widget.setStyleSheet(stylesheet())
            text_palette(self.request)
            text_palette(self.assistant_dock.log)

    def add_local_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self.dock,
            "Add local data to QGIS",
            "",
            "Geographical files (*.tif *.tiff *.gpkg *.geojson *.shp)",
        )
        loaded, errors = [], []
        for path in files:
            file = Path(path)
            if not file.is_file():
                continue
            layer = (
                QgsRasterLayer(str(file), file.stem)
                if file.suffix.lower() in (".tif", ".tiff")
                else QgsVectorLayer(str(file), file.stem, "ogr")
            )
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                loaded.append(file.name)
                if not layer.crs().isValid():
                    errors.append(
                        file.name + ": coordinate reference missing; review before modelling."
                    )
            else:
                errors.append(file.name + ": QGIS could not read this file.")
        text = "\n".join(["Added to QGIS: " + ", ".join(loaded)] + errors)
        self.report.setPlainText(text)
        if self.assistant_dock:
            self.assistant_dock.say(text)

    def sync_tools(self, index):
        self.tools_toggle.blockSignals(True)
        self.tools_toggle.setChecked(index == 1)
        self.tools_toggle.blockSignals(False)
        self.tools_toggle.setText("Back to discovery" if index == 1 else "More tools")
        self.advanced.setVisible(index == 1)
        self.advanced_panel.setVisible(index == 1 and self.advanced.isChecked())

    def find_data(self):
        self.tabs.setCurrentIndex(0)
        self.assistant_dock.submit_request()

    def set_workflow_busy(self, busy):
        if not hasattr(self, "tabs"):
            return
        for control in (
            self.mode,
            self.extent,
            self.spacing,
            self.buffer,
            self.source,
            self.advanced,
        ):
            control.setEnabled(not busy)
        # Do not allow manual commands to compete with an approved assistant workflow.
        if self.tabs.count() > 1:
            self.tabs.setTabEnabled(1, not busy)
            self.find_button.setEnabled(not busy)
            self.tools_toggle.setEnabled(not busy)
            self.import_local.setEnabled(not busy)

    def area(self):
        canvas = self.iface.mapCanvas()
        wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        mode = self.mode.currentIndex()
        layer = self.iface.activeLayer()
        if mode in (2, 3) and layer is None:
            raise ValueError("Select an active layer.")
        if mode == 2:
            if (
                not hasattr(layer, "geometryType")
                or layer.geometryType() != QgsWkbTypes.PolygonGeometry
                or not 1 <= layer.selectedFeatureCount() <= 2000
            ):
                raise ValueError("Select between one and 2,000 polygon features.")
            g = QgsGeometry.unaryUnion([f.geometry() for f in layer.selectedFeatures()])
            src = layer.crs()
        else:
            if mode == 0:
                rect, src = self.extent.outputExtent(), self.extent.outputCrs()
            elif mode == 1:
                rect, src = canvas.extent(), canvas.mapSettings().destinationCrs()
            else:
                rect, src = layer.extent(), layer.crs()
            if rect.isEmpty():
                raise ValueError("Choose an extent first.")
            g = QgsGeometry.fromRect(rect)
        if not src.isValid() or g.isEmpty() or not g.isGeosValid():
            raise ValueError("Choose a valid area and coordinate reference system.")
        project = QgsProject.instance()
        if self.buffer.value():
            wgs_bounds = QgsCoordinateTransform(src, wgs, project).transformBoundingBox(
                g.boundingBox()
            )
            lon, lat = wgs_bounds.center().x(), wgs_bounds.center().y()
            if wgs_bounds.width() > 12:
                raise ValueError("For a metric buffer, choose a smaller local area.")
            zone = max(1, min(60, int((lon + 180) // 6) + 1))
            epsg = (
                3413
                if lat >= 84
                else 3031 if lat < -80 else ((32600 if lat >= 0 else 32700) + zone)
            )
            target = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
            g.transform(QgsCoordinateTransform(src, target, project))
            g = g.buffer(self.buffer.value(), 16)
            src = target
        if g.isEmpty() or not g.isGeosValid():
            raise ValueError("Invalid area geometry.")
        bounds = QgsCoordinateTransform(src, wgs, project).transformBoundingBox(g.boundingBox())
        return g, src, discover(box(bounds))

    def refresh_sources(self, sources):
        previous = self.source.currentData()
        self.source.clear()
        self.source.addItem("Automatic (recommended)", "auto")
        for key, records in source_groups(sources).items():
            _, adapter = acquisition_adapter(sources, key)
            suffix = "" if adapter else " — manual download"
            self.source.addItem(records[0]["providerName"] + suffix, key)
        index = self.source.findData(previous)
        if index >= 0:
            self.source.setCurrentIndex(index)
        return previous

    def discover(self):
        try:
            geom, crs, sources = self.area()
            self.refresh_sources(sources)
            all_sources = sources
            request = self.request.text().casefold().strip()
            if request:
                dem = any(
                    word in request
                    for word in ("terrain", "elevation", "dtm", "dem", "topograph", "landscape")
                )
                photo = any(
                    word in request for word in ("imagery", "photo", "image", "aerial", "landscape")
                )
                if not (dem or photo):
                    raise ValueError("Search for terrain or imagery, or open the AI assistant.")
                sources = [
                    s
                    for s in sources
                    if (dem and s["role"] == "DTM") or (photo and s["role"] == "imagery")
                ]
            lines = [s["name"] + " · " + s["reason"] + "\n" + s["source"] for s in sources]
            for key, records in source_groups(sources).items():
                _, adapter = acquisition_adapter(all_sources, key)
                if adapter:
                    try:
                        native = QgsGeometry(geom)
                        native.transform(
                            QgsCoordinateTransform(
                                crs,
                                QgsCoordinateReferenceSystem(adapter.crs),
                                QgsProject.instance(),
                            )
                        )
                        count = len(adapter.plan(box(native.boundingBox())))
                        lines.append(
                            f"{records[0]['providerName']}: {count} tile pair(s). "
                            "Review acquisition before downloading."
                        )
                    except ValueError as exc:
                        lines.append(str(exc))
                else:
                    lines.append(
                        records[0]["providerName"] + ": download manually; prepare local layers."
                    )
            self.report.setPlainText(
                "\n\n".join(lines) or "No regional catalogue match. Prepare local layers."
            )
        except Exception as exc:
            self.report.setPlainText(str(exc))

    def download_area(self, open_studio=False, *, assistant_review=False):
        if self.task or (
            not assistant_review and self.assistant_dock and self.assistant_dock.running
        ):
            return
        try:
            geom, crs, sources = self.area()
            selected = self.source.currentData()
            self.refresh_sources(sources)
            if selected != "auto" and self.source.findData(selected) < 0:
                raise ValueError("Selected source no longer matches this area. Review the sources.")
            provider, adapter = acquisition_adapter(sources, selected)
            if adapter is None:
                records = source_groups(sources).get(
                    selected, sources if selected == "auto" else []
                )
                lines = [
                    "No automatic acquisition adapter for this area/source.",
                    "Use Prepare from local layers with compatible GeoTIFFs.",
                ]
                lines.extend(record["name"] + " — " + record["source"] for record in records)
                self.report.setPlainText("\n\n".join(lines))
                return
            target = QgsCoordinateReferenceSystem(adapter.crs)
            geom.transform(QgsCoordinateTransform(crs, target, QgsProject.instance()))
            bounds = box(geom.boundingBox())
            _, w, h = grid(bounds, self.spacing.value())
            message = adapter.review(bounds, w, h)
            if (
                QMessageBox.question(
                    self.dock,
                    "Review acquisition",
                    message,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
            destination = str(self.new_transfer_folder("Landscape") / "landscape")
            if not destination:
                return
            if Path(destination).exists():
                raise ValueError("Choose an unused directory name.")
            with tempfile.TemporaryDirectory() as tmp:
                mask = Path(mask_file(geom, target, tmp)).read_text()
            request = self.request.text().casefold()
            self.open_after = open_studio or (
                not assistant_review and "open" in request and "studio" in request
            )
            self.task = LandscapeTask(
                destination, bounds, self.spacing.value(), mask, provider, adapter, self.finished
            )
            self.download.setEnabled(False)
            self.report.setPlainText("Preparing terrain. Cancel from the QGIS task manager.")
            QgsApplication.taskManager().addTask(self.task)
        except Exception as exc:
            self.report.setPlainText(str(exc))

    def finished(self, ok, folder, error):
        self.task = None
        self.download.setEnabled(True)
        self.package = folder if ok else self.package
        self.report.setPlainText(f"Ready. {folder}" if ok else error or "Cancelled.")

        if self.assistant_dock:
            self.assistant_dock.acquired(ok, folder, error)
        if ok and self.open_after:
            self.studio(folder=folder)

    def pick(self):
        return QFileDialog.getExistingDirectory(
            self.dock, "Select a GroundSurf transfer folder", self.package or ""
        )

    def preview(self):
        root = self.pick()
        if root:
            try:
                path = Path(tempfile.mkdtemp(dir=self.preview_tmp.name)) / "terrain.html"
                write_view(root, path)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            except Exception as exc:
                self.report.setPlainText(str(exc))

    def studio(self, checked=False, folder=None):
        try:
            folder = folder or self.pick()
            if not folder:
                return
            validate(folder)
            return self.open_studio_folder(folder)
        except Exception as exc:
            self.report.setPlainText(str(exc))

    def new_transfer_folder(self, kind):
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        root = Path(documents or Path.home()) / "GroundSurf Transfers"
        root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=kind + "-", dir=root))

    def studio_suggestion(self):
        downloads = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        if not downloads:
            return str(Path.home())
        root = Path(downloads)
        matches = []
        for path in root.glob("GroundSurf-Studio-*-Preview-*/GroundSurf-Studio-Connect.html"):
            try:
                if path.is_file() and not path.is_symlink():
                    matches.append((path.stat().st_mtime, str(path)))
            except OSError:
                continue
        return max(matches)[1] if matches else downloads

    def check_setup(self):
        lines = ["QGIS · ready", "GDAL / Processing · available"]
        for name, executable in (
            ("ParaView", "paraview"),
            ("Desktop Studio", "groundsurf-studio"),
            ("Ollama", "ollama"),
        ):
            lines.append(
                name + (" · executable found" if which(executable) else " · not found on PATH")
            )
        app = QgsSettings().value("GroundSurfConnect/studio", "", type=str)
        lines.append(
            "Preferred portable Studio · " + (app or "automatic discovery")
        )
        lines.append(
            "AI is optional. Open AI setup to check model readiness. No software was installed."
        )
        self.report.setPlainText("\n".join(lines))

    def open_studio_folder(self, folder, boreholes=False, profile_evidence=False):
        settings = QgsSettings()
        mode = settings.value("GroundSurfConnect/studioMode", 0, type=int)
        exe = handoff.desktop() if mode != 1 else None
        if mode == 2 and not exe and QMessageBox.question(
            self.dock, "Desktop Studio unavailable", "Open this evidence in browser Studio instead?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return False
        payload = handoff.prepare(folder, boreholes)
        if exe:
            path = handoff.launch_file(self.preview_tmp.name, payload)
            subprocess.Popen([str(exe), "--groundsurf-transfer", str(path)])
            message = "Opening evidence in a new desktop Studio session."
        else:
            downloads = Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation))
            candidates = [settings.value("GroundSurfConnect/studio", "", type=str),
                          downloads/handoff.RECEIVER, downloads/"GroundSurf-Connector-0.6"/handoff.RECEIVER,
                          Path.home()/".groundsurf"/"browser"/handoff.RECEIVER]
            html = handoff.portable(candidates)
            if html is None:
                def received(job, html):
                    self.browser_jobs.remove(job)
                    if job.isCanceled():
                        return
                    if html is None:
                        msg = ("The public browser trial does not supply this compatible receiver. "
                               "Extract the separate 0.6 preview kit in Downloads. Your original transfer is at " + str(folder))
                        self.assistant_dock.say(msg)
                        self.report.setPlainText(msg)
                        return
                    self.launch_browser(payload, html)
                job = BrowserDownload(received)
                self.browser_jobs.append(job)
                QgsApplication.taskManager().addTask(job)
                self.assistant_dock.say("Retrieving browser Studio from studio.groundsurf.net. Evidence stays local.")
                return True
            return self.launch_browser(payload, html)
        self.report.setPlainText(message)
        self.assistant_dock.say(message)
        return True

    def desktop_download(self):
        import platform
        from urllib.request import build_opener
        from .catalogue import NoRedirect
        def lookup(task):
            with build_opener(NoRedirect()).open("https://studio.groundsurf.net/", timeout=8) as reply:
                return handoff.installer_link(reply.read(512000).decode("utf-8"), platform.system(), platform.machine())
        def finished(error, link=None):
            if link:
                QDesktopServices.openUrl(QUrl(link))
            else:
                QMessageBox.information(None, "Desktop Studio", "A verified installer for this system is unavailable. Continue in browser Studio.")
        QgsApplication.taskManager().addTask(QgsTask.fromFunction("Find official Studio installer", lookup, on_finished=finished))

    def launch_browser(self, payload, html):
        try:
            path = handoff.launch_file(self.preview_tmp.name, payload, html)
            url = QUrl.fromLocalFile(str(path))
            url.setFragment("connect")
            if not QDesktopServices.openUrl(url):
                raise ValueError("Browser launch failed. The prepared evidence is available for conventional import.")
            msg = ("You're using the browser edition of GroundSurf Studio. Install the desktop edition "
                   "for advanced local workflows and larger projects.")
            self.report.setPlainText(msg)
            self.assistant_dock.say(msg)
            return True
        except Exception as exc:
            self.assistant_dock.say(str(exc))
            return False

    def choose_studio(self):
        settings = QgsSettings()
        app = QFileDialog.getOpenFileName(
            self.dock,
            "Choose GroundSurf Studio (offline HTML)",
            settings.value("GroundSurfConnect/studio", "") or self.studio_suggestion(),
            "Studio application (*.html)",
        )[0]
        if app:
            # Reconfirm the selected application on next launch.
            settings.setValue("GroundSurfConnect/studio", app)
            settings.remove("GroundSurfConnect/studioHash")
            settings.remove("GroundSurfConnect/studioProfileHash")

    def assistant(self):
        self.show()
        self.tabs.setCurrentIndex(0)

"""Dockable workflow planner. All QGIS interaction stays on the GUI thread."""

import json
from pathlib import Path

import processing
from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsTask, QgsVectorLayer
from qgis.PyQt.QtCore import QProcess, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .account import Accounts, PERSONAL_BUILD
from .context import snapshot
from .inference import API, local_plan, message, request, responses_plan
from .ollama_setup import installed_models, pull_recommended
from .package import validate
from .evidence_discovery import (
    BGR_TERMS,
    TERRAIN,
    classify,
    portals,
    query_bgr,
    supports_bgr,
)
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY
from .raster import open_tif
from .berlin_profiles import (
    BERLIN,
    TERMS as BERLIN_TERMS,
    query_berlin,
    supports_berlin,
    profile_url,
)
from .workflow import TOOLS, check_plan, default_steps, describe_steps


class Job(QgsTask):
    def __init__(self, name, run, done):
        super().__init__(name, QgsTask.CanCancel)
        self.work, self.done = run, done
        self.value, self.error = None, ""

    def run(self):
        try:
            self.value = self.work(self.isCanceled)
            return not self.isCanceled()
        except (KeyError, IndexError, TypeError):
            self.error = "The service returned an unexpected response. No workflow was accepted."
        except Exception as exc:
            self.error = str(exc)
        return False

    def finished(self, ok):
        if self.done:
            self.done(ok and not self.isCanceled(), self.value, self.error or "Cancelled.")


class AssistantDock(QWidget):
    def __init__(self, connect):
        super().__init__(connect.dock)
        self.setObjectName("GroundSurfAssistant")
        self.connect = connect
        self.job = self.waiting = None
        self.running = self.closed = False
        self.steps, self.history, self.results = [], [], []
        self.key = self.folder = None
        self.accounts = Accounts(
            Path(QgsApplication.qgisSettingsDirPath()) / "groundsurf-assistant"
        )
        widget = self
        widget.setObjectName("GroundSurfAssistant")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.provider = QComboBox()
        self.provider.addItems(["Manual", "Ollama", "llama.cpp", "OpenAI API", "ChatGPT"])
        self.connection = QPushButton("AI settings · Manual")
        self.connection.setCheckable(True)
        self.connection_panel = QWidget()
        connection_layout = QVBoxLayout(self.connection_panel)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.other_ai = QPushButton("Other AI providers and advanced settings")
        self.other_ai.setCheckable(True)
        self.provider_panel = QWidget()
        provider_layout = QVBoxLayout(self.provider_panel)
        provider_layout.setContentsMargins(0, 0, 0, 0)
        form.addRow("Provider", self.provider)
        provider_layout.addLayout(form)
        self.provider_panel.hide()
        self.other_ai.toggled.connect(self.provider_panel.setVisible)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        connection_layout.addWidget(self.hint)
        self.configure = QPushButton("Connection settings…")
        self.configure.clicked.connect(self.settings)
        provider_layout.addWidget(self.configure)
        self.ollama_panel = QWidget()
        ollama_layout = QVBoxLayout(self.ollama_panel)
        ollama_layout.setContentsMargins(0, 0, 0, 0)
        self.ollama_status = QLabel("Detecting local AI…")
        self.ollama_status.setWordWrap(True)
        ollama_layout.addWidget(self.ollama_status)
        self.ollama_models = QComboBox()
        self.ollama_models.currentTextChanged.connect(self.choose_ollama)
        ollama_layout.addWidget(self.ollama_models)
        self.ollama_detect = QPushButton("Check again")
        self.ollama_detect.clicked.connect(self.detect_ollama)
        ollama_layout.addWidget(self.ollama_detect)
        self.ollama_install = QPushButton("Set up local AI…")
        self.ollama_install.clicked.connect(self.launch_ollama_setup)
        ollama_layout.addWidget(self.ollama_install)
        self.ollama_pull = QPushButton("Download free AI model (2.5 GB)")
        self.ollama_pull.clicked.connect(self.download_ollama)
        ollama_layout.addWidget(self.ollama_pull)
        self.ollama_local = QCheckBox("Local-only setup completed")
        self.ollama_local.toggled.connect(self.invalidate_ai_plan)
        self.ollama_local.toggled.connect(self.local_setup_confirmed)
        ollama_layout.addWidget(self.ollama_local)
        connection_layout.addWidget(self.ollama_panel)
        self.ollama_pull.hide()
        self.ollama_models.hide()
        self.account_row = QWidget()
        ar = QVBoxLayout(self.account_row)
        ar.setContentsMargins(0, 0, 0, 0)
        self.account = QComboBox()
        ar.addWidget(self.account)
        self.login = QPushButton("Continue with ChatGPT")
        self.login.clicked.connect(self.sign_in)
        ar.addWidget(self.login)
        self.logout = QPushButton("Sign out")
        self.logout.clicked.connect(self.sign_out)
        ar.addWidget(self.logout)
        usage = QPushButton("Manage usage in ChatGPT…")
        usage.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://chatgpt.com/settings/usage"))
        )
        ar.addWidget(usage)
        provider_layout.addWidget(self.account_row)
        self.share = QCheckBox("Include project summary")
        provider_layout.addWidget(self.share)
        self.connection_panel.hide()
        self.connection.toggled.connect(self.connection_panel.setVisible)
        self.connection.toggled.connect(self.open_ai_settings)
        self.connection.toggled.connect(lambda _: self.controls())
        self.setup_poll = QTimer(self)
        self.setup_poll.setInterval(6000)
        self.setup_poll.timeout.connect(self.poll_setup)
        self.setup_checks = 0
        self.mode_notice = QLabel("Manual workflow · no AI or account required.")
        self.mode_notice.setWordWrap(True)
        connection_layout.addWidget(self.mode_notice)
        self.quick_ai = QPushButton("Use free local AI")
        self.quick_ai.clicked.connect(self.quick_local_ai)
        connection_layout.addWidget(self.quick_ai)
        self.manual_return = QPushButton("Continue without AI")
        self.manual_return.clicked.connect(self.disable_ai)
        connection_layout.addWidget(self.manual_return)
        area = QPushButton("Inspect area and sources")
        area.clicked.connect(self.context_review)
        provider_layout.addWidget(area)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Available data and results will appear here.")
        layout.addWidget(self.log, 1)
        self.prompt = connect.request
        self.boreholes = None
        self.borehole_key = None
        self.save_boreholes = QPushButton("Add boreholes to map")
        self.save_boreholes.clicked.connect(self.export_boreholes)
        layout.addWidget(self.save_boreholes)
        self.save_boreholes.hide()
        self.send_boreholes = QPushButton("Open boreholes in Studio")
        self.send_boreholes.clicked.connect(self.transfer_boreholes)
        layout.addWidget(self.send_boreholes)
        self.send_boreholes.hide()
        self.open_profile = QPushButton("View original borehole profile…")
        self.open_profile.clicked.connect(self.view_profile)
        layout.addWidget(self.open_profile)
        self.open_profile.hide()
        self.landscape_ready = False
        self.plan_button = QPushButton("Prepare landscape for Studio")
        self.plan_button.clicked.connect(lambda: self.plan(force_manual=True))
        layout.addWidget(self.plan_button)
        row = QHBoxLayout()
        self.edit = QPushButton("Edit steps…")
        self.edit.clicked.connect(self.edit_plan)
        self.execute = QPushButton("Approve and prepare")
        self.execute.clicked.connect(self.execute_plan)
        self.cancel = QPushButton("Stop")
        self.cancel.clicked.connect(self.stop)
        for b in (self.edit, self.execute, self.cancel):
            row.addWidget(b)
        layout.addLayout(row)
        layout.addWidget(self.connection)
        layout.addWidget(self.connection_panel)
        self.ai_plan = QPushButton("Ask AI to plan a workflow")
        self.ai_plan.clicked.connect(lambda: self.plan())
        connection_layout.addWidget(self.ai_plan)
        connection_layout.addWidget(self.other_ai)
        connection_layout.addWidget(self.provider_panel)
        self.models = {"OpenAI API": "", "Ollama": "", "llama.cpp": "", "ChatGPT": ""}
        self.ports = {"Ollama": 11434, "llama.cpp": 8080}
        self.api_key = ""
        self.provider.currentTextChanged.connect(self.changed)
        self.prompt.textChanged.connect(self.invalidate_plan)
        self.share.toggled.connect(self.invalidate_ai_plan)
        self.account.currentIndexChanged.connect(self.account_changed)
        self.changed()
        self.project = QgsProject.instance()
        self.project.cleared.connect(self.clear_project)

    def say(self, text):
        # insertPlainText prevents markup in provider or dataset text becoming actionable.
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(("\n\n" if self.log.toPlainText() else "") + str(text))
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def clear_project(self):
        self.stop()
        self.log.clear()
        self.history.clear()
        self.results.clear()
        self.steps.clear()
        self.prompt.clear()
        self.folder = self.key = None
        self.landscape_ready = False
        self.boreholes = None
        self.save_boreholes.hide()
        self.send_boreholes.hide()
        self.open_profile.hide()
        self.controls()

    def controls(self):
        busy = self.running or self.job is not None or self.waiting is not None
        for w in (self.provider, self.configure, self.account_row, self.prompt, self.share):
            w.setEnabled(not busy)
        ready = self.provider.currentText() != "Ollama" or (
            bool(self.models["Ollama"]) and self.ollama_local.isChecked()
        )
        self.plan_button.setEnabled(not busy and self.landscape_ready)
        self.plan_button.setVisible(self.landscape_ready and not busy and not self.steps)
        self.ai_plan.setEnabled(not busy and ready and self.provider.currentText() != "Manual")
        self.ai_plan.setVisible(self.provider.currentText() != "Manual")
        self.connection.setText(
            "AI · "
            + (
                "optional setup"
                if self.provider.currentText() == "Manual"
                else (
                    "local model ready"
                    if self.provider.currentText() == "Ollama" and ready
                    else (
                        "setup needed"
                        if self.provider.currentText() == "Ollama"
                        else self.provider.currentText()
                    )
                )
            )
        )
        self.save_boreholes.setEnabled(not busy)
        self.send_boreholes.setEnabled(not busy)
        self.open_profile.setEnabled(not busy)
        self.quick_ai.setEnabled(not busy)
        self.manual_return.setEnabled(not busy)
        self.connection.setEnabled(not busy)
        self.ollama_panel.setEnabled(not busy)
        self.edit.setVisible(bool(self.steps) and not busy and self.connection.isChecked())
        self.execute.setVisible(bool(self.steps) and not busy)
        self.cancel.setVisible(busy)
        self.connect.set_workflow_busy(busy)
        self.edit.setEnabled(not busy and bool(self.steps))
        self.execute.setEnabled(not busy and bool(self.steps))
        self.cancel.setEnabled(busy)

    def invalidate_plan(self, *_):
        if not self.running and self.job is None and self.waiting is None:
            self.steps.clear()
            self.landscape_ready = False
            self.boreholes = None
            self.save_boreholes.hide()
            self.send_boreholes.hide()
            self.open_profile.hide()
            self.controls()

    def invalidate_ai_plan(self, *_):
        if not self.running and self.job is None and self.waiting is None:
            self.steps.clear()
            self.controls()

    def local_setup_confirmed(self, checked):
        if checked and self.models["Ollama"]:
            self.share.setChecked(True)
            self.connection.setChecked(False)
            self.say(
                "Local AI model selected. Requests use the local service; scientific workflows still require review."
            )

    def open_ai_settings(self, opened):
        if opened and self.provider.currentText() == "Manual":
            self.provider.setCurrentText("Ollama")

    def poll_setup(self):
        self.setup_checks += 1
        if self.closed or self.setup_checks > 100 or self.provider.currentText() != "Ollama":
            self.setup_poll.stop()
        elif not self.job and not self.running and not self.waiting and self.connection.isChecked():
            self.detect_ollama()

    def changed(self, *_):
        kind = self.provider.currentText()
        self.steps.clear()
        self.history.clear()
        self.share.setChecked(False)
        self.share.setVisible(kind != "Manual")
        self.quick_ai.setVisible(kind == "Manual")
        self.manual_return.setVisible(kind != "Manual")
        self.prompt.setVisible(True)
        self.connection.setText("AI settings · " + ("Off (optional)" if kind == "Manual" else kind))
        self.mode_notice.setText(
            "Prepare terrain and imagery without an account."
            if kind == "Manual"
            else ("Local AI · " + kind if kind in self.ports else "Cloud AI · " + kind)
        )
        self.plan_button.setText("Prepare landscape for Studio")
        self.configure.setVisible(kind in ("llama.cpp", "OpenAI API"))
        self.ollama_panel.setVisible(kind == "Ollama")
        if kind == "Ollama":
            self.ports[kind] = 11434
            QTimer.singleShot(0, self.detect_ollama)
        self.account_row.setVisible(kind == "ChatGPT" and PERSONAL_BUILD)
        self.hint.setText(
            {
                "Manual": "Review a terrain workflow locally. All Processing tools are available.",
                "Ollama": "Free local AI. Set up once, use in Connector and Studio.",
                "llama.cpp": "Use a trusted local llama-server with tool calling enabled.",
                "OpenAI API": "Your API key uses separately billed OpenAI API usage.",
                "ChatGPT": (
                    "Eligible requests consume your ChatGPT plan allowance or available credits."
                    if PERSONAL_BUILD
                    else "Plan access for this private distribution awaits eligibility confirmation."
                ),
            }[kind]
        )
        if kind == "ChatGPT" and PERSONAL_BUILD:
            self.load_accounts()
        self.controls()

    def load_accounts(self, active=None):
        self.account.blockSignals(True)
        self.account.clear()
        self.account.addItem("Add an account or workspace", None)
        for cid, label in self.accounts.labels():
            self.account.addItem(label + " · " + cid[-8:], cid)
        self.account.setCurrentIndex(max(0, self.account.findData(active)))
        self.account.blockSignals(False)
        self.account_changed()

    def account_changed(self, *_):
        self.steps.clear()
        self.history.clear()
        self.models["ChatGPT"] = ""
        self.logout.setEnabled(bool(self.account.currentData()))
        self.controls()

    def start_job(self, name, work, completed, failed=None):
        def done(ok, value, error):
            self.job = None
            self.controls()
            if ok:
                try:
                    completed(value)
                except Exception as exc:
                    self.say(str(exc))
            else:
                self.say(error)
                if failed:
                    failed(error)

        self.job = Job(name, work, done)
        self.controls()
        QgsApplication.taskManager().addTask(self.job)

    def sign_in(self):
        cid = self.account.currentData()
        if not self.ask(
            "Use your ChatGPT plan?",
            "Open the system browser to authorise GroundSurf Studio Connector. "
            "Eligible requests use your ChatGPT allowance or available credits.",
        ):
            return
        self.start_job(
            "ChatGPT authorisation",
            lambda cancel: self.accounts.sign_in(cid, cancel),
            self.load_accounts,
        )

    def sign_out(self):
        cid = self.account.currentData()
        if cid:

            def ended(detail):
                self.load_accounts()
                self.say(detail)

            self.start_job("Disconnect ChatGPT", lambda _: self.accounts.sign_out(cid), ended)

    def disable_ai(self):
        self.provider.setCurrentText("Manual")
        self.connection.setChecked(False)
        self.setup_poll.stop()

    def quick_local_ai(self):
        self.connection.setChecked(True)
        self.provider.setCurrentText("Ollama")

    def choose_ollama(self, name):
        if hasattr(self, "models"):
            self.models["Ollama"] = name
            self.invalidate_ai_plan()

    def show_ollama_models(self, names):
        self.ollama_models.clear()
        self.ollama_models.addItems(names)
        self.ollama_models.setVisible(bool(names))
        self.ollama_install.setVisible(not names)
        if names:
            self.setup_poll.stop()
        self.ollama_pull.setVisible(not names)
        self.ollama_status.setText(
            "Local model found. Confirm local-only setup to use it."
            if names
            else "No suitable local model. Download the recommended model once."
        )
        self.choose_ollama(self.ollama_models.currentText())
        if names and self.ollama_local.isChecked():
            self.local_setup_confirmed(True)

    def launch_ollama_setup(self):
        helper = Path(__file__).with_name("setup-local-ai-ubuntu.sh")
        terminal = Path("/usr/bin/x-terminal-emulator")
        if helper.is_file() and terminal.is_file() and Path("/bin/bash").is_file():
            result = QProcess.startDetached(
                str(terminal), ["-e", "/bin/bash", str(helper), "--pause"]
            )
            if result[0] if isinstance(result, tuple) else result:
                self.ollama_status.setText(
                    "Complete the setup window. GroundSurf will check for the model automatically."
                )
                self.setup_checks = 0
                self.setup_poll.start()
                return
        QDesktopServices.openUrl(QUrl("https://ollama.com/download"))
        self.ollama_status.setText(
            "Install Ollama, configure local-only mode and return here. GroundSurf will check automatically."
        )
        self.setup_checks = 0
        self.setup_poll.start()

    def detect_ollama(self):
        if self.closed or self.provider.currentText() != "Ollama" or self.job or self.running:
            return
        self.ollama_models.clear()
        self.ollama_models.hide()
        self.ollama_pull.hide()
        self.ollama_status.setText("Checking local Ollama…")

        def work(cancel):
            try:
                return installed_models(cancel)
            except Exception:
                return None

        def done(names):
            if names is None:
                self.ollama_status.setText(
                    "Local AI is not running. Choose Set up local AI to begin."
                )
                self.ollama_install.show()
            else:
                self.show_ollama_models(names)

        self.start_job("Detect local AI", work, done)

    def download_ollama(self):
        if self.job or self.running or not self.ollama_local.isChecked():
            self.ollama_status.setText("Confirm local-only Ollama configuration first.")
            return
        if not self.ask(
            "Download local AI model?",
            "Download Qwen3 4B from Ollama (about 2.5 GB). Internet is required once. "
            "Both GroundSurf applications can reuse this model. No project data is sent.",
        ):
            return
        self.ollama_status.setText("Downloading model… See QGIS tasks to cancel.")
        self.start_job(
            "Download Qwen3 4B",
            pull_recommended,
            self.show_ollama_models,
            lambda _: self.ollama_status.setText(
                "Download stopped or failed. Detect models again."
            ),
        )

    def settings(self):
        kind = self.provider.currentText()
        dlg = QDialog(self)
        dlg.setWindowTitle(kind)
        dlg.setMinimumWidth(360)
        form = QFormLayout(dlg)
        model = QLineEdit(self.models[kind])
        model.setPlaceholderText(
            "Installed model name" if kind in self.ports else "Model available to your API key"
        )
        form.addRow("Model", model)
        port = QSpinBox()
        key = QLineEdit()
        if kind in self.ports:
            port.setRange(1, 65535)
            port.setValue(self.ports[kind])
            form.addRow("127.0.0.1 port", port)
        else:
            key.setEchoMode(QLineEdit.Password)
            key.setText(self.api_key)
            form.addRow("Session API key", key)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec():
            self.models[kind] = model.text().strip()
            if kind in self.ports:
                self.ports[kind] = port.value()
            else:
                self.api_key = key.text().strip()
            self.steps.clear()
            self.controls()

    def ask(self, title, body):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.PlainText)
        box.setText(body)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def submit_request(self):
        if self.job or self.running or self.waiting:
            return
        text = self.prompt.text().strip()
        if len(text) > 4000:
            self.say("Please shorten the request to 4,000 characters.")
            return
        if classify(text):
            self.find_data()
        elif self.provider.currentText() == "Ollama" and (
            not self.models["Ollama"] or not self.ollama_local.isChecked()
        ):
            self.connection.setChecked(True)
            self.say("Set up free local AI, or describe the geographical data you want to find.")
        elif self.provider.currentText() != "Manual":
            self.plan()
        else:
            self.say("Describe the data you need, or enable optional local AI for other workflows.")

    def find_data(self):
        if self.job or self.running or self.waiting:
            return
        self.steps.clear()
        self.landscape_ready = False
        self.boreholes = None
        self.save_boreholes.hide()
        self.send_boreholes.hide()
        self.open_profile.hide()
        self.log.clear()
        self.controls()
        try:
            roles = classify(self.prompt.text())
            if not roles:
                self.say(
                    "Describe the data you need: boreholes, terrain, aerial imagery, geological maps, "
                    "groundwater, CPT or geophysics."
                )
                return
            summary, _, self.key = snapshot(self.connect)
            geom, crs, records = self.connect.area()
            wgs = QgsCoordinateReferenceSystem("EPSG:4326")
            rect = QgsCoordinateTransform(crs, wgs, self.project).transformBoundingBox(
                geom.boundingBox()
            )
            bounds = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]
            if roles & TERRAIN:
                matches = [
                    r
                    for r in records
                    if (r["role"] == "DTM" and "terrain" in roles)
                    or (r["role"] == "imagery" and "imagery" in roles)
                ]
                if matches:
                    self.say(
                        "Terrain and imagery sources:\n"
                        + "\n".join(
                            r["name"] + " · " + r["access"] + "\n" + r["source"] for r in matches
                        )
                    )
                else:
                    self.say(
                        "No verified regional terrain/imagery match. Try local layers or the source portals."
                    )
                if not summary["automaticPair"]:
                    self.landscape_ready = True
                    self.controls()
                if summary["automaticPair"]:
                    self.landscape_ready = True
                    self.controls()
                    self.say(
                        "Automatic landscape preparation available. Use Prepare landscape for Studio."
                    )
            geological = roles - TERRAIN
            if geological:
                matches = portals(bounds, geological)
                self.say(
                    "Geological sources to investigate (coverage and rights not yet verified):"
                )
                if matches:
                    for region, name, url in matches:
                        self.say(f"{region} · {name}\n{url}")
                else:
                    self.say("No regional source recommendation for these data types yet.")
            if "boreholes" not in roles:
                if geological:
                    self.say(
                        "Automatic acquisition for these geological data types is not yet available."
                    )
                return
            if not supports_bgr(bounds):
                self.say(
                    "Automatic borehole search currently supports Germany. Other portals are manual."
                )
                return
            regional = supports_berlin(bounds)
            if regional:
                native = QgsCoordinateTransform(
                    crs, QgsCoordinateReferenceSystem("EPSG:25833"), self.project
                ).transformBoundingBox(geom.boundingBox())
                native_bounds = [
                    native.xMinimum(),
                    native.yMinimum(),
                    native.xMaximum(),
                    native.yMaximum(),
                ]
                source_name = "Berlin geological survey"
                review = (
                    "Query the regional Berlin geological database? The area bounds are sent "
                    "to Berlin. Up to 500 records, with original profile links where supplied. "
                    "No structured intervals. Regional coverage only. Terms: " + BERLIN_TERMS
                )
            else:
                source_name = "BGR"
                review = (
                    "Query BGR for published locations and reported total lengths? "
                    "The area bounds are sent to BGR. No geological logs. Up to 2,000 records. "
                    "Terms: " + BGR_TERMS
                )
            if not self.ask("Find published boreholes?", review):
                return
            # Keep full geometry in its original CRS, filter actual points on the GUI thread.
            query_key = self.key
            area = QgsGeometry(geom)
            transform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"), crs, self.project
            )

            def completed(data):
                if snapshot(self.connect)[2] != query_key:
                    self.say("Area changed during discovery. Search again.")
                    return
                inside = []
                for feature in data["features"]:
                    pt = QgsGeometry.fromPointXY(
                        transform.transform(QgsPointXY(*feature["geometry"]["coordinates"]))
                    )
                    if area.intersects(pt):
                        inside.append(feature)
                data["features"] = inside
                data["groundsurf"]["selected_area_wkt"] = area.asWkt()
                data["groundsurf"]["selected_area_crs"] = crs.authid() or crs.toWkt()
                self.boreholes = data
                self.borehole_key = query_key
                self.save_boreholes.setVisible(bool(inside))
                self.send_boreholes.setVisible(bool(inside))
                meta = data["groundsurf"]
                profiles = sum(
                    bool(profile_url(f["properties"].get("profile_url"))) for f in inside
                )
                self.open_profile.setVisible(bool(profiles))
                self.say(
                    f"{source_name} returned {len(inside)} published borehole location(s) inside the selected area."
                    + (
                        " Search reached the record limit; choose a smaller area for more complete results."
                        if meta["limit_reached"]
                        else ""
                    )
                    + (
                        f" {meta['invalid_records']} invalid/outside-envelope records excluded."
                        if meta["invalid_records"]
                        else ""
                    )
                    + (
                        f"\n{profiles} original profile link(s). "
                        "Reported collar heights have unverified vertical datum. "
                        "No structured intervals; individual links have not all been checked."
                        if regional
                        else "\nLocations and reported total lengths only. No layer logs or collar elevations."
                    )
                    + "\n"
                    + meta["attribution"]
                )
                if not inside:
                    self.say(
                        "No published points returned inside the selected area is not proof of no boreholes."
                    )

            self.start_job(
                "Find official boreholes",
                lambda cancel: (
                    query_berlin(bounds, native_bounds, cancel)
                    if regional
                    else query_bgr(bounds, cancel)
                ),
                completed,
            )
        except Exception as exc:
            self.say(str(exc))

    def view_profile(self):
        if not self.boreholes:
            return
        options = [
            (f["properties"]["borehole_id"], profile_url(f["properties"].get("profile_url")))
            for f in self.boreholes["features"]
        ]
        options = [(key, url) for key, url in options if url]
        if not options:
            return
        choice, ok = QInputDialog.getItem(
            self,
            "Original geological profile",
            "Choose borehole",
            [key for key, _ in options],
            0,
            False,
        )
        if ok:
            url = dict(options).get(choice)
            if url and self.ask(
                "Open original profile?", "Open the published image in your browser?"
            ):
                if not QDesktopServices.openUrl(QUrl(url)):
                    self.say("Could not open the profile in your browser.")

    def export_boreholes(self):
        if not self.boreholes or not self.boreholes["features"]:
            return
        try:
            path = self.connect.new_transfer_folder("Boreholes") / "boreholes.geojson"
            payload = json.dumps(self.boreholes, ensure_ascii=False, allow_nan=False, indent=2)
            with path.open("x", encoding="utf-8") as handle:
                handle.write(payload)
            meta = self.boreholes["groundsurf"]
            label = (
                "Berlin borehole evidence" if meta["source"] == BERLIN else "BGR borehole locations"
            )
            layer = QgsVectorLayer(str(path), label, "ogr")
            if not layer.isValid():
                raise ValueError("File saved but QGIS could not open it.")
            layer.setCustomProperty("groundsurf/source", meta["source"])
            layer.setCustomProperty("groundsurf/attribution", meta["attribution"])
            self.project.addMapLayer(layer)
            self.say(
                f"Saved {len(self.boreholes['features'])} locations and added them to the map.\n{path}"
            )
            self.save_boreholes.hide()
        except Exception as exc:
            self.say(str(exc))

    def transfer_boreholes(self):
        if not self.boreholes or not self.boreholes["features"]:
            return
        try:
            payload = json.dumps(self.boreholes, ensure_ascii=False, allow_nan=False, indent=2)
            folder = self.connect.new_transfer_folder("Boreholes")
            (folder / "boreholes.geojson").write_text(payload, encoding="utf-8")
            self.say("Borehole transfer saved: " + str(folder))
            regional = self.boreholes["groundsurf"]["source"] == BERLIN
            if regional:
                self.say("Regional profiles require standalone Studio 0.11 Preview 4 or later.")
            self.connect.open_studio_folder(str(folder), boreholes=True, profile_evidence=regional)
        except Exception as exc:
            self.say(str(exc))

    def context_review(self):
        try:
            summary, sources, _ = snapshot(self.connect)
            self.say(
                f"Selected area: {summary['areaMode']}\n"
                f"Grid spacing: {summary['gridSpacingM']} m\n"
                f"Project layers: {summary['layerCount']}\n"
                + (
                    "Automatic terrain and imagery available."
                    if summary["automaticPair"]
                    else "Automatic acquisition unavailable. Local layers can be prepared."
                )
                + "\n\n"
                + sources
            )
        except Exception as exc:
            self.say(str(exc))

    def plan(self, force_manual=False):
        if self.job or self.running:
            return
        try:
            summary, sources, self.key = snapshot(self.connect)
            kind = "Manual" if force_manual else self.provider.currentText()
            prompt = self.prompt.text().strip()
            if len(prompt) > 4000:
                raise ValueError("Please shorten your request to 4,000 characters.")
            roles = classify(prompt)
            if roles - TERRAIN and not (force_manual and roles & TERRAIN):
                self.say(
                    "For geological evidence requests, use Find data. Terrain preparation is separate; "
                    "geological logs are not yet transferred to Studio."
                )
                return
            if kind == "Manual" and prompt and not roles:
                self.say("Enter a terrain or aerial imagery request, or use Find data.")
                return
            self.steps.clear()
            self.results.clear()
            self.folder = None
            self.controls()
            if kind == "Manual":
                self.install_plan(default_steps(bool(summary["automaticPair"])), sources)
                return
            if kind == "ChatGPT" and not PERSONAL_BUILD:
                raise ValueError(self.hint.text())
            if not prompt:
                raise ValueError("Describe the workflow first.")
            if kind == "Ollama" and not self.ollama_local.isChecked():
                raise ValueError("Confirm Ollama cloud features are disabled in AI settings.")
            if kind in self.ports and not self.models[kind]:
                raise ValueError("Detect an installed local model in AI settings.")
            if kind == "OpenAI API" and not (self.models[kind] and self.api_key):
                raise ValueError(
                    "Set an API model and your own session API key in Connection settings."
                )
            cid = self.account.currentData()
            if kind == "ChatGPT" and not cid:
                raise ValueError("Continue with ChatGPT first.")
            content = message(
                prompt, summary if self.share.isChecked() else None, list(self.history)
            )
            destination = (
                f"127.0.0.1:{self.ports[kind]}" if kind in self.ports else "api.openai.com"
            )
            if not self.ask(
                "Review inference request",
                f"{kind} · {destination}\n{self.hint.text()}\n\n"
                "The following user content will be sent with the fixed workflow instructions and tool schema.\n"
                + content,
            ):
                return
            self.say("You · " + prompt)
            model = self.models[kind]
            if kind == "ChatGPT" and not model:

                def choose(models):
                    slugs = [m["slug"] for m in models["models"] if m.get("visibility") == "list"]
                    if not slugs:
                        raise ValueError("No eligible models for this registration.")
                    choice, ok = QInputDialog.getItem(
                        self, "ChatGPT plan", "Account model", slugs, 0, False
                    )
                    if ok:
                        self.models[kind] = choice
                        self.infer(kind, choice, content, sources, cid)

                self.start_job(
                    "List account models",
                    lambda _: request(API + "/models", token=self.accounts.access(cid)),
                    choose,
                )
            else:
                self.infer(kind, model, content, sources, cid)
        except Exception as exc:
            self.say(str(exc))

    def infer(self, kind, model, content, sources, cid):
        port, api_key = self.ports.get(kind), self.api_key

        def work(_):
            if port:
                return local_plan(kind, port, model, content)
            token = self.accounts.access(cid) if kind == "ChatGPT" else api_key
            return responses_plan(model, token, content, kind == "ChatGPT")

        self.start_job(
            "Plan GroundSurf workflow", work, lambda steps: self.install_plan(steps, sources)
        )

    def install_plan(self, steps, sources):
        self.steps = check_plan(dict(version="1.0", steps=steps))
        self.say(describe_steps(self.steps))
        if any(s in self.steps for s in ("discover_data", "acquire_landscape")):
            self.say(sources)
        self.controls()

    def edit_plan(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit workflow steps")
        layout = QVBoxLayout(dlg)
        lst = QListWidget()
        lst.setDragDropMode(lst.InternalMove)
        layout.addWidget(QLabel("Drag to reorder. Select a step to remove it."))
        layout.addWidget(lst)
        for s in self.steps:
            lst.addItem(TOOLS[s]["title"])
            lst.item(lst.count() - 1).setData(Qt.UserRole, s)
        choices = QComboBox()
        for s, t in TOOLS.items():
            choices.addItem(t["title"], s)
        layout.addWidget(choices)

        def add():
            lst.addItem(choices.currentText())
            lst.item(lst.count() - 1).setData(Qt.UserRole, choices.currentData())

        for label, action in [
            ("Add step", add),
            ("Remove selected", lambda: lst.takeItem(lst.currentRow())),
        ]:
            b = QPushButton(label)
            b.clicked.connect(action)
            layout.addWidget(b)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec():
            try:
                self.install_plan(
                    [lst.item(i).data(Qt.UserRole) for i in range(lst.count())],
                    snapshot(self.connect)[1],
                )
            except Exception as exc:
                self.say(str(exc))

    def execute_plan(self):
        if self.running or self.job or self.waiting or not self.steps:
            return
        try:
            _, sources, key = snapshot(self.connect)
            if key != self.key:
                raise ValueError("The project or area changed. Review a fresh workflow.")
            check_plan(dict(version="1.0", steps=self.steps))
            details = describe_steps(self.steps)
            if "acquire_landscape" in self.steps:
                details += "\n\n" + sources
            if not self.ask("Execute reviewed steps?", details):
                return
            self.history = (
                self.history + [dict(request=self.prompt.text().strip(), steps=list(self.steps))]
            )[-3:]
            self.running = True
            self.controls()
            self.advance()
        except Exception as exc:
            self.say(str(exc))

    def record(self, step, status, detail):
        self.results.append(dict(version="1.0", tool=step, status=status, detail=detail))
        self.say(f"{TOOLS[step]['title']} · {status}\n{detail}")

    def advance(self):
        if not self.running or not self.steps or self.closed:
            self.running = False
            self.controls()
            return
        step = self.steps[0]
        try:
            summary, sources, key = snapshot(self.connect)
            if key != self.key:
                raise ValueError("Project context changed. Review a fresh workflow.")
            if step == "acquire_landscape":
                if self.connect.task:
                    raise ValueError("Another landscape task is running.")
                if not summary["automaticPair"]:
                    raise ValueError(
                        "No verified automatic pair here. Edit this step to Prepare from local layers."
                    )
                self.connect.download_area(assistant_review=True)
                self.waiting = self.connect.task
                if self.waiting:
                    self.say("Acquisition queued. Progress is available in the QGIS task manager.")
                    return
                raise InterruptedError(
                    self.connect.report.toPlainText() or "Acquisition was not started."
                )
            if step in ("inspect_project", "inspect_layers"):
                detail = json.dumps(
                    summary if step == "inspect_project" else summary["layers"], ensure_ascii=False
                )
            elif step == "define_area":
                detail = f"{summary['areaMode']} · WGS 84 bounds {summary['extentWgs84']}"
            elif step == "discover_data":
                detail = sources
            elif step in ("validate_transfer_package", "open_studio"):
                self.folder = self.folder or self.connect.pick()
                if not self.folder:
                    raise InterruptedError("No transfer selected.")
                manifest = validate(self.folder)
                detail = (
                    f"Validated {manifest['terrainRole']} · {manifest['verticalDatum']} · "
                    f"{manifest['grid']['dimensions']}"
                )
                if step == "open_studio":
                    if not self.connect.studio(folder=self.folder):
                        raise InterruptedError(
                            "Studio was not opened. Check the Connect dock or select a trusted application."
                        )
                    detail = (
                        "Studio opened. Choose Import transfer folder and select " + self.folder
                    )
            else:
                detail = self.processing_step(step)
            self.record(step, "handoff" if step == "open_studio" else "completed", detail)
            self.steps.pop(0)
            QTimer.singleShot(0, self.advance)
        except Exception as exc:
            self.running = False
            self.record(
                step, "cancelled" if isinstance(exc, InterruptedError) else "failed", str(exc)
            )
            self.controls()

    def processing_step(self, step):
        from .provider import AREA

        params = {}
        if step in AREA:
            geom, crs, _ = self.connect.area()
            # Bind the actual polygon, including multipart areas and buffer, to the native dialog.
            geom = QgsGeometry(geom)
            geom.convertToMultiType()
            layer = QgsVectorLayer("MultiPolygon", "Reviewed area", "memory")
            layer.setCrs(crs)
            f = QgsFeature()
            f.setGeometry(geom)
            layer.dataProvider().addFeatures([f])
            layer.updateExtents()
            params["POLYGON"] = layer
            if crs.isValid() and not crs.isGeographic():
                params["CRS"] = crs
            if step != "prepare_vectors":
                params["STEP"] = self.connect.spacing.value()
        result = processing.execAlgorithmDialog("groundsurf:" + step, params)
        if not result or "REPORT" not in result:
            raise InterruptedError("Processing closed without a completed result.")
        report = json.loads(result["REPORT"])
        if step == "create_transfer_package":
            validate(result["OUTPUT"])
            self.folder = result["OUTPUT"]
            return "Transfer created and validated."
        if step in ("prepare_dem", "prepare_imagery", "align_rasters"):
            open_tif(result["OUTPUT"])
        if (
            step == "prepare_vectors"
            and not QgsVectorLayer(result["OUTPUT"], "Evidence", "ogr").isValid()
        ):
            raise ValueError("Prepared vector output could not be opened.")
        return json.dumps(report, ensure_ascii=False)[:2000]

    def acquired(self, ok, folder, error):
        if not self.waiting:
            return
        cancelled = self.waiting.isCanceled()
        self.waiting = None
        if not self.running:
            self.controls()
            return
        try:
            if not ok or cancelled:
                raise ValueError(error or "Acquisition stopped.")
            validate(folder)
            self.folder = folder
            self.record(
                self.steps.pop(0), "completed", "Prepared and validated the terrain and imagery."
            )
            QTimer.singleShot(0, self.advance)
        except Exception as exc:
            self.running = False
            self.record(self.steps[0], "cancelled" if cancelled else "failed", str(exc))
            self.controls()

    def stop(self):
        if hasattr(self, "setup_poll"):
            self.setup_poll.stop()
        if self.job:
            self.job.cancel()
        if self.waiting:
            self.waiting.cancel()
        if self.running and self.steps:
            self.record(
                self.steps[0], "cancelled", "Stopped the workflow. Completed outputs are retained."
            )
        self.running = False
        self.controls()

    def shutdown(self):
        self.closed = True
        self.setup_poll.stop()
        self.project.cleared.disconnect(self.clear_project)
        self.stop()
        if self.job:
            self.job.done = None
        self.api_key = ""

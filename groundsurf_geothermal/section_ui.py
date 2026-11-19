"""QGIS 3 section controls and an editable, separate interpretation window."""
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from . import db, sections, section_geo
from .section_canvas import SectionCanvas


class SectionWindow(QDialog):
    """One saved section, shown in a separate freely resizable QGIS window."""
    def __init__(self, project_file, well_layer, section_id, dark, parent=None):
        super().__init__(parent)
        self.project_file = project_file
        self.well_layer = well_layer
        self.section_id = section_id
        self.dark = dark
        self.setWindowTitle("GroundSurf Geothermal · Geological cross-section")
        self.resize(1190, 730)
        self.setMinimumSize(420, 360)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        outer = QVBoxLayout(self)
        self.description = QLabel("")
        self.description.setWordWrap(True)
        outer.addWidget(self.description)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.canvas = None
        outer.addWidget(self.scroll, 1)
        controls = QHBoxLayout()
        for caption, handler in (
            ("Add / edit interpreted contact", self.edit_pick),
            ("Remove interpreted contact", self.remove_pick),
            ("Export PNG", self.export_png),
            ("Close", self.close),
        ):
            button = QPushButton(caption)
            button.clicked.connect(handler)
            controls.addWidget(button)
        outer.addLayout(controls)
        self.refresh()

    def refresh(self):
        scene = section_geo.build_scene(
            self.project_file, self.well_layer, self.section_id
        )
        self.scene = scene
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.canvas = SectionCanvas(scene, self.dark)
        self.scroll.setWidget(self.canvas)
        datum = (f"Vertical reference: {scene['datum']}" if scene["elevation_mode"]
                 else "Depth-only mode; correlations disabled (inconsistent datums)")
        self.description.setText(
            f"{scene['name']} · {scene['well_count']} wells · {datum}.  "
            "A dashed line between two wells is only a geological correlation hypothesis."
        )

    def edit_pick(self):
        wells = self.scene["well_rows"]
        codes = sorted(self.scene["formations"])
        if not wells or not codes:
            QMessageBox.information(self, "Cannot interpret",
                "Include logged wells and define at least one formation first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Section-only interpreted contact")
        form = QFormLayout(dialog)
        well_combo = QComboBox()
        for w in wells:
            well_combo.addItem(f"{w['well_id']} · {w['name']}", w["well_id"])
        formation_combo = QComboBox()
        formation_combo.addItems(codes)
        depth = QLineEdit()
        depth.setPlaceholderText("Metres below local ground, e.g. 45.0")
        note = QLineEdit()
        note.setPlaceholderText("Interpretation rationale (optional)")
        form.addRow("Well", well_combo)
        form.addRow("Formation", formation_combo)
        form.addRow("Interpreted top depth (m bgl)", depth)
        form.addRow("Reason or source", note)

        def defaults():
            wid = well_combo.currentData()
            code = formation_combo.currentText()
            original = next((w for w in wells if w["well_id"] == wid), None)
            if not original:
                return
            match = original["contacts"].get(code)
            depth.setText(str(match["depth"]) if match else "")

        well_combo.currentIndexChanged.connect(defaults)
        formation_combo.currentIndexChanged.connect(defaults)
        defaults()
        footnote = QLabel(
            "This interpretation is stored in the section only. "
            "Original borehole logs and formation tops remain unchanged."
        )
        footnote.setWordWrap(True)
        form.addRow(footnote)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        wid = str(well_combo.currentData())
        code = formation_combo.currentText()
        well = next(w for w in wells if w["well_id"] == wid)
        try:
            sections.save_pick(
                self.project_file, self.section_id, wid, code,
                depth.text(), well_total_depth=well["total_depth_m"],
                note=note.text(),
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Cannot save interpreted contact", str(exc))

    def remove_pick(self):
        records = sections.list_picks(self.project_file, self.section_id)
        if not records:
            QMessageBox.information(self, "No interpreted contacts",
                                    "This section has no editable contact picks.")
            return
        labels = [f"{well} / {code} / {depth:g} m bgl"
                  for well, code, depth, _ in records]
        label, ok = QInputDialog.getItem(self, "Remove contact",
                                        "Section-only interpretation", labels, 0, False)
        if not ok:
            return
        i = labels.index(label)
        well_id, code, _, _ = records[i]
        if QMessageBox.question(
            self, "Remove interpreted contact?",
            f"Remove section-only pick {well_id}/{code}?\n"
            "Original well data will not be changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            sections.delete_pick(self.project_file, self.section_id, well_id, code)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Cannot delete interpreted contact", str(exc))

    def export_png(self):
        name, _ = QFileDialog.getSaveFileName(
            self, "Export geological cross-section",
            str(Path(self.project_file).with_suffix("").as_posix() +
                f"-section-{self.section_id}.png"),
            "PNG (*.png)"
        )
        if not name:
            return
        if not name.lower().endswith(".png"):
            name += ".png"
        try:
            self.canvas.save_png(name)
            QMessageBox.information(
                self, "Export saved",
                "Schematic geological cross-section exported to:\n" + name
            )
        except Exception as exc:
            QMessageBox.warning(self, "Cannot export PNG", str(exc))


class SectionToolsMixin:
    """Small QGIS dock tab; all heavy drawing lives in SectionWindow."""

    def setup_section_tools(self, tabs):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        message = QLabel(
            "Create a section from a selected QGIS line, or automatically through "
            "your imported wells. Only wells within its corridor are included."
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        buttons = QHBoxLayout()
        auto = QPushButton("Auto from wells")
        selected = QPushButton("Selected QGIS line")
        auto.clicked.connect(self.auto_section)
        selected.clicked.connect(self.selected_section)
        buttons.addWidget(auto)
        buttons.addWidget(selected)
        layout.addLayout(buttons)

        self.section_combo = QComboBox()
        self.section_combo.setMinimumHeight(28)
        layout.addWidget(QLabel("Saved geological sections"))
        layout.addWidget(self.section_combo)
        open_button = QPushButton("Open cross-section")
        open_button.clicked.connect(self.open_section)
        layout.addWidget(open_button)
        map_button = QPushButton("Show section line on QGIS map")
        map_button.clicked.connect(self.show_section_line)
        layout.addWidget(map_button)
        delete_button = QPushButton("Delete selected section")
        delete_button.clicked.connect(self.delete_section)
        layout.addWidget(delete_button)
        disclaimer = QLabel(
            "Displayed section contacts are hypotheses unless observed. "
            "Common vertical datums are required for elevation-based correlation. "
            "This is not a calculated 3D geological model."
        )
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)
        layout.addStretch()
        tabs.addTab(panel, "Cross-sections")
        self._section_window = None
        self.refresh_sections()

    def refresh_sections(self):
        if not hasattr(self, "section_combo"):
            return
        selected_id = self.section_combo.currentData()
        self.section_combo.clear()
        if self.path and sections.has_schema(self.path):
            for section in sections.list_sections(self.path):
                self.section_combo.addItem(section["name"], section["id"])
        if selected_id is not None:
            n = self.section_combo.findData(selected_id)
            if n >= 0:
                self.section_combo.setCurrentIndex(n)

    def _save_new_section(self, vertices, suggested_width):
        default = f"Section {len(sections.list_sections(self.path))+1}"
        name, ok = QInputDialog.getText(
            self, "New geological section", "Section name", text=default
        )
        if not ok:
            return
        corridor, ok = QInputDialog.getDouble(
            self, "Well corridor", "Include wells within ± metres of line",
            float(min(100000, max(1, suggested_width))), 1, 100000, 1
        )
        if not ok:
            return
        sid = sections.create_section(self.path, name, vertices, corridor)
        self.refresh_sections()
        self.section_combo.setCurrentIndex(self.section_combo.findData(sid))
        self.status.setText(f"Section '{name}' saved in local project.")
        self.open_section()

    def auto_section(self):
        if not self._require_project():
            return
        try:
            vertices, suggested = section_geo.auto_vertices_from_wells(self.well_layer)
            self._save_new_section(vertices, suggested)
        except Exception as exc:
            self._error("Cannot create automatic section", exc)

    def selected_section(self):
        if not self._require_project():
            return
        try:
            vertices = section_geo.selected_line_vertices(self.iface)
            self._save_new_section(vertices, 250)
        except Exception as exc:
            self._error("Cannot use selected QGIS line", exc)

    def open_section(self):
        if not self._require_project():
            return
        sid = self.section_combo.currentData()
        if sid is None:
            QMessageBox.information(
                self, "Create section", "Create a section first using the buttons above."
            )
            return
        try:
            if self._section_window is not None:
                self._section_window.close()
            window = SectionWindow(
                self.path, self.well_layer, sid, self.theme == "dark",
                self.iface.mainWindow()
            )
            self._section_window = window
            window.show()
            window.raise_()
            self.status.setText("Opened cross-section in separate window.")
        except Exception as exc:
            self._error("Could not open section", exc)

    def show_section_line(self):
        if not self._require_project():
            return
        sid = self.section_combo.currentData()
        if sid is None:
            QMessageBox.information(self,"Select section","Select a saved section first.")
            return
        try:
            section = sections.get_section(self.path,sid)
            from qgis.core import QgsCoordinateTransform, QgsProject
            layer = section_geo.section_map_layer(section)
            if not hasattr(self, "_preview_line_ids"):
                self._preview_line_ids = {}
            old_id = self._preview_line_ids.pop(sid,None)
            if old_id:
                QgsProject.instance().removeMapLayer(old_id)
            QgsProject.instance().addMapLayer(layer)
            self._preview_line_ids[sid] = layer.id()
            canvas = self.iface.mapCanvas()
            transform = QgsCoordinateTransform(
                layer.crs(),canvas.mapSettings().destinationCrs(),
                QgsProject.instance()
            )
            extent = transform.transformBoundingBox(layer.extent())
            extent.scale(1.5)
            canvas.setExtent(extent)
            canvas.refresh()
            self.status.setText("Section line shown in QGIS; view is not a modelled horizon.")
        except Exception as exc:
            self._error("Cannot show section on map",exc)

    def delete_section(self):
        if not self._require_project():
            return
        sid = self.section_combo.currentData()
        if sid is None:
            return
        if QMessageBox.question(
            self, "Delete section",
            "Delete this section and all its separate interpreted contacts?\n"
            "Original wells and formations will remain unchanged.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            if self._section_window:
                self._section_window.close()
                self._section_window = None
            sections.delete_section(self.path, sid)
            self.refresh_sections()
            self.status.setText("Section deleted. Original boreholes untouched.")
        except Exception as exc:
            self._error("Could not delete section", exc)

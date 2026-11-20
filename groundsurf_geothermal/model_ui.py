"""QGIS dock UI for transparent preliminary 3D horizon/volume modelling."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from qgis.PyQt.QtCore import QFile, Qt, QUrl, QProcess, QStandardPaths
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from . import (
    model_adapter, contact_adapter, local_xyz, model_core, models,
    scene_style,
)


class ModelToolsMixin:
    def setup_model_tools(self, tabs):
        tab=QWidget()
        self.model_tab=tab
        layout=QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        title=QLabel("3D Geological Models · PRELIMINARY")
        title.setObjectName("gsModelTitle")
        layout.addWidget(title)
        explanation=QLabel(
            "Build conceptual 3D geological surfaces from boreholes or XYZ "
            "contacts. Export to ParaView (VTK)."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(QLabel("Choose the data used to build the 3D model:"))
        self.model_source = QComboBox()
        self.model_source.addItem(
            "Well-log depths (ground elevation + intervals)", "well_logs"
        )
        self.model_source.addItem(
            "Imported contact Z elevations (source vertical datum)", "z_contacts"
        )
        self.model_source.addItem(
            "LOCAL XYZ (metres, NO geographic CRS) → ParaView", "local_xyz"
        )
        layout.addWidget(self.model_source)
        model_note = QLabel(
            "Conceptual IDW only. Z contacts are elevations, not depths. "
            "Ambiguous horizons are excluded."
        )
        model_note.setToolTip(
            "No faults, groundwater or heat-flow simulation. No model "
            "extrapolation beyond the well footprint. Check vertical "
            "datums and geological units before engineering use."
        )
        model_note.setWordWrap(True)
        layout.addWidget(model_note)
        scene_settings = QHBoxLayout()
        scene_settings.addWidget(QLabel("Display Z ×"))
        self.scene_vertical = QDoubleSpinBox()
        self.scene_vertical.setRange(0.5, 10.0)
        self.scene_vertical.setDecimals(1)
        self.scene_vertical.setSingleStep(0.5)
        self.scene_vertical.setValue(
            float(self.settings.value("3d_vertical_exaggeration", 1.0))
        )
        self.scene_vertical.setToolTip(
            "Display-only vertical exaggeration; original XYZ and model "
            "geological elevations remain unchanged."
        )
        self.scene_vertical.valueChanged.connect(
            lambda value: self.settings.setValue(
                "3d_vertical_exaggeration", float(value)
            )
        )
        scene_settings.addWidget(self.scene_vertical)
        self.show_boreholes = QCheckBox("Boreholes")
        self.show_boreholes.setChecked(True)
        self.show_boreholes.setToolTip(
            "Include source-contact markers and schematic vertical well "
            "sticks in the ParaView scene. They are NOT drilled trajectories."
        )
        scene_settings.addWidget(self.show_boreholes)
        self._scene_palette = self.settings.value("3d_palette", "earth")
        if self._scene_palette not in scene_style.PALETTE_LABELS:
            self._scene_palette = "earth"
        self._scene_edges = self._scene_setting_bool("3d_edges", False)
        self._scene_orientation = self._scene_setting_bool(
            "3d_orientation", True
        )
        self._scene_bounds = self._scene_setting_bool("3d_bounds", False)
        self.scene_look_button = QPushButton("Scene look…")
        self.scene_look_button.setToolTip(
            "Choose formation colours, optional mesh outlines and a "
            "local XYZ orientation/extent guide. Dark background: #212121."
        )
        self.scene_look_button.clicked.connect(self._edit_scene_look)
        scene_settings.addWidget(self.scene_look_button)
        layout.addLayout(scene_settings)
        buttons=QHBoxLayout()
        for text,action in (
            ("Build model",self.build_model),
            ("Open in ParaView",self.open_in_paraview),
        ):
            button=QPushButton(text)
            button.clicked.connect(action)
            buttons.addWidget(button)
        folder_button=QPushButton("Model folder")
        folder_button.setToolTip("Open the selected model output directory")
        folder_button.clicked.connect(self.open_model_folder)
        buttons.addWidget(folder_button)
        self.delete_model_button = QPushButton("Delete model…")
        self.delete_model_button.setToolTip(
            "Remove the selected generated model from GroundSurf. "
            "Optionally move ONLY its verified generated files to Trash. "
            "Imported wells and contacts are never deleted."
        )
        self.delete_model_button.clicked.connect(self.delete_selected_model)
        buttons.addWidget(self.delete_model_button)
        layout.addLayout(buttons)
        self.model_table=QTableWidget(0,3)
        # Reserve space for a header AND at least one saved-model row.
        self.model_table.setMinimumHeight(92)
        self.model_table.setHorizontalHeaderLabels(
            ["Model", "Built (UTC)", "Wells"]
        )
        self.model_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.model_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.model_table,1)
        # The table now has all the remaining height: saved-model rows
        # must not disappear behind fixed explanatory widgets.
        tabs.insertTab(0,tab,"3D Models")
        self.refresh_models()

    def _scene_setting_bool(self, key, default):
        raw = self.settings.value(key, default)
        return str(raw).strip().lower() in ("true", "1", "yes")

    def _edit_scene_look(self):
        # Subsurface modelling conventions, not a cloned vendor interface.
        dialog = QDialog(self)
        dialog.setWindowTitle("ParaView · GroundSurf geological scene")
        dialog.setMinimumWidth(475)
        form = QFormLayout(dialog)
        heading = QLabel(
            "Background: #212121 (charcoal) · independent strata colours."
        )
        heading.setWordWrap(True)
        form.addRow(heading)
        palette = QComboBox()
        for key, label in scene_style.PALETTE_LABELS.items():
            palette.addItem(label, key)
        index = palette.findData(self._scene_palette)
        palette.setCurrentIndex(max(0, index))
        form.addRow("Formation colours", palette)
        edges = QCheckBox("Show geological formation outlines")
        edges.setChecked(self._scene_edges)
        form.addRow(edges)
        orientation = QCheckBox("Show the 3D XYZ orientation axes")
        orientation.setChecked(self._scene_orientation)
        form.addRow(orientation)
        bounds = QCheckBox("Show local XYZ bounding box and labels")
        bounds.setChecked(self._scene_bounds)
        form.addRow(bounds)
        warning = QLabel(
            "A local XYZ box is not a georeferenced map. Colours show "
            "stratigraphic identity, not temperature, certainty or hazard. "
            "These settings affect display only."
        )
        warning.setWordWrap(True)
        form.addRow(warning)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._scene_palette = palette.currentData()
        self._scene_edges = edges.isChecked()
        self._scene_orientation = orientation.isChecked()
        self._scene_bounds = bounds.isChecked()
        for key, value in (
            ("3d_palette", self._scene_palette),
            ("3d_edges", self._scene_edges),
            ("3d_orientation", self._scene_orientation),
            ("3d_bounds", self._scene_bounds),
        ):
            self.settings.setValue(key, value)
        self.status.setText(
            f"Next ParaView scene: {scene_style.PALETTE_LABELS[self._scene_palette]} "
            "on #212121. Changes affect newly built models only."
        )

    def refresh_models(self):
        if not hasattr(self,"model_table"):
            return
        self.model_table.setRowCount(0)
        if not self.path or not models.has_schema(self.path):
            return
        for record in models.list_models(self.path):
            row=self.model_table.rowCount()
            self.model_table.insertRow(row)
            for col,value in enumerate((record[1],record[2],record[7])):
                item=QTableWidgetItem(str(value))
                if col==0:
                    item.setData(Qt.ItemDataRole.UserRole,record[0])
                self.model_table.setItem(row,col,item)
        self.model_table.resizeColumnsToContents()

    def build_model(self):
        if not self._require_project():
            return
        try:
            if self.model_source.currentData() == "local_xyz":
                selected_batch=self.local_batch_combo.currentData()
                if selected_batch is None:
                    raise ValueError(
                        "Import metre-based local XYZ contacts into GroundSurf "
                        "and select a source dataset in the Local XYZ tab first."
                    )
                constraints=local_xyz.model_inputs(self.path, selected_batch)
            elif self.model_source.currentData() == "z_contacts":
                constraints=contact_adapter.gather_contacts(
                    self.path, self.well_layer
                )
            else:
                constraints=model_adapter.gather_wells(
                    self.path,self.well_layer
                )
        except Exception as exc:
            self._error("Cannot prepare 3D model",exc)
            return
        name,ok=QInputDialog.getText(
            self,"GroundSurf Geothermal 3D","Model name",
            text=f"Conceptual model {datetime.now(timezone.utc):%Y-%m-%d}"
        )
        if not ok:
            return
        name=name.strip()
        if not name or len(name)>120:
            self._error("Model name","Enter a name of 1–120 characters")
            return
        resolution,ok=QInputDialog.getInt(
            self,"Surface density","Subdivisions per input well triangle "
            "(2–22; higher creates larger output files)",10,2,22,1
        )
        if not ok:
            return
        directory=QFileDialog.getExistingDirectory(
            self,"Choose local folder for model output",
            str(Path(self.path).parent)
        )
        if not directory:
            return
        method=model_core.METHOD
        summary=(
            f"Create a preliminary 3D geological model?\n\n"
            f"Contributing wells: {len(constraints['samples'])}\n"
            f"Source: {self.model_source.currentText()}\n"
            f"Shared horizons: {', '.join(constraints['horizons'])}\n"
            f"Horizontal reference: {constraints['epsg']}\n"
            f"Vertical datum: {constraints['datum']}\n"
            f"Method: {method}\n"
            f"Output: {directory}\n\n"
            + (
                "IMPORTANT: These are UNLOCATED source coordinates in assumed "
                "metres. The ParaView local origin shift is recorded in "
                "model.json. The scene cannot be overlaid correctly on a "
                "world map until the true source CRS is independently "
                "identified. Web Mercator map scale may distort distances.\n\n"
                if self.model_source.currentData() == "local_xyz"
                else ""
            )
            + "Contact elevations and well-log depths are separate evidence "
            "types. Only conceptual horizons within the well footprint are "
            "modelled. No fault surfaces, geothermal flow or independent "
            "vertical-datum verification. Review imported ambiguities."
        )
        if QMessageBox.question(
            self,"Confirm 3D modelling",summary,
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No
        )!=QMessageBox.StandardButton.Yes:
            return
        try:
            mesh=model_core.build_mesh(
                constraints["samples"],constraints["horizons"],resolution
            )
            if len(mesh["faces"])>80000:
                raise ValueError("Too many triangles; reduce subdivisions")
            safe=model_core._safe_name(name)
            stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            output=Path(directory)/(f"gsmodel-{safe}-{stamp}-{uuid.uuid4().hex[:5]}")
            provenance={
                "wells":constraints["provenance"],
                "horizons":constraints["horizons"],
                "epsg":constraints["epsg"],
                "datum":constraints["datum"],
                "subdivisions":resolution,
                "method":method,
                "source_type":self.model_source.currentData(),
            }
            source_hash=hashlib.sha256(
                json.dumps(provenance,sort_keys=True).encode("utf-8")
            ).hexdigest()
            scene,manifest=model_core.export_model(
                mesh,output,name,constraints["epsg"],constraints["datum"],
                constraints["provenance"],warnings=constraints["warnings"],
                vertical_exaggeration=self.scene_vertical.value(),
                show_boreholes=self.show_boreholes.isChecked(),
                palette=self._scene_palette,
                show_edges=self._scene_edges,
                show_orientation=self._scene_orientation,
                show_bounds=self._scene_bounds,
            )
            if self.model_source.currentData() == "local_xyz":
                # Persist the translation required to reconstruct original
                # source XYZ from the ParaView-local coordinates.
                raw=json.loads(manifest.read_text(encoding="utf-8"))
                raw["georeferenced"]=False
                raw["coordinate_basis"]=local_xyz.BASIS
                raw["local_origin_m"]=constraints["local_origin_m"]
                raw["input_batch_id"]=constraints["batch_id"]
                raw["horizontal_units"]="m (user-assumed)"
                raw["vertical_units"]="m (user-assumed)"
                raw["source_coordinates"]="local Cartesian, no EPSG"
                manifest.write_text(
                    json.dumps(raw, ensure_ascii=False, indent=2)+"\n",
                    encoding="utf-8"
                )
            models.record(
                self.path,name,output,constraints["epsg"],constraints["datum"],
                len(constraints["samples"]),source_hash,method
            )
            self.refresh_models()
            self.model_table.selectRow(0)
            self.status.setText(
                f"3D model created: {len(mesh['faces'])} triangles; "
                f"{len(mesh['horizons'])-1} volume units. "
                "Open in ParaView for geological colours, borehole markers "
                "and per-unit visibility. Distance to nearest well measures "
                "data coverage, not confidence."
            )
            QMessageBox.information(
                self,"3D model exported",
                f"Saved:\n{scene}\n\n"
                f"Exported {len(mesh['faces'])} triangle cells and "
                f"{len(mesh['horizons'])-1} geological volume units.\n"
                "The ParaView scene includes unit colours and observed "
                "contact markers. Review model.json for assumptions."
            )
        except Exception as exc:
            self._error("3D model creation failed",exc)

    def _selected_model(self):
        if not self.path:
            return None
        row=self.model_table.currentRow()
        if row<0 or self.model_table.item(row,0) is None:
            QMessageBox.information(self,"Select model","Select a saved model row.")
            return None
        model_id=self.model_table.item(row,0).data(Qt.ItemDataRole.UserRole)
        match=next(
            (r for r in models.list_models(self.path) if r[0]==model_id),
            None
        )
        if match is None:
            self._error("Model unavailable","Model catalogue record not found")
            return None
        folder=models.find_output(self.path,match)
        if folder is None:
            self._error(
                "Model source missing",
                "Output folder moved or deleted. Rebuild the conceptual model."
            )
            return None
        return folder

    def delete_selected_model(self):
        """Safe explicit removal of one model; preserve raw geological data."""
        if not self._require_project():
            return
        selected = self.model_table.currentRow()
        if selected < 0 or self.model_table.item(selected, 0) is None:
            QMessageBox.information(
                self, "Select model", "Select a saved model row to remove."
            )
            return
        model_id = self.model_table.item(selected, 0).data(
            Qt.ItemDataRole.UserRole
        )
        try:
            # The unique ID matters: several saved models may share a name.
            row = models.find_record(self.path, model_id)
            if row is None:
                raise ValueError("The selected model is no longer saved")
            safe_folder = models.safe_trash_folder(self.path, row)
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle("Remove conceptual 3D model")
            dialog.setText(f"Remove the selected model from GroundSurf?\n\n{row[1]}")
            dialog.setInformativeText(
                "This removes only one saved model entry. Imported "
                "boreholes, geological contacts, maps and observations "
                "remain unchanged.\n\n"
                "You can separately move its generated ParaView files to "
                "your system Trash."
            )
            trash = QCheckBox(
                "Also move this model's generated files to Trash"
            )
            trash.setChecked(False)
            if safe_folder is None:
                trash.setEnabled(False)
                trash.setToolTip(
                    "Generated folder is missing or cannot be safely "
                    "identified. Only the list entry can be removed."
                )
            else:
                trash.setToolTip(str(safe_folder))
            dialog.setCheckBox(trash)
            remove_button = dialog.addButton(
                "Remove selected model", QMessageBox.ButtonRole.AcceptRole
            )
            cancel_button = dialog.addButton(
                "Cancel", QMessageBox.ButtonRole.RejectRole
            )
            dialog.setDefaultButton(cancel_button)
            dialog.exec()
            if dialog.clickedButton() != remove_button:
                return
            if trash.isChecked():
                # Revalidate before touching the filesystem. Qt moves the
                # entire folder to the user Trash, not permanent deletion.
                target = models.safe_trash_folder(self.path, row)
                if target is None or target != safe_folder:
                    raise ValueError(
                        "Generated model folder changed; no files or "
                        "catalogue entries were removed"
                    )
                moved = QFile.moveToTrash(str(target))
                moved_ok = moved[0] if isinstance(moved, tuple) else bool(moved)
                if not moved_ok:
                    raise OSError(
                        "The model folder could not be moved to Trash. "
                        "The catalogue entry is unchanged."
                    )
            models.remove_model(self.path, model_id)
            self.refresh_models()
            self.status.setText(
                "Removed one conceptual model"
                + (" and moved its generated files to Trash."
                   if trash.isChecked() else " from the model list. "
                   "Generated files remain on disk.")
                + " Boreholes, geological contacts and maps are unchanged."
            )
        except Exception as exc:
            self._error("Could not remove 3D model", exc)

    def open_model_folder(self):
        folder=self._selected_model()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_in_paraview(self):
        folder=self._selected_model()
        if not folder:
            return
        # Open an explicit, selected local model only via the Qt process API.
        # No shell, command interpolation, or network operation.
        executable = QStandardPaths.findExecutable("paraview")
        if not executable:
            QMessageBox.information(
                self, "ParaView not found",
                "Install ParaView, or open model.vtm manually in an existing "
                "ParaView session.\n\nFile: " + str(folder / "model.vtm")
            )
            return
        try:
            presentation = folder / "view_in_paraview.py"
            # ParaView 6.x GUI accepts --script (official CLI). Older
            # models without a presentation script still open the VTM.
            args = (
                ["--script", str(presentation)]
                if presentation.is_file()
                else [str(folder / "model.vtm")]
            )
            launched, _pid = QProcess.startDetached(
                executable, args, str(folder)
            )
            if not launched:
                raise RuntimeError("ParaView did not start")
            self.status.setText(
                "Opening ParaView with geological unit colours and "
                "observed borehole markers." if presentation.is_file()
                else "Opening legacy VTK model in ParaView."
            )
        except (OSError, RuntimeError) as exc:
            self._error("Cannot launch ParaView", exc)

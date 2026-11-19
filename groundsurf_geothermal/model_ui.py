"""QGIS dock UI for transparent preliminary 3D horizon/volume modelling."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from . import model_adapter, model_core, models


class ModelToolsMixin:
    def setup_model_tools(self, tabs):
        tab=QWidget()
        layout=QVBoxLayout(tab)
        title=QLabel("3D Geological Models · PRELIMINARY")
        title.setObjectName("gsModelTitle")
        layout.addWidget(title)
        explanation=QLabel(
            "Interpolate shared contact elevations from three or more wells "
            "with the same vertical datum. Export triangulated 3D horizons and "
            "wedge volumes in ParaView-readable VTK format."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        buttons=QHBoxLayout()
        for text,action in (
            ("Build model",self.build_model),
            ("Open in ParaView",self.open_in_paraview),
        ):
            button=QPushButton(text)
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.model_table=QTableWidget(0,3)
        self.model_table.setHorizontalHeaderLabels(
            ["Model", "Built (UTC)", "Wells"]
        )
        self.model_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.model_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.model_table,1)
        folder_button=QPushButton("Open selected model folder")
        folder_button.clicked.connect(self.open_model_folder)
        layout.addWidget(folder_button)
        limitations=QLabel(
            "IDW horizon interpolation is a conceptual approximation, not "
            "a calibrated geostatistical or thermal model. No extrapolation "
            "beyond the well footprint. No faults or reservoir flow simulation. "
            "Imported and model-generated evidence remain separate."
        )
        limitations.setWordWrap(True)
        layout.addWidget(limitations)
        tabs.addTab(tab,"3D Models")
        self.refresh_models()

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
                    item.setData(Qt.UserRole,record[0])
                self.model_table.setItem(row,col,item)
        self.model_table.resizeColumnsToContents()

    def build_model(self):
        if not self._require_project():
            return
        try:
            constraints=model_adapter.gather_wells(self.path,self.well_layer)
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
            f"Shared horizons: {', '.join(constraints['horizons'])}\n"
            f"Horizontal reference: {constraints['epsg']}\n"
            f"Vertical datum: {constraints['datum']}\n"
            f"Method: {method}\n"
            f"Output: {directory}\n\n"
            "Only conceptual contacts between wells are modelled. "
            "No predictive geothermal flow or engineering validation."
        )
        if QMessageBox.question(
            self,"Confirm 3D modelling",summary,
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No
        )!=QMessageBox.Yes:
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
            }
            source_hash=hashlib.sha256(
                json.dumps(provenance,sort_keys=True).encode("utf-8")
            ).hexdigest()
            scene,manifest=model_core.export_model(
                mesh,output,name,constraints["epsg"],constraints["datum"],
                constraints["provenance"],warnings=constraints["warnings"]
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
                "Open in ParaView or inspect model.json for assumptions."
            )
            QMessageBox.information(
                self,"3D model exported",
                f"Saved:\n{scene}\n\n"
                f"Exported {len(mesh['faces'])} triangle cells and "
                f"{len(mesh['horizons'])-1} geological volume units.\n"
                "Review model.json before interpreting the result."
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
        model_id=self.model_table.item(row,0).data(Qt.UserRole)
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

    def open_model_folder(self):
        folder=self._selected_model()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_in_paraview(self):
        folder=self._selected_model()
        if not folder:
            return
        exe=shutil.which("paraview")
        if not exe:
            QMessageBox.information(
                self,"ParaView not found",
                "Install ParaView or open model.vtm manually in an existing "
                "ParaView session.\n\nFile: "+str(folder/"model.vtm")
            )
            return
        try:
            # Never use a shell; do not pass untrusted command arguments.
            subprocess.Popen(
                [exe,str(folder/"model.vtm")],
                cwd=str(folder),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            self.status.setText("Opening selected 3D model in desktop ParaView.")
        except OSError as exc:
            self._error("Cannot launch ParaView",exc)

"""Additional QGIS well log, formation top and measurement editor UI."""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from . import db


def _table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QTableWidget.NoEditTriggers)
    widget.setSelectionBehavior(QTableWidget.SelectRows)
    widget.setAlternatingRowColors(True)
    return widget


def _widget_tab(button_specs, table):
    container = QWidget()
    layout = QVBoxLayout(container)
    actions = QHBoxLayout()
    for text, func in button_specs:
        button = QPushButton(text)
        button.clicked.connect(func)
        actions.addWidget(button)
    layout.addLayout(actions)
    layout.addWidget(table, 1)
    return container


class WellManagerMixin:
    def setup_well_manager(self, outer, tabs):
        self.well_select = QComboBox()
        self.well_select.setMinimumHeight(29)
        self.well_select.currentIndexChanged.connect(self.refresh_well_details)
        outer.addWidget(QLabel("Active well"))
        outer.addWidget(self.well_select)

        self.intervals_table = _table(
            ["Formation", "Top (m bgl)", "Base (m bgl)", "Thickness (m)", "Description"]
        )
        tabs.addTab(_widget_tab((
            ("Formation", self.ui_add_formation),
            ("Interval", self.ui_add_interval),
            ("Import CSV", self.ui_import_intervals),
            ("Delete", lambda: self.ui_delete("interval")),
        ), self.intervals_table), "Well log")

        self.tops_table = _table(
            ["Formation", "Depth (m bgl)", "Basis", "Source"]
        )
        tabs.addTab(_widget_tab((
            ("Add top", self.ui_add_top),
            ("Delete", lambda: self.ui_delete("top")),
        ), self.tops_table), "Formation tops")

        self.observations_table = _table(
            ["Observed UTC", "Quantity", "Value", "Unit", "Depth bgl (m)", "Datum"]
        )
        tabs.addTab(_widget_tab((
            ("Add observation", self.ui_add_observation),
            ("Delete", lambda: self.ui_delete("observation")),
        ), self.observations_table), "Measurements")

    def active_well(self):
        if not self._require_project():
            return None
        well_id = self.well_select.currentData()
        if not well_id:
            QMessageBox.information(
                self, "Select well", "Add or select a well before editing its log."
            )
            return None
        return str(well_id)

    def refresh_well_details(self, *_):
        if not hasattr(self, "well_select"):
            return
        current = self.well_select.currentData()
        self.well_select.blockSignals(True)
        self.well_select.clear()
        if self.well_layer is not None:
            for f in self.well_layer.getFeatures():
                self.well_select.addItem(
                    f"{f['well_id']} · {f['name']}", str(f["well_id"])
                )
        if current:
            idx = self.well_select.findData(current)
            if idx >= 0:
                self.well_select.setCurrentIndex(idx)
        self.well_select.blockSignals(False)
        well_id = self.well_select.currentData()
        for table in (
            self.intervals_table, self.tops_table, self.observations_table
        ):
            table.setRowCount(0)
        if not self.path or not well_id:
            return

        self._fill_table(self.intervals_table, [
            (row[0], [row[1], row[2], row[3],
                      round(row[3] - row[2], 3), row[4]])
            for row in db.intervals(self.path, well_id)
        ])
        self._fill_table(self.tops_table, [
            (row[0], [row[1], row[2], row[3], row[4]])
            for row in db.formation_tops(self.path, well_id)
        ])
        self._fill_table(self.observations_table, [
            (row[0], [row[1], row[2], row[3], row[4], row[5], row[6]])
            for row in db.observations(self.path, well_id)
        ])

    def _fill_table(self, table, entries):
        for record_id, values in entries:
            row_num = table.rowCount()
            table.insertRow(row_num)
            for col, val in enumerate(values):
                item = QTableWidgetItem("" if val is None else str(val))
                if col == 0:
                    item.setData(Qt.UserRole, record_id)
                table.setItem(row_num, col, item)
        table.resizeColumnsToContents()

    def _form(self, title, fields, combos=None):
        """Return a validated user's text choices or None when cancelled."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QFormLayout(dialog)
        controls = {}
        for key, caption, default in fields:
            if combos and key in combos:
                input_widget = QComboBox()
                input_widget.addItems(combos[key])
                if default:
                    index = input_widget.findText(str(default))
                    if index >= 0:
                        input_widget.setCurrentIndex(index)
            else:
                input_widget = QLineEdit(str(default or ""))
            controls[key] = input_widget
            layout.addRow(caption, input_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return {
            key: widget.currentText() if isinstance(widget, QComboBox)
                 else widget.text()
            for key, widget in controls.items()
        }

    def _formation_codes(self):
        codes = [row[0] for row in db.formations(self.path)]
        if not codes:
            QMessageBox.information(
                self, "Define formation",
                "Add a formation with its code first, then add log intervals or tops."
            )
        return codes

    def ui_add_formation(self):
        if not self._require_project():
            return
        row = self._form("New stratigraphic formation", (
            ("code", "Formation code *", ""),
            ("name", "Formation name *", ""),
            ("lithology", "Lithology", ""),
            ("notes", "Notes", ""),
        ))
        if row is None:
            return
        try:
            db.add_formation(self.path, **row)
            self.status.setText("Formation saved: " + row["code"])
        except Exception as exc:
            self._error("Cannot create formation", exc)

    def ui_add_interval(self):
        well = self.active_well()
        if not well:
            return
        codes = self._formation_codes()
        if not codes:
            return
        row = self._form("Add lithological interval to " + well, (
            ("formation_code", "Formation", codes[0]),
            ("top_depth_m", "Top (m below ground) *", ""),
            ("base_depth_m", "Base (m below ground) *", ""),
            ("description", "Lithology description", ""),
        ), {"formation_code": codes})
        if row is None:
            return
        try:
            db.add_interval(self.path, self.well_layer, well, **row)
            self.refresh_well_details()
            self.status.setText("Lithological interval saved in project.")
        except Exception as exc:
            self._error("Cannot add interval", exc)

    def ui_import_intervals(self):
        if not self._require_project():
            return
        name, _ = QFileDialog.getOpenFileName(
            self, "Import lithological intervals", "", "CSV files (*.csv)"
        )
        if not name:
            return
        try:
            with open(name, encoding="utf-8-sig", newline="") as handle:
                count = db.import_intervals_csv(self.path, self.well_layer, handle.read())
            self.refresh_well_details()
            self.status.setText(f"Imported {count} intervals from CSV.")
        except Exception as exc:
            self._error("Interval import failed", exc)

    def ui_add_top(self):
        well = self.active_well()
        if not well:
            return
        codes = self._formation_codes()
        if not codes:
            return
        row = self._form("Formation top for " + well, (
            ("formation_code", "Formation", codes[0]),
            ("depth_bgl_m", "Depth (m below ground) *", ""),
            ("interpretation", "Basis", "observed"),
            ("source", "Source", ""),
            ("notes", "Notes", ""),
        ), {"formation_code": codes, "interpretation": ["observed", "interpreted"]})
        if row is None:
            return
        try:
            db.add_formation_top(self.path, self.well_layer, well, **row)
            self.refresh_well_details()
            self.status.setText("Formation top saved with its interpretation basis.")
        except Exception as exc:
            self._error("Cannot add formation top", exc)

    def ui_add_observation(self):
        well = self.active_well()
        if not well:
            return
        row = self._form("Record measurement for " + well, (
            ("observed_utc", "Observed time (ISO 8601, UTC) *", db.utcnow()),
            ("kind", "Measurement quantity", "water_depth_bgl_m"),
            ("value", "Observed value *", ""),
            ("depth_bgl_m", "Measurement depth (m bgl)", ""),
            ("reference_datum", "Water datum / pressure basis", ""),
            ("source", "Source", ""),
            ("notes", "Notes", ""),
        ), {"kind": list(db.OBSERVATION_UNITS)})
        if row is None:
            return
        try:
            db.add_observation(self.path, self.well_layer, well, **row)
            self.refresh_well_details()
            self.status.setText(
                "Observation saved; units from quantity: " +
                db.OBSERVATION_UNITS[row["kind"]]
            )
        except Exception as exc:
            self._error("Cannot save observation", exc)

    def ui_delete(self, kind):
        well = self.active_well()
        if not well:
            return
        table = {
            "interval": self.intervals_table,
            "top": self.tops_table,
            "observation": self.observations_table
        }[kind]
        row = table.currentRow()
        if row < 0 or not table.item(row, 0):
            QMessageBox.information(self, "Select record", "Select a row to delete.")
            return
        record_id = table.item(row, 0).data(Qt.UserRole)
        answer = QMessageBox.question(
            self, "Delete record?", f"Delete selected {kind} record for well {well}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        try:
            db.delete_well_record(self.path, kind, record_id, well)
            self.refresh_well_details()
            self.status.setText("Selected record deleted.")
        except Exception as exc:
            self._error("Could not delete record", exc)

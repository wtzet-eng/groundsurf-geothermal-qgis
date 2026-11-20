"""QGIS dock view for persisted raw Z contact elevations.

Different from depth_bgl_m intervals: the supplied Z value is retained
without inventing a ground surface, drilling TD or verified vertical datum.
"""
from qgis.PyQt.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import elevation_contacts, local_xyz


class ContactToolsMixin:
    def setup_contact_tab(self, tabs):
        self.contact_tab = QWidget()
        layout = QVBoxLayout(self.contact_tab)
        heading = QLabel("3D stratigraphic contacts · raw Z elevations")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        note = QLabel(
            "These are source elevation observations, NOT depths below "
            "ground. Multiple values for the same unit are preserved; "
            "check the vertical datum before modelling."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        search = QHBoxLayout()
        search.addWidget(QLabel("Filter by borehole or unit"))
        self.contact_filter = QLineEdit()
        self.contact_filter.setPlaceholderText("BH9, Cretaceous, …")
        self.contact_filter.textChanged.connect(self._filter_contacts)
        search.addWidget(self.contact_filter)
        layout.addLayout(search)
        self.contact_table = QTableWidget(0, 5)
        self.contact_table.setHorizontalHeaderLabels([
            "Borehole", "Strata / unit", "Z elevation (m)",
            "Vertical reference", "Source layer",
        ])
        self.contact_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.contact_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.contact_table, 1)
        self.contact_summary = QLabel("No Z contacts in this GroundSurf project")
        self.contact_summary.setWordWrap(True)
        layout.addWidget(self.contact_summary)
        tabs.addTab(self.contact_tab, "Z Contacts")

        self.local_xyz_tab = QWidget()
        local_layout = QVBoxLayout(self.local_xyz_tab)
        local_note = QLabel(
            "LOCAL XYZ — NOT GEOREFERENCED. X/Y/Z are source metre values "
            "grouped as boreholes. The source's global map position and "
            "vertical reference may be unknown. These are deliberately "
            "separate from EPSG:4326 Wells and georeferenced Z Contacts."
        )
        local_note.setWordWrap(True)
        local_layout.addWidget(local_note)
        local_row = QHBoxLayout()
        local_row.addWidget(QLabel("Local source dataset:"))
        self.local_batch_combo = QComboBox()
        self.local_batch_combo.currentIndexChanged.connect(
            self.refresh_local_xyz_table
        )
        local_row.addWidget(self.local_batch_combo, 1)
        local_layout.addLayout(local_row)
        self.local_table = QTableWidget(0, 5)
        self.local_table.setHorizontalHeaderLabels(
            ["Borehole", "Stratum", "X (m)", "Y (m)", "Z (m)"]
        )
        self.local_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.local_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        local_layout.addWidget(self.local_table,1)
        self.local_summary=QLabel("No unlocated local XYZ sources.")
        self.local_summary.setWordWrap(True)
        local_layout.addWidget(self.local_summary)
        tabs.addTab(self.local_xyz_tab, "Local XYZ")

    def refresh_contacts(self):
        if not hasattr(self, "contact_table"):
            return
        self.contact_table.setRowCount(0)
        if not self.path or not elevation_contacts.has_schema(self.path):
            self.contact_summary.setText("No GroundSurf contact database loaded.")
            return
        rows = elevation_contacts.list_contacts(self.path)
        for row_data in rows[:5000]:
            well, code, z, datum, source = row_data[:5]
            row = self.contact_table.rowCount()
            self.contact_table.insertRow(row)
            for col, value in enumerate((well, code, f"{z:.3f}", datum, source)):
                self.contact_table.setItem(
                    row, col, QTableWidgetItem(str(value))
                )
        self.contact_table.resizeColumnsToContents()
        self.contact_summary.setText(
            f"{len(rows)} saved contact elevations for "
            f"{len({r[0] for r in rows})} boreholes. "
            + ("Showing first 5,000 rows." if len(rows) > 5000 else "")
            + " These are observations, not interpreted depths."
        )
        self._filter_contacts(self.contact_filter.text())

    def refresh_local_xyz(self):
        if not hasattr(self, "local_batch_combo"):
            return
        remembered=self.local_batch_combo.currentData()
        batches=local_xyz.list_batches(self.path) if self.path else []
        self.local_batch_combo.blockSignals(True)
        self.local_batch_combo.clear()
        for b in batches:
            self.local_batch_combo.addItem(
                f"#{b[0]} · {b[1]} · {b[7]} XYZ records / "
                f"{b[8]} boreholes · UNLOCATED", b[0]
            )
        if remembered is not None:
            index=self.local_batch_combo.findData(remembered)
            if index >= 0:
                self.local_batch_combo.setCurrentIndex(index)
        self.local_batch_combo.blockSignals(False)
        self.refresh_local_xyz_table()

    def refresh_local_xyz_table(self, *_):
        if not hasattr(self, "local_table"):
            return
        self.local_table.setRowCount(0)
        if not self.path or self.local_batch_combo.currentData() is None:
            self.local_summary.setText(
                "No LOCAL XYZ records. Import a metre-based source layer "
                "using Import from QGIS → Local XYZ."
            )
            return
        batch_id=self.local_batch_combo.currentData()
        records=local_xyz.list_contacts(self.path, batch_id)
        for row in records[:5000]:
            _batch, well, unit, x, y, z, _source_feature = row
            pos=self.local_table.rowCount()
            self.local_table.insertRow(pos)
            for index, val in enumerate(
                (well,unit,f"{x:.3f}",f"{y:.3f}",f"{z:.3f}")
            ):
                self.local_table.setItem(
                    pos,index,QTableWidgetItem(str(val))
                )
        self.local_table.resizeColumnsToContents()
        batches=[b for b in local_xyz.list_batches(self.path) if b[0]==batch_id]
        ref=batches[0][5] if batches else "UNKNOWN"
        self.local_summary.setText(
            f"{len(records)} records, "
            f"{len({r[1] for r in records})} unlocated boreholes. "
            f"Vertical basis: {ref}. "
            "X/Y/Z stored in original assumed metres; no GIS world-map "
            "coordinates have been invented."
        )

    def _filter_contacts(self, text):
        if not hasattr(self, "contact_table"):
            return
        term = text.casefold().strip()
        for row in range(self.contact_table.rowCount()):
            key = " ".join(
                (self.contact_table.item(row, col).text()
                 if self.contact_table.item(row, col) else "")
                for col in (0, 1)
            ).casefold()
            self.contact_table.setRowHidden(row, bool(term) and term not in key)

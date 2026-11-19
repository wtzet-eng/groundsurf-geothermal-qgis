"""QGIS dock view for persisted raw Z contact elevations.

Different from depth_bgl_m intervals: the supplied Z value is retained
without inventing a ground surface, drilling TD or verified vertical datum.
"""
from qgis.PyQt.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import elevation_contacts


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

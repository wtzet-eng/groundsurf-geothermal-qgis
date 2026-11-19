"""2D geological cross-section drawing; no new numerical modelling engine."""
import hashlib
import math
from qgis.PyQt.QtCore import Qt, QPointF, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

# Geological unit colours with good distinction on charcoal and white UI.
FORMATION_COLORS = (
    "#b89b72", "#80a9a3", "#bb8179", "#aa9fc9",
    "#9cae6e", "#d0aa6b", "#789dc4", "#b69eab",
    "#9bbca5", "#b68e64", "#82acbf", "#d1a1ad",
)


def color_for(code):
    digest = hashlib.sha256(str(code).encode("utf-8")).digest()
    return QColor(FORMATION_COLORS[digest[0] % len(FORMATION_COLORS)])


class SectionCanvas(QWidget):
    """A redrawable 2D panel (not a spatially accurate ground surface)."""
    def __init__(self, scene, dark=True, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.dark = dark
        self.setMinimumSize(960, 570)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self.draw(painter, self.width(), self.height())
        finally:
            painter.end()

    def _y(self, value, bottom, top, lo, hi):
        if self.scene["elevation_mode"]:
            return top + (hi - value) / (hi - lo) * (bottom - top)
        return top + (value - lo) / (hi - lo) * (bottom - top)

    def draw(self, painter, width, height):
        s = self.scene
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        background = QColor("#212121" if self.dark else "#ffffff")
        foreground = QColor("#e9eee9" if self.dark else "#25372a")
        muted = QColor("#a6b7ad" if self.dark else "#52645a")
        panel = QColor("#292e2b" if self.dark else "#f5f7f5")
        grid = QColor("#445047" if self.dark else "#d8e1da")
        painter.fillRect(0, 0, width, height, background)

        def line(x1, y1, x2, y2, colour, thickness=1, dashed=False):
            pen = QPen(colour, thickness)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x1,y1), QPointF(x2,y2))

        def label(x, y, content, colour=None, size=10, bold=False):
            painter.setPen(colour or foreground)
            font = QFont("Sans Serif", size)
            font.setBold(bold)
            painter.setFont(font)
            painter.drawText(QPointF(x,y), str(content))

        label(28, 29, s["name"], foreground, 15, True)
        subtitle = (
            f"{s['well_count']} wells  ·  length {s['length_m']:.0f} m"
            f"  ·  corridor ±{s['buffer_m']:.0f} m  ·  {s['utm']}"
        )
        label(28, 52, subtitle, muted, 9)
        top = 120
        bottom = max(top + 200, height - 105)
        left = 88
        right = max(left + 200, width - 65)
        painter.fillRect(QRectF(left, top, right-left, bottom-top), panel)

        lo = s["axis_min"]
        hi = s["axis_max"]
        if hi - lo < 1e-9:
            hi = lo + 1
        length = max(s["length_m"], 1)
        def x_plot(chainage):
            return left + chainage / length * (right - left)

        def y_plot(vertical):
            return self._y(vertical, bottom, top, lo, hi)

        # Reference grid, common horizontal distance and vertical value axes.
        for n in range(6):
            vertical = lo + (hi-lo)*n/5
            pos = y_plot(vertical)
            line(left, pos, right, pos, grid)
            label(9, pos+3, f"{vertical:.0f}", muted, 9)
            dist = length*n/5
            xpos = x_plot(dist)
            line(xpos, top, xpos, bottom, grid)
            label(xpos-15, bottom+22, f"{dist:.0f}", muted, 9)
        if s["elevation_mode"]:
            label(9, top-16, f"Elevation (m, {s['datum']})", muted, 9)
        else:
            label(9, top-16, "Depth below local ground (m)", muted, 9)
        label(right-132, bottom+48, "Chainage (m)", muted, 10)

        # Hypothetical correlations only where two *adjacent* wells support
        # the same unit. Never extrapolate contacts beyond these wells.
        if s["elevation_mode"]:
            rows = s["well_rows"]
            for well_a, well_b in zip(rows, rows[1:]):
                shared = sorted(set(well_a["contacts"]) & set(well_b["contacts"]))
                for formation_code in shared:
                    pick_a = well_a["contacts"][formation_code]
                    pick_b = well_b["contacts"][formation_code]
                    xa, xb = x_plot(well_a["chainage_m"]), x_plot(well_b["chainage_m"])
                    ya = y_plot(well_a["ground_elev_m"] - pick_a["depth"])
                    yb = y_plot(well_b["ground_elev_m"] - pick_b["depth"])
                    line(xa, ya, xb, yb, color_for(formation_code), 1.5, dashed=True)

        # Show observed/interpretive lithology as solid well columns.
        thickness = max(7., min(22., 420 / (len(s["well_rows"])+5)))
        for well in s["well_rows"]:
            xpos = x_plot(well["chainage_m"])
            head = well["top_axis"]
            base = well["bottom_axis"]
            y_head, y_base = y_plot(head), y_plot(base)
            line(xpos, y_head, xpos, y_base, foreground, 3)
            for interval in well["intervals"]:
                z_top = (well["ground_elev_m"] - interval["top"]
                         if s["elevation_mode"] else interval["top"])
                z_base = (well["ground_elev_m"] - interval["base"]
                          if s["elevation_mode"] else interval["base"])
                y1, y2 = y_plot(z_top), y_plot(z_base)
                rect = QRectF(xpos-thickness/2, min(y1, y2), thickness, abs(y2-y1))
                painter.fillRect(rect, color_for(interval["formation"]))
                painter.setPen(QPen(background, .5))
                painter.drawRect(rect)
            for code, pick in well["contacts"].items():
                depth = pick["depth"]
                vertical = (well["ground_elev_m"]-depth
                            if s["elevation_mode"] else depth)
                py = y_plot(vertical)
                c = color_for(code)
                # Filled for source-observed, open for interpreted/log-derived.
                if pick["basis"] == "observed":
                    painter.setBrush(c)
                else:
                    painter.setBrush(background)
                painter.setPen(QPen(c, 2.2))
                painter.drawEllipse(QPointF(xpos,py),4.3,4.3)
                if pick["basis"] == "section-interpreted":
                    line(xpos-6,py-6,xpos+6,py+6,c,2)
            label(xpos-21, max(80, y_head-15), well["well_id"], foreground, 9, True)

        # Use a clearly labelled, compact horizontal key.
        line(left, bottom+63, left+32, bottom+63, muted, 1.5, dashed=True)
        label(left+39, bottom+67, "Dashed = correlation hypothesis", muted, 9)
        label(left+290, bottom+67, "Filled contact = observed; open = interpreted/log-derived",
              muted, 9)
        # Limit legend to first six formations so labels do not overlap.
        used = sorted({i["formation"] for w in s["well_rows"] for i in w["intervals"]
                       if i["formation"]})
        for n, code in enumerate(used[:6]):
            xpos = left + n*max(112, (right-left)/6)
            painter.fillRect(QRectF(xpos, height-27, 14, 10), color_for(code))
            text = f"{code} {s['formations'].get(code,'')}"[:17]
            label(xpos+18, height-17, text, muted, 8)

        # Indicate that common elevation datums do not imply true terrain
        # between boreholes is known, and show warning for synthetic data.
        warnings = [w for w in s["warnings"] if w]
        note = (
            "Schematic between wells. No interpolation beyond adjacent logs. "
            "Vertical/horizontal display scales differ."
        )
        if warnings:
            note += "  " + " | ".join(warnings)
        label(28, 91, note[:195], QColor("#e4ad83" if self.dark else "#865221"), 8)

    def save_png(self, path):
        image = QImage(1800, 950, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            self.draw(painter, image.width(), image.height())
        finally:
            painter.end()
        if not image.save(path, "PNG"):
            raise OSError("Could not save PNG image")

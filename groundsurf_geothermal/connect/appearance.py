"""Calm, accessible greys following the current Qt application palette."""

from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QPlainTextEdit


class RequestEdit(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setObjectName("GroundSurfRequest")
        self.setMinimumHeight(220)
        self.setPlaceholderText(
            "Describe what you need in your own words…\n\n"
            "For example: Find boreholes, terrain and aerial imagery in this area."
        )

    def text(self):
        return self.toPlainText()


def colours(dark):
    return (
        ("#252525", "#2d2d2d", "#e0e0de", "#a9a9a7", "#525252", "#414141", "#555555")
        if dark
        else ("#e6e6e3", "#efefec", "#383838", "#666664", "#bcbcb8", "#d5d5d1", "#c7c7c3")
    )


def text_palette(widget):
    dark = QApplication.palette().color(QPalette.Window).lightness() < 128
    _, field, fg, muted, _, _, _ = colours(dark)
    palette = widget.palette()
    palette.setColor(QPalette.Base, QColor(field))
    palette.setColor(QPalette.Text, QColor(fg))
    if hasattr(QPalette, "PlaceholderText"):
        palette.setColor(QPalette.PlaceholderText, QColor(muted))
    widget.setPalette(palette)


def stylesheet(dark=None):
    if dark is None:
        dark = QApplication.palette().color(QPalette.Window).lightness() < 128
    bg, field, fg, muted, border, button, hover = colours(dark)
    return f"""
    QWidget {{ background-color: {bg}; color: {fg}; }}
    QLabel, QCheckBox {{ color: {fg}; background: transparent; }}
    QPlainTextEdit, QTextEdit, QTextBrowser, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {field}; color: {fg}; border: 1px solid {border}; border-radius: 5px;
        padding: 6px; selection-background-color: {hover}; selection-color: {fg};
    }}
    QPlainTextEdit#GroundSurfRequest {{ padding: 10px; }}
    QPushButton {{ background: {button}; color: {fg}; border: 1px solid {border};
        border-radius: 5px; padding: 7px; }}
    QPushButton:hover, QPushButton:checked {{ background: {hover}; }}
    QPushButton:disabled {{ color: {muted}; background: {bg}; }}
    QPushButton#GroundSurfPrimary {{ font-weight: 600; padding: 10px; background: {hover}; }}
    QPushButton#GroundSurfPrimary:disabled {{ color: {muted}; background: {bg}; }}
    QTabWidget::pane {{ border: 0; background: {bg}; }}
    QComboBox QAbstractItemView {{ background: {field}; color: {fg}; selection-background-color: {hover}; }}
    """

"""Responsive dock acceptance on a short QGIS window."""
import os
import json
import traceback
from pathlib import Path
from qgis import utils
from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QPushButton

root = Path(os.environ["GS_LAYOUT_QA"])


def finish(ok, error=""):
    (root / "result.json").write_text(json.dumps({"ok": ok, "error": error}))
    QgsProject.instance().setDirty(False)
    QApplication.instance().quit()


def within(widget, viewport):
    from qgis.PyQt.QtCore import QPoint
    point = widget.mapTo(viewport, QPoint(0, 0))
    return point.y() >= 0 and point.y() + widget.height() <= viewport.height()


def start():
    try:
        from processing.core.Processing import Processing
        Processing.initialize()
        utils.updateAvailablePlugins()
        assert utils.loadPlugin("groundsurf_geothermal")
        assert utils.startPlugin("groundsurf_geothermal")
        plugin = utils.plugins["groundsurf_geothermal"]
        plugin.open_dock()
        win = utils.iface.mainWindow()
        win.resize(1100, 690)
        win.resizeDocks([plugin.dock], [440], Qt.Horizontal)
        QTimer.singleShot(600, lambda: verify(plugin))
    except Exception:
        finish(False, traceback.format_exc())


def verify(plugin):
    try:
        dock, c = plugin.dock, plugin.connect
        a = c.assistant_dock
        assert dock.height() <= 690, dock.height()
        assert 105 <= c.request.height() <= 240
        assert c.tabs.currentIndex() == 0 and not c.advanced.isVisible()
        for button in (c.find_button, a.ai_plan, c.tools_toggle, c.import_local):
            assert within(button, c.page_scroll.viewport()), button.text()
        c.request.setPlainText("Could you connect boreholes for this area?")
        palette = QApplication.palette()
        for name, colour in (("Light", "#e6e6e3"), ("Dark", "#252525")):
            mode = QPalette(palette)
            mode.setColor(QPalette.Window, QColor(colour))
            QApplication.setPalette(mode)
            QApplication.processEvents()
            dock.grab().save(str(root / (name + ".png")))
        QApplication.setPalette(palette)
        c.tools_toggle.click()
        QApplication.processEvents()
        assert c.tabs.currentIndex() == 1
        c.advanced.click()
        QApplication.processEvents()
        button = next(b for b in c.manual_scroll.widget().findChildren(QPushButton)
                      if b.text() == "Check my setup")
        c.manual_scroll.ensureWidgetVisible(button, 0, 0)
        QApplication.processEvents()
        assert within(button, c.manual_scroll.viewport())
        assert within(c.tools_toggle, c.page_scroll.viewport())
        dock.grab().save(str(root / "Advanced.png"))
        c.tools_toggle.click()
        QApplication.processEvents()
        assert c.tabs.currentIndex() == 0
        a.connection.setChecked(True)
        QApplication.processEvents()
        a.provider.setCurrentText("Manual")
        QApplication.processEvents()
        c.assistant_scroll.ensureWidgetVisible(a.existing_ai, 0, 0)
        QApplication.processEvents()
        assert within(a.existing_ai, c.assistant_scroll.viewport())
        dock.grab().save(str(root / "AI-setup.png"))
        a.connection.setChecked(False)
        dock.workspace_tabs.setCurrentIndex(1)
        QApplication.processEvents()
        assert dock.model_scroll.widget() is dock.model_content
        splitter = dock.explorer_splitter
        dock.open_studio()
        dock.close_studio()
        assert splitter.parent() is dock.model_content
        dock.workspace_tabs.setCurrentIndex(0)
        QApplication.processEvents()
        assert c.request.text() == "Could you connect boreholes for this area?"
        assert utils.unloadPlugin("groundsurf_geothermal")
        QTimer.singleShot(500, lambda: finish(True))
    except Exception:
        finish(False, traceback.format_exc())


QTimer.singleShot(800, start)

"""QGIS smoke test: Studio by GroundSurf launches an independent local process.

Run with PYTHONPATH=$PWD QT_QPA_PLATFORM=offscreen /usr/bin/python3
tools/smoke_desktop_launcher_v0414.py. No actual desktop Studio is started.
"""
import tempfile
import time
from pathlib import Path

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QMainWindow

from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin

app = QgsApplication([], False)
app.initQgis()


class Iface:
    def __init__(self):
        self.window = QMainWindow()

    def mainWindow(self):
        return self.window

    def addDockWidget(self, area, widget):
        self.window.addDockWidget(area, widget)

    def removeDockWidget(self, widget):
        self.window.removeDockWidget(widget)

    def addPluginToMenu(self, *args):
        pass

    def removePluginMenu(self, *args):
        pass

    def addToolBarIcon(self, *args):
        pass

    def removeToolBarIcon(self, *args):
        pass


iface = Iface()
plugin = GroundSurfGeothermalPlugin(iface)
plugin.initGui()
assert plugin.action.text() == "Studio by GroundSurf"
plugin.open_dock()
dock = plugin.dock
assert dock.windowTitle().startswith("Studio by GroundSurf")
with tempfile.TemporaryDirectory() as temporary:
    temp = Path(temporary)
    marker = temp / "args.txt"
    launcher = temp / "standalone-studio.sh"
    launcher.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > ' + repr(str(marker)) + '\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    # Replacing the settings object avoids changing user preferences.
    dock.settings = QSettings(str(temp / "settings.ini"), QSettings.IniFormat)
    dock.settings.setValue("desktop_studio_launcher", str(launcher))
    dock.path = str(temp / "demo model.gpkg")
    dock.launch_desktop_studio()
    for _ in range(40):
        if marker.exists():
            break
        time.sleep(0.05)
        app.processEvents()
    assert marker.exists(), "The separate desktop process was not started."
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "--project", str(temp / "demo model.gpkg")
    ]

plugin.unload()
iface.window.close()
QgsProject.instance().clear()
print("PASS: Studio by GroundSurf QGIS action and independent launcher")

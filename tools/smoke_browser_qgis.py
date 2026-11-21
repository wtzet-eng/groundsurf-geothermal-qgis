"""Verify QGIS button opens a loopback browser studio and unload shuts it down."""
import urllib.error
import urllib.request
from unittest.mock import patch
from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QMainWindow

from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin
q=QgsApplication([],False)
q.initQgis()
class Iface:
    def __init__(self):self.window=QMainWindow()
    def mainWindow(self):return self.window
    def addPluginToMenu(self,*a):pass
    def removePluginMenu(self,*a):pass
    def addToolBarIcon(self,*a):pass
    def removeToolBarIcon(self,*a):pass
    def addDockWidget(self,area,widget):self.window.addDockWidget(area,widget)
    def removeDockWidget(self,widget):self.window.removeDockWidget(widget)
i=Iface()
plugin=GroundSurfGeothermalPlugin(i)
plugin.initGui()
plugin.open_dock()
dock=plugin.dock
try:
    captured=[]
    def capture(url):
        captured.append(url.toString())
        return True
    with patch.object(QDesktopServices,'openUrl',side_effect=capture):
        dock.open_browser_studio()
    assert len(captured)==1
    target=captured[0]
    assert target.startswith('http://127.0.0.1:'),target
    with urllib.request.urlopen(target,timeout=5) as response:
        assert response.status==200
        assert b'GroundSurf Studio' in response.read()
    assert dock._browser_studio is not None
    print('QGIS_BROWSER_BUTTON_PASS',target.split('/')[2])
finally:
    url=dock._browser_studio.url if dock._browser_studio else None
    plugin.unload()
    if url:
        try:urllib.request.urlopen(url,timeout=2)
        except (urllib.error.URLError, ConnectionError,TimeoutError):print('QGIS_BROWSER_UNLOAD_SHUTDOWN_PASS')
        else:raise AssertionError('Local browser server persisted after plugin unload!')

"""QGIS 3 dock layout regression: no hidden 3D tab or explorer rows."""
import os
import tempfile
from pathlib import Path
from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QMainWindow
from groundsurf_geothermal import storage
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app=QgsApplication([], False)
app.initQgis()

class Iface:
    def __init__(self):
        self.window=QMainWindow()
    def mainWindow(self): return self.window
    def addDockWidget(self, area, dock):
        self.window.addDockWidget(area,dock)
    def removeDockWidget(self, dock): self.window.removeDockWidget(dock)
    def addPluginToMenu(self,*args): pass
    def removePluginMenu(self,*args): pass
    def addToolBarIcon(self,*args): pass
    def removeToolBarIcon(self,*args): pass

with tempfile.TemporaryDirectory() as folder:
    gpkg=Path(folder)/"layout.gpkg"
    storage.create_project(gpkg)
    iface=Iface()
    plugin=GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    dock=plugin.dock
    dock.load_project(str(gpkg))
    iface.window.resize(640,900)
    iface.window.show()
    dock.show()
    app.processEvents()
    assert dock.tabs.tabText(0)=="3D Models",[
        dock.tabs.tabText(i) for i in range(dock.tabs.count())
    ]
    assert dock.tabs.tabBar().tabRect(0).x()>=0
    assert dock.more_tools_button.isCheckable()
    dock.more_tools_button.setChecked(False)
    app.processEvents()
    assert not dock.extra_actions.isVisible()
    assert dock.tree.minimumHeight()>=120
    assert dock.explorer_splitter.sizes()[0]>=120,        dock.explorer_splitter.sizes()
    assert dock.models_shortcut.isVisible()
    dock.models_shortcut.click()
    assert dock.tabs.currentWidget()==dock.model_tab
    # Explorer headings now open their corresponding workspace too.
    for key, target in (
        ("Wells", dock.wells_table),
        ("Maps", dock.maps_table),
        ("Z Contacts · geological elevations", dock.contact_tab),
        ("Local XYZ · unlocated metre data", dock.local_xyz_tab),
        ("3D Models · preliminary", dock.model_tab),
    ):
        match = next(
            dock.tree.topLevelItem(i) for i in range(dock.tree.topLevelItemCount())
            if dock.tree.topLevelItem(i).text(0) == key
        )
        dock._tree_selected(match, 0)
        assert dock.tabs.currentWidget() == target, key
    # Simulate a saved-model entry: ensure the table shows a whole row.
    from qgis.PyQt.QtWidgets import QTableWidgetItem
    dock.model_table.insertRow(0)
    dock.model_table.setItem(0,0,QTableWidgetItem("Synthetic saved model"))
    app.processEvents()
    first_row=dock.model_table.visualItemRect(dock.model_table.item(0,0))
    assert first_row.top()>=0 and first_row.bottom()<=dock.model_table.viewport().height(), (
        first_row, dock.model_table.viewport().height()
    )
    assert dock.model_table.height()>=92
    preview=Path("/tmp/groundsurf_layout_v048.png")
    assert dock.grab().save(str(preview))
    print("LAYOUT:",dock.width(),dock.height(),
          "TREE",dock.tree.height(),
          "TAB",dock.tabs.height(),
          "BUTTONS",dock.models_shortcut.isVisible(),
          "SPLIT",dock.explorer_splitter.sizes(),
          "PREVIEW",preview)
    dock.more_tools_button.setChecked(True)
    app.processEvents()
    assert dock.extra_actions.isVisible()
    dock.more_tools_button.setChecked(False)
    app.processEvents()
    assert dock.tabs.currentWidget()==dock.model_tab
    assert dock.tree.height()>120
    plugin.unload()
    iface.window.close()
    QgsProject.instance().clear()
    print("PASS v0.4.8: first visible 3D Models tab, one-click shortcut, "
          "collapsible secondary tools and non-clipped explorer")

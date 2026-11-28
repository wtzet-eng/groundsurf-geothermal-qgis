"""Unified Studio QGIS acceptance, isolated profile only."""
import json
import os
import traceback
from pathlib import Path
from qgis import utils
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsRectangle
from qgis.PyQt.QtGui import QColor, QPalette
from unittest.mock import patch
from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtWidgets import QApplication, QDockWidget

root = Path(os.environ["GS_UNIFIED_QA"])


def finish(ok, error=""):
    (root / "result.json").write_text(json.dumps({"ok": ok, "error": error}))
    QgsProject.instance().setDirty(False)
    QApplication.instance().quit()


def start():
    try:
        from processing.core.Processing import Processing
        Processing.initialize()
        utils.updateAvailablePlugins()
        assert utils.loadPlugin("groundsurf_geothermal")
        assert utils.startPlugin("groundsurf_geothermal")
        plugin = utils.plugins["groundsurf_geothermal"]
        plugin.open_dock()
        dock = plugin.dock
        win = utils.iface.mainWindow()
        win.resize(1440, 900)
        win.resizeDocks([dock], [470], Qt.Horizontal)
        QTimer.singleShot(500, lambda: verify(plugin))
    except Exception:
        finish(False, traceback.format_exc())


def verify(plugin):
    try:
        dock, connect = plugin.dock, plugin.connect
        assert connect.registered and connect.embedded and connect.dock is dock
        assert len([d for d in utils.iface.mainWindow().findChildren(QDockWidget)
                    if d.objectName() in ("GroundSurfGeothermalDock", "GroundSurfConnectDock")]) == 1
        assert dock.workspace_tabs.currentIndex() == 0
        assert connect.request.isVisible() and 105 <= connect.request.height() <= 240
        assert QgsApplication.processingRegistry().algorithmById("groundsurf:discover_data")
        assert dock.windowTitle().startswith("GroundSurf Studio Connector")
        palette = QApplication.palette()
        for name, colour in (("Light", "#e6e6e3"), ("Dark", "#252525")):
            mode = QPalette(palette)
            mode.setColor(QPalette.Window, QColor(colour))
            QApplication.setPalette(mode)
            QApplication.processEvents()
            assert colour in connect.theme_widget.styleSheet()
            dock.grab().save(str(root / (name + ".png")))
        QApplication.setPalette(palette)
        connect.mode.setCurrentIndex(3)
        utils.iface.setActiveLayer(next(iter(QgsProject.instance().mapLayers().values())))
        connect.request.setPlainText("Find terrain and aerial imagery")
        connect.find_button.click()
        assert "Terrain and imagery sources" in connect.assistant_dock.log.toPlainText()
        from groundsurf_geothermal import storage, local_xyz
        path = root / "synthetic.gpkg"
        storage.create_project(path)
        local_xyz.store_batch(path, {
            "source_layer": "Synthetic geology",
            "source_layer_crs_claim": "EPSG:4326",
            "vertical_reference": "UNVERIFIED_SOURCE_Z",
            "records": [
                {"well_id": f"BH{i+1}", "unit_label": label,
                 "x_m": 600000.+i*130, "y_m": 5200000.+i*120,
                 "z_m": -45.-j*60, "source_feature_id": str(i*3+j)}
                for i in range(3)
                for j, label in enumerate(("Quaternary", "Cretaceous", "Base"))
            ],
        })
        dock.workspace_tabs.setCurrentIndex(1)
        dock.load_project(str(path))
        assert dock.local_table.rowCount() == 9
        splitter = dock.explorer_splitter
        dock.models_shortcut.click()
        assert dock.tabs.currentWidget() is dock.model_tab and dock._studio_window is None
        dock.grab().save(str(root / "Model.png"))
        dock.workspace_tabs.setCurrentIndex(0)
        assert connect.request.text() == "Find terrain and aerial imagery"
        dock.workspace_tabs.setCurrentIndex(1)
        assert dock.explorer_splitter is splitter and dock.local_table.rowCount() == 9
        # Existing optional detachable workspace still shares state.
        dock.open_studio()
        assert dock._studio_window is not None
        dock.close_studio()
        assert splitter.parent() is dock.model_content
        assert dock.local_table.rowCount() == 9
        # A second provider must not replace the registered one.
        from groundsurf_geothermal.connect.plugin import Connect
        duplicate = Connect(utils.iface)
        duplicate.embedded = True
        assert not duplicate.register()
        duplicate.unload()
        assert QgsApplication.processingRegistry().algorithmById("groundsurf:discover_data")
        dock.workspace_tabs.setCurrentIndex(0)
        area = QgsVectorLayer("Polygon?crs=EPSG:25833", "QA Berlin area", "memory")
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromRect(QgsRectangle(388600, 5818100, 388900, 5818400)))
        assert area.dataProvider().addFeatures([f])[0]
        area.updateExtents()
        QgsProject.instance().addMapLayer(area)
        area.selectAll()
        utils.iface.setActiveLayer(area)
        connect.mode.setCurrentIndex(2)
        connect.request.setPlainText("Find boreholes with geological profiles")
        with patch.object(connect.assistant_dock, "ask", return_value=True):
            connect.find_button.click()
        QTimer.singleShot(500, lambda: finish_search(plugin, 0))
    except Exception:
        finish(False, traceback.format_exc())


def finish_search(plugin, count):
    try:
        a = plugin.connect.assistant_dock
        if a.job:
            assert count < 60, "Live search timed out"
            QTimer.singleShot(500, lambda: finish_search(plugin, count + 1))
            return
        assert a.boreholes and a.boreholes["features"], a.log.toPlainText()
        assert a.open_profile.isVisible(), a.log.toPlainText()
        assert a.boreholes["groundsurf"]["source"] == "https://gdi.berlin.de/services/wfs/bohrdaten"
        assert all(f["properties"]["intervals_available"] is None for f in a.boreholes["features"])
        folder = root / "transfer"
        folder.mkdir()
        with patch.object(plugin.connect, "new_transfer_folder", return_value=folder), \
             patch.object(plugin.connect, "open_studio_folder", return_value=True) as launch:
            a.transfer_boreholes()
            assert launch.call_args.kwargs["profile_evidence"] is True
        assert (folder / "boreholes.geojson").is_file()
        plugin.dock.grab().save(str(root / "Berlin.png"))
        (root / "live-count.txt").write_text(str(len(a.boreholes["features"])))
        assert utils.unloadPlugin("groundsurf_geothermal")
        assert not QgsApplication.processingRegistry().providerById("groundsurf")
        QTimer.singleShot(500, lambda: finish(True))
    except Exception:
        finish(False, traceback.format_exc())


QTimer.singleShot(800, start)

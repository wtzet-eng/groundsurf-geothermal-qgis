"""Live local AI workflow proposal in disposable QGIS profile."""
import json
import os
import traceback
from pathlib import Path
from unittest.mock import patch
from qgis import utils
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication

root = Path(os.environ["GS_AI_QA"])


def finish(ok, error=""):
    (root / "result.json").write_text(json.dumps({"ok": ok, "error": error}))
    QgsProject.instance().setDirty(False)
    QApplication.instance().quit()


def wait_for(a, next_step, count=0):
    try:
        if a.job is not None:
            assert count < 120, "Job timeout"
            QTimer.singleShot(500, lambda: wait_for(a, next_step, count + 1))
            return
        next_step()
    except Exception:
        finish(False, traceback.format_exc())


def start():
    try:
        from processing.core.Processing import Processing
        Processing.initialize()
        utils.updateAvailablePlugins()
        assert utils.loadPlugin("groundsurf_geothermal")
        assert utils.startPlugin("groundsurf_geothermal")
        plugin = utils.plugins["groundsurf_geothermal"]
        plugin.open_dock()
        a = plugin.connect.assistant_dock
        assert a.ai_plan.isVisible()
        assert "optional setup" in a.ai_plan.text()
        a.ai_plan.click()
        assert a.connection_panel.isVisible()
        wait_for(a, lambda: connect_local(a, plugin))
    except Exception:
        finish(False, traceback.format_exc())


def connect_local(a, plugin):
    # Simulate user approval only; discovery and inference are real.
    approval = patch.object(a, "ask", return_value=True)
    approval.start()
    review = patch.object(a, "review_inference", return_value=True)
    review.start()
    a._qa_review = review
    a.existing_ai.click()
    wait_for(a, lambda: propose(a, plugin, approval))


def propose(a, plugin, approval):
    assert a.provider.currentText() == "llama.cpp", a.log.toPlainText()
    assert a.ai_plan.text() == "Ask AI"
    assert not a.connection_panel.isVisible()
    plugin.connect.mode.setCurrentIndex(3)
    utils.iface.setActiveLayer(next(iter(QgsProject.instance().mapLayers().values())))
    a.prompt.setPlainText("Find terrain and aerial imagery for the selected area. "
                          "Prepare a landscape transfer, validate it and open Studio.")
    # Do not share project context for this test.
    a.share.setChecked(False)
    a.ai_plan.click()
    wait_for(a, lambda: verified(a, plugin, approval))


def verified(a, plugin, approval):
    approval.stop()
    a._qa_review.stop()
    assert a.steps == ["define_area", "discover_data", "acquire_landscape",
                       "validate_transfer_package", "open_studio"], a.log.toPlainText()
    assert a.execute.isVisible() and not a.running and plugin.connect.task is None
    plugin.dock.grab().save(str(root / "AI-ready.png"))
    (root / "plan.json").write_text(json.dumps(a.steps))
    a.disable_ai()
    assert "optional setup" in a.ai_plan.text()
    assert utils.unloadPlugin("groundsurf_geothermal")
    QTimer.singleShot(500, lambda: finish(True))


QTimer.singleShot(800, start)

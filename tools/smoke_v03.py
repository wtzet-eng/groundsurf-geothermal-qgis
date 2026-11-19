"""QGIS 3.34 offscreen: real storage, section rendering and feedback links."""
import tempfile
from pathlib import Path
from qgis.core import (
    QgsApplication, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
)
from qgis.PyQt.QtWidgets import QMainWindow
from groundsurf_geothermal import db, sections, section_geo, storage
from groundsurf_geothermal.plugin import GroundSurfGeothermalPlugin
from groundsurf_geothermal.section_canvas import SectionCanvas
from groundsurf_geothermal.section_ui import SectionWindow

app=QgsApplication([],False)
app.initQgis()


class Iface:
    def __init__(self):
        self.window=QMainWindow()
        self.selected_layer=None
        self._canvas=None
    def mainWindow(self): return self.window
    def addDockWidget(self,area,dock): self.window.addDockWidget(area,dock)
    def removeDockWidget(self,dock): self.window.removeDockWidget(dock)
    def addPluginToMenu(self,*args): pass
    def removePluginMenu(self,*args): pass
    def addToolBarIcon(self,*args): pass
    def removeToolBarIcon(self,*args): pass
    def activeLayer(self): return self.selected_layer
    def mapCanvas(self):
        if self._canvas is None:
            from qgis.gui import QgsMapCanvas
            self._canvas=QgsMapCanvas()
        return self._canvas


with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/"synthetic.gpkg"
    storage.create_project(path)
    assert sections.has_schema(path)
    layer=storage.open_wells(str(path))
    examples=Path(__file__).resolve().parent.parent/"examples"
    wells=db.parse_well_csv((examples/"sample_wells.csv").read_text())
    storage.add_wells(layer,wells)
    for code,name in (("Q","Sand"),("C","Clay"),("B","Sandstone")):
        db.add_formation(path,code,name)
    db.import_intervals_csv(
        path,layer,(examples/"sample_intervals.csv").read_text())
    db.add_formation_top(
        path,layer,"SIM-01","C",18,"observed",source="synthetic")
    line,width=section_geo.auto_vertices_from_wells(layer)
    sid=sections.create_section(path,"Synthetic auto-section",line,width)
    scene=section_geo.build_scene(path,layer,sid)
    assert scene["well_count"]==3
    assert scene["elevation_mode"] and scene["warnings"]
    sections.save_pick(
        path,sid,"SIM-02","C",15,220,"user interpretation")
    scene=section_geo.build_scene(path,layer,sid)
    assert next(w for w in scene["well_rows"] if w["well_id"]=="SIM-02")[
        "contacts"]["C"]["depth"]==15
    assert db.formation_tops(path,"SIM-02")==[]

    # A mixed vertical datum must suppress elevation correlations.
    feature=next(f for f in layer.getFeatures() if f["well_id"]=="SIM-03")
    field=layer.fields().indexFromName("vertical_datum")
    original=str(feature["vertical_datum"])
    assert layer.startEditing()
    assert layer.changeAttributeValue(feature.id(),field,"DIFFERENT-DATUM")
    assert layer.commitChanges()
    layer.reload()
    mixed=section_geo.build_scene(path,layer,sid)
    assert not mixed["elevation_mode"], "Unsafe datum mix permitted!"
    assert any("disabled" in message for message in mixed["warnings"])
    assert layer.startEditing()
    assert layer.changeAttributeValue(feature.id(),field,original)
    assert layer.commitChanges()
    layer.reload()
    assert section_geo.build_scene(path,layer,sid)["elevation_mode"]

    selected_line=QgsVectorLayer(
        "LineString?crs=EPSG:4326","Line","memory")
    feature=QgsFeature()
    feature.setGeometry(QgsGeometry.fromPolylineXY(
        [QgsPointXY(13.345,52.493),QgsPointXY(13.375,52.507)]
    ))
    assert selected_line.dataProvider().addFeatures([feature])[0]
    selected_line.updateExtents()
    selected_line.selectByIds([f.id() for f in selected_line.getFeatures()])
    iface=Iface()
    iface.selected_layer=selected_line
    vertices=section_geo.selected_line_vertices(iface)
    assert len(vertices)==2
    sid2=sections.create_section(path,"Selected line",vertices,1000)
    assert section_geo.build_scene(path,layer,sid2)["well_count"]>0

    canvas=SectionCanvas(scene,dark=True)
    img=Path(directory)/"crosssection.png"
    canvas.save_png(str(img))
    assert img.stat().st_size>10000
    dialog=SectionWindow(path,layer,sid,True,parent=iface.window)
    assert dialog.scene["well_count"]==3
    dialog.close()
    plugin=GroundSurfGeothermalPlugin(iface)
    plugin.initGui()
    plugin.open_dock()
    dock=plugin.dock
    dock.load_project(path)
    assert dock.section_combo.count()==2
    assert dock.tabs.tabText(dock.help_tab_index)=="Help"
    dock.open_help()
    assert dock.tabs.currentIndex()==dock.help_tab_index
    # Verify transient section-trace map rendering works and tracks its layer.
    dock.show_section_line()
    assert dock._preview_line_ids
    layer_id = next(iter(dock._preview_line_ids.values()))
    assert QgsProject.instance().mapLayer(layer_id) is not None
    plugin.unload()
    assert QgsProject.instance().mapLayer(layer_id) is None
    QgsProject.instance().clear()
    print("PASS: QGIS cross-sections, edits, selection, PNG, Help/Feedback UI")

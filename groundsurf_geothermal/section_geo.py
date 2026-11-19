"""QGIS coordinate transformations and evidence assembly for cross-sections."""
import math

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsVectorLayer, QgsWkbTypes,
)
from qgis.PyQt.QtGui import QColor
from . import db, sections, section_math


def _finite_field(feature, name):
    value = feature[name]
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def _field_text(feature, name):
    value = feature[name]
    return "" if value is None or str(value) == "NULL" else str(value).strip()


def metric_projection(vertices):
    lon = sum(p[0] for p in vertices) / len(vertices)
    lat = sum(p[1] for p in vertices) / len(vertices)
    if lat > 83 or lat < -79:
        raise ValueError("High-latitude/polar sections require a different projection")
    if (max(p[0] for p in vertices) - min(p[0] for p in vertices) > 5 or
            max(p[1] for p in vertices) - min(p[1] for p in vertices) > 2):
        raise ValueError("Section spans too many UTM zones; use shorter sections")
    zone = min(60, max(1, int((lon+180)/6)+1))
    code = (32600 if lat >= 0 else 32700) + zone
    return QgsCoordinateReferenceSystem.fromEpsgId(code)


def _transformer(a, b):
    return QgsCoordinateTransform(a, b, QgsProject.instance())


def _project_vertices(vertices, to_crs):
    crs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    converter = _transformer(crs84, to_crs)
    return [converter.transform(lon, lat) for lon, lat in vertices]


def _wgs84_vertices(xy, from_crs):
    crs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    converter = _transformer(from_crs, crs84)
    return [[converter.transform(x, y).x(),
             converter.transform(x, y).y()] for x, y in xy]


def selected_line_vertices(iface):
    active = iface.activeLayer()
    if not isinstance(active, QgsVectorLayer):
        raise ValueError("Select a vector line layer in QGIS")
    if active.selectedFeatureCount() != 1:
        raise ValueError("Select exactly one line feature in the QGIS map")
    feat = active.selectedFeatures()[0]
    geometry = feat.geometry()
    if geometry.isEmpty() or QgsWkbTypes.geometryType(geometry.wkbType()) != QgsWkbTypes.GeometryType.LineGeometry:
        raise ValueError("Selected geometry is not a line")
    if geometry.isMultipart():
        parts = geometry.asMultiPolyline()
        if len(parts) != 1:
            raise ValueError("Select a single-part line, not a multipart line")
        points = parts[0]
    else:
        points = geometry.asPolyline()
    if len(points) < 2:
        raise ValueError("Line must have at least two distinct vertices")
    transformer = _transformer(active.crs(), QgsCoordinateReferenceSystem("EPSG:4326"))
    vertices = []
    for point in points:
        gp = transformer.transform(point)
        vertices.append([gp.x(),gp.y()])
    return sections._validate_line(vertices)


def auto_vertices_from_wells(well_layer):
    wells = [f for f in well_layer.getFeatures() if f.hasGeometry()]
    if len(wells) < 2:
        raise ValueError("Import at least two wells to generate an automatic section")
    vertices = [[f.geometry().asPoint().x(), f.geometry().asPoint().y()] for f in wells]
    utm = metric_projection(vertices)
    coords = _project_vertices(vertices, utm)
    line, default_buffer = section_math.auto_line([(p.x(),p.y()) for p in coords])
    vertices_wgs84 = _wgs84_vertices(line, utm)
    return vertices_wgs84, default_buffer


def build_scene(project_path, well_layer, section_id):
    section = sections.get_section(project_path, section_id)
    utm = metric_projection(section["vertices"])
    line = [(p.x(), p.y()) for p in _project_vertices(section["vertices"], utm)]
    line_total = section_math.chainage_for_point(line[0], line)[2]
    if line_total > 100000:
        raise ValueError("Maximum section length 100 km for initial local-UTM prototype")
    # Source well points are stored in EPSG:4326 in GroundSurf's GeoPackage.
    transformer = _transformer(well_layer.crs(), utm)
    names = {item[0]: item[1] for item in db.formations(project_path)}
    pick_map = {(well, code): (depth, note)
                for well, code, depth, note in sections.list_picks(project_path, section_id)}
    well_rows = []
    for feature in well_layer.getFeatures():
        if not feature.hasGeometry():
            continue
        transformed = transformer.transform(feature.geometry().asPoint())
        chainage, offset, _ = section_math.chainage_for_point(
            (transformed.x(), transformed.y()), line
        )
        if offset > section["buffer_m"]:
            continue
        well_id = _field_text(feature, "well_id")
        records = db.intervals(project_path, well_id)
        tops = db.formation_tops(project_path, well_id)
        total = _finite_field(feature, "total_depth_m")
        if total is None:
            total = max([r[3] for r in records] + [0])
        if total <= 0:
            continue
        ground = _finite_field(feature, "ground_elev_m")
        datum = _field_text(feature, "vertical_datum")
        contact_map = {}
        for rec in records:
            if rec[1] and rec[1] not in contact_map:
                contact_map[rec[1]] = {"depth":rec[2], "basis":"log-derived"}
        for rec in tops:
            code = rec[1]
            # Explicit source tops override log-derived picks.
            contact_map[code] = {"depth":rec[2], "basis":rec[3]}
        original_contacts = dict(contact_map)
        for (pick_well, code), (depth, note) in pick_map.items():
            if pick_well == well_id:
                contact_map[code] = {"depth":depth, "basis":"section-interpreted"}
        well_rows.append({
            "well_id":well_id, "name":_field_text(feature,"name"),
            "chainage_m":chainage, "offset_m":offset, "ground_elev_m":ground,
            "datum":datum, "total_depth_m":total,
            "intervals":[{"formation":r[1], "top":r[2], "base":r[3],
                          "description":r[4]} for r in records],
            "contacts":contact_map,"original_contacts":original_contacts,
        })
    well_rows.sort(key=lambda w:(w["chainage_m"],w["well_id"]))
    if not well_rows:
        raise ValueError("No logged wells intersect the selected section corridor")
    if len(well_rows) > 80:
        raise ValueError("More than 80 wells intersect; narrow the corridor for readability")
    # Absolute-elevation correlations require the SAME known vertical datum for all wells.
    datums = {w["datum"] for w in well_rows}
    elevation_mode = (len(datums) == 1 and "" not in datums and
                      all(w["ground_elev_m"] is not None for w in well_rows))
    datum = next(iter(datums)) if elevation_mode else ""
    for w in well_rows:
        w["top_axis"] = w["ground_elev_m"] if elevation_mode else 0.0
        w["bottom_axis"] = w["top_axis"] - w["total_depth_m"] if elevation_mode else w["total_depth_m"]
    if elevation_mode:
        axis_max = max(w["top_axis"] for w in well_rows)
        axis_min = min(w["bottom_axis"] for w in well_rows)
    else:
        axis_max = max(w["bottom_axis"] for w in well_rows)
        axis_min = 0.
    return {
        "name":section["name"],"id":section_id,
        "length_m":line_total, "buffer_m":section["buffer_m"],
        "utm":utm.authid(), "datum":datum,
        "elevation_mode":elevation_mode,
        "axis_min":axis_min, "axis_max":axis_max,
        "well_count":len(well_rows),
        "well_rows":well_rows,"formations":names,
        "warnings":[
            ("SYNTHETIC/UNDEFINED datum — not survey-grade" if
             datum.upper().startswith("DEMO") else "")
        ] if elevation_mode else [
            "Missing or inconsistent vertical datums: depth-only display.",
            "Contact correlations disabled until datum consistency is resolved.",
        ],
    }

def section_map_layer(section):
    """Create a transient map line for a saved section (not a simulated contact)."""
    layer = QgsVectorLayer("LineString?crs=EPSG:4326",
                           "GroundSurf · " + section["name"], "memory")
    if not layer.isValid():
        raise RuntimeError("Cannot create QGIS map preview layer")
    feat = QgsFeature(layer.fields())
    feat.setGeometry(QgsGeometry.fromPolylineXY([
        QgsPointXY(float(lon),float(lat)) for lon, lat in section["vertices"]
    ]))
    if not layer.dataProvider().addFeatures([feat])[0]:
        raise RuntimeError("Cannot draw geological section line")
    layer.updateExtents()
    layer.renderer().symbol().setColor(QColor("#6cbe88"))
    layer.renderer().symbol().setWidth(0.9)
    return layer

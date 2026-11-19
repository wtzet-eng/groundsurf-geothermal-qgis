"""Read PointZ/XYZ stratigraphic contacts from an already-open QGIS layer.

The input is a set of geological elevation observations, not a depth log.
Repeated borehole IDs become one well, with all raw Z contacts preserved.
Selecting a source CRS changes only the import transform, not the QGIS layer.
"""
from collections import Counter, OrderedDict
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
    QgsWkbTypes,
)

from . import db, elevation_contacts, grouped_import, qgis_import, storage

MAX_CONTACTS = 50000


def detect_fields(names):
    names = list(names)
    def find(*aliases):
        normalized = {qgis_import.normalised_field(n): n for n in names}
        for alias in aliases:
            match = normalized.get(qgis_import.normalised_field(alias))
            if match:
                return match
        return None
    return {
        "well_id": find("ID", "well_id", "BH_ID", "Borehole_ID",
                        "Hole_ID", "WellName"),
        "formation_code": find("Strata", "Formation", "Lithology", "Unit",
                               "formation_code", "geological_unit"),
        "elevation_m": find("Z", "Elevation_Z", "Contact_Z", "Elevation",
                            "Z_m", "Elevation_m", "Top_elevation_m"),
        "x": find("X", "Easting", "X_m", "Easting_m", "coord_x"),
        "y": find("Y", "Northing", "Y_m", "Northing_m", "coord_y"),
    }


def _source_point(feature):
    geom = feature.geometry()
    if geom.isEmpty():
        raise ValueError("Point geometry is empty")
    if geom.isMultipart():
        points = geom.asMultiPoint()
        if len(points) != 1:
            raise ValueError("Multipoint geometry must contain one point")
        point = points[0]
    else:
        point = geom.asPoint()
    return (float(point.x()), float(point.y()))


def prepare_contacts(layer, fields, source_crs=None, use_xy_fields=False,
                     use_geometry_z=False, vertical_datum="UNSPECIFIED",
                     selected_only=False):
    """Preflight all rows; never infer drilled depths or ground elevation."""
    if not qgis_import.is_point_layer(layer):
        raise ValueError("Select an open QGIS point layer with borehole contacts")
    crs = source_crs or layer.crs()
    if crs is None or not crs.isValid():
        raise ValueError("Select a valid horizontal source CRS")
    known = {field.name() for field in layer.fields()}
    fields = fields or {}
    required = ("well_id", "formation_code")
    for key in required:
        if not fields.get(key):
            raise ValueError(f"Map a source attribute to {key}")
    if not use_geometry_z and not fields.get("elevation_m"):
        raise ValueError("Map a Z elevation attribute or choose PointZ geometry")
    if use_xy_fields and not (fields.get("x") and fields.get("y")):
        raise ValueError("Map both X and Y coordinate columns")
    for field in fields.values():
        if field and field not in known:
            raise ValueError(f"Mapped attribute {field!r} is missing")
    datum = str(vertical_datum).strip() or "UNSPECIFIED"
    if len(datum) > 100:
        raise ValueError("Vertical datum label is too long")
    if selected_only and layer.selectedFeatureCount() == 0:
        raise ValueError("No selected QGIS features")
    features = layer.getSelectedFeatures() if selected_only else layer.getFeatures()
    transform = QgsCoordinateTransform(
        crs, QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance(),
    )
    wells = OrderedDict()
    contact_rows = []
    by_unit = Counter()
    repeated = {}
    for n, feature in enumerate(features, 1):
        if n > MAX_CONTACTS:
            raise ValueError(f"Maximum {MAX_CONTACTS} contact features per import")
        try:
            well_id = db._text(
                qgis_import._source_value(feature, fields["well_id"]),
                "Borehole ID", True, 80
            )
            code = db._text(
                qgis_import._source_value(feature, fields["formation_code"]),
                "Stratigraphic unit", True, 80
            )
            source_x, source_y = _source_point(feature)
            if use_xy_fields:
                source_x = db._num(
                    qgis_import._source_value(feature, fields["x"]),
                    "X coordinate", True
                )
                source_y = db._num(
                    qgis_import._source_value(feature, fields["y"]),
                    "Y coordinate", True
                )
            lon, lat = qgis_import.checked_wgs84_point(
                feature, layer, transform, source_crs=crs,
                xy_override=(source_x, source_y) if use_xy_fields else None,
            )
            if use_geometry_z:
                if not QgsWkbTypes.hasZ(feature.geometry().wkbType()):
                    raise ValueError("Feature has no PointZ elevation")
                # QGIS 3 asPoint() returns QgsPointXY and discards Z;
                # vertexAt(0) preserves QgsPointZ elevation.
                z = feature.geometry().vertexAt(0).z()
            else:
                z = qgis_import._source_value(feature, fields["elevation_m"])
            elevation = db._num(z, "Contact Z elevation", True)
            contact = {
                "well_id": well_id, "formation_code": code,
                "elevation_m": elevation, "vertical_datum": datum,
                "source_layer": layer.name(),
                "source_crs": crs.authid() or crs.description(),
                "source_x": source_x, "source_y": source_y,
                "source_feature_id": str(feature.id()),
            }
            new_well = db.validate_well({
                "well_id": well_id, "name": well_id,
                "longitude": lon, "latitude": lat,
                "source": f"QGIS contact layer: {layer.name()}",
                "notes": "Raw geological Z contacts; NOT interval depths",
                "vertical_datum": datum,
            })
            if well_id in wells:
                previous = wells[well_id]
                distance = grouped_import._distance_metres(
                    (previous["longitude"], previous["latitude"]), (lon, lat)
                )
                if distance > grouped_import.POSITION_TOLERANCE_M:
                    raise ValueError(
                        f"Borehole {well_id} has contact coordinates "
                        f"{distance:.1f} m apart (>5 m)."
                    )
            else:
                wells[well_id] = new_well
                if len(wells) > db.MAX_CSV_WELLS:
                    raise ValueError("More than 10,000 unique boreholes")
            key = (well_id, code)
            repeated.setdefault(key, []).append(elevation)
            by_unit[code] += 1
            contact_rows.append(contact)
        except Exception as exc:
            raise ValueError(f"QGIS feature {feature.id()}: {exc}") from exc
    if not contact_rows:
        raise ValueError("No contact records to import")
    ambiguous = [
        (well, code, heights) for (well, code), heights in sorted(repeated.items())
        if len(heights) > 1 and max(heights)-min(heights) > 0.001
    ]
    warnings = []
    for well, code, heights in ambiguous[:12]:
        warnings.append(
            f"{well}: {code} is recorded at multiple Z elevations "
            f"({', '.join(format(x,'.2f') for x in sorted(heights))}). "
            "Both records will be preserved; resolve the unit identity "
            "before using this horizon in 3D."
        )
    if datum.upper() in ("UNSPECIFIED", "UNKNOWN", "UNVERIFIED"):
        warnings.append(
            "Vertical reference is unspecified. Raw Z elevations are saved "
            "as observations, NOT surveyed heights or drilling depths."
        )
    all_codes = set(by_unit)
    for well in wells:
        codes = {c for wid,c in repeated if wid == well}
        missing = all_codes-codes
        if missing:
            warnings.append(
                f"{well}: missing relative to dataset: "
                + ", ".join(sorted(missing))
                + ". Nothing will be fabricated."
            )
    warnings.append(
        "No drilled depth or ground elevation has been inferred from Z. "
        "Source unit labels are preserved, not independently verified."
    )
    return {
        "wells": list(wells.values()),
        "contacts": contact_rows,
        "well_count": len(wells),
        "contact_count": len(contact_rows),
        "source_rows": len(contact_rows),
        "counts": {
            well: sum(1 for entry in contact_rows if entry["well_id"] == well)
            for well in wells
        },
        "units": dict(by_unit),
        "ambiguous": ambiguous,
        "warnings": warnings,
        "vertical_datum": datum,
        "source_crs": crs.authid() or crs.description(),
    }


def import_contacts(path, well_layer, staged):
    """Copy wells and contacts with compensation on later SQLite failure."""
    new_ids = {row["well_id"] for row in staged["wells"]}
    if new_ids & {str(f["well_id"]) for f in well_layer.getFeatures()}:
        raise ValueError(
            "One or more imported well IDs already exist in GroundSurf. "
            "No replacement or merge is performed; choose an empty project "
            "or import an appropriate subset."
        )
    wrote_wells = False
    try:
        storage.add_wells(well_layer, staged["wells"])
        wrote_wells = True
        elevation_contacts.store_contacts(path, staged["contacts"])
    except Exception as exc:
        if wrote_wells:
            try:
                feature_ids = [
                    f.id() for f in well_layer.getFeatures()
                    if str(f["well_id"]) in new_ids
                ]
                if not well_layer.startEditing():
                    raise RuntimeError("Cannot open well GeoPackage for rollback")
                if not well_layer.deleteFeatures(feature_ids):
                    raise RuntimeError("Cannot remove the newly imported wells")
                if not well_layer.commitChanges():
                    errors = "; ".join(well_layer.commitErrors())
                    well_layer.rollBack()
                    raise RuntimeError(errors)
                well_layer.reload()
            except Exception as rollback:
                raise RuntimeError(
                    "Contact import failed and recovery FAILED: "
                    f"{rollback}. Check the project before retrying."
                ) from exc
        raise
    return (staged["well_count"], staged["contact_count"])

"""Group repeated QGIS point records into individual GroundSurf well logs.

Each unique Well ID becomes exactly one well. Optional from/to interval
columns yield geological intervals attached to that same well. Original
QGIS features are read only. All inputs are validated before any copy.
"""
import math
from collections import OrderedDict
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
)
from . import db, qgis_import, storage

MAX_ROWS = 50000
POSITION_TOLERANCE_M = 5.0
INTERVAL_FIELDS = (
    ("formation_code", "Formation / lithology / unit code"),
    ("top_depth_m", "Interval top / from depth (m)"),
    ("base_depth_m", "Interval base / to depth (m)"),
    ("description", "Lithology or interval description"),
)
INTERVAL_ALIASES = {
    "formation_code": (
        "formation_code", "formation", "formation_name", "unit_code",
        "geological_unit", "geol_unit", "lithology", "litho", "soil_type",
        "material", "stratum", "strata",
    ),
    "top_depth_m": (
        "top_depth_m", "top_depth", "depth_top", "from_depth",
        "depth_from", "from_m", "top_m", "top", "start_depth",
        "interval_top", "depth_start",
    ),
    "base_depth_m": (
        "base_depth_m", "base_depth", "depth_base", "to_depth",
        "depth_to", "to_m", "base_m", "bottom", "bottom_depth",
        "end_depth", "depth_end", "interval_base",
    ),
    "description": (
        "lithology_description", "litho_description", "stratum_description",
        "interval_description", "geology_description", "soil_description",
        "description", "remarks", "comments",
    ),
}


def guess_interval_mapping(field_names):
    found = {}
    for target, _ in INTERVAL_FIELDS:
        matches = {
            qgis_import.normalised_field(alias): priority
            for priority, alias in enumerate(INTERVAL_ALIASES[target])
        }
        available = [
            (matches[qgis_import.normalised_field(name)], index, name)
            for index, name in enumerate(field_names)
            if qgis_import.normalised_field(name) in matches
        ]
        found[target] = min(available)[2] if available else None
    return found


def default_group_well_mapping(fields):
    """Avoid silently interpreting a general 'Depth' column as drilled TD."""
    mapping = qgis_import.guess_mapping(fields)
    if mapping.get("total_depth_m") and qgis_import.normalised_field(
        mapping["total_depth_m"]
    ) in ("depth", "depthm"):
        mapping["total_depth_m"] = None
    return mapping


def _distance_metres(a, b):
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    angle = (
        math.sin((lat2-lat1)/2)**2
        + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    )
    return 2*6371008.8*math.asin(min(1., math.sqrt(max(0., angle))))


def _consistent(original, incoming, attribute, well_id):
    if incoming is None or incoming == "":
        return original
    if original is None or original == "":
        return incoming
    if attribute in ("ground_elev_m", "total_depth_m"):
        if abs(float(original)-float(incoming)) > 0.001:
            raise ValueError(
                f"Well {well_id}: conflicting {attribute} values "
                f"({original} vs {incoming}). Check source attributes."
            )
    elif str(original) != str(incoming):
        raise ValueError(
            f"Well {well_id}: conflicting {attribute} values "
            f"({original!r} vs {incoming!r})"
        )
    return original


def prepare_groups(layer, mapping, interval_mapping=None, selected_only=False,
                   source_crs=None):
    """Return staged wells, intervals and data-validation summary.

    One source row normally represents one lithological interval; multiple
    source rows for the same ID become a *single* well. Repeated positions
    must agree within 5 metres. Any inconsistent row rejects the entire batch.
    """
    if not qgis_import.is_point_layer(layer):
        raise ValueError("Grouped borehole import requires a QGIS point layer")
    if not (source_crs or layer.crs()).isValid():
        raise ValueError("Select a valid source CRS for the well layer")
    known = {field.name() for field in layer.fields()}
    mapping = mapping or {}
    interval_mapping = interval_mapping or {}
    if not mapping.get("well_id"):
        raise ValueError("Map an attribute containing the borehole ID")
    for name in list(mapping.values()) + list(interval_mapping.values()):
        if name and name not in known:
            raise ValueError(f"Field {name!r} is not in the selected layer")
    top = interval_mapping.get("top_depth_m")
    base = interval_mapping.get("base_depth_m")
    formation = interval_mapping.get("formation_code")
    has_intervals = bool(top or base or formation)
    if has_intervals and not (top and base and formation):
        raise ValueError(
            "To import intervals, map Formation, Top depth and Base depth. "
            "Otherwise leave all three unmapped to import only grouped wells."
        )
    if selected_only and layer.selectedFeatureCount() == 0:
        raise ValueError("No selected features exist in this QGIS layer")
    features = layer.getSelectedFeatures() if selected_only else layer.getFeatures()
    transform = QgsCoordinateTransform(
        source_crs or layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance(),
    )
    unique = OrderedDict()
    intervals = []
    counts = {}
    raw_count = 0
    for feature in features:
        raw_count += 1
        if raw_count > MAX_ROWS:
            raise ValueError(f"Grouped import supports at most {MAX_ROWS} rows")
        label = f"QGIS feature {feature.id()}"
        try:
            raw = {
                key: qgis_import._source_value(feature, mapping.get(key))
                for key, _ in qgis_import.FIELD_OPTIONS
            }
            well_id = raw["well_id"]
            if not well_id:
                raise ValueError("Missing borehole ID")
            coords = qgis_import.checked_wgs84_point(
                feature, layer, transform, source_crs=source_crs
            )
            has_name = bool(raw["name"])
            raw["name"] = raw["name"] or well_id
            raw["longitude"], raw["latitude"] = coords
            raw["source"] = raw["source"] or f"QGIS layer: {layer.name()}"
            candidate = db.validate_well(raw)
            if well_id not in unique:
                unique[well_id] = candidate
                counts[well_id] = 0
                if len(unique) > db.MAX_CSV_WELLS:
                    raise ValueError("More than 10,000 distinct wells")
            else:
                existing = unique[well_id]
                prior = (existing["longitude"], existing["latitude"])
                separation = _distance_metres(prior, coords)
                if separation > POSITION_TOLERANCE_M:
                    raise ValueError(
                        f"Well {well_id}: repeated positions differ by "
                        f"{separation:.1f} m (limit {POSITION_TOLERANCE_M:g} m)"
                    )
                # Do not accidentally choose an unknown well name over a
                # later supplied specific name.
                if existing["name"] == well_id and has_name:
                    existing["name"] = candidate["name"]
                elif has_name and existing["name"] != candidate["name"]:
                    _consistent(existing["name"], candidate["name"], "name", well_id)
                for attribute in (
                    "total_depth_m", "ground_elev_m", "vertical_datum",
                ):
                    existing[attribute] = _consistent(
                        existing[attribute], candidate[attribute], attribute, well_id
                    )
            if has_intervals:
                data = {
                    key: qgis_import._source_value(
                        feature, interval_mapping.get(key)
                    )
                    for key, _ in INTERVAL_FIELDS
                }
                code = db._text(
                    data["formation_code"], "Formation or lithology", True, 80
                )
                depth_top = db._num(data["top_depth_m"], "Top depth", True, 0)
                depth_base = db._num(data["base_depth_m"], "Base depth", True, 0)
                if depth_base <= depth_top:
                    raise ValueError("Interval base must be deeper than top")
                description = db._text(
                    data["description"], "Interval description", limit=2000
                )
                intervals.append(
                    (well_id, code, depth_top, depth_base, description)
                )
                counts[well_id] += 1
        except Exception as exc:
            raise ValueError(f"{label}: {exc}") from exc
    if not unique:
        raise ValueError("No valid borehole records in source layer")
    if len(intervals) > db.MAX_CSV_INTERVALS:
        raise ValueError("More than 50,000 interval records")
    by_well = {}
    for well, code, start, end, description in intervals:
        by_well.setdefault(well, []).append((start, end, code))
    for well, records in by_well.items():
        ordered = sorted(records)
        for (_a, earlier_end, _c), (later_start, _b, _d) in zip(
            ordered, ordered[1:]
        ):
            if later_start < earlier_end - 1e-6:
                raise ValueError(
                    f"Well {well}: overlapping intervals at "
                    f"{later_start:g}–{earlier_end:g} m; correct before import"
                )
        total = unique[well]["total_depth_m"]
        if total is not None and ordered[-1][1] > total + 1e-6:
            raise ValueError(
                f"Well {well}: an interval extends below total depth {total:g} m"
            )
    missing_total = sum(
        r["total_depth_m"] is None for r in unique.values()
    )
    warnings = []
    if missing_total:
        warnings.append(
            f"{missing_total} well(s) lack drilled total depth; "
            "the deepest interval is NOT assumed to be total well depth."
        )
    if intervals:
        warnings.append(
            "Formation/unit labels come from your source attributes; "
            "review their geological meaning before 3D modelling."
        )
    return {
        "wells": list(unique.values()),
        "intervals": intervals,
        "counts": counts,
        "source_rows": raw_count,
        "interval_count": len(intervals),
        "well_count": len(unique),
        "warnings": warnings,
    }


def import_groups(project_path, groundsurf_wells, staged):
    """Commit fully validated groups, with compensation if SQL writing fails."""
    rows = staged["wells"]
    interval_rows = staged["intervals"]
    ids = {row["well_id"] for row in rows}
    existing = {str(f["well_id"]) for f in groundsurf_wells.getFeatures()}
    overlap = existing & ids
    if overlap:
        raise ValueError(
            "Well ID(s) already exist in GroundSurf: "
            + ", ".join(sorted(overlap)[:10])
            + ". Duplicate wells are not automatically merged."
        )
    codes = sorted({r[1] for r in interval_rows})
    existing_formations = {r[0] for r in db.formations(project_path)}
    # All geological intervals have passed overlap and depth checks above.
    added = False
    try:
        storage.add_wells(groundsurf_wells, rows)
        added = True
        if interval_rows:
            with db.connect(project_path) as con:
                for code in codes:
                    if code not in existing_formations:
                        con.execute(
                            """INSERT INTO gs_formations(code,name,lithology,notes)
                               VALUES(?,?,?,?)""",
                            (code, code, "",
                             "Imported source unit label; verify stratigraphy."),
                        )
                con.executemany(
                    """INSERT INTO gs_intervals
                       (well_id,formation_code,top_depth_m,base_depth_m,description)
                       VALUES(?,?,?,?,?)""",
                    interval_rows,
                )
    except Exception as exc:
        if added:
            # Explicit compensation if the GeoPackage metadata transaction
            # fails *after* the separate QGIS well-layer edit transaction.
            try:
                to_delete = [
                    f.id() for f in groundsurf_wells.getFeatures()
                    if str(f["well_id"]) in ids
                ]
                if not groundsurf_wells.startEditing():
                    raise RuntimeError("Cannot reopen well layer for rollback")
                if not groundsurf_wells.deleteFeatures(to_delete):
                    raise RuntimeError("Cannot remove imported wells")
                if not groundsurf_wells.commitChanges():
                    errors = "; ".join(groundsurf_wells.commitErrors())
                    groundsurf_wells.rollBack()
                    raise RuntimeError(errors)
                groundsurf_wells.reload()
            except Exception as rollback_exc:
                raise RuntimeError(
                    "Import encountered an error and automatic well rollback "
                    f"FAILED: {rollback_exc}. Check newly imported wells before "
                    "repeating the operation."
                ) from exc
        raise
    return staged["well_count"], staged["interval_count"]

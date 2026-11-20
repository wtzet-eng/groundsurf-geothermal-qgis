"""Unreferenced, local metre XYZ contacts: preserved without fabricated WGS84.

This store is independent of gs_wells, gs_elevation_contacts and geographical
QGIS layers. One import batch defines one shared source coordinate frame.
3D geometry can be centred for ParaView while original source XYZ survive.
No transform to longitude/latitude is attempted or implied.
"""
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import math
import sqlite3

from qgis.core import QgsWkbTypes

from . import db, elevation_import, model_core, qgis_import

VERSION = "1"
BASIS = "LOCAL_XYZ_METRES_UNGEOREFERENCED"


def has_schema(path):
    if not db.valid_project(path):
        return False
    try:
        with db.connect(path) as con:
            meta = con.execute(
                "SELECT value FROM gs_meta WHERE key='local_xyz_schema_version'"
            ).fetchone()
            names = {
                row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('gs_local_xyz_batches','gs_local_xyz_contacts')"
                )
            }
        return bool(
            meta and meta[0] == VERSION and names
            == {"gs_local_xyz_batches", "gs_local_xyz_contacts"}
        )
    except sqlite3.Error:
        return False


def ensure_schema(path, backup_existing=True):
    if not db.valid_project(path):
        raise ValueError("Open a GroundSurf Geothermal project first")
    if has_schema(path):
        return None
    path = Path(path).resolve()
    backup = None
    if backup_existing:
        label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(
            path.name + ".backup-prelocalxyz-" + label
        )
        with db.connect(path) as source, sqlite3.connect(backup) as output:
            source.backup(output)
    with db.connect(path) as con:
        old = con.execute(
            "SELECT value FROM gs_meta WHERE key='local_xyz_schema_version'"
        ).fetchone()
        if old:
            raise ValueError("Unknown local XYZ schema version; no changes made")
        con.execute(
            """CREATE TABLE gs_local_xyz_batches(
                   id INTEGER PRIMARY KEY,
                   label TEXT NOT NULL,
                   source_layer TEXT NOT NULL,
                   imported_utc TEXT NOT NULL,
                   coordinate_basis TEXT NOT NULL,
                   vertical_reference TEXT NOT NULL,
                   horizontal_units TEXT NOT NULL
                      CHECK(horizontal_units='m'),
                   vertical_units TEXT NOT NULL CHECK(vertical_units='m'),
                   source_layer_claimed_crs TEXT NOT NULL)"""
        )
        con.execute(
            """CREATE TABLE gs_local_xyz_contacts(
                   id INTEGER PRIMARY KEY,
                   batch_id INTEGER NOT NULL,
                   well_id TEXT NOT NULL,
                   unit_label TEXT NOT NULL,
                   x_m REAL NOT NULL,
                   y_m REAL NOT NULL,
                   z_m REAL NOT NULL,
                   source_feature_id TEXT NOT NULL,
                   FOREIGN KEY(batch_id) REFERENCES gs_local_xyz_batches(id)
                     ON DELETE CASCADE)"""
        )
        con.execute(
            "CREATE INDEX gs_local_xyz_batch_well "
            "ON gs_local_xyz_contacts(batch_id,well_id)"
        )
        con.execute(
            "INSERT INTO gs_meta(key,value) VALUES('local_xyz_schema_version',?)",
            (VERSION,)
        )
    return str(backup) if backup else None


def list_batches(path):
    if not has_schema(path):
        return []
    with db.connect(path) as con:
        return con.execute(
            """SELECT b.id,b.label,b.source_layer,b.imported_utc,
                      b.coordinate_basis,b.vertical_reference,
                      b.source_layer_claimed_crs,
                      count(c.id),count(DISTINCT c.well_id)
               FROM gs_local_xyz_batches b LEFT JOIN gs_local_xyz_contacts c
               ON c.batch_id=b.id GROUP BY b.id ORDER BY b.id DESC"""
        ).fetchall()


def list_contacts(path, batch_id=None):
    if not has_schema(path):
        return []
    query = (
        "SELECT batch_id,well_id,unit_label,x_m,y_m,z_m,source_feature_id "
        "FROM gs_local_xyz_contacts"
    )
    if batch_id is None:
        with db.connect(path) as con:
            return con.execute(
                query + " ORDER BY batch_id,well_id,z_m DESC,id"
            ).fetchall()
    with db.connect(path) as con:
        return con.execute(
            query + " WHERE batch_id=? ORDER BY well_id,z_m DESC,id",
            (int(batch_id),)
        ).fetchall()


def prepare_local(layer, mapping, use_xy_fields=False, use_geometry_z=False,
                  selected_only=False, vertical_reference="UNVERIFIED_SOURCE_Z"):
    """Read local XY and Z in declared metre units without CRS operation.

    This is only for *unlocated* local engineering models. No layer
    CRS, project CRS, WGS84 geometry or georeferenced well is generated.
    """
    if not qgis_import.is_point_layer(layer):
        raise ValueError("Choose a QGIS point layer for local XYZ import")
    names = {field.name() for field in layer.fields()}
    for label in ("well_id", "formation_code"):
        if not mapping.get(label):
            raise ValueError(f"Map a field for {label}")
    if use_xy_fields and not (mapping.get("x") and mapping.get("y")):
        raise ValueError("Map both X and Y coordinate fields")
    if not use_geometry_z and not mapping.get("elevation_m"):
        raise ValueError("Map a Z contact field or select PointZ geometry")
    for field in mapping.values():
        if field and field not in names:
            raise ValueError(f"Mapped field {field!r} is missing")
    if selected_only and layer.selectedFeatureCount() == 0:
        raise ValueError("There are no selected features")
    features = layer.getSelectedFeatures() if selected_only else layer.getFeatures()
    records = []
    coordinates = OrderedDict()
    grouped = defaultdict(lambda: defaultdict(list))
    for index, feature in enumerate(features):
        if index >= 50000:
            raise ValueError("Maximum 50,000 local XYZ source records")
        try:
            well_id = db._text(
                qgis_import._source_value(feature, mapping["well_id"]),
                "Borehole ID", True, 80
            )
            code = db._text(
                qgis_import._source_value(feature, mapping["formation_code"]),
                "Stratigraphic unit", True, 80
            )
            if use_xy_fields:
                x = db._num(
                    qgis_import._source_value(feature, mapping["x"]),
                    "Local X (m)", True
                )
                y = db._num(
                    qgis_import._source_value(feature, mapping["y"]),
                    "Local Y (m)", True
                )
            else:
                x, y = elevation_import._source_point(feature)
                x = db._num(x, "Local X (m)", True)
                y = db._num(y, "Local Y (m)", True)
            if use_geometry_z:
                geom = feature.geometry()
                if not QgsWkbTypes.hasZ(geom.wkbType()):
                    raise ValueError("PointZ geometry is required to use geometry Z")
                z = geom.vertexAt(0).z()
            else:
                z = qgis_import._source_value(
                    feature, mapping["elevation_m"]
                )
            z = db._num(z, "Local contact Z (m)", True)
            if well_id in coordinates:
                original = coordinates[well_id]
                if math.hypot(x-original[0], y-original[1]) > 5.0:
                    raise ValueError(
                        f"{well_id}: repeated local XY positions disagree "
                        "by more than 5 metres"
                    )
            else:
                coordinates[well_id] = (x,y)
                if len(coordinates) > 10000:
                    raise ValueError("Maximum 10,000 distinct boreholes")
            grouped[well_id][code].append(z)
            records.append({
                "well_id":well_id, "unit_label":code, "x_m":x,
                "y_m":y, "z_m":z, "source_feature_id":str(feature.id()),
            })
        except Exception as exc:
            raise ValueError(f"QGIS feature {feature.id()}: {exc}") from exc
    if not records:
        raise ValueError("No local XYZ records selected")
    reference = db._text(
        vertical_reference or "UNVERIFIED_SOURCE_Z",
        "Vertical Z reference", True, 100
    )
    ambiguous = [
        (well,code,values)
        for well,groups in grouped.items() for code,values in groups.items()
        if len(values)>1 and max(values)-min(values)>0.001
    ]
    warnings = [
        "LOCAL XYZ ONLY: data are NOT georeferenced and will NOT appear "
        "in the world-map Wells layer.",
        "Units are ASSUMED metres as explicitly confirmed by the user. "
        "GroundSurf cannot verify the units or original CRS.",
        "These are source Z contact elevations, not drilling depths.",
        "ParaView scene can be viewed in a relative local Cartesian frame "
        "without EPSG. This is NOT a geographic coordinate correction.",
    ]
    if reference.upper() in ("UNVERIFIED_SOURCE_Z","UNSPECIFIED","UNKNOWN"):
        warnings.append(
            "Vertical reference is UNVERIFIED: model may be visualised "
            "but cannot be related to surveyed ground or national datum."
        )
    for well,code,zs in ambiguous[:12]:
        warnings.append(
            f"{well}: {code} has multiple heights "
            + ", ".join(f"{v:g}" for v in sorted(zs))
            + ". Both saved; well excluded from this horizon in conceptual model."
        )
    return {
        "records": records,
        "well_count":len(coordinates),
        "contact_count":len(records),
        "counts": {well:sum(len(zs) for zs in units.values())
                   for well,units in grouped.items()},
        "ambiguous":ambiguous,
        "warnings":warnings,
        "source_layer":layer.name(),
        "source_layer_crs_claim":layer.crs().authid() or "UNDEFINED",
        "vertical_reference":reference,
    }


def store_batch(path, prepared):
    if not has_schema(path):
        raise ValueError("Local XYZ database is unavailable")
    batch_label = db._text(
        prepared["source_layer"], "Source layer name", True, 200
    )
    records = prepared["records"]
    with db.connect(path) as con:
        cur = con.execute(
            """INSERT INTO gs_local_xyz_batches
               (label,source_layer,imported_utc,coordinate_basis,
                vertical_reference,horizontal_units,vertical_units,
                source_layer_claimed_crs)
               VALUES(?,?,?,?,?,?,?,?)""",
            (batch_label, batch_label,db.utcnow(),BASIS,
             prepared["vertical_reference"],"m","m",
             prepared["source_layer_crs_claim"])
        )
        batch_id = cur.lastrowid
        con.executemany(
            """INSERT INTO gs_local_xyz_contacts
               (batch_id,well_id,unit_label,x_m,y_m,z_m,source_feature_id)
               VALUES(?,?,?,?,?,?,?)""",
            [(
                batch_id, r["well_id"], r["unit_label"], r["x_m"],
                r["y_m"],r["z_m"],r["source_feature_id"],
            ) for r in records]
        )
    return batch_id


def model_inputs(path, batch_id):
    """Construct local-metre surface samples without any global map CRS.

    Identical wells with conflicting repeated unit Z are omitted from
    conceptual interpolation; all records remain stored for inspection.
    """
    batches = [b for b in list_batches(path) if b[0] == int(batch_id)]
    if not batches:
        raise ValueError("Local XYZ dataset not found in this GroundSurf project")
    meta = batches[0]
    rows = list_contacts(path, batch_id)
    by_well = defaultdict(lambda: defaultdict(list))
    locations = {}
    for _batch,well,code,x,y,z,_feature in rows:
        by_well[well][code].append(float(z))
        locations.setdefault(well,(float(x),float(y)))
    excluded=[]
    candidates={}
    for well,groups in by_well.items():
        bad=[code for code,values in groups.items()
             if max(values)-min(values) > 0.001]
        if bad:
            excluded.append(f"{well}: repeated/conflicting "
                            + ", ".join(sorted(bad)))
            continue
        candidates[well] = {
            code: values[0] for code, values in groups.items()
        }
    if len(candidates) < 3:
        raise ValueError(
            "At least three boreholes with unambiguous Z contacts "
            "are required for a conceptual local model. "
            + "; ".join(excluded[:10])
        )
    common=set(next(iter(candidates.values())))
    for codes in candidates.values():
        common.intersection_update(codes)
    if len(common)<2:
        raise ValueError(
            "Cannot interpolate without at least two geological units "
            "common to all unambiguous wells."
        )
    mean_z={
        code:sum(sample[code] for sample in candidates.values())/len(candidates)
        for code in common
    }
    horizons=sorted(common,key=lambda code:(-mean_z[code],code))
    for well,values in candidates.items():
        for high,low in zip(horizons,horizons[1:]):
            if values[high] - values[low] < model_core.MIN_THICKNESS_M:
                raise ValueError(
                    f"Well {well} has inverted or touching "
                    f"strata: {high}/{low}. Resolve geological labels first."
                )
    # Translation only: preserves relative XY distances and source Z.
    points=[locations[well] for well in candidates]
    x0=(min(x for x,y in points)+max(x for x,y in points))/2
    y0=(min(y for x,y in points)+max(y for x,y in points))/2
    samples=[]; provenance=[]
    for well,values in candidates.items():
        x,y=locations[well]
        samples.append({
            "well_id":well,"x":x-x0,"y":y-y0,
            "elevations":{h:values[h] for h in horizons},
        })
        provenance.append({
            "well_id":well, "raw_local_x_m":x, "raw_local_y_m":y,
            "local_x_m":x-x0,"local_y_m":y-y0,
            "vertical_reference":meta[5],
            "unit_contact_heights_m":values,
            "input_batch_id":int(batch_id),
            "source_layer":meta[2],
            "geographically_located":False,
        })
    missing = sorted(
        set().union(*(set(group) for group in candidates.values()))-set(horizons)
    )
    warnings=[
        "NO GEOGRAPHIC CRS: output is LOCAL Cartesian XYZ in metres, "
        "not EPSG:4326 and not accurately locatable on a world map.",
        "X/Y are shifted by a recorded common origin; distances between "
        "points are unchanged by the translation.",
        "Source X/Y are ASSUMED to be metrically meaningful. If the source "
        "was Web Mercator, map-scale distortion may make ground distances "
        "different from coordinate differences.",
        "Z is preserved as supplied and is a contact height, not depth. "
        "Vertical reference is user-provided/possibly unverified.",
        "No groundwater or thermal simulation, faults or geotechnical validation.",
    ]
    if missing:
        warnings.append(
            "Noncommon horizons omitted from mesh: "+", ".join(missing)
        )
    if excluded:
        warnings.append(
            "Ambiguous boreholes omitted from mesh: "+"; ".join(excluded[:20])
        )
    return {
        "samples":samples, "horizons":horizons, "datum":meta[5],
        "epsg":BASIS,
        "local_origin_m":{"x":x0,"y":y0,"z":0.0},
        "provenance":provenance,
        "warnings":warnings,
        "excluded_wells":excluded,
        "batch_id":int(batch_id),
        "source_type":"LOCAL_UNGEOREFERENCED_XYZ",
    }

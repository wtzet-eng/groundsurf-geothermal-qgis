"""Local GroundSurf project schema v2 and validated subsurface observations.

No QGIS imports. QGIS creates the GeoPackage itself. We add app-specific
SQLite tables; existing geometry tables are never modified by this module.
"""
import csv
import io
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "2"
MAX_CSV_WELLS = 10000
MAX_CSV_INTERVALS = 50000
REQUIRED = ("well_id", "name", "latitude", "longitude")
OBSERVATION_UNITS = {
    "water_depth_bgl_m": "m",
    "water_head_elev_m": "m",
    "temperature_c": "degC",
    "pressure_kpa": "kPa",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=4000")
    return con


TABLES = (
    """CREATE TABLE IF NOT EXISTS gs_meta
        (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS gs_formations
        (code TEXT PRIMARY KEY, name TEXT NOT NULL, lithology TEXT, notes TEXT)""",
    """CREATE TABLE IF NOT EXISTS gs_intervals
        (id INTEGER PRIMARY KEY, well_id TEXT NOT NULL, formation_code TEXT,
        top_depth_m REAL NOT NULL, base_depth_m REAL NOT NULL, description TEXT,
        CHECK (top_depth_m >= 0 AND base_depth_m > top_depth_m))""",
    """CREATE INDEX IF NOT EXISTS gs_interval_well ON gs_intervals(well_id)""",
    """CREATE TABLE IF NOT EXISTS gs_observations
        (id INTEGER PRIMARY KEY, well_id TEXT NOT NULL,
        observed_utc TEXT NOT NULL, kind TEXT NOT NULL, value REAL NOT NULL,
        unit TEXT NOT NULL, depth_bgl_m REAL, reference_datum TEXT,
        source TEXT, notes TEXT,
        CHECK(depth_bgl_m IS NULL OR depth_bgl_m >= 0))""",
    """CREATE INDEX IF NOT EXISTS gs_obs_well ON gs_observations(well_id)""",
    """CREATE TABLE IF NOT EXISTS gs_map_layers
        (id INTEGER PRIMARY KEY, path TEXT NOT NULL, layer_name TEXT NOT NULL,
         kind TEXT NOT NULL, added_utc TEXT NOT NULL, relative_path TEXT,
         source_layer TEXT NOT NULL DEFAULT '',
         UNIQUE(path, source_layer))""",
    """CREATE TABLE IF NOT EXISTS gs_maps
        (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
        layer_name TEXT NOT NULL, kind TEXT NOT NULL, added_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS gs_formation_tops
        (id INTEGER PRIMARY KEY, well_id TEXT NOT NULL, formation_code TEXT NOT NULL,
        depth_bgl_m REAL NOT NULL CHECK(depth_bgl_m >= 0),
        interpretation TEXT NOT NULL CHECK(interpretation IN ('observed','interpreted')),
        source TEXT, notes TEXT,
        FOREIGN KEY(formation_code) REFERENCES gs_formations(code))""",
    """CREATE INDEX IF NOT EXISTS gs_top_well ON gs_formation_tops(well_id)""",
)


def _columns(con, table):
    return {row[1] for row in con.execute("PRAGMA table_info(" + table + ")")}


def _ensure_tables(con):
    for statement in TABLES:
        con.execute(statement)
    existing = _columns(con, "gs_maps")
    if "relative_path" not in existing:
        con.execute("ALTER TABLE gs_maps ADD COLUMN relative_path TEXT")
    if "source_layer" not in existing:
        con.execute("ALTER TABLE gs_maps ADD COLUMN source_layer TEXT")
    # Preserve legacy map records while enabling multiple sublayers from one GPKG.
    con.execute(
        """INSERT OR IGNORE INTO gs_map_layers
           (path,layer_name,kind,added_utc,relative_path,source_layer)
           SELECT path,layer_name,kind,added_utc,relative_path,
                  COALESCE(source_layer,'') FROM gs_maps"""
    )


def bootstrap(path):
    """Initialise only new project schema, do not silently upgrade v1."""
    with connect(path) as con:
        existing = None
        try:
            existing = con.execute(
                "SELECT value FROM gs_meta WHERE key='schema_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            pass
        if existing and existing[0] != SCHEMA_VERSION:
            raise ValueError("Existing schema requires explicit migration")
        _ensure_tables(con)
        con.execute("INSERT OR IGNORE INTO gs_meta VALUES ('schema_version',?)",
                    (SCHEMA_VERSION,))
        con.execute("INSERT OR IGNORE INTO gs_meta VALUES ('created_utc',?)",
                    (utcnow(),))


def project_version(path):
    if not Path(path).is_file():
        return None
    try:
        with connect(path) as con:
            well = con.execute(
                "SELECT 1 FROM gpkg_contents WHERE table_name='gs_wells'"
            ).fetchone()
            row = con.execute(
                "SELECT value FROM gs_meta WHERE key='schema_version'"
            ).fetchone()
        if not well or row is None:
            return None
        return str(row[0])
    except sqlite3.Error:
        return None


def valid_project(path):
    return project_version(path) == SCHEMA_VERSION


def migrate_v1(path):
    """Backup a verified v1 database, then upgrade in place to schema v2."""
    if project_version(path) != "1":
        raise ValueError("Migration accepts only a GroundSurf v1 GeoPackage")
    source = Path(path).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = source.with_name(source.name + ".backup-v1-" + stamp)
    if backup.exists():
        raise FileExistsError("Backup already exists: " + str(backup))
    with connect(path) as con, sqlite3.connect(str(backup)) as backup_con:
        con.backup(backup_con)
    try:
        with connect(path) as con:
            _ensure_tables(con)
            # v1 used absolute source paths; relative variants help relocation.
            for map_id, map_path in con.execute("SELECT id,path FROM gs_maps").fetchall():
                relative = os.path.relpath(map_path, start=str(source.parent))
                con.execute("UPDATE gs_maps SET relative_path=? WHERE id=?",
                            (relative, map_id))
                con.execute("UPDATE gs_map_layers SET relative_path=? WHERE path=?",
                            (relative, map_path))
            con.execute("UPDATE gs_meta SET value=? WHERE key='schema_version'",
                        (SCHEMA_VERSION,))
        if not valid_project(path):
            raise RuntimeError("Migration verification failed")
    except Exception:
        # Do not delete backup. Provide explicit path for manual recovery.
        raise RuntimeError("Migration failed. Original backup: " + str(backup)) from None
    return str(backup)


def _num(raw, label, required=False, min_value=None, max_value=None):
    if raw is None or str(raw).strip() == "":
        if required:
            raise ValueError(label + " is required")
        return None
    try:
        number = float(raw)
    except (ValueError, TypeError):
        raise ValueError(label + " must be numeric") from None
    if not math.isfinite(number):
        raise ValueError(label + " must be finite")
    if min_value is not None and number < min_value:
        raise ValueError(label + f" must be >= {min_value}")
    if max_value is not None and number > max_value:
        raise ValueError(label + f" must be <= {max_value}")
    return number


def _text(raw, label, required=False, limit=500):
    value = str(raw or "").strip()
    if required and not value:
        raise ValueError(label + " is required")
    if len(value) > limit:
        raise ValueError(label + f" exceeds {limit} characters")
    return value


def validate_well(record):
    return {
        "well_id": _text(record.get("well_id"), "well_id", True, 80),
        "name": _text(record.get("name"), "name", True, 200),
        "latitude": _num(record.get("latitude"), "latitude", True, -90, 90),
        "longitude": _num(record.get("longitude"), "longitude", True, -180, 180),
        "total_depth_m": _num(record.get("total_depth_m"), "total_depth_m",
                              min_value=0),
        "ground_elev_m": _num(record.get("ground_elev_m"), "ground_elev_m"),
        "vertical_datum": _text(record.get("vertical_datum"), "datum", limit=100),
        "source": _text(record.get("source"), "source", limit=500),
        "notes": _text(record.get("notes"), "notes", limit=2000),
    }


def parse_well_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV requires a header row")
    missing = set(REQUIRED) - set(reader.fieldnames)
    if missing:
        raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
    result, seen = [], set()
    for line, record in enumerate(reader, 2):
        if len(result) >= MAX_CSV_WELLS:
            raise ValueError("Import limit: 10,000 wells")
        try:
            well = validate_well(record)
        except ValueError as exc:
            raise ValueError(f"CSV row {line}: {exc}") from exc
        if well["well_id"] in seen:
            raise ValueError(f"CSV row {line}: repeated well_id")
        result.append(well)
        seen.add(well["well_id"])
    if not result:
        raise ValueError("CSV does not contain any wells")
    return result


def _well_depth(well_layer, well_id):
    # The caller owns the well layer, which is the canonical GeoPackage table.
    for feature in well_layer.getFeatures():
        if str(feature["well_id"]) == well_id:
            raw = feature["total_depth_m"]
            return None if raw is None or str(raw) == "NULL" else float(raw)
    raise ValueError("Unknown well_id: " + well_id)


def formations(path):
    with connect(path) as con:
        return con.execute(
            "SELECT code,name,lithology,notes FROM gs_formations ORDER BY code"
        ).fetchall()


def add_formation(path, code, name, lithology="", notes=""):
    code = _text(code, "Formation code", True, 80)
    name = _text(name, "Formation name", True, 200)
    lithology = _text(lithology, "Lithology")
    notes = _text(notes, "Notes", limit=2000)
    with connect(path) as con:
        con.execute(
            "INSERT INTO gs_formations(code,name,lithology,notes) VALUES(?,?,?,?)",
            (code, name, lithology, notes),
        )


def _check_formation(con, code):
    if code and not con.execute(
        "SELECT 1 FROM gs_formations WHERE code=?", (code,)
    ).fetchone():
        raise ValueError("Define formation before using code: " + code)


def intervals(path, well_id):
    with connect(path) as con:
        return con.execute(
            """SELECT id,formation_code,top_depth_m,base_depth_m,description
               FROM gs_intervals WHERE well_id=? ORDER BY top_depth_m,id""",
            (well_id,),
        ).fetchall()


def add_interval(path, well_layer, well_id, formation_code,
                 top_depth_m, base_depth_m, description=""):
    well_id = _text(well_id, "Well ID", True, 80)
    code = _text(formation_code, "Formation code", True, 80)
    top = _num(top_depth_m, "Top depth", True, 0)
    base = _num(base_depth_m, "Base depth", True, 0)
    if base <= top:
        raise ValueError("Base depth must be deeper than top depth")
    total = _well_depth(well_layer, well_id)
    if total is not None and base > total:
        raise ValueError("Interval extends below recorded total well depth")
    with connect(path) as con:
        _check_formation(con, code)
        # Partial overlapping intervals are ambiguous for a single lithological log.
        clash = con.execute(
            """SELECT id FROM gs_intervals WHERE well_id=?
               AND top_depth_m<? AND base_depth_m>? LIMIT 1""",
            (well_id, base, top),
        ).fetchone()
        if clash:
            raise ValueError("Interval overlaps an existing interval")
        con.execute(
            """INSERT INTO gs_intervals
               (well_id,formation_code,top_depth_m,base_depth_m,description)
               VALUES(?,?,?,?,?)""",
            (well_id, code, top, base, _text(description, "Description", limit=2000)),
        )


def formation_tops(path, well_id):
    with connect(path) as con:
        return con.execute(
            """SELECT id, formation_code, depth_bgl_m, interpretation, source
               FROM gs_formation_tops WHERE well_id=? ORDER BY depth_bgl_m,id""",
            (well_id,),
        ).fetchall()


def add_formation_top(path, well_layer, well_id, formation_code,
                      depth_bgl_m, interpretation="interpreted", source="", notes=""):
    well_id = _text(well_id, "Well ID", True, 80)
    code = _text(formation_code, "Formation code", True, 80)
    depth = _num(depth_bgl_m, "Depth", True, 0)
    total = _well_depth(well_layer, well_id)
    if total is not None and depth > total:
        raise ValueError("Formation top is deeper than total well depth")
    if interpretation not in ("observed", "interpreted"):
        raise ValueError("Interpretation must be observed or interpreted")
    with connect(path) as con:
        _check_formation(con, code)
        con.execute(
            """INSERT INTO gs_formation_tops
               (well_id,formation_code,depth_bgl_m,interpretation,source,notes)
               VALUES(?,?,?,?,?,?)""",
            (well_id, code, depth, interpretation,
             _text(source, "Source"), _text(notes, "Notes", limit=2000)),
        )


def observations(path, well_id):
    with connect(path) as con:
        return con.execute(
            """SELECT id,observed_utc,kind,value,unit,depth_bgl_m,
                      reference_datum,source,notes
               FROM gs_observations WHERE well_id=? ORDER BY observed_utc DESC,id DESC""",
            (well_id,),
        ).fetchall()


def add_observation(path, well_layer, well_id, observed_utc,
                    kind, value, depth_bgl_m="", reference_datum="",
                    source="", notes=""):
    well_id = _text(well_id, "Well ID", True, 80)
    total = _well_depth(well_layer, well_id)
    kind = _text(kind, "Observation kind", True, 100)
    if kind not in OBSERVATION_UNITS:
        raise ValueError("Unsupported observation kind: " + kind)
    moment = str(observed_utc).strip()
    try:
        parsed = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Observation time must be ISO 8601 with UTC offset") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Observation time must include a UTC offset")
    moment = parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    number = _num(value, "Observed value", True)
    depth = _num(depth_bgl_m, "Measurement depth", min_value=0)
    if total is not None and depth is not None and depth > total:
        raise ValueError("Measurement depth exceeds total well depth")
    if kind in ("temperature_c", "pressure_kpa") and depth is None:
        raise ValueError("Temperature and pressure measurements need a depth")
    if kind == "water_depth_bgl_m" and number < 0:
        raise ValueError("Water depth below ground cannot be negative")
    if kind == "pressure_kpa" and number < 0:
        raise ValueError("Pressure cannot be negative")
    datum = _text(reference_datum, "Reference datum", limit=200)
    if kind == "water_head_elev_m" and not datum:
        raise ValueError("Water-head elevation needs a vertical datum")
    if kind == "pressure_kpa" and datum not in ("absolute", "gauge"):
        raise ValueError("Pressure needs 'absolute' or 'gauge' as its basis")
    with connect(path) as con:
        con.execute(
            """INSERT INTO gs_observations
               (well_id,observed_utc,kind,value,unit,depth_bgl_m,
                reference_datum,source,notes)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (well_id, moment, kind, number, OBSERVATION_UNITS[kind], depth,
             datum, _text(source, "Source"), _text(notes, "Notes", limit=2000)),
        )


def delete_well_record(path, table, record_id, well_id):
    # Table names are not SQL parameters. Use fixed SQL literals per record type.
    arguments = (int(record_id), str(well_id))
    with connect(path) as con:
        if table == "interval":
            cursor = con.execute(
                "DELETE FROM gs_intervals WHERE id=? AND well_id=?", arguments
            )
        elif table == "top":
            cursor = con.execute(
                "DELETE FROM gs_formation_tops WHERE id=? AND well_id=?", arguments
            )
        elif table == "observation":
            cursor = con.execute(
                "DELETE FROM gs_observations WHERE id=? AND well_id=?", arguments
            )
        else:
            raise ValueError("Unrecognised record type")
        if cursor.rowcount != 1:
            raise ValueError("Record was not found for this well")


def maps(path):
    with connect(path) as con:
        return con.execute(
            """SELECT id,path,layer_name,kind,relative_path,source_layer
               FROM gs_map_layers ORDER BY id"""
        ).fetchall()


def resolve_map(project_path, row):
    """Prefer valid relative file reference, fall back to recorded absolute."""
    identifier, stored, name, kind, relative, source_layer = row
    root = Path(project_path).resolve().parent
    candidates = [root / relative] if relative else []
    candidates.append(Path(stored))
    target = next((p.resolve() for p in candidates if p.is_file()), None)
    return target, source_layer


def record_map(path, file_path, layer_name, kind, source_layer=None):
    abs_path = str(Path(file_path).resolve())
    rel = os.path.relpath(abs_path, start=str(Path(path).resolve().parent))
    with connect(path) as con:
        con.execute(
            """INSERT INTO gs_map_layers
               (path,layer_name,kind,added_utc,relative_path,source_layer)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(path,source_layer) DO UPDATE SET
                  layer_name=excluded.layer_name,
                  kind=excluded.kind, relative_path=excluded.relative_path,
                  source_layer=excluded.source_layer""",
            (abs_path, layer_name, kind, utcnow(), rel, source_layer or ""),
        )


def relink_map(path, record_id, new_file, source_layer=None):
    abs_path = str(Path(new_file).resolve())
    if not Path(abs_path).is_file():
        raise ValueError("Selected map source file does not exist")
    rel = os.path.relpath(abs_path, start=str(Path(path).resolve().parent))
    with connect(path) as con:
        cursor = con.execute(
            """UPDATE gs_map_layers SET path=?,relative_path=?,source_layer=?
               WHERE id=?""",
            (abs_path, rel, source_layer or "", int(record_id)),
        )
        if cursor.rowcount != 1:
            raise ValueError("Map record not found")


def import_intervals_csv(path, well_layer, text):
    """Validate all rows and import in a single atomic transaction.

    Header: well_id,formation_code,top_depth_m,base_depth_m,description.
    """
    reader = csv.DictReader(io.StringIO(text))
    required = {"well_id", "formation_code", "top_depth_m", "base_depth_m"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV needs well_id, formation_code, top_depth_m, base_depth_m")
    records = []
    depth_by_well = {}
    for line, row in enumerate(reader, start=2):
        if len(records) >= MAX_CSV_INTERVALS:
            raise ValueError("Import limit: 50,000 lithological intervals")
        try:
            well = _text(row.get("well_id"), "well_id", True, 80)
            code = _text(row.get("formation_code"), "formation code", True, 80)
            top = _num(row.get("top_depth_m"), "Top depth", True, 0)
            base = _num(row.get("base_depth_m"), "Base depth", True, 0)
            if base <= top:
                raise ValueError("Base must be deeper than top")
            if well not in depth_by_well:
                depth_by_well[well] = _well_depth(well_layer, well)
            total = depth_by_well[well]
            if total is not None and base > total:
                raise ValueError("Interval exceeds well total depth")
            description = _text(row.get("description"), "Description", limit=2000)
            records.append((well, code, top, base, description))
        except ValueError as exc:
            raise ValueError(f"CSV row {line}: {exc}") from exc
    if not records:
        raise ValueError("No lithological intervals found")
    with connect(path) as con:
        for line, (well, code, top, base, description) in enumerate(records, 2):
            try:
                _check_formation(con, code)
                conflict = con.execute(
                    """SELECT 1 FROM gs_intervals WHERE well_id=? AND
                       top_depth_m<? AND base_depth_m>? LIMIT 1""",
                    (well, base, top)
                ).fetchone()
                if conflict:
                    raise ValueError("Overlapping interval")
                con.execute(
                    """INSERT INTO gs_intervals
                       (well_id,formation_code,top_depth_m,base_depth_m,description)
                       VALUES(?,?,?,?,?)""",
                    (well, code, top, base, description)
                )
            except (ValueError, sqlite3.IntegrityError) as exc:
                raise ValueError(f"CSV row {line}: {exc}") from exc
    return len(records)

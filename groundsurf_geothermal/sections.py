"""Versioned, local section definitions and *separate* interpreted tie points.

The existing GeoPackage holds geometry and logs. Sections are stored as
WGS84 polyline vertices and use a separate schema version; source logs are
never edited when a section-specific interpretation is changed.
"""
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from . import db

SECTION_SCHEMA = "1"
MAX_VERTICES = 500


def _validate_line(vertices):
    if not isinstance(vertices, (list, tuple)) or not 2 <= len(vertices) <= MAX_VERTICES:
        raise ValueError("Section needs 2–500 vertices")
    result = []
    for vertex in vertices:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 2:
            raise ValueError("Section point must be [longitude,latitude]")
        lon, lat = vertex
        try:
            lon, lat = float(lon), float(lat)
        except (TypeError, ValueError):
            raise ValueError("Section coordinates must be numeric") from None
        if not all(math.isfinite(n) for n in (lon, lat)):
            raise ValueError("Section coordinates must be finite")
        if abs(lon) > 180 or abs(lat) > 90:
            raise ValueError("Section longitude/latitude outside WGS84 range")
        if result and result[-1] == [lon, lat]:
            raise ValueError("Section must not contain consecutive repeated vertices")
        result.append([lon, lat])
    return result


def has_schema(path):
    if not db.valid_project(path):
        return False
    try:
        with db.connect(path) as con:
            value = con.execute(
                "SELECT value FROM gs_meta WHERE key='section_schema_version'"
            ).fetchone()
            table = con.execute(
                "SELECT name FROM sqlite_master WHERE name='gs_section_picks'"
            ).fetchone()
        return bool(table and value and value[0] == SECTION_SCHEMA)
    except sqlite3.Error:
        return False


def ensure_schema(path, backup_existing=True):
    """Create an additive module schema; backup existing project beforehand."""
    if not db.valid_project(path):
        raise ValueError("Open a supported GroundSurf project before adding sections")
    if has_schema(path):
        return None
    path = Path(path).resolve()
    backup_path = None
    if backup_existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = path.with_name(path.name + ".backup-presections-" + stamp)
        with db.connect(path) as source, sqlite3.connect(backup_path) as dst:
            source.backup(dst)
    try:
        with db.connect(path) as con:
            current = con.execute(
                "SELECT value FROM gs_meta WHERE key='section_schema_version'"
            ).fetchone()
            if current:
                raise ValueError("Unknown section schema version; refusing conversion")
            con.execute(
                """CREATE TABLE IF NOT EXISTS gs_sections (
                   id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                   vertices_wgs84 TEXT NOT NULL,
                   buffer_m REAL NOT NULL CHECK(buffer_m > 0 AND buffer_m <= 100000),
                   created_utc TEXT NOT NULL)"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS gs_section_picks (
                   id INTEGER PRIMARY KEY,
                   section_id INTEGER NOT NULL REFERENCES gs_sections(id) ON DELETE CASCADE,
                   well_id TEXT NOT NULL,
                   formation_code TEXT NOT NULL REFERENCES gs_formations(code),
                   depth_bgl_m REAL NOT NULL CHECK(depth_bgl_m >= 0),
                   note TEXT NOT NULL DEFAULT '',
                   UNIQUE(section_id,well_id,formation_code))"""
            )
            con.execute(
                "INSERT INTO gs_meta(key,value) VALUES('section_schema_version',?)",
                (SECTION_SCHEMA,),
            )
        if not has_schema(path):
            raise RuntimeError("Section schema not installed")
    except Exception as exc:
        raise RuntimeError(
            "Section schema upgrade failed. Unmodified backup: " +
            (str(backup_path) if backup_path else "(not requested)")
        ) from exc
    return str(backup_path) if backup_path else None


def list_sections(path):
    with db.connect(path) as con:
        rows = con.execute(
            "SELECT id,name,vertices_wgs84,buffer_m FROM gs_sections ORDER BY id"
        ).fetchall()
    return [
        dict(id=row[0], name=row[1], vertices=json.loads(row[2]), buffer_m=row[3])
        for row in rows
    ]


def get_section(path, section_id):
    with db.connect(path) as con:
        r = con.execute(
            "SELECT id,name,vertices_wgs84,buffer_m FROM gs_sections WHERE id=?",
            (int(section_id),),
        ).fetchone()
    if r is None:
        raise ValueError("Section not found")
    return dict(id=r[0], name=r[1], vertices=_validate_line(json.loads(r[2])),
                buffer_m=r[3])


def create_section(path, name, vertices, buffer_m):
    name = str(name).strip()
    if not name or len(name) > 150:
        raise ValueError("Section name required (max 150 characters)")
    vertices = _validate_line(vertices)
    try:
        buffer_m = float(buffer_m)
    except (TypeError, ValueError):
        raise ValueError("Corridor width must be a number") from None
    if not math.isfinite(buffer_m) or not 1 <= buffer_m <= 100000:
        raise ValueError("Corridor width must be 1–100,000 m")
    with db.connect(path) as con:
        cursor = con.execute(
            """INSERT INTO gs_sections(name,vertices_wgs84,buffer_m,created_utc)
               VALUES(?,?,?,?)""",
            (name, json.dumps(vertices), buffer_m, db.utcnow()),
        )
        return cursor.lastrowid


def delete_section(path, section_id):
    with db.connect(path) as con:
        r = con.execute("DELETE FROM gs_sections WHERE id=?", (int(section_id),))
        if r.rowcount != 1:
            raise ValueError("Section not found")


def list_picks(path, section_id):
    with db.connect(path) as con:
        return con.execute(
            """SELECT well_id,formation_code,depth_bgl_m,note
               FROM gs_section_picks WHERE section_id=?
               ORDER BY well_id,formation_code""",
            (int(section_id),),
        ).fetchall()


def save_pick(path, section_id, well_id, formation_code,
              depth_bgl_m, well_total_depth=None, note=""):
    """Upsert an explicitly interpreted section contact; leave original logs unchanged."""
    well_id = str(well_id).strip()
    formation_code = str(formation_code).strip()
    if not well_id or not formation_code:
        raise ValueError("Well ID and formation code required")
    try:
        depth = float(depth_bgl_m)
    except (TypeError, ValueError):
        raise ValueError("Contact depth must be numeric") from None
    if not math.isfinite(depth) or depth < 0:
        raise ValueError("Contact depth must be nonnegative and finite")
    if well_total_depth is not None and depth > float(well_total_depth):
        raise ValueError("Contact below recorded total depth")
    if len(str(note)) > 1000:
        raise ValueError("Contact note is too long")
    with db.connect(path) as con:
        if not con.execute(
            "SELECT 1 FROM gs_sections WHERE id=?", (int(section_id),)
        ).fetchone():
            raise ValueError("Unknown section")
        if not con.execute(
            "SELECT 1 FROM gs_formations WHERE code=?", (formation_code,)
        ).fetchone():
            raise ValueError("Unknown formation")
        con.execute(
            """INSERT INTO gs_section_picks
               (section_id,well_id,formation_code,depth_bgl_m,note)
               VALUES(?,?,?,?,?)
               ON CONFLICT(section_id,well_id,formation_code)
               DO UPDATE SET depth_bgl_m=excluded.depth_bgl_m,note=excluded.note""",
            (int(section_id), well_id, formation_code, depth, str(note)),
        )


def delete_pick(path, section_id, well_id, formation_code):
    with db.connect(path) as con:
        cursor = con.execute(
            """DELETE FROM gs_section_picks
               WHERE section_id=? AND well_id=? AND formation_code=?""",
            (int(section_id), str(well_id), str(formation_code)),
        )
        if cursor.rowcount != 1:
            raise ValueError("Contact interpretation not found")

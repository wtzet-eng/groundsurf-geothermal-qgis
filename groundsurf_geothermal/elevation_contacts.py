"""Additive local storage for Z-elevation contact observations.

These are absolute/relative heights supplied by the source, NOT borehole
interval depths. Imported strata labels are preserved verbatim. Model
constraints require a separately verified vertical datum and interpretation.
"""
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db

VERSION = "1"


def has_schema(path):
    if not db.valid_project(path):
        return False
    try:
        with db.connect(path) as con:
            version = con.execute(
                "SELECT value FROM gs_meta WHERE key='elevation_schema_version'"
            ).fetchone()
            table = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='gs_elevation_contacts'"
            ).fetchone()
        return bool(version and version[0] == VERSION and table)
    except sqlite3.Error:
        return False


def ensure_schema(path, backup_existing=True):
    if not db.valid_project(path):
        raise ValueError("Open an existing GroundSurf Geothermal GeoPackage")
    if has_schema(path):
        return None
    project = Path(path).resolve()
    backup = None
    if backup_existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = project.with_name(
            project.name + ".backup-precontacts-" + stamp
        )
        with db.connect(project) as source, sqlite3.connect(backup) as output:
            source.backup(output)
    with db.connect(project) as con:
        current = con.execute(
            "SELECT value FROM gs_meta WHERE key='elevation_schema_version'"
        ).fetchone()
        if current:
            raise ValueError("Unknown contact-elevation schema version")
        con.execute(
            """CREATE TABLE gs_elevation_contacts (
               id INTEGER PRIMARY KEY,
               well_id TEXT NOT NULL,
               formation_code TEXT NOT NULL,
               elevation_m REAL NOT NULL,
               vertical_datum TEXT NOT NULL,
               source_layer TEXT NOT NULL,
               source_crs TEXT NOT NULL,
               source_x REAL NOT NULL,
               source_y REAL NOT NULL,
               source_feature_id TEXT NOT NULL,
               imported_utc TEXT NOT NULL,
               FOREIGN KEY(formation_code) REFERENCES gs_formations(code))"""
        )
        con.execute(
            """CREATE INDEX gs_elevation_well
               ON gs_elevation_contacts(well_id)"""
        )
        con.execute(
            """INSERT INTO gs_meta(key,value)
               VALUES('elevation_schema_version',?)""", (VERSION,)
        )
    return str(backup) if backup else None


def list_contacts(path, well_id=None):
    if not has_schema(path):
        return []
    with db.connect(path) as con:
        if well_id is not None:
            return con.execute(
                """SELECT well_id,formation_code,elevation_m,vertical_datum,
                          source_layer,source_crs,source_x,source_y,
                          source_feature_id,id
                   FROM gs_elevation_contacts WHERE well_id=?
                   ORDER BY elevation_m DESC,id""",
                (str(well_id),)
            ).fetchall()
        return con.execute(
            """SELECT well_id,formation_code,elevation_m,vertical_datum,
                      source_layer,source_crs,source_x,source_y,
                      source_feature_id,id
               FROM gs_elevation_contacts ORDER BY well_id,elevation_m DESC,id"""
        ).fetchall()


def store_contacts(path, records):
    """Insert preserved raw contact elevations into SQLite atomically.

    Caller is responsible for ensuring unique well points exist in gs_wells,
    and for compensating a failed multi-store operation if needed.
    """
    if not has_schema(path):
        raise ValueError("Contact storage is not initialized")
    unique_codes = {item["formation_code"] for item in records}
    with db.connect(path) as con:
        existing = {
            row[0] for row in con.execute(
                "SELECT code FROM gs_formations"
            )
        }
        for code in sorted(unique_codes - existing):
            con.execute(
                """INSERT INTO gs_formations(code,name,lithology,notes)
                   VALUES(?,?,?,?)""",
                (code, code, "",
                 "Source contact label only; verify stratigraphy before modelling."),
            )
        values = []
        for item in records:
            z = float(item["elevation_m"])
            if not math.isfinite(z):
                raise ValueError("Contact elevation Z must be finite")
            values.append((
                db._text(item["well_id"], "Well ID", True, 80),
                db._text(item["formation_code"], "Contact unit", True, 80),
                z,
                db._text(item["vertical_datum"], "Elevation datum", True, 100),
                db._text(item["source_layer"], "Source layer", True, 500),
                db._text(item["source_crs"], "Source CRS", True, 100),
                float(item["source_x"]), float(item["source_y"]),
                str(item["source_feature_id"]), db.utcnow(),
            ))
        con.executemany(
            """INSERT INTO gs_elevation_contacts
               (well_id,formation_code,elevation_m,vertical_datum,source_layer,
                source_crs,source_x,source_y,source_feature_id,imported_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            values,
        )
    return len(records)

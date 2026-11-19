"""Local, additive catalogue for generated preliminary 3D geological models."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from . import db

SCHEMA = "1"


def has_schema(path):
    if not db.valid_project(path):
        return False
    try:
        with db.connect(path) as con:
            row=con.execute(
                "SELECT value FROM gs_meta WHERE key='model_schema_version'"
            ).fetchone()
            table=con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='gs_model_runs'"
            ).fetchone()
        return bool(row and row[0]==SCHEMA and table)
    except sqlite3.Error:
        return False


def ensure_schema(path, backup_existing=True):
    if not db.valid_project(path):
        raise ValueError("Not a GroundSurf GeoPackage v2 project")
    if has_schema(path):
        return None
    path=Path(path).resolve()
    backup=None
    if backup_existing:
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup=path.with_name(path.name+".backup-premodels-"+stamp)
        with db.connect(path) as source, sqlite3.connect(backup) as output:
            source.backup(output)
    with db.connect(path) as con:
        version=con.execute(
            "SELECT value FROM gs_meta WHERE key='model_schema_version'"
        ).fetchone()
        if version:
            raise ValueError("Unknown model module schema; no upgrade performed")
        con.execute(
            """CREATE TABLE gs_model_runs(
               id INTEGER PRIMARY KEY, name TEXT NOT NULL,
               created_utc TEXT NOT NULL, output_dir TEXT NOT NULL,
               relative_output TEXT NOT NULL,
               epsg TEXT NOT NULL, vertical_datum TEXT NOT NULL,
               well_count INTEGER NOT NULL,
               source_hash TEXT NOT NULL, method TEXT NOT NULL)"""
        )
        con.execute("INSERT INTO gs_meta VALUES('model_schema_version',?)",(SCHEMA,))
    return str(backup) if backup else None


def record(path, name, output_folder, epsg, datum, well_count, source_hash, method):
    if not has_schema(path):
        raise ValueError("Model catalogue not installed")
    directory=str(Path(output_folder).resolve())
    rel=os.path.relpath(directory, start=str(Path(path).resolve().parent))
    with db.connect(path) as con:
        cursor=con.execute(
            """INSERT INTO gs_model_runs(
               name, created_utc, output_dir, relative_output,
               epsg, vertical_datum, well_count, source_hash, method)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (name, db.utcnow(), directory, rel, epsg, datum, well_count,
             source_hash, method),
        )
    return cursor.lastrowid


def list_models(path):
    if not has_schema(path):
        return []
    with db.connect(path) as con:
        return con.execute(
            """SELECT id,name,created_utc,output_dir,relative_output,
                      epsg,vertical_datum,well_count,source_hash,method
               FROM gs_model_runs ORDER BY id DESC"""
        ).fetchall()


def find_output(project_file,row):
    project=Path(project_file).resolve()
    relative=row[4]
    absolute=row[3]
    for candidate in (project.parent/relative,Path(absolute)):
        if (candidate/"model.vtm").is_file():
            return candidate.resolve()
    return None

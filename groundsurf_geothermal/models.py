"""Local, additive catalogue for generated preliminary 3D geological models."""
import json
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


def find_record(path, record_id):
    """Locate a single model by immutable catalogue ID, not its display name."""
    if not has_schema(path):
        raise ValueError("No GroundSurf model catalogue is available")
    if isinstance(record_id, bool) or not isinstance(record_id, int):
        raise ValueError("Model ID must be a positive integer")
    if record_id < 1:
        raise ValueError("Model ID must be a positive integer")
    with db.connect(path) as con:
        return con.execute(
            """SELECT id,name,created_utc,output_dir,relative_output,
                      epsg,vertical_datum,well_count,source_hash,method
               FROM gs_model_runs WHERE id=?""",
            (record_id,)
        ).fetchone()


def safe_trash_folder(path, model_row):
    """Return a provable GroundSurf-generated folder, else None.

    Model output can live outside the GeoPackage directory by user
    choice. Never trust an arbitrary catalogue path as permission to
    delete a tree. Require GroundSurf's generated directory prefix,
    no symlink at the folder itself, VTK and manifest, and matching
    application/model name. Do not touch unrelated source paths.
    """
    if not model_row or not db.valid_project(path):
        return None
    folder = find_output(path, model_row)
    if folder is None or folder.is_symlink() or not folder.is_dir():
        return None
    # A symlinked catalogue path must never grant permission to move
    # the resolved target folder to Trash.
    project_folder = Path(path).resolve().parent
    original_paths = (
        project_folder / model_row[4], Path(model_row[3])
    )
    if any(
        candidate.is_symlink() and candidate.resolve() == folder
        for candidate in original_paths
    ):
        return None
    # A generated output might be referenced more than once. Do not
    # trash files that a second saved entry still needs.
    for other in list_models(path):
        if other[0] == model_row[0]:
            continue
        referenced = (
            project_folder / other[4], Path(other[3])
        )
        if any(candidate.resolve() == folder for candidate in referenced):
            return None
    if not folder.name.startswith("gsmodel-"):
        return None
    manifest_file = folder / "model.json"
    vtk_file = folder / "model.vtm"
    if (
        manifest_file.is_symlink() or vtk_file.is_symlink()
        or not manifest_file.is_file() or not vtk_file.is_file()
    ):
        return None
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    if manifest.get("application") != "GroundSurf Geothermal":
        return None
    if manifest.get("name") != model_row[1]:
        return None
    # Never offer trashing the directory containing the project itself.
    if folder == Path(path).resolve().parent or folder == Path(path).resolve():
        return None
    return folder


def remove_model(path, record_id):
    """Remove ONE generated-model catalogue row, never boreholes or sources.

    Physical output folder deletion is controlled separately by the UI
    using Qt's moveToTrash, not performed by this database operation.
    """
    record = find_record(path, record_id)
    if record is None:
        raise ValueError("Selected 3D model is no longer in the catalogue")
    with db.connect(path) as con:
        cursor = con.execute(
            "DELETE FROM gs_model_runs WHERE id=?", (record_id,)
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Could not remove the selected model entry")
    return record

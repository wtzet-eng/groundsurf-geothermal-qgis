"""Tests for formation, lithology, temperature, groundwater and migration."""
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from groundsurf_geothermal import db


class FakeWellLayer:
    def getFeatures(self):
        return iter([
            {"well_id": "W1", "total_depth_m": 120.0},
            {"well_id": "W2", "total_depth_m": 240.0},
        ])


class V02Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "project.gpkg"
        with sqlite3.connect(self.path) as con:
            con.execute("CREATE TABLE gpkg_contents(table_name TEXT)")
            con.execute("INSERT INTO gpkg_contents VALUES('gs_wells')")
        db.bootstrap(self.path)
        self.layer = FakeWellLayer()

    def test_basic_schema(self):
        self.assertTrue(db.valid_project(self.path))
        self.assertEqual(db.project_version(self.path), "2")
        self.assertEqual(db.formations(self.path), [])

    def test_formations_intervals_tops(self):
        db.add_formation(self.path, "CL", "Clay", "Clayey silt")
        db.add_formation(self.path, "SD", "Sand", "Coarse sand")
        db.add_interval(self.path, self.layer, "W1", "CL", 0, 30, "soft clay")
        db.add_interval(self.path, self.layer, "W1", "SD", 30, 100)
        self.assertEqual(len(db.intervals(self.path, "W1")), 2)
        with self.assertRaisesRegex(ValueError, "overlaps"):
            db.add_interval(self.path, self.layer, "W1", "SD", 20, 40)
        with self.assertRaisesRegex(ValueError, "total well depth"):
            db.add_interval(self.path, self.layer, "W1", "SD", 121, 125)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            db.add_interval(self.path, self.layer, "wrong", "SD", 0, 1)
        db.add_formation_top(self.path, self.layer, "W1", "SD", 30,
                             interpretation="observed", source="synthetic log")
        self.assertEqual(db.formation_tops(self.path, "W1")[0][3], "observed")
        top_id = db.formation_tops(self.path, "W1")[0][0]
        with self.assertRaises(ValueError):
            db.delete_well_record(self.path, "top", top_id, "W2")
        db.delete_well_record(self.path, "top", top_id, "W1")
        self.assertEqual(len(db.formation_tops(self.path, "W1")), 0)

    def test_observation_distinctions(self):
        t = "2026-11-19T16:40:00+01:00"
        db.add_observation(self.path, self.layer, "W1", t,
                           "water_depth_bgl_m", 3.1, source="logger")
        db.add_observation(self.path, self.layer, "W1", t,
                           "temperature_c", 35.2, depth_bgl_m=70)
        db.add_observation(self.path, self.layer, "W1", t,
                           "water_head_elev_m", 48.6,
                           reference_datum="DHHN2016")
        got = db.observations(self.path, "W1")
        self.assertEqual(len(got), 3)
        self.assertEqual({r[4] for r in got}, {"m", "degC"})
        self.assertTrue(all(r[1].endswith("+00:00") for r in got))
        with self.assertRaisesRegex(ValueError, "vertical datum"):
            db.add_observation(self.path, self.layer, "W1", t,
                               "water_head_elev_m", 45.6)
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            db.add_observation(self.path, self.layer, "W1",
                               "2026-11-19T16:40:00", "temperature_c", 10)
        with self.assertRaises(ValueError):
            db.add_observation(self.path, self.layer, "W1", t,
                               "temperature_c", 10, depth_bgl_m=200)

    def test_atomic_csv_import(self):
        db.add_formation(self.path, "S", "Sand")
        db.add_formation(self.path, "C", "Clay")
        text = ("well_id,formation_code,top_depth_m,base_depth_m,description\n"
                "W1,S,0,10,sand\nW1,C,10,20,clay\nW2,S,0,30,sand\n")
        count = db.import_intervals_csv(self.path, self.layer, text)
        self.assertEqual(count, 3)
        self.assertEqual(len(db.intervals(self.path, "W1")), 2)
        invalid = ("well_id,formation_code,top_depth_m,base_depth_m\n"
                   "W1,S,30,40\nW1,C,35,50\n")
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            db.import_intervals_csv(self.path, self.layer, invalid)
        self.assertEqual(len(db.intervals(self.path, "W1")), 2)

    def test_relocatable_maps_and_relink(self):
        source = self.root / "map.tif"
        source.write_bytes(b"test placeholder")
        db.record_map(self.path, source, "Map", "raster")
        row = db.maps(self.path)[0]
        resolved, layer = db.resolve_map(self.path, row)
        self.assertEqual(resolved, source)
        self.assertEqual(row[4], "map.tif")
        moved_root = self.root / "moved"
        moved_root.mkdir()
        moved_db = moved_root / "project.gpkg"
        shutil.copy2(self.path, moved_db)
        shutil.copy2(source, moved_root / "map.tif")
        moved, _ = db.resolve_map(moved_db, db.maps(moved_db)[0])
        self.assertEqual(moved, moved_root / "map.tif")
        repaired = moved_root / "new.tif"
        repaired.write_bytes(b"another placeholder")
        db.relink_map(moved_db, row[0], repaired)
        row2 = db.maps(moved_db)[0]
        self.assertEqual(row2[4], "new.tif")

    def test_multilayer_gpkg_source(self):
        file_path = self.root / "maps.gpkg"
        file_path.write_bytes(b"not a real map; database catalog test")
        db.record_map(self.path, file_path, "Geology", "vector", "geology")
        db.record_map(self.path, file_path, "Faults", "vector", "faults")
        self.assertEqual(len(db.maps(self.path)), 2)
        db.record_map(self.path, file_path, "Faults updated", "vector", "faults")
        self.assertEqual(len(db.maps(self.path)), 2)
        self.assertIn("Faults updated", [x[2] for x in db.maps(self.path)])

    def test_temperature_and_pressure_bases(self):
        t = "2026-11-19T17:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "need a depth"):
            db.add_observation(self.path, self.layer, "W1", t,
                               "temperature_c", 22.0)
        with self.assertRaisesRegex(ValueError, "absolute"):
            db.add_observation(self.path, self.layer, "W1", t,
                               "pressure_kpa", 110, depth_bgl_m=10)
        db.add_observation(self.path, self.layer, "W1", t,
                           "pressure_kpa", 110, depth_bgl_m=10,
                           reference_datum="absolute")
        self.assertEqual(len(db.observations(self.path, "W1")), 1)

    def test_v1_migration_writes_backup(self):
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE gs_meta SET value='1' WHERE key='schema_version'")
            con.execute("DROP TABLE gs_formation_tops")
            con.execute("ALTER TABLE gs_maps DROP COLUMN relative_path")
            con.execute("ALTER TABLE gs_maps DROP COLUMN source_layer")
        self.assertEqual(db.project_version(self.path), "1")
        backup = db.migrate_v1(self.path)
        self.assertEqual(db.project_version(backup), "1")
        self.assertTrue(db.valid_project(self.path))
        self.assertTrue(Path(backup).is_file())
        with self.assertRaises(ValueError):
            db.migrate_v1(self.path)


if __name__ == "__main__":
    unittest.main()

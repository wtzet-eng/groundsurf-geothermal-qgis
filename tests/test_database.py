"""Zero-network tests for the database and data validation layer."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from groundsurf_geothermal import db


class DatabaseTests(unittest.TestCase):
    def test_schema_and_maps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.sqlite3"
            db.bootstrap(path)
            with sqlite3.connect(path) as con:
                tables = {r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                for required in ("gs_meta", "gs_observations", "gs_formations",
                                 "gs_intervals", "gs_maps"):
                    self.assertIn(required, tables)
            db.record_map(path, Path(tmp) / "map.geojson", "Local test map", "vector")
            self.assertEqual(len(db.maps(path)), 1)
            self.assertFalse(db.valid_project(path))  # Not yet a GeoPackage.

    def test_well_csv(self):
        text = (
            "well_id,name,latitude,longitude,total_depth_m,ground_elev_m\n"
            "A,Well A,52.4,13.4,120,55\n"
            "B,Well B,52.5,13.5,,\n"
        )
        results = db.parse_well_csv(text)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["total_depth_m"], 120.0)
        self.assertIsNone(results[1]["ground_elev_m"])

    def test_invalid_well_or_duplicate(self):
        with self.assertRaises(ValueError):
            db.validate_well({"well_id":"X", "name":"Test",
                              "latitude":"91", "longitude":"0"})
        with self.assertRaises(ValueError):
            db.validate_well({"well_id":"X", "name":"Test",
                              "latitude":"NaN", "longitude":"0"})
        with self.assertRaises(ValueError):
            db.parse_well_csv("well_id,name,latitude,longitude\n"
                              "A,One,20,10\nA,Two,20,10\n")
        with self.assertRaises(ValueError):
            db.validate_well({"well_id":"X", "name":"Test",
                              "latitude":"30", "longitude":"20",
                              "total_depth_m":"-1"})


if __name__ == "__main__":
    unittest.main()

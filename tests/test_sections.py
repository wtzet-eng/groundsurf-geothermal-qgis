"""Persistence and metric geometry tests for section interpretations."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from groundsurf_geothermal import db, sections, section_math


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"site.gpkg"
        with sqlite3.connect(self.path) as con:
            con.execute("CREATE TABLE gpkg_contents(table_name TEXT)")
            con.execute("INSERT INTO gpkg_contents VALUES('gs_wells')")
        db.bootstrap(self.path)

    def test_backup_and_schema(self):
        backup=sections.ensure_schema(self.path,True)
        self.assertTrue(Path(backup).is_file())
        self.assertIsNone(sections.ensure_schema(self.path,True))
        self.assertTrue(sections.has_schema(self.path))
        self.assertEqual(db.project_version(self.path),"2")

    def test_sections_and_picks(self):
        sections.ensure_schema(self.path,False)
        db.add_formation(self.path,"CL","Clay")
        sid=sections.create_section(
            self.path,"E-W",[[13.3,52.5],[13.4,52.5]],250)
        self.assertEqual(len(sections.list_sections(self.path)),1)
        sections.save_pick(self.path,sid,"W1","CL",18,100,"from section")
        sections.save_pick(self.path,sid,"W1","CL",22,100,"edited")
        self.assertEqual(sections.list_picks(self.path,sid)[0][2],22)
        self.assertEqual(len(sections.list_picks(self.path,sid)),1)
        with db.connect(self.path) as con:
            self.assertEqual(con.execute(
                "SELECT count(*) FROM gs_formation_tops").fetchone()[0],0)
        with self.assertRaises(ValueError):
            sections.save_pick(self.path,sid,"W1","CL",101,100)
        sections.delete_section(self.path,sid)
        with db.connect(self.path) as con:
            self.assertEqual(con.execute(
                "SELECT count(*) FROM gs_section_picks").fetchone()[0],0)

    def test_invalid_section_geometry(self):
        sections.ensure_schema(self.path,False)
        for bad in (
            [],[[13.3,52.5]],[[13.3,52.5],[13.3,52.5]],
            [[float("nan"),52],[13,52]],[[300,52],[13,52]],
        ):
            with self.assertRaises(ValueError):
                sections.create_section(self.path,"Bad",bad,250)

    def test_chainage(self):
        distance,offset,total=section_math.chainage_for_point(
            (90,40),[(0,0),(100,0),(100,100)])
        self.assertAlmostEqual(distance,140)
        self.assertAlmostEqual(offset,10)
        self.assertAlmostEqual(total,200)
        points=[(0,0),(200,10),(400,-10)]
        vertices,width=section_math.auto_line(points)
        self.assertTrue(all(
            section_math.chainage_for_point(p,vertices)[1] < width
            for p in points))


if __name__=="__main__":
    unittest.main()

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from osgeo import gdal, osr

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append("/usr/share/qgis/python/plugins")
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsRectangle,
    QgsFeature,
    QgsGeometry,
    QgsProcessingContext,
    QgsProject,
    QgsVectorLayer,
)
from processing.core.Processing import Processing
import processing
from groundsurf_geothermal.connect.catalogue import (
    acquire,
    acquisition_adapter,
    discover,
    source_groups,
    tile_plan,
)
from groundsurf_geothermal.connect.plugin import Connect
from groundsurf_geothermal.connect.package import FILES, create_package, digest, validate
from groundsurf_geothermal.connect.provider import HELP, Provider
from groundsurf_geothermal.connect.raster import grid, open_tif


def fixture(path, arr, gt=(400000, 2, 0, 5800020, 0, -2), epsg=25832):
    arr = np.atleast_3d(arr) if arr.ndim == 2 else arr
    h, w, n = arr.shape
    d = gdal.GetDriverByName("GTiff").Create(
        str(path), w, h, n, gdal.GDT_Byte if n > 1 else gdal.GDT_Float32
    )
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    d.SetProjection(s.ExportToWkt())
    d.SetGeoTransform(gt)
    for i in range(n):
        b = d.GetRasterBand(i + 1)
        b.WriteArray(arr[:, :, i])
        if n == 1:
            b.SetNoDataValue(-9999)
    d = None


class ConnectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication([], False)
        cls.app.setPrefixPath("/usr", True)
        cls.app.initQgis()
        Processing.initialize()
        cls.provider = Provider()
        QgsApplication.processingRegistry().addProvider(cls.provider)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dem, self.rgb = self.root / "d.tif", self.root / "i.tif"
        self.bounds = [400002, 5800002, 400018, 5800018]
        self.z = np.arange(100, dtype="float32").reshape(10, 10)
        self.z[4, 4] = -9999
        self.img = np.stack(
            [
                np.tile(np.arange(10), (10, 1)) * 10,
                np.tile(np.arange(10)[:, None], (1, 10)) * 20,
                np.full((10, 10), 50),
            ],
            axis=-1,
        ).astype("uint8")
        fixture(self.dem, self.z)
        fixture(self.rgb, self.img)
        self.out = self.root / "package"
        self.extent = "400002,400018,5800002,5800018 [EPSG:25832]"

    def run_alg(self, key, **params):
        ctx = QgsProcessingContext()
        ctx.setProject(QgsProject.instance())
        return processing.run("groundsurf:" + key, params, context=ctx)

    def package(self, **kw):
        return create_package(
            self.out,
            [self.dem],
            [self.rgb],
            self.bounds,
            "EPSG:25832",
            2,
            "DTM",
            "unknown",
            "Synthetic test data",
            {},
            **kw
        )

    def test_registered_tools(self):
        self.assertEqual({a.name() for a in self.provider.algorithms()}, set(HELP))
        for key in ("inspect_layers", "inspect_project"):
            self.assertIn("crs", json.loads(self.run_alg(key)["REPORT"]))

    def test_values_nodata_position_precision(self):
        m = self.package()
        self.assertEqual(m["frame"]["origin"], [400010, 5800010, 0])
        dem = open_tif(self.out / FILES["terrain"])
        z = dem.ReadAsArray()
        self.assertTrue(np.isnan(z[3, 3]))
        expected = self.z[1:9, 1:9].copy()
        expected[3, 3] = np.nan
        np.testing.assert_array_equal(z, expected)
        rgb = open_tif(self.out / FILES["imagery"]).ReadAsArray()
        np.testing.assert_array_equal(rgb[:3].transpose(1, 2, 0), self.img[1:9, 1:9])
        self.assertIn("unknown", (self.out / FILES["validation"]).read_text())
        self.assertEqual(float(open_tif(self.dem).ReadAsArray()[4, 4]), -9999)
        self.assertEqual(validate(self.out)["terrainRole"], "DTM")

    def test_public_processing_roundtrip(self):
        args = dict(
            DEM=str(self.dem),
            IMAGE=str(self.rgb),
            AREA=self.extent,
            CRS="EPSG:25832",
            METRES=True,
            STEP=2,
            RIGHTS="Synthetic",
            OUTPUT=str(self.out),
        )
        self.run_alg("create_transfer_package", **args)
        for key in ("validate_transfer_package", "send_to_studio"):
            opts = {"OUTPUT": str(self.root / "view.html")} if key == "send_to_studio" else {}
            self.run_alg(key, PACKAGE=str(self.out), **opts)
        self.assertTrue((self.root / "view.html").is_file())
        self.assertIn(
            "geoTransform",
            json.loads(self.run_alg("validate_coordinates", DEM=str(self.dem))["REPORT"]),
        )

    def test_prepare_and_align(self):
        d, i = str(self.root / "cut.tif"), str(self.root / "aligned.tif")
        self.run_alg(
            "prepare_dem", DEM=str(self.dem), AREA=self.extent, METRES=True, STEP=2, OUTPUT=d
        )
        self.run_alg("align_rasters", DEM=d, IMAGE=str(self.rgb), BANDS="3,2,1", OUTPUT=i)
        self.assertEqual(open_tif(i).GetGeoTransform(), open_tif(d).GetGeoTransform())
        self.assertEqual(open_tif(i).ReadAsArray()[0, 0, 0], 50)
        self.run_alg(
            "prepare_imagery",
            IMAGE=str(self.rgb),
            AREA=self.extent,
            STEP=2,
            OUTPUT=str(self.root / "rgb.tif"),
        )

    def test_geographic_input_reprojection(self):
        source = self.root / "degrees.tif"
        fixture(source, np.full((10, 10), 73.0), gt=(8.99, 0.002, 0, 52.01, 0, -0.002), epsg=4326)
        result = self.run_alg(
            "prepare_dem",
            DEM=str(source),
            AREA="8.995,9.005,51.995,52.005 [EPSG:4326]",
            STEP=20,
            CRS="EPSG:25832",
            METRES=True,
            OUTPUT=str(self.root / "utm.tif"),
        )
        z = open_tif(result["OUTPUT"]).ReadAsArray()
        self.assertEqual(float(np.nanmedian(z)), 73.0)
        self.assertGreater(np.isfinite(z).sum(), 100)
        with self.assertRaises(Exception):
            self.run_alg(
                "prepare_dem",
                DEM=str(source),
                AREA=self.extent,
                CRS="EPSG:4326",
                METRES=True,
                OUTPUT=str(self.root / "bad.tif"),
            )

    def test_polygon_vector_and_buffer(self):
        layer = QgsVectorLayer("Polygon?crs=epsg:25832", "parcel", "memory")
        f = QgsFeature()
        f.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON ((400002 5800002,400018 5800002,400002 5800018,400002 5800002))"
            )
        )
        layer.dataProvider().addFeatures([f])
        layer.updateExtents()
        area = json.loads(self.run_alg("define_area", POLYGON=layer, BUFFER=2)["REPORT"])
        self.assertLess(area["extent"][0], 400002)
        d = self.root / "masked.tif"
        self.run_alg(
            "prepare_dem", DEM=str(self.dem), POLYGON=layer, METRES=True, STEP=2, OUTPUT=str(d)
        )
        self.assertTrue(np.isnan(open_tif(d).ReadAsArray()[0, -1]))
        v = self.root / "parcels.gpkg"
        self.run_alg("prepare_vectors", VECTOR=layer, POLYGON=layer, OUTPUT=str(v))
        self.assertEqual(QgsVectorLayer(str(v), "v", "ogr").featureCount(), 1)

    def test_cancel_no_partial_or_overwrite(self):
        with self.assertRaisesRegex(ValueError, "Cancelled"):
            self.package(cancel=lambda: True)
        self.assertFalse(self.out.exists())
        self.package()
        with self.assertRaisesRegex(ValueError, "new package"):
            self.package()

    def test_invalid_packages(self):
        self.package()
        path = self.out / "manifest.json"
        m = json.loads(path.read_text())
        m["files"]["terrain"]["path"] = "../d.tif"
        path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, "path"):
            validate(self.out)
        m["files"]["terrain"]["path"] = FILES["terrain"]
        path.write_text(json.dumps(m))
        (self.out / FILES["terrain"]).write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "size"):
            validate(self.out)

    def test_same_size_corruption(self):
        self.package()
        p = self.out / FILES["imagery"]
        with p.open("r+b") as output:
            output.seek(-1, 2)
            value = output.read(1)[0]
            output.seek(-1, 2)
            output.write(bytes([value ^ 1]))
        with self.assertRaisesRegex(ValueError, "Checksum"):
            validate(self.out)

    def test_mid_job_cancel_and_retry(self):
        progress = []

        def cancel():
            return bool(progress and max(progress) >= 35)

        with self.assertRaisesRegex(ValueError, "Cancelled"):
            self.package(cancel=cancel, progress=progress.append)
        self.assertFalse(self.out.exists())
        self.package()
        self.assertTrue((self.out / "manifest.json").is_file())

    def test_no_coverage(self):
        self.bounds = [1000, 1000, 1016, 1016]
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.out.exists())

    def test_preview_input_and_symlink(self):
        self.package()
        p = self.out / FILES["preview"]
        content = json.loads(p.read_text())
        content["nx"] = 9000000
        p.write_text(json.dumps(content))
        m = json.loads((self.out / "manifest.json").read_text())
        m["files"]["preview"].update(sha256=digest(p), bytes=p.stat().st_size)
        (self.out / "manifest.json").write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, "dimensions"):
            validate(self.out)
        p.unlink()
        p.symlink_to(self.rgb)
        with self.assertRaisesRegex(ValueError, "linked"):
            validate(self.out)

    def test_discovery_limits_service_failure(self):
        self.assertEqual(len(discover([10.74, 47.55, 10.75, 47.56])), 2)
        self.assertEqual(len(discover([19, 51, 19.1, 51.1])), 2)
        res = self.run_alg("discover_data", AREA="10.74,10.75,47.55,47.56 [EPSG:4326]")
        self.assertEqual(len(json.loads(res["REPORT"])["sources"]), 2)
        self.assertEqual(discover([-73, 42, -72, 43]), [])
        with self.assertRaises(ValueError):
            grid([0, 0, 100000, 100000], 1)
        with self.assertRaises(ValueError):
            tile_plan([0, 0, 5000, 5000])
        with patch("groundsurf_geothermal.connect.catalogue.build_opener") as client:
            client.return_value.open.side_effect = OSError("offline")
            with self.assertRaisesRegex(ValueError, "unavailable"):
                acquire(self.bounds, self.root)

    def test_source_selection_and_adapter_dispatch(self):
        bavaria = discover([10.74, 47.55, 10.75, 47.56])
        poland = discover([19, 51, 19.1, 51.1])
        self.assertEqual(list(source_groups(bavaria)), ["bavaria"])
        key, adapter = acquisition_adapter(bavaria, "auto")
        self.assertEqual(key, "bavaria")
        self.assertEqual(adapter.crs, "EPSG:25832")
        self.assertIn("CC BY 4.0", adapter.review([631080, 5268100, 631980, 5268980], 450, 440))
        self.assertEqual(acquisition_adapter(bavaria, "poland"), (None, None))
        self.assertEqual(acquisition_adapter(poland, "auto"), (None, None))
        self.assertEqual(acquisition_adapter(poland, "poland"), (None, None))
        self.assertEqual(acquisition_adapter([], "auto"), (None, None))
        self.assertEqual(acquisition_adapter(bavaria[:1], "auto"), (None, None))

    def test_dock_discovery_without_bavarian_projection(self):
        dock = Mock()
        canvas = dock.iface.mapCanvas.return_value
        canvas.mapSettings.return_value.destinationCrs.return_value = QgsCoordinateReferenceSystem(
            "EPSG:4326"
        )
        canvas.extent.return_value = QgsRectangle(19, 51, 19.1, 51.1)
        dock.mode.currentIndex.return_value = 1
        dock.buffer.value.return_value = 0
        _, crs, sources = Connect.area(dock)
        self.assertEqual(crs.authid(), "EPSG:4326")
        self.assertEqual(list(source_groups(sources)), ["poland"])
        canvas.extent.return_value = QgsRectangle(151.2, -33.9, 151.21, -33.89)
        dock.buffer.value.return_value = 20
        geom, crs, sources = Connect.area(dock)
        self.assertEqual(crs.authid(), "EPSG:32756")
        self.assertTrue(geom.isGeosValid())
        self.assertEqual(sources, [])

    def test_reject_image_as_dem(self):
        with self.assertRaisesRegex(ValueError, "elevation"):
            create_package(
                self.out,
                [self.rgb],
                [self.rgb],
                self.bounds,
                "EPSG:25832",
                2,
                "DTM",
                "unknown",
                "Synthetic",
                {},
            )
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

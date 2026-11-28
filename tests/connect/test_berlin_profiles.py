import unittest
from unittest.mock import patch
from groundsurf_geothermal.connect.berlin_profiles import (
    BERLIN,
    profile_url,
    query_berlin,
    supports_berlin,
)

URL = (
    "https://gdi.berlin.de/ext/bohrungen/getimage?"
    "PRJID=BL413A&LOCID=3127&LAYOUT=1&RESOLUTION=2500&IMAGETYPE=JPG"
)
BOUNDS = [13.35, 52.50, 13.37, 52.52]
NATIVE = [388600, 5818100, 388900, 5818400]


class BerlinTests(unittest.TestCase):
    def test_profile_url_allowlist(self):
        self.assertEqual(profile_url(URL), URL)
        for value in (
            URL.replace("https:", "http:"),
            URL.replace("gdi.berlin.de", "example.com"),
            URL + "&LOCID=1",
            URL + "#fragment",
            URL.replace("JPG", "HTML"),
        ):
            self.assertIsNone(profile_url(value))

    @patch("groundsurf_geothermal.connect.berlin_profiles.request")
    def test_evidence_preserves_unverified_height_and_unknown_intervals(self, request):
        row = {
            "geometry": {"type": "Point", "coordinates": [13.36, 52.51]},
            "properties": {
                "schluessel": "413A00192",
                "endteufe": 8.1,
                "ansatzhoehe": "32.3",
                "profil": URL,
            },
        }
        request.return_value = {
            "type": "FeatureCollection",
            "crs": {"properties": {"name": "urn:ogc:def:crs:CRS::84"}},
            "features": [row, row],
            "numberMatched": 501,
        }
        data = query_berlin(BOUNDS, NATIVE)
        self.assertEqual(len(data["features"]), 1)
        self.assertEqual(data["groundsurf"]["source"], BERLIN)
        self.assertTrue(data["groundsurf"]["limit_reached"])
        p = data["features"][0]["properties"]
        self.assertEqual(p["reported_collar_m"], 32.3)
        self.assertIsNone(p["vertical_datum"])
        self.assertIsNone(p["intervals_available"])
        self.assertEqual(p["record_type"], "profile_document_link")

    @patch("groundsurf_geothermal.connect.berlin_profiles.request")
    def test_wrong_crs_and_cancel_fail_closed(self, request):
        request.return_value = {"type": "FeatureCollection", "features": []}
        with self.assertRaises(ValueError):
            query_berlin(BOUNDS, NATIVE)
        with self.assertRaises(InterruptedError):
            query_berlin(BOUNDS, NATIVE, lambda: True)
        self.assertFalse(supports_berlin([10, 50, 10.1, 50.1]))

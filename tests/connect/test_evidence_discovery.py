import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from groundsurf_geothermal.connect.evidence_discovery import (
    BGR,
    BGR_CREDIT,
    classify,
    portals,
    query_bgr,
)


def feature(identifier, xy, depth=None):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": xy},
        "properties": {"gml_ID": identifier, "OBJECTID": 1, "totalLength": depth},
    }


class EvidenceDiscoveryTests(unittest.TestCase):
    def test_requests_and_regional_recommendations(self):
        self.assertEqual(classify("could we download boreholes within the area?"), {"boreholes"})
        self.assertEqual(classify("terrain and aerial imagery"), {"terrain", "imagery"})
        self.assertEqual(classify("boreholes and geological maps"), {"boreholes", "geology"})
        self.assertEqual(classify("Bohrungen"), {"boreholes"})
        self.assertEqual(classify("CPT and groundwater"), {"cpt", "groundwater"})
        self.assertEqual(classify("?"), set())
        self.assertTrue(any(r[0] == "Poland" for r in portals([19, 51, 19.1, 51.1], {"boreholes"})))
        self.assertEqual(portals([150, -34, 151, -33], {"boreholes"}), [])

    @patch("groundsurf_geothermal.connect.evidence_discovery.request")
    def test_bgr_location_data_not_invented_logs(self, request):
        request.return_value = {
            "type": "FeatureCollection",
            "features": [
                feature("A", [13.36, 52.49], 26),
                feature("A", [13.36, 52.49], 26),
                feature("B", [13.37, 52.5]),
                feature("outside", [14, 52.5], 4),
            ],
            "properties": {"exceededTransferLimit": True},
        }
        result = query_bgr([13.35, 52.48, 13.4, 52.52])
        self.assertEqual(len(result["features"]), 2)
        a, b = [f["properties"] for f in result["features"]]
        self.assertEqual(a["reported_length_m"], 26)
        self.assertIsNone(b["reported_length_m"])
        self.assertIsNone(a["intervals_available"])
        self.assertEqual(a["attribution"], BGR_CREDIT)
        self.assertEqual(a["source"], BGR)
        self.assertTrue(result["groundsurf"]["limit_reached"])
        self.assertEqual(result["groundsurf"]["invalid_records"], 1)
        params = parse_qs(urlparse(request.call_args.args[0]).query)
        self.assertEqual(params["geometryType"], ["esriGeometryEnvelope"])
        self.assertEqual(params["outSR"], ["4326"])
        self.assertEqual(params["resultRecordCount"], ["2000"])

    @patch("groundsurf_geothermal.connect.evidence_discovery.request")
    def test_invalid_area_and_cancel_never_query(self, request):
        for bounds in ([13, 51, 15, 52], [19, 51, 19.1, 51.1], [13, 52, 12, 53]):
            with self.assertRaises(ValueError):
                query_bgr(bounds)
        with self.assertRaises(InterruptedError):
            query_bgr([13.35, 52.48, 13.4, 52.52], lambda: True)
        request.assert_not_called()

    @patch("groundsurf_geothermal.connect.evidence_discovery.request")
    def test_error_is_not_empty_coverage(self, request):
        request.return_value = {"error": {"message": "unavailable"}}
        with self.assertRaises(ValueError):
            query_bgr([13.35, 52.48, 13.4, 52.52])
        request.return_value = {"type": "FeatureCollection", "features": []}
        self.assertEqual(query_bgr([13.35, 52.48, 13.4, 52.52])["features"], [])

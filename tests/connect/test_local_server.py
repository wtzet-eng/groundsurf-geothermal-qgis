import unittest
from unittest.mock import patch
from groundsurf_geothermal.connect.local_server import existing_servers


class ExistingLocalTests(unittest.TestCase):
    @patch("groundsurf_geothermal.connect.local_server.request")
    def test_only_fixed_loopback_and_valid_model_names(self, request):
        request.side_effect = [
            {
                "data": [],
                "models": [
                    {"name": "valid:4b"},
                    {"name": "x-cloud"},
                    {"name": "x", "remote_host": "remote"},
                    {"name": "bad?query"},
                ],
            },
            {"data": [{"id": "proxy"}]},
            OSError("not running"),
        ]
        self.assertEqual(existing_servers(), [(8080, "valid:4b")])
        self.assertEqual(
            [c.args[0] for c in request.call_args_list],
            [f"http://127.0.0.1:{p}/v1/models" for p in (8080, 18090, 18089)],
        )

    @patch("groundsurf_geothermal.connect.local_server.request")
    def test_cancel_before_probing(self, request):
        with self.assertRaises(InterruptedError):
            existing_servers(lambda: True)
        request.assert_not_called()

import io
import json
import unittest
from unittest.mock import patch

from groundsurf_geothermal.connect import ollama_setup as setup


class SetupTests(unittest.TestCase):
    @patch.object(setup, "request")
    def test_detection_prefers_small_and_rejects_cloud(self, request):
        request.side_effect = [
            {
                "models": [
                    {"name": "other:8b", "size": 300},
                    {"name": "qwen3:4b", "size": 200},
                    {"name": "bad:cloud", "size": 100},
                    {"name": "remote", "size": 100, "remote_host": "x"},
                ]
            },
            {"model_info": {"arch": "qwen"}, "capabilities": ["tools"]},
            {"model_info": {"arch": "other"}, "capabilities": ["completion"]},
        ]
        self.assertEqual(setup.installed_models(), ["qwen3:4b"])
        self.assertEqual(request.call_count, 3)

    @patch.object(setup, "installed_models", side_effect=[[], ["qwen3:4b"]])
    @patch.object(setup, "build_opener")
    def test_pull_is_fixed_and_verified(self, opener, models):
        opener.return_value.open.return_value = io.BytesIO(b'{"status":"success"}\n')
        self.assertEqual(setup.pull_recommended(lambda: False), ["qwen3:4b"])
        req = opener.return_value.open.call_args.args[0]
        self.assertEqual(req.full_url, setup.BASE + "/api/pull")
        self.assertEqual(json.loads(req.data), {"model": "qwen3:4b", "stream": True})

    @patch.object(setup, "installed_models", return_value=[])
    @patch.object(setup, "build_opener")
    def test_cancel_before_pull(self, opener, models):
        with self.assertRaises(InterruptedError):
            setup.pull_recommended(lambda: True)
        opener.assert_not_called()

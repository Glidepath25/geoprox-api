import json
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import requests

from geoprox import core


class OverpassTests(unittest.TestCase):
    def setUp(self):
        self.query = core.QueryInput(52.520986, -1.507158, 100, ["manufacturing"])
        for name, value in (
            ("OVERPASS_ENDPOINTS", ["https://first.example/api/interpreter", "https://second.example/api/interpreter"]),
            ("log", Mock()),
            ("time", Mock()),
        ):
            replacement = patch.object(core, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    @staticmethod
    def response(status=200, payload=None):
        response = Mock(status_code=status)
        response.json.return_value = {"elements": []} if payload is None else payload
        return response

    def test_complete_empty_search_is_successful(self):
        with patch.object(core, "_http_post", return_value=self.response()) as post:
            self.assertEqual(core.run_overpass_resilient(self.query), {"elements": []})
        self.assertEqual(post.call_count, 1)
        core.time.sleep.assert_not_called()

    def test_transient_failures_recover_on_second_round(self):
        with patch.object(core, "_http_post", side_effect=[self.response(500), self.response(504), self.response()]) as post:
            self.assertEqual(core.run_overpass_resilient(self.query), {"elements": []})
        self.assertEqual(post.call_count, 3)
        core.time.sleep.assert_called_once_with(2.0)

    def test_partial_results_never_produce_an_assessment(self):
        response = self.response(payload={"elements": [{"type": "node", "id": 1}], "remark": "runtime error: timed out"})
        with patch.object(core, "_http_post", return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError, "No proximity assessment was completed"):
                core.run_overpass_resilient(self.query)
        self.assertEqual(post.call_count, 4)

    def test_access_restrictions_are_not_retried(self):
        with patch.object(core, "_http_post", return_value=self.response(403)) as post:
            with self.assertRaises(RuntimeError):
                core.run_overpass_resilient(self.query)
        self.assertEqual(post.call_count, 2)
        core.time.sleep.assert_not_called()

    def test_invalid_payload_falls_back(self):
        for payload in ([1], {"error": "unavailable"}, {"elements": "invalid"}):
            with self.subTest(payload=payload):
                with patch.object(core, "_http_post", side_effect=[self.response(payload=payload), self.response()]):
                    self.assertEqual(core.run_overpass_resilient(self.query), {"elements": []})

    def test_cancellation_makes_no_request(self):
        with patch.object(core, "_http_post") as post:
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                core.run_overpass_resilient(self.query, lambda: True)
        post.assert_not_called()

    def test_network_errors_do_not_log_provider_key(self):
        secret = "provider-test-key"
        core.OVERPASS_ENDPOINTS = [f"https://provider.example/{secret}/api/interpreter"]
        error = requests.ConnectionError(f"Failed at {core.OVERPASS_ENDPOINTS[0]}")
        with patch.object(core, "_http_post", side_effect=error):
            with self.assertRaises(RuntimeError):
                core.run_overpass_resilient(self.query)
        self.assertNotIn(secret, str(core.log.warning.call_args_list))
        self.assertIn("provider.example", str(core.log.warning.call_args_list))

    def test_endpoint_override_replaces_public_defaults(self):
        environment = dict(os.environ, OVERPASS_ENDPOINTS="https://dedicated.example/key/api/interpreter,\n https://backup.example/api/interpreter")
        result = subprocess.run(
            [sys.executable, "-c", "import json; from geoprox.core import OVERPASS_ENDPOINTS; print(json.dumps(OVERPASS_ENDPOINTS))"],
            env=environment, capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout), [
            "https://dedicated.example/key/api/interpreter",
            "https://backup.example/api/interpreter",
        ])

    def test_overspan_key_selects_authenticated_provider(self):
        environment = dict(os.environ, OVERSPAN_API_KEY="overspan-test-key", OVERPASS_ENDPOINTS="")
        result = subprocess.run(
            [sys.executable, "-c", "import json; from geoprox.core import OVERPASS_ENDPOINTS; print(json.dumps(OVERPASS_ENDPOINTS))"],
            env=environment, capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout), ["https://api.overspan.dev/api/interpreter"])

    def test_overspan_credential_only_sent_to_its_https_host(self):
        with patch.object(core, "OVERSPAN_API_KEY", "overspan-test-key"):
            for url in (
                "https://api.overspan.dev/api/interpreter",
                "https://overpass-api.de/api/interpreter",
                "https://api.overspan.dev.other.example/api/interpreter",
                "http://api.overspan.dev/api/interpreter",
                "https://api.overspan.dev@other.example/api/interpreter",
            ):
                with self.subTest(url=url), patch.object(requests, "post") as post:
                    core._http_post(url, {"data": "test query"})
                    headers = post.call_args.kwargs["headers"]
                    if url == "https://api.overspan.dev/api/interpreter":
                        self.assertEqual(headers["Authorization"], "Bearer overspan-test-key")
                    else:
                        self.assertNotIn("Authorization", headers)

    def test_overspan_without_credential_sends_no_authorization(self):
        with patch.object(core, "OVERSPAN_API_KEY", ""), patch.object(requests, "post") as post:
            core._http_post("https://api.overspan.dev/api/interpreter", {"data": "test query"})
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])


if __name__ == "__main__":
    unittest.main()

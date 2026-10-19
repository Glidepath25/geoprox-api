import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi import HTTPException

from geoprox import core, history_store, main, search_report_store


def sample_data():
    return {"elements": [
        {"type": "node", "id": 1, "lat": 52.520986, "lon": -1.507058,
         "tags": {"power": "substation", "name": "Near substation"}},
        {"type": "way", "id": 2, "geometry": [
            {"lat": 52.5208, "lon": -1.5073}, {"lat": 52.5208, "lon": -1.5050},
            {"lat": 52.5211, "lon": -1.5050}, {"lat": 52.5211, "lon": -1.5073},
            {"lat": 52.5208, "lon": -1.5073},
        ], "tags": {"landuse": "industrial", "name": "Industrial boundary"}},
    ]}


class AssessmentReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out_dir = Path(self.temp.name)
        self.args = dict(location="52.520986,-1.507158", radius_m=100,
                         categories=["manufacturing", "substations"], permit="SAME/PERMIT", out_dir=self.out_dir)
        self.environment = patch.dict(os.environ, {"GEOPROX_BUCKET": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_deferred_assessment_returns_exact_geometry_distances_without_rendering(self):
        with patch.object(core, "run_overpass_resilient", return_value=sample_data()) as query, \
             patch.object(core, "make_map") as html, patch.object(core, "_render_static_map_image") as image, \
             patch.object(core, "generate_pdf_summary") as pdf:
            result = core.run_geoprox_search(**self.args, defer_reports=True)
        query.assert_called_once()
        html.assert_not_called()
        image.assert_not_called()
        pdf.assert_not_called()
        self.assertEqual(result["summary"]["outcome"], "HIGH")
        self.assertEqual(result["artifacts"], {})
        details = result["details_100m"]
        self.assertIsInstance(details[0]["distance_m"], float)
        self.assertEqual(details[0]["name"], "Industrial boundary")
        self.assertEqual(details[0]["distance_m"], 0)
        self.assertGreater(details[1]["distance_m"], 6)
        self.assertLess(details[1]["distance_m"], 8)
        self.assertNotEqual(details[1]["distance_m"], round(details[1]["distance_m"]))
        for i, feature in enumerate(result["map_features"]["features"]):
            self.assertEqual(feature["properties"]["feature_index"], i)
            self.assertEqual(feature["properties"]["distance_m"], details[i]["distance_m"])
        self.assertEqual(result["map_features"]["features"][0]["geometry"]["type"], "Polygon")
        json.dumps(result, allow_nan=False)

    def test_reports_rebuild_from_saved_json_without_a_second_data_query(self):
        with patch.object(core, "run_overpass_resilient", return_value=sample_data()):
            assessment = core.run_geoprox_search(**self.args, defer_reports=True)
        context = assessment.pop("_report_context")
        assessment, context = json.loads(json.dumps([assessment, context]))
        snapshot = copy.deepcopy(assessment)
        with patch.object(core, "run_overpass_resilient") as query, \
             patch.object(core.requests, "get", side_effect=requests.Timeout):
            ready = core.generate_geoprox_reports(assessment, context, out_dir=self.out_dir)
        query.assert_not_called()
        self.assertEqual(ready["summary"], snapshot["summary"])
        self.assertEqual(ready["details_100m"], snapshot["details_100m"])
        pdf = Path(ready["artifacts"]["pdf_path"])
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertTrue(Path(ready["artifacts"]["map_html_path"]).is_file())
        self.assertTrue(Path(ready["artifacts"]["map_image_path"]).is_file())

    def test_synchronous_default_still_renders_and_uses_unique_same_permit_paths(self):
        def write_pdf(**kwargs):
            Path(kwargs["pdf_path"]).write_bytes(b"%PDF test")
        with patch.object(core, "run_overpass_resilient", return_value=sample_data()), \
             patch.object(core, "_render_static_map_image", return_value=None), \
             patch.object(core, "generate_pdf_summary", side_effect=write_pdf) as pdf:
            first = core.run_geoprox_search(**self.args)
            second = core.run_geoprox_search(**self.args)
        self.assertEqual(pdf.call_count, 2)
        self.assertNotIn("_report_context", first)
        for detail in first["details_100m"]:
            self.assertIsInstance(detail["distance_m"], int)
            self.assertIsInstance(detail["distance_m_exact"], float)
            self.assertEqual(detail["distance_m"], round(detail["distance_m_exact"]))
        self.assertNotEqual(first["artifacts"]["pdf_path"], second["artifacts"]["pdf_path"])
        self.assertTrue(Path(first["artifacts"]["pdf_path"]).is_file())

    def test_deferred_report_requires_durable_upload_before_becoming_ready(self):
        with patch.object(core, "run_overpass_resilient", return_value=sample_data()):
            assessment = core.run_geoprox_search(**self.args, defer_reports=True)
        context = assessment.pop("_report_context")
        assessment["report"] = {"status": "pending", "url": "/api/search/reports/test"}
        storage = Mock()
        storage.upload_file.side_effect = RuntimeError("storage unavailable")
        with patch.dict(os.environ, {"GEOPROX_BUCKET": "test-bucket"}), \
             patch("boto3.client", return_value=storage), \
             patch.object(core, "_render_static_map_image", return_value=None), \
             patch.object(core, "generate_pdf_summary"), patch.object(core, "run_overpass_resilient") as query:
            with self.assertRaisesRegex(RuntimeError, "Reports could not be stored"):
                core.generate_geoprox_reports(assessment, context, out_dir=self.out_dir)
        query.assert_not_called()
        self.assertEqual(assessment["artifacts"], {})
        self.assertEqual(assessment["report"]["status"], "pending")

    def test_polygon_boundary_and_verified_site_survive_the_split(self):
        polygon = [[52.5205, -1.508], [52.5205, -1.506], [52.5215, -1.506], [52.5215, -1.508]]
        with patch.object(core, "run_overpass_resilient", return_value={"elements": []}) as query:
            result = core.run_geoprox_search(
                **dict(self.args, location="52.521,-1.507"), defer_reports=True,
                selection_mode="polygon", polygon=polygon,
                extra_locations=[{"id": 7, "name": "Verified site", "category": "substations",
                                  "lat": 52.521, "lon": -1.5059}],
            )
        detail = result["details_100m"][0]
        self.assertEqual(detail["name"], "Verified site")
        self.assertGreater(detail["distance_m"], 6)
        self.assertLess(detail["distance_m"], 8)
        self.assertEqual(result["selection"]["polygon"], polygon)
        self.assertGreater(query.call_args.args[0].radius_m, 100)
        self.assertEqual(result["map_features"]["features"][0]["properties"]["source"], "verified_report")

    def test_exact_band_boundaries_preserve_existing_petrol_and_other_rules(self):
        for tags, label, distances in (
            ({"power": "substation"}, "Sub-Stations", [9.999, 10.0, 24.999, 25.0]),
            ({"amenity": "fuel"}, "Petrol stations / Garages", [24.999, 25.0, 49.999, 50.0]),
        ):
            with self.subTest(category=label):
                frame = core.pd.DataFrame([{"tags": tags, "distance_m": value} for value in distances])
                bins = core.summarise_by_bins(frame, (52.52, -1.50))[label]
                self.assertEqual(bins["<10m"], 1)
                self.assertEqual(bins["10-25m"], 2)
                self.assertEqual(bins["25-100m"], 1)


class ReportEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.owner = "first-user"
        self.request = SimpleNamespace(session={})
        patches = [
            patch.object(history_store, "_DB_PATH", Path(self.temp.name) / "history.db"),
            patch.object(history_store, "USE_POSTGRES", False),
            patch.object(main, "ARTIFACTS_DIR", (Path(self.temp.name) / "artifacts").resolve()),
            patch.object(main, "S3_BUCKET", ""),
            patch.dict(os.environ, {"GEOPROX_BUCKET": ""}),
            patch.object(main, "_require_desktop_user", side_effect=lambda request: self.owner),
            patch.object(main, "_load_w3w_key", return_value=None),
            patch.object(main.user_store, "get_user_by_username", return_value={"username": self.owner}),
            patch.object(main.user_store, "get_license_monthly_limit", return_value=None),
            patch.object(main.report_store, "list_verified_reports", return_value=[]),
            patch.object(core, "run_overpass_resilient", return_value=sample_data()),
            patch.object(core, "_render_static_map_image", return_value=None),
            patch.object(core, "generate_pdf_summary", side_effect=lambda **kw: Path(kw["pdf_path"]).write_bytes(b"%PDF test")),
        ]
        self.mocks = []
        for replacement in patches:
            self.mocks.append(replacement.start())
            self.addCleanup(replacement.stop)
        history_store.init_db()
        search_report_store.init_db()
        self.query = self.mocks[10]

    def search(self):
        response = main.api_search(self.request, main.SearchReq(
            location="52.520986,-1.507158", radius_m=100,
            categories=["manufacturing", "substations"], defer_reports=True,
        ))
        self.assertEqual(response.status, "done", response.error)
        self.assertNotIn("_report_context", response.result)
        self.assertEqual(response.result["report"]["status"], "pending")
        self.assertEqual(history_store.get_monthly_search_count(self.owner), 1)
        return response.result["report"]["url"].rsplit("/", 1)[-1], response.result

    def test_owner_isolation_report_idempotency_and_history_updated_once(self):
        job_id, assessment = self.search()
        self.owner = "another-user"
        with self.assertRaises(HTTPException) as denied:
            main.api_search_reports(self.request, job_id)
        self.assertEqual(denied.exception.status_code, 404)
        self.owner = "first-user"
        with patch.object(main, "generate_geoprox_reports", wraps=core.generate_geoprox_reports) as render:
            ready = main.api_search_reports(self.request, job_id)
            repeat = main.api_search_reports(self.request, job_id)
        self.assertEqual(ready.status, "done")
        self.assertEqual(ready.result["report"]["status"], "ready")
        self.assertEqual(repeat.result["artifacts"], ready.result["artifacts"])
        self.assertEqual(ready.result["summary"], assessment["summary"])
        render.assert_called_once()
        self.query.assert_called_once()
        self.assertEqual(history_store.get_monthly_search_count(self.owner), 1)
        history = history_store.get_history(self.owner)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["pdf_path"], ready.result["artifacts"]["pdf_url"])
        self.assertEqual(history[0]["map_path"], ready.result["artifacts"]["map_url"])

    def test_report_failure_keeps_assessment_and_retries_without_quota_or_query(self):
        job_id, assessment = self.search()
        with patch.object(main, "generate_geoprox_reports", side_effect=RuntimeError("tile failure")), \
             patch.object(main.log, "exception"):
            failed = main.api_search_reports(self.request, job_id)
        self.assertEqual(failed.status, "error")
        self.assertEqual(failed.result["report"]["status"], "error")
        self.assertEqual(failed.result["summary"], assessment["summary"])
        ready = main.api_search_reports(self.request, job_id)
        self.assertEqual(ready.result["report"]["status"], "ready")
        self.query.assert_called_once()
        self.assertEqual(history_store.get_monthly_search_count(self.owner), 1)

    def test_concurrent_claims_only_render_once_and_crashed_request_can_retry(self):
        job_id, _ = self.search()
        with ThreadPoolExecutor(max_workers=4) as executor:
            claims = list(executor.map(lambda _: search_report_store.claim_job(job_id, self.owner), range(4)))
        tokens = [token for token in claims if token]
        self.assertEqual(len(tokens), 1)
        with patch.object(main, "generate_geoprox_reports") as render:
            busy = main.api_search_reports(self.request, job_id)
        render.assert_not_called()
        self.assertEqual(busy.status, "processing")
        self.assertEqual(busy.result["report"]["retry_after_seconds"], 2)
        with history_store._get_conn() as conn:
            conn.execute("UPDATE search_report_jobs SET lease_until = 0 WHERE id = ?", (job_id,))
        new_token = search_report_store.claim_job(job_id, self.owner)
        self.assertTrue(new_token)
        self.assertFalse(search_report_store.finish_job(job_id, self.owner, tokens[0], result={}, status="ready"))
        self.assertTrue(search_report_store.finish_job(job_id, self.owner, new_token, result=busy.result, status="error"))
        self.assertEqual(main.api_search_reports(self.request, job_id).status, "done")

    def test_existing_clients_keep_synchronous_default(self):
        self.assertFalse(main.SearchReq(location="52,-1", radius_m=100).defer_reports)
        response = main.api_search(self.request, main.SearchReq(location="52.520986,-1.507158", radius_m=100))
        self.assertEqual(response.status, "done", response.error)
        self.assertTrue(response.result["artifacts"]["pdf_url"])
        self.assertNotIn("report", response.result)


if __name__ == "__main__":
    unittest.main()

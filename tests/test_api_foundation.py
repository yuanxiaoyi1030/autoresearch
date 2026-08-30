# Purpose: Verifies the Goal 0 loopback API exposes neutral project foundation records.
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import Settings


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


class ApiFoundationTests(unittest.TestCase):
    def test_health_and_generic_topic_project(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            settings = Settings(runtime_root=Path(directory) / "runtime",
                                allowed_import_roots=[Path(directory)])
            with TestClient(create_app(settings)) as client:
                health = client.get("/health")
                self.assertEqual(health.status_code, 200)
                self.assertFalse(health.json()["foundation_only"])
                self.assertEqual(health.json()["llm_status"], "unconfigured")
                response = client.post("/api/projects", json={
                    "title": "Unrelated research",
                    "project_type": "topic_based",
                    "topic": "How does a generic intervention affect a measured outcome?",
                })
                self.assertEqual(response.status_code, 201, response.text)
                payload = response.json()
                self.assertEqual(payload["state"]["stage"], "initializing")
                self.assertNotIn("weight", payload["project"]["topic"].lower())
                listed = client.get("/api/projects").json()
                self.assertEqual(len(listed), 1)

                allowed = client.options("/health", headers={
                    "Origin": "http://127.0.0.1:3000",
                    "Access-Control-Request-Method": "GET",
                })
                self.assertEqual(allowed.status_code, 200)
                self.assertEqual(
                    allowed.headers["access-control-allow-origin"],
                    "http://127.0.0.1:3000",
                )
                denied = client.options("/health", headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                })
                self.assertEqual(denied.status_code, 400)


if __name__ == "__main__":
    unittest.main()

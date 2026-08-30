# Purpose: Verifies process-only credentials and secret-free success/failure API, persistence, logs, and child environments.
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import ENV_PREFIX, Settings
from research_runtime.llm import (
    HTTPResult, LLMRuntime, LLMRuntimeConfig, LLMStage, TransportHTTPError, build_default_registry,
    sanitized_subprocess_environment,
)
from research_runtime.jobs import JobKind
from research_runtime.security import assert_secret_free


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


def runtime_config(base_url="https://provider.example.test/v1"):
    config = {
        "default_route": {
            "model": {
                "provider_id": "user-primary",
                "provider_type": "openai_compatible",
                "model": "user-selected-model",
                "base_url": base_url,
                "protocol": "chat_completions",
                "temperature": 0.3,
                "max_output_tokens": 128,
                "timeout_seconds": 1,
                "retry_count": 0,
                "input_cost_per_million_tokens": 1.0,
                "output_cost_per_million_tokens": 2.0,
            },
            "budget": {
                "max_calls": 5,
                "max_input_tokens": 2000,
                "max_output_tokens": 1000,
                "max_total_tokens": 3000,
                "max_cost_usd": 2.5,
            },
        },
        "stages": {
            "writer": {
                "model": {
                    "provider_id": "user-primary",
                    "provider_type": "openai_compatible",
                    "model": "writer-model",
                    "base_url": base_url,
                    "protocol": "responses",
                    "temperature": 0.1,
                    "max_output_tokens": 512,
                    "timeout_seconds": 2,
                    "retry_count": 1,
                    "input_cost_per_million_tokens": 1.5,
                    "output_cost_per_million_tokens": 3.0,
                },
                "budget": {
                    "max_calls": 9,
                    "max_input_tokens": 9000,
                    "max_output_tokens": 4000,
                    "max_total_tokens": 13000,
                    "max_cost_usd": 4.0,
                },
            }
        },
        "offline_mode": False,
    }
    return config


class SuccessTransport:
    def __init__(self, secret):
        self.secret = secret
        self.headers = []

    def post_json(self, url, headers, payload, timeout_seconds):
        self.headers.append(dict(headers))
        return HTTPResult(status_code=200, headers={"x-request-id": "req_safe"}, data={
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": '{"ok":true,"echo":"' + self.secret + '"}'},
            }],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        })

    def post_sse(self, url, headers, payload, timeout_seconds):
        return iter(())


class FailureTransport:
    def __init__(self, secret):
        self.secret = secret

    def post_json(self, url, headers, payload, timeout_seconds):
        raise TransportHTTPError(
            401,
            f"Authorization: Bearer {self.secret}; api_key={self.secret}",
            {"x-request-id": "req_failed"},
        )

    def post_sse(self, url, headers, payload, timeout_seconds):
        return iter(())


class LLMSecurityApiTests(unittest.TestCase):
    def _app(self, directory, transport=None):
        settings = Settings(runtime_root=Path(directory) / "runtime", allowed_import_roots=[Path(directory)])
        runtime = LLMRuntime(registry=build_default_registry(transport)) if transport is not None else None
        return create_app(settings, llm_runtime=runtime)

    def test_unconfigured_status_and_non_secret_user_configuration(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            with TestClient(self._app(directory)) as client:
                initial = client.get("/api/llm/config")
                self.assertEqual(initial.status_code, 200)
                self.assertEqual(initial.json()["status"]["status"], "unconfigured")
                configured = client.put("/api/llm/config", json=runtime_config())
                self.assertEqual(configured.status_code, 200, configured.text)
                body = configured.json()
                self.assertEqual(body["status"]["status"], "credential_missing")
                self.assertEqual(body["config"]["stages"]["writer"]["model"]["model"], "writer-model")
                self.assertEqual(body["config"]["default_route"]["budget"]["max_cost_usd"], 2.5)
                provider_types = {item["provider_type"] for item in body["providers"]}
                self.assertTrue({"openai", "anthropic", "gemini", "local_openai_compatible"} <= provider_types)

    def test_secret_never_returns_or_persists_on_success(self):
        secret = "sk-success-never-persist-7KX"
        transport = SuccessTransport(secret)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            app = self._app(directory, transport)
            log_output = io.StringIO()
            handler = logging.StreamHandler(log_output)
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            try:
                with TestClient(app) as client:
                    self.assertEqual(client.put("/api/llm/config", json=runtime_config()).status_code, 200)
                    credential = client.put(
                        "/api/llm/credentials/user-primary", json={"api_key": secret},
                    )
                    self.assertEqual(credential.status_code, 200, credential.text)
                    self.assertNotIn(secret, credential.text)
                    self.assertTrue(credential.json()["configured"])
                    self.assertTrue(credential.json()["fingerprint"].startswith("sha256:"))
                    status = client.get("/api/llm/config")
                    self.assertEqual(status.json()["status"]["status"], "ready")
                    self.assertNotIn(secret, status.text)
                    tested = client.post(
                        "/api/llm/connection-tests", json={"stage": "project_understanding"},
                    )
                    self.assertEqual(tested.status_code, 200)
                    self.assertTrue(tested.json()["ok"], tested.text)
                    self.assertNotIn(secret, tested.text)
            finally:
                root_logger.removeHandler(handler)
            self.assertNotIn(secret, log_output.getvalue())
            self.assertEqual(transport.headers[0]["Authorization"], f"Bearer {secret}")
            runtime_files = [path for path in (Path(directory) / "runtime").rglob("*") if path.is_file()]
            self.assertTrue(runtime_files)
            for path in runtime_files:
                self.assertNotIn(secret.encode("utf-8"), path.read_bytes(), str(path))

    def test_failure_error_is_redacted_and_key_is_not_in_sqlite_or_events(self):
        secret = "sk-failure-never-persist-9QZ"
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            app = self._app(directory, FailureTransport(secret))
            with TestClient(app) as client:
                project_response = client.post("/api/projects", json={
                    "title": "Security boundary",
                    "project_type": "topic_based",
                    "topic": "Can persistence reject credentials?",
                })
                project_id = project_response.json()["project"]["project_id"]
                client.put("/api/llm/config", json=runtime_config())
                client.put("/api/llm/credentials/user-primary", json={"api_key": secret})
                response = client.post(
                    "/api/llm/connection-tests", json={"stage": "analysis"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["ok"])
                self.assertIn("[REDACTED]", response.json()["error"])
                self.assertNotIn(secret, response.text)
                config_response = client.get("/api/llm/config")
                self.assertNotIn(secret, config_response.text)
                with self.assertRaisesRegex(ValueError, "credential-like"):
                    app.state.services.events.append(
                        project_id, "unsafe.event", "must reject", payload={"note": secret},
                    )
                with self.assertRaisesRegex(ValueError, "credential-like"):
                    app.state.services.jobs.create(
                        project_id, JobKind.RUN_RESEARCH_STAGE, {"api_key": secret},
                    )
            for path in (Path(directory) / "runtime").rglob("*"):
                if path.is_file():
                    self.assertNotIn(secret.encode("utf-8"), path.read_bytes(), str(path))

    def test_environment_credential_and_child_environment_boundary(self):
        secret = "sk-env-process-only-3LM"
        environment = {
            ENV_PREFIX + "LLM_PROVIDER": "openai_compatible",
            ENV_PREFIX + "LLM_MODEL": "env-model",
            ENV_PREFIX + "LLM_BASE_URL": "https://env.example.test/v1",
            ENV_PREFIX + "LLM_API_KEY": secret,
            "OPENAI_API_KEY": "must-also-be-removed",
            "SAFE_EXPERIMENT_SETTING": "keep-me",
        }
        with patch.dict(os.environ, environment, clear=True):
            runtime = LLMRuntime.from_environment()
            status = runtime.status()
            self.assertTrue(status.ready, status.detail)
            self.assertEqual(status.credentials[0].source, "environment")
            serialized = runtime.config().model_dump_json() + status.model_dump_json()
            self.assertNotIn(secret, serialized)
            child = sanitized_subprocess_environment()
            self.assertEqual(child["SAFE_EXPERIMENT_SETTING"], "keep-me")
            self.assertNotIn(ENV_PREFIX + "LLM_API_KEY", child)
            self.assertNotIn("OPENAI_API_KEY", child)
            self.assertNotIn(secret, str(child))
            for context in ("Agent metadata", "Artifact"):
                with self.assertRaisesRegex(ValueError, "credential-like"):
                    assert_secret_free(
                        {"metadata": {"value": secret}}, [secret], context=context,
                    )

    def test_configured_loopback_openai_compatible_endpoint_uses_real_http_transport(self):
        secret = "sk-loopback-http-contract-5TR"
        observed = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", "0"))
                observed["path"] = self.path
                observed["authorization"] = self.headers.get("authorization")
                observed["payload"] = json.loads(self.rfile.read(length).decode("utf-8"))
                body = json.dumps({
                    "id": "chat_loopback", "choices": [{
                        "finish_reason": "stop", "message": {"content": '{"ok":true}'},
                    }],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}/v1"
            runtime = LLMRuntime()
            runtime.configure(LLMRuntimeConfig.model_validate(runtime_config(base_url)))
            runtime.set_credential("user-primary", secret)
            result = runtime.test_connection(LLMStage.PROJECT_UNDERSTANDING)
            self.assertTrue(result.ok, result.error)
            self.assertEqual(observed["path"], "/v1/chat/completions")
            self.assertEqual(observed["authorization"], f"Bearer {secret}")
            self.assertEqual(observed["payload"]["model"], "user-selected-model")
            self.assertEqual(observed["payload"]["response_format"]["type"], "json_schema")
            self.assertNotIn(secret, result.model_dump_json())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

# Purpose: Verifies read-only v0.1 import, builtin regression, idempotency, confinement, and tamper detection.
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import os
import subprocess
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import Settings


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)
REAL_V0_1_RUNTIME = Path(r"D:\code\work\autoresearch\v_0_1_runtime_data")


def canonical_hash(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_v01_fixture(root: Path) -> Path:
    runtime = root / "v0_1_runtime"
    runtime.mkdir(parents=True)
    database = runtime / "autoresearch.sqlite3"
    with sqlite3.connect(str(database)) as connection:
        connection.executescript("""
        CREATE TABLE experiment_runs(
            run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, job_id TEXT,
            plan_hash TEXT NOT NULL, fixture_id TEXT, status TEXT NOT NULL,
            evidence_eligible INTEGER NOT NULL, config_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL, finished_at TEXT
        );
        CREATE TABLE artifacts(
            artifact_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL,
            kind TEXT NOT NULL, relative_path TEXT NOT NULL, sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL, evidence_eligible INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
        """)
        project_id = "legacy_project"
        job_id = "legacy_job"
        plan_hash = "a" * 64
        for condition, weight_decay in (("baseline", 0.0), ("treatment", 0.001)):
            for seed in (0, 1, 2):
                run_id = f"legacy_{condition}_{seed}"
                artifact_id = f"legacy_metrics_{condition}_{seed}"
                relative = f"runs/{run_id}/artifacts/metrics.json"
                path = runtime / "projects" / project_id / Path(relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                metrics = {
                    "study_id": "weight_decay_condensation_v1",
                    "condition": condition,
                    "seed": seed,
                    "neuron_alignment": 0.4 + seed * 0.01 + (0.1 if condition == "treatment" else 0),
                }
                path.write_text(json.dumps(metrics, sort_keys=True), encoding="utf-8")
                config = {
                    "study_id": "weight_decay_condensation_v1",
                    "condition": condition,
                    "seed": seed,
                    "weight_decay": weight_decay,
                    "paired_initialization_key": f"weight_decay_v1_seed_{seed}",
                    "device": "cpu",
                }
                payload = {
                    "run_id": run_id, "project_id": project_id, "job_id": job_id,
                    "plan_hash": plan_hash, "fixture_id": "weight_decay_condensation_v1",
                    "status": "completed", "evidence_eligible": True,
                    "config_sha256": canonical_hash(config), "config": config,
                    "artifact_ids": [artifact_id],
                    "finished_at": f"2026-01-01T00:00:0{seed}Z",
                }
                connection.execute(
                    "INSERT INTO experiment_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, project_id, job_id, plan_hash,
                        "weight_decay_condensation_v1", "completed", 1,
                        canonical_hash(config), json.dumps(payload), payload["finished_at"],
                    ),
                )
                artifact_payload = {
                    "artifact_id": artifact_id, "project_id": project_id,
                    "run_id": run_id, "kind": "metrics", "relative_path": relative,
                    "sha256": file_hash(path), "size_bytes": path.stat().st_size,
                    "media_type": "application/json", "evidence_eligible": True,
                }
                connection.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        artifact_id, project_id, run_id, "metrics", relative,
                        artifact_payload["sha256"], artifact_payload["size_bytes"], 1,
                        json.dumps(artifact_payload),
                    ),
                )
    return runtime


class V01CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temporary.name)
        self.v0_1 = create_v01_fixture(self.root)
        self.settings = Settings(
            runtime_root=self.root / "v0_2_runtime",
            allowed_import_roots=[self.root],
            v0_1_runtime_root=self.v0_1,
        )
        self.client_context = TestClient(create_app(self.settings))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_builtin_import_is_read_only_idempotent_persistent_and_tamper_evident(self):
        database = self.v0_1 / "autoresearch.sqlite3"
        before = file_hash(database)
        builtins = self.client.get("/api/builtins")
        self.assertEqual(builtins.status_code, 200, builtins.text)
        self.assertEqual(builtins.json()[0]["builtin_id"], "builtin/weight_decay_v1")
        response = self.client.post("/api/compatibility/v0.1/imports/weight-decay-v1")
        self.assertEqual(response.status_code, 201, response.text)
        record = response.json()
        self.assertEqual(len(record["runs"]), 6)
        self.assertEqual(len(record["artifacts"]), 6)
        self.assertTrue(record["source_integrity_unchanged"])
        self.assertEqual(before, file_hash(database))
        self.assertFalse(database.with_name(database.name + "-wal").exists())
        self.assertFalse(database.with_name(database.name + "-journal").exists())

        reused = self.client.post("/api/compatibility/v0.1/imports/weight-decay-v1")
        self.assertEqual(reused.status_code, 201, reused.text)
        self.assertEqual(
            reused.json()["compatibility_import_id"], record["compatibility_import_id"],
        )
        verified = self.client.post(
            f"/api/compatibility/v0.1/imports/{record['compatibility_import_id']}/verify"
        )
        self.assertTrue(verified.json()["passed"], verified.text)
        first = record["artifacts"][0]
        content = self.client.get(
            f"/api/compatibility/v0.1/imports/{record['compatibility_import_id']}/artifacts/"
            f"{first['legacy_artifact_id']}/content"
        )
        self.assertEqual(content.status_code, 200, content.text)
        self.assertEqual(hashlib.sha256(content.content).hexdigest(), first["imported_sha256"])

        restarted_context = TestClient(create_app(self.settings))
        with restarted_context as restarted:
            listed = restarted.get("/api/compatibility/v0.1/imports").json()
            self.assertEqual([item["compatibility_import_id"] for item in listed], [
                record["compatibility_import_id"],
            ])

        copied = self.settings.runtime_root / Path(first["imported_relative_path"])
        copied.write_text("tampered", encoding="utf-8")
        failed = self.client.post(
            f"/api/compatibility/v0.1/imports/{record['compatibility_import_id']}/verify"
        )
        self.assertFalse(failed.json()["passed"])
        self.assertEqual(self.client.get(
            f"/api/compatibility/v0.1/imports/{record['compatibility_import_id']}/artifacts/"
            f"{first['legacy_artifact_id']}/content"
        ).status_code, 409)
        self.assertEqual(before, file_hash(database))

    def test_traversal_and_symlink_escape_are_rejected_without_source_mutation(self):
        database = self.v0_1 / "autoresearch.sqlite3"
        with sqlite3.connect(str(database)) as connection:
            connection.execute(
                "UPDATE artifacts SET relative_path='../../outside.json' WHERE artifact_id=?",
                ("legacy_metrics_baseline_0",),
            )
        before = file_hash(database)
        traversal = self.client.post("/api/compatibility/v0.1/imports/weight-decay-v1")
        self.assertEqual(traversal.status_code, 422, traversal.text)
        self.assertIn("confined", traversal.json()["detail"])
        self.assertEqual(before, file_hash(database))

        other = self.root / "symlink_case"
        symlink_runtime = create_v01_fixture(other)
        source = (
            symlink_runtime / "projects" / "legacy_project" / "runs" /
            "legacy_baseline_0" / "artifacts" / "metrics.json"
        )
        artifact_directory = source.parent
        outside_directory = other / "outside_artifacts"
        artifact_directory.replace(outside_directory)
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(artifact_directory), str(outside_directory)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        symlink_settings = Settings(
            runtime_root=other / "v0_2_runtime", allowed_import_roots=[other],
            v0_1_runtime_root=symlink_runtime,
        )
        try:
            with TestClient(create_app(symlink_settings)) as client:
                escaped = client.post("/api/compatibility/v0.1/imports/weight-decay-v1")
                self.assertEqual(escaped.status_code, 422, escaped.text)
                self.assertIn("symlink or reparse", escaped.json()["detail"])
        finally:
            if artifact_directory.exists():
                os.rmdir(str(artifact_directory))
        outside = outside_directory / "metrics.json"
        self.assertEqual(outside.read_bytes(), json.dumps({
            "condition": "baseline", "neuron_alignment": 0.4, "seed": 0,
            "study_id": "weight_decay_condensation_v1",
        }, sort_keys=True).encode("utf-8"))


class RealV01CompatibilityAcceptance(unittest.TestCase):
    def test_real_v0_1_weight_decay_runtime_imports_without_mutation(self):
        self.assertTrue(REAL_V0_1_RUNTIME.is_dir(), "required v0.1 runtime is unavailable")
        database = REAL_V0_1_RUNTIME / "autoresearch.sqlite3"
        before = file_hash(database)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            root = Path(directory)
            settings = Settings(
                runtime_root=root / "v0_2_runtime", allowed_import_roots=[root],
                v0_1_runtime_root=REAL_V0_1_RUNTIME,
            )
            with TestClient(create_app(settings)) as client:
                response = client.post("/api/compatibility/v0.1/imports/weight-decay-v1")
                self.assertEqual(response.status_code, 201, response.text)
                record = response.json()
                self.assertEqual(record["builtin_id"], "builtin/weight_decay_v1")
                self.assertEqual(
                    {(item["condition"], item["seed"]) for item in record["runs"]},
                    {(condition, seed) for condition in ("baseline", "treatment") for seed in (0, 1, 2)},
                )
                self.assertGreaterEqual(len(record["artifacts"]), 54)
                verification = client.post(
                    f"/api/compatibility/v0.1/imports/{record['compatibility_import_id']}/verify"
                )
                self.assertTrue(verification.json()["passed"], verification.text)
                self.assertEqual(
                    record["source_database_sha256_before"],
                    record["source_database_sha256_after"],
                )
        self.assertEqual(before, file_hash(database))


if __name__ == "__main__":
    unittest.main()

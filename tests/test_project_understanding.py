# Purpose: Verifies generic A/B understanding, static-only legacy inspection, reuse strategies, lineage, and visualization persistence.
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import Settings
from research_runtime.imports import sha256_file


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


class ProjectUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.settings = Settings(
            runtime_root=self.root / "runtime",
            allowed_import_roots=[self.allowed],
        )
        self.app = create_app(self.settings)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_arbitrary_topic_contexts_preserve_topic_and_constraints(self):
        topics = [
            (
                "How does urban tree canopy coverage affect pedestrian heat exposure?",
                {"compute_budget": "CPU only", "time_budget": "two hours", "network_allowed": False},
            ),
            (
                "Can adaptive error correction reduce packet loss in intermittent sensor networks?",
                {
                    "allowed_dependencies": ["stdlib"],
                    "methodological_constraints": ["Report uncertainty intervals"],
                    "output_requirements": ["Reproducible table"],
                },
            ),
            (
                "Which archival features best predict manuscript preservation outcomes?",
                {"data_constraints": ["No personally identifying data"]},
            ),
        ]
        for index, (topic, constraints) in enumerate(topics):
            created = self.client.post("/api/projects", json={
                "title": f"Synthetic topic {index}", "project_type": "topic_based", "topic": topic,
            })
            self.assertEqual(created.status_code, 201, created.text)
            project_id = created.json()["project"]["project_id"]
            response = self.client.post(
                f"/api/projects/{project_id}/understanding",
                json={"constraints": constraints},
            )
            self.assertEqual(response.status_code, 201, response.text)
            context = response.json()["context"]
            self.assertEqual(context["mode"], "topic_based")
            self.assertEqual(context["topic"], topic)
            self.assertEqual(context["research_questions"], [topic])
            self.assertEqual(context["materials"], [])
            for key, value in constraints.items():
                self.assertEqual(context["user_constraints"][key], value)
            persisted = self.client.get(f"/api/projects/{project_id}/understanding")
            self.assertEqual(persisted.json()["context"]["context_id"], context["context_id"])

    def test_python_package_project_static_understanding_lineage_and_visualization(self):
        source = self.allowed / "package_project"
        (source / "src").mkdir(parents=True)
        (source / "config").mkdir()
        (source / "data").mkdir()
        (source / "results").mkdir()
        (source / "figures").mkdir()
        (source / "paper").mkdir()
        sentinel = self.root / "must_not_be_created_by_import.txt"
        (source / "README.md").write_text(
            "# River Sensor Study\n\nResearch question: Does calibrated sensing reduce river-level forecast error?\n"
            "Objective: Compare calibrated and raw sensing pipelines.\n"
            "Conclusion: The legacy run reports lower RMSE, but it has not been reproduced.\n",
            encoding="utf-8",
        )
        (source / "src" / "modeling.py").write_text(
            "from pathlib import Path\nimport numpy as np\n"
            f"Path({str(sentinel)!r}).write_text('EXECUTED')\n"
            "def train_forecaster(data):\n    return np.mean(data)\n"
            "def evaluate_rmse(prediction, target):\n    return float(np.sqrt(np.mean((prediction-target)**2)))\n",
            encoding="utf-8",
        )
        (source / "src" / "visualize.py").write_text(
            "import matplotlib.pyplot as plt\n"
            "def plot_results(x, y):\n"
            "    fig, ax = plt.subplots(figsize=(6.5, 4.0), constrained_layout=True)\n"
            "    ax.plot(x, y, color='#336699', marker='o', linestyle='--')\n"
            "    fig.savefig('forecast.pdf', dpi=240)\n",
            encoding="utf-8",
        )
        (source / "config" / "experiment.yaml").write_text(
            "model: linear\nseed: 17\nbatch_size: 32\nmetric: rmse\n",
            encoding="utf-8",
        )
        (source / "data" / "observations.csv").write_text(
            "time,level\n0,1.2\n1,1.5\n", encoding="utf-8",
        )
        (source / "results" / "metrics.json").write_text(
            '{"rmse": 0.31, "status": "legacy result"}', encoding="utf-8",
        )
        (source / "figures" / "forecast.png").write_bytes(b"legacy-png-placeholder")
        (source / "paper" / "manuscript.tex").write_text(
            "\\section{Results} Legacy results require verification.", encoding="utf-8",
        )
        before = self._source_fingerprint(source)

        project_id, import_id = self._create_import(source, "Package project")
        response = self.client.post(
            f"/api/projects/{project_id}/understanding",
            json={"constraints": {"compute_budget": "one CPU", "network_allowed": False}},
        )
        self.assertEqual(response.status_code, 201, response.text)
        bundle = response.json()
        context = bundle["context"]
        assessment = bundle["legacy_reuse_assessment"]
        self.assertEqual(context["mode"], "existing_project")
        self.assertEqual(context["import_id"], import_id)
        self.assertTrue(any("calibrated sensing" in item.lower() for item in context["research_questions"]))
        inventory = {
            kind for material in context["materials"] for kind in material["kinds"]
        }
        self.assertTrue({
            "code", "config", "data", "experiment", "metric", "result", "paper", "figure",
            "plotting_code",
        } <= inventory)
        self.assertIn("numpy", context["detected_dependencies"])
        self.assertTrue(any("train" in item.lower() for item in context["detected_experiments"]))
        self.assertTrue(any("rmse" in item.lower() for item in context["detected_metrics"]))
        self.assertEqual(assessment["recommended_strategy"], "adapt_existing")
        self.assertTrue(assessment["requires_user_approval"])
        self.assertIn("semantic changes require", assessment["approval_summary"])
        persisted_assessment = self.client.get(
            f"/api/projects/{project_id}/understanding/{context['context_id']}/reuse-assessment"
        )
        self.assertEqual(persisted_assessment.status_code, 200, persisted_assessment.text)
        self.assertEqual(persisted_assessment.json()["assessment_id"], assessment["assessment_id"])
        figure = next(
            item for item in context["materials"] if item["relative_path"] == "figures/forecast.png"
        )
        self.assertTrue(figure["legacy"])
        self.assertEqual(figure["verification_status"], "unverified")
        self.assertFalse(figure["evidence_eligible"])
        self.assertTrue(figure["source_data_available"])
        self.assertFalse(figure["candidate_execution_allowed"])
        profiles = bundle["visualization_profiles"]
        self.assertEqual(len(profiles), 1)
        profile = profiles[0]
        self.assertIn("#336699", profile["colors"])
        self.assertIn([6.5, 4.0], profile["figure_sizes_inches"])
        self.assertIn(240, profile["dpi_values"])
        self.assertIn("pdf", profile["output_formats"])
        self.assertFalse(sentinel.exists(), "static understanding executed imported Python")
        self.assertEqual(before, self._source_fingerprint(source))

        lineage_response = self.client.post(f"/api/projects/{project_id}/code-lineage", json={
            "context_id": context["context_id"],
            "source_relative_path": "src/modeling.py",
            "derived_workspace_path": "candidates/modeling.py",
            "strategy": "adapt_existing",
        })
        self.assertEqual(lineage_response.status_code, 201, lineage_response.text)
        lineage = lineage_response.json()
        self.assertFalse(lineage["has_semantic_changes"])
        self.assertFalse(lineage["execution_eligible"])
        candidate = self.root / "runtime" / "projects" / project_id / "workspace" / "candidates" / "modeling.py"
        self.assertTrue(candidate.is_file())
        self.assertEqual(sha256_file(candidate), lineage["derived_sha256"])
        self.assertEqual(before, self._source_fingerprint(source))
        persisted_lineage = self.client.get(f"/api/projects/{project_id}/code-lineage").json()
        self.assertEqual(persisted_lineage[0]["lineage_id"], lineage["lineage_id"])

        spec_response = self.client.post(f"/api/projects/{project_id}/figure-specs", json={
            "context_id": context["context_id"],
            "title": "Forecast error comparison",
            "purpose": "Compare verified forecast error after reproduction",
            "visualization_profile_id": profile["profile_id"],
            "panels": [{
                "panel_id": "a", "purpose": "Show RMSE by pipeline", "metrics": ["rmse"],
                "input_artifact_ids": [],
            }],
            "legacy_reference_paths": ["figures/forecast.png"],
            "caption": "Planned figure; values require verified artifacts.",
        })
        self.assertEqual(spec_response.status_code, 201, spec_response.text)
        listed_specs = self.client.get(f"/api/projects/{project_id}/figure-specs").json()
        self.assertEqual(listed_specs[0]["figure_spec_id"], spec_response.json()["figure_spec_id"])
        listed_profiles = self.client.get(f"/api/projects/{project_id}/visualization-profiles").json()
        self.assertEqual(listed_profiles[0]["profile_id"], profile["profile_id"])
        with TestClient(create_app(self.settings)) as restarted:
            restarted_lineage = restarted.get(f"/api/projects/{project_id}/code-lineage").json()
            restarted_profiles = restarted.get(f"/api/projects/{project_id}/visualization-profiles").json()
            restarted_specs = restarted.get(f"/api/projects/{project_id}/figure-specs").json()
            self.assertEqual(restarted_lineage[0]["lineage_id"], lineage["lineage_id"])
            self.assertEqual(restarted_profiles[0]["profile_id"], profile["profile_id"])
            self.assertEqual(restarted_specs[0]["figure_spec_id"], spec_response.json()["figure_spec_id"])

    def test_notebook_project_is_partial_refactor_and_code_is_never_executed(self):
        source = self.allowed / "notebook_project"
        (source / "notebooks").mkdir(parents=True)
        (source / "images").mkdir()
        sentinel = self.root / "notebook_execution_sentinel.txt"
        notebook = {
            "cells": [
                {
                    "cell_type": "markdown", "metadata": {},
                    "source": [
                        "# Habitat analysis\n",
                        "Research question: Do seasonal habitat changes alter migration timing?\n",
                        "Figure 1: Legacy migration timing overview.\n",
                    ],
                },
                {
                    "cell_type": "code", "metadata": {}, "execution_count": 9, "outputs": [],
                    "source": [
                        "from pathlib import Path\n",
                        "import pandas as pd\n",
                        "import matplotlib.pyplot as plt\n",
                        f"Path({str(sentinel)!r}).write_text('EXECUTED')\n",
                        "fig, ax = plt.subplots(figsize=(8, 5))\n",
                        "ax.scatter([1], [2], color='navy', marker='x')\n",
                        "plt.savefig('migration.svg', dpi=180)\n",
                    ],
                },
            ],
            "metadata": {"kernelspec": {"name": "python3"}},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        (source / "notebooks" / "analysis.ipynb").write_text(
            json.dumps(notebook), encoding="utf-8",
        )
        (source / "images" / "migration.svg").write_text(
            '<svg width="800" height="500"><path stroke="#224466"/></svg>', encoding="utf-8",
        )
        before = self._source_fingerprint(source)
        project_id, _ = self._create_import(source, "Notebook project")
        response = self.client.post(f"/api/projects/{project_id}/understanding", json={})
        self.assertEqual(response.status_code, 201, response.text)
        bundle = response.json()
        self.assertEqual(
            bundle["legacy_reuse_assessment"]["recommended_strategy"], "partial_refactor",
        )
        context = bundle["context"]
        notebook_material = next(
            item for item in context["materials"] if item["relative_path"].endswith(".ipynb")
        )
        self.assertIn("notebook", notebook_material["kinds"])
        figure = next(item for item in context["materials"] if "figure" in item["kinds"])
        self.assertFalse(figure["source_data_available"])
        self.assertEqual(
            set(figure["allowed_uses"]), {"style_reference", "preliminary_observation"},
        )
        self.assertTrue(any("source data" in item.lower() for item in context["missing_evidence"]))
        self.assertFalse(sentinel.exists(), "static notebook inspection executed a cell")
        self.assertEqual(before, self._source_fingerprint(source))

    def test_document_only_project_selects_safe_reimplementation(self):
        source = self.allowed / "document_project"
        source.mkdir()
        (source / "study_notes.md").write_text(
            "Research question: Can a revised survey improve response completeness?\n"
            "Conclusion: A preliminary legacy note reports improvement.\n",
            encoding="utf-8",
        )
        (source / "legacy_chart.png").write_bytes(b"no-source-data")
        project_id, _ = self._create_import(source, "Document-only project")
        response = self.client.post(f"/api/projects/{project_id}/understanding", json={})
        self.assertEqual(response.status_code, 201, response.text)
        assessment = response.json()["legacy_reuse_assessment"]
        self.assertEqual(assessment["recommended_strategy"], "safe_reimplementation")
        self.assertTrue(any("No reusable executable source" in item for item in response.json()["context"]["missing_evidence"]))

    def test_path_symlink_execution_and_semantic_revision_gates(self):
        source = self.allowed / "boundary_project"
        source.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "outside.py").write_text("raise RuntimeError('must not run')\n", encoding="utf-8")
        (source / "runner.py").write_text(
            "def train_model():\n    return 1\n", encoding="utf-8",
        )
        source_link = source / "linked_directory"
        self._create_junction(source_link, outside)
        try:
            project_id, import_id = self._create_import(source, "Boundary project")
            manifest = self.app.state.services.imports.get_manifest(import_id)
            self.assertFalse(any(
                item.relative_path.startswith("linked_directory/") for item in manifest.files
            ))
            self.assertTrue(any(
                item.reason == "symlink_or_reparse_directory" for item in manifest.excluded
            ))
        finally:
            os.rmdir(source_link)
        response = self.client.post(f"/api/projects/{project_id}/understanding", json={})
        self.assertEqual(response.status_code, 201, response.text)
        context_id = response.json()["context"]["context_id"]

        traversal = self.client.post(f"/api/projects/{project_id}/code-lineage", json={
            "context_id": context_id,
            "source_relative_path": "runner.py",
            "derived_workspace_path": "../escape.py",
            "strategy": "adapt_existing",
        })
        self.assertEqual(traversal.status_code, 422)
        source_traversal = self.client.post(f"/api/projects/{project_id}/code-lineage", json={
            "context_id": context_id,
            "source_relative_path": "../outside/outside.py",
            "derived_workspace_path": "candidate.py",
            "strategy": "adapt_existing",
        })
        self.assertEqual(source_traversal.status_code, 422)

        initial = self.client.post(f"/api/projects/{project_id}/code-lineage", json={
            "context_id": context_id,
            "source_relative_path": "runner.py",
            "derived_workspace_path": "candidate/runner.py",
            "strategy": "adapt_existing",
        })
        self.assertEqual(initial.status_code, 201, initial.text)
        candidate = self.root / "runtime" / "projects" / project_id / "workspace" / "candidate" / "runner.py"
        candidate.write_text(
            "def train_model(optimizer='new'):\n    return optimizer\n", encoding="utf-8",
        )
        semantic = {
            "context_id": context_id,
            "source_relative_path": "runner.py",
            "derived_workspace_path": "candidate/runner.py",
            "strategy": "partial_refactor",
            "copy_from_snapshot": False,
            "base_plan_revision": 3,
            "modifications": [{
                "classification": "semantic", "category": "optimizer",
                "summary": "Changed the optimizer contract.",
            }],
        }
        rejected = self.client.post(f"/api/projects/{project_id}/code-lineage", json=semantic)
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertIn("newer Experiment Plan revision", rejected.text)
        semantic["target_plan_revision"] = 4
        accepted = self.client.post(f"/api/projects/{project_id}/code-lineage", json=semantic)
        self.assertEqual(accepted.status_code, 201, accepted.text)
        self.assertTrue(accepted.json()["has_semantic_changes"])
        self.assertFalse(accepted.json()["execution_eligible"])

        workspace = self.root / "runtime" / "projects" / project_id / "workspace"
        workspace_link = workspace / "escape_link"
        self._create_junction(workspace_link, outside)
        try:
            linked_target = self.client.post(f"/api/projects/{project_id}/code-lineage", json={
                "context_id": context_id,
                "source_relative_path": "runner.py",
                "derived_workspace_path": "escape_link/outside.py",
                "strategy": "adapt_existing",
                "copy_from_snapshot": False,
            })
            self.assertEqual(linked_target.status_code, 422)
            self.assertIn("symlink", linked_target.text.lower())
        finally:
            os.rmdir(workspace_link)

    def _create_import(self, source: Path, title: str):
        created = self.client.post("/api/projects", json={
            "title": title,
            "project_type": "existing_project",
            "source_root": str(source),
        })
        self.assertEqual(created.status_code, 201, created.text)
        project_id = created.json()["project"]["project_id"]
        imported = self.client.post(
            f"/api/projects/{project_id}/imports", json={"source_root": str(source)},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        return project_id, imported.json()["import_id"]

    @staticmethod
    def _source_fingerprint(source: Path):
        return {
            path.relative_to(source).as_posix(): sha256_file(path)
            for path in source.rglob("*") if path.is_file() and not path.is_symlink()
        }

    @staticmethod
    def _create_junction(link: Path, target: Path):
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
            check=False, capture_output=True, text=True,
        )
        if result.returncode != 0 or not link.exists():
            raise AssertionError(f"failed to create isolated test junction: {result.stderr or result.stdout}")


if __name__ == "__main__":
    unittest.main()

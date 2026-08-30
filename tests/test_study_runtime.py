# Purpose: Verifies generic A/B Study implementation, safe execution, controls, recovery, lineage, figures, and hashes.
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import Settings
from research_runtime.experiments import (
    AgentResponse, EngineerCodePackage, ExperimentRunStatus, ExperimentalLead,
    ImplementationFile, ImplementationTask, ImplementationTaskGraph, LegacyCodeMapping,
    ResearchEngineer,
)
from research_runtime.literature import (
    AccessLevel, EvidenceRole, LiteratureEvidence, LiteratureEvidenceMatrix,
    LiteratureProvider, LiteratureQuery, LiteratureQueryPlan, LiteratureSource, ResearchGap,
)
from research_runtime.planning import PlannedModification
from research_runtime.understanding import ModificationCategory, ModificationClass
from tests.test_hypothesis_planning import ScriptedCriticalReviewer, ScriptedDesignLead


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


RUNNER_SOURCE = r'''import json
import os
from pathlib import Path
import sys
import time

config = json.loads(Path(os.environ["AUTORESEARCH_CONFIG_PATH"]).read_text(encoding="utf-8"))
artifact_dir = Path(os.environ["AUTORESEARCH_ARTIFACT_DIR"])
profile_path = Path(os.environ["AUTORESEARCH_VISUALIZATION_PROFILE_PATH"])
smoke = bool(config.get("smoke"))
delay = float(config.get("smoke_overrides", {}).get("delay_seconds", 0))
if delay:
    time.sleep(delay)
parameters = config["run_spec"].get("parameters", {})
condition_value = next(iter(parameters.values()), "target")
sensitive_marker = "API" + "KEY"
sensitive_present = any(sensitive_marker in name.upper() or "TOKEN" in name.upper() for name in os.environ)
metrics = {
    "smoke": smoke,
    "condition": condition_value,
    "sensitive_env_present": sensitive_present,
    "value": 1.25 if condition_value == "target" else 0.75,
}
(artifact_dir / "metrics.json").write_text(json.dumps(metrics, sort_keys=True), encoding="utf-8")
profile = json.loads(profile_path.read_text(encoding="utf-8"))
if profile.get("profile_id"):
    color = (profile.get("colors") or ["#336699"])[0]
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><path stroke="' + color + '" d="M0 80 L200 20"/></svg>'
    (artifact_dir / "result.svg").write_text(svg, encoding="utf-8")
    manifest = {
        "profile_id": profile["profile_id"],
        "profile_hash": profile["approved_profile_hash"],
        "figures": {"result.svg": {"inputs": ["metrics.json"]}},
    }
    (artifact_dir / "figure_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
print(json.dumps({"status": "completed", "smoke": smoke}))
print("runtime diagnostic", file=sys.stderr)
if not smoke and condition_value == "reference":
    raise SystemExit(7)
'''


class ScriptedExperimentalLead(ExperimentalLead):
    def create_tasks(self, context, hypothesis, plan):
        run_ids = [item.run_spec_id for item in plan.plan.runs]
        return AgentResponse(ImplementationTaskGraph(
            model_specification="Implement the approved two-condition estimator without adding variables.",
            objective_function="Compute the approved primary metric for every RunSpec.",
            implementation_strategy="One deterministic JSON-configured Python runner.",
            tasks=[ImplementationTask(
                title="Implement approved run matrix",
                scientific_purpose="Evaluate the selected approved Hypothesis.",
                implementation_requirements=["Read runtime JSON config", "Write metrics Artifact"],
                plan_run_spec_ids=run_ids,
                expected_artifacts=["metrics.json", "optional approved-profile figure"],
            )],
            entrypoint="runner.py",
            required_artifacts=["metrics.json", "stdout", "stderr", "environment"],
            plan_conformance_checks=["RunSpec IDs unchanged", "No unapproved variables"],
        ), "1" * 64)


class ScriptedResearchEngineer(ResearchEngineer):
    def implement(self, context, hypothesis, plan, tasks, visualization_profile):
        files = [ImplementationFile(
            relative_path="runner.py", content=RUNNER_SOURCE,
            purpose="Deterministic approved Study entrypoint.",
        )]
        mappings = []
        binding = plan.plan.b_mode_binding
        if binding is not None:
            for decision in binding.code_reuse_decisions:
                suffix = Path(decision.source_relative_path).suffix.lower()
                target = "adapted/" + decision.source_relative_path
                if suffix == ".py":
                    content = (
                        "# Adapted legacy module; never imported by the runtime entrypoint.\n"
                        "def preserved_design_reference():\n    return 'verified mapping only'\n"
                    )
                else:
                    content = json.dumps({"adapted_from": decision.source_relative_path})
                files.append(ImplementationFile(
                    relative_path=target, content=content,
                    purpose="Workspace-confined derivative of approved legacy source.",
                ))
                mappings.append(LegacyCodeMapping(
                    source_relative_path=decision.source_relative_path,
                    derived_relative_path=target, action=decision.action.value,
                    modifications=[PlannedModification.model_validate(
                        item.model_dump(mode="json")
                    ) for item in decision.modifications],
                ))
        extra = []
        topic = (context.topic or context.summary).casefold()
        if "semantic divergence" in topic:
            extra = [PlannedModification(
                classification=ModificationClass.SEMANTIC,
                category=ModificationCategory.HYPERPARAMETER,
                summary="Proposed an unapproved change to the experimental threshold.",
            )]
        return AgentResponse(EngineerCodePackage(
            entrypoint="runner.py", files=files, declared_dependencies=[],
            smoke_config={"delay_seconds": 0.8}, legacy_mappings=mappings,
            implementation_modifications=extra,
            verification_notes=["Uses fixed runtime contract and writes only Artifact outputs."],
        ), "2" * 64)


class StudyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.settings = Settings(
            runtime_root=self.root / "runtime", allowed_import_roots=[self.allowed],
        )
        self.app = create_app(
            self.settings,
            research_design_lead=ScriptedDesignLead(),
            critical_reviewer=ScriptedCriticalReviewer(),
            experimental_lead=ScriptedExperimentalLead(),
            research_engineer=ScriptedResearchEngineer(),
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        deadline = time.time() + 5
        while self.app.state.services.study_runtime._threads and time.time() < deadline:
            time.sleep(0.05)
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_non_domain_specific_study_smoke_formal_failure_pause_resume_and_artifacts(self):
        previous = os.environ.get("AUTORESEARCH_TEST_API_KEY")
        os.environ["AUTORESEARCH_TEST_API_KEY"] = "must-not-reach-study"
        try:
            project_id, plan = self._approved_topic_plan(
                "Calibration", "Robust calibration effects on river sensor forecast error",
            )
            created = self.client.post(f"/api/projects/{project_id}/studies", json={
                "plan_revision_id": plan["plan_revision_id"],
            })
            self.assertEqual(created.status_code, 201, created.text)
            payload = created.json()
            study = payload["study"]
            self.assertIsNotNone(study)
            self.assertEqual(payload["implementation"]["status"], "verified")
            self.assertRegex(study["code_tree_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                {item["role"] for item in payload["agent_runs"]},
                {"experimental_lead", "research_engineer"},
            )
            run_specs = plan["plan"]["runs"]
            target = next(item for item in run_specs if "target" in item["parameters"].values())
            reference = next(item for item in run_specs if "reference" in item["parameters"].values())

            blocked_formal = self.client.post(
                f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
                json={"run_spec_id": target["run_spec_id"], "smoke": False},
            )
            self.assertEqual(blocked_formal.status_code, 422)
            smoke = self.client.post(
                f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
                json={"run_spec_id": target["run_spec_id"], "smoke": True},
            )
            self.assertEqual(smoke.status_code, 202, smoke.text)
            smoke_detail = self._wait(project_id, smoke.json()["run_id"])
            self.assertEqual(smoke_detail["run"]["status"], "completed", smoke_detail)
            metrics = self._artifact_json(smoke_detail, "metrics")
            self.assertFalse(metrics["sensitive_env_present"])
            self.assertTrue(metrics["smoke"])
            self.assertTrue({"config", "environment", "stdout", "stderr", "metrics"} <= {
                item["kind"] for item in smoke_detail["artifacts"]
            })
            self.assertIn("completed", self._artifact_text(smoke_detail, "stdout"))
            self.assertIn("runtime diagnostic", self._artifact_text(smoke_detail, "stderr"))

            formal = self.client.post(
                f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
                json={"run_spec_id": target["run_spec_id"], "smoke": False},
            )
            formal_detail = self._wait(project_id, formal.json()["run_id"])
            self.assertEqual(formal_detail["run"]["status"], "completed", formal_detail)
            self.assertTrue(next(
                item for item in formal_detail["artifacts"] if item["kind"] == "metrics"
            )["evidence_eligible"])

            failed = self.client.post(
                f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
                json={"run_spec_id": reference["run_spec_id"], "smoke": False},
            )
            failed_detail = self._wait(project_id, failed.json()["run_id"])
            self.assertEqual(failed_detail["run"]["status"], "failed")
            self.assertEqual(failed_detail["run"]["exit_code"], 7)
            self.assertTrue(failed_detail["artifacts"], "failed Run artifacts were discarded")

            pausable = self.client.post(
                f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
                json={"run_spec_id": reference["run_spec_id"], "smoke": True},
            )
            self.assertEqual(pausable.status_code, 202, pausable.text)
            run_id = pausable.json()["run_id"]
            self._wait_for_status(project_id, run_id, {"running"})
            self.assertEqual(self.client.post(
                f"/api/projects/{project_id}/runs/{run_id}/pause"
            ).status_code, 200)
            paused = self._wait_for_status(project_id, run_id, {"paused"})
            resumed = self.client.post(f"/api/projects/{project_id}/runs/{run_id}/resume")
            self.assertEqual(resumed.status_code, 200, resumed.text)
            resumed_detail = self._wait(project_id, resumed.json()["run_id"])
            self.assertEqual(resumed_detail["run"]["status"], "completed")
            self.assertEqual(resumed_detail["run"]["parent_run_id"], paused["run_id"])
            self.assertEqual(resumed_detail["run"]["attempt"], 2)

            metrics_artifact = next(
                item for item in formal_detail["artifacts"] if item["kind"] == "metrics"
            )
            verification = self.client.get(
                f"/api/projects/{project_id}/artifacts/{metrics_artifact['artifact_id']}/verification"
            )
            self.assertTrue(verification.json()["hash_matches"])
            path = self.settings.runtime_root / "projects" / project_id / metrics_artifact["relative_path"]
            path.write_text("tampered", encoding="utf-8")
            self.assertFalse(self.client.get(
                f"/api/projects/{project_id}/artifacts/{metrics_artifact['artifact_id']}/verification"
            ).json()["hash_matches"])
        finally:
            if previous is None:
                os.environ.pop("AUTORESEARCH_TEST_API_KEY", None)
            else:
                os.environ["AUTORESEARCH_TEST_API_KEY"] = previous

    def test_b_mode_copy_adapt_lineage_profile_figure_cancel_and_source_immutability(self):
        source = self.allowed / "legacy_b"
        (source / "src").mkdir(parents=True)
        (source / "results").mkdir()
        sentinel = self.root / "legacy-executed.txt"
        (source / "src" / "experiment.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('executed')\n"
            "def run_experiment(data):\n    return {'score': 0.5}\n",
            encoding="utf-8",
        )
        (source / "src" / "plot.py").write_text(
            "import matplotlib.pyplot as plt\n"
            "def plot(x,y):\n    plt.plot(x,y,color='#336699')\n    plt.savefig('result.svg',dpi=180)\n",
            encoding="utf-8",
        )
        (source / "results" / "metrics.json").write_text('{"score":0.5}', encoding="utf-8")
        before = self._fingerprint(source)
        project_id, plan, context, profiles = self._approved_b_plan(source)
        self.assertTrue(profiles)
        profile = profiles[0]
        approval = self.client.post(
            f"/api/projects/{project_id}/visualization-profiles/{profile['profile_id']}/decision",
            json={"approved": True, "feedback": "Reuse this visual style for new verified figures."},
        )
        self.assertEqual(approval.status_code, 201, approval.text)
        created = self.client.post(f"/api/projects/{project_id}/studies", json={
            "plan_revision_id": plan["plan_revision_id"],
            "visualization_profile_id": profile["profile_id"],
        })
        self.assertEqual(created.status_code, 201, created.text)
        payload = created.json()
        study = payload["study"]
        self.assertTrue(payload["lineage_ids"])
        lineage = self.client.get(f"/api/projects/{project_id}/code-lineage").json()
        self.assertEqual({item["lineage_id"] for item in lineage}, set(payload["lineage_ids"]))
        self.assertTrue(all(item["execution_eligible"] for item in lineage))
        self.assertTrue(all(item["legacy_baseline"] for item in lineage))
        implementation_id = payload["implementation"]["implementation_revision_id"]
        implementation_diff = self.client.get(
            f"/api/projects/{project_id}/implementation-revisions/{implementation_id}/diff"
        )
        self.assertEqual(implementation_diff.status_code, 200, implementation_diff.text)
        self.assertTrue(implementation_diff.json()["entries"])
        self.assertTrue(any(
            item["source_relative_path"] == "src/experiment.py"
            and item["unified_diff"].startswith("--- legacy/src/experiment.py")
            for item in implementation_diff.json()["entries"]
        ))
        imported_source = self.client.get(
            f"/api/projects/{project_id}/imports/{context['import_id']}/files/src/plot.py"
        )
        self.assertEqual(imported_source.status_code, 200, imported_source.text)
        self.assertIn("#336699", imported_source.text)
        escaped_source = self.client.get(
            f"/api/projects/{project_id}/imports/{context['import_id']}/files/../manifest.json"
        )
        self.assertEqual(escaped_source.status_code, 404)
        self.assertEqual(before, self._fingerprint(source))
        self.assertFalse(sentinel.exists(), "legacy source code executed directly")

        target = next(item for item in plan["plan"]["runs"] if "target" in item["parameters"].values())
        smoke = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
            json={"run_spec_id": target["run_spec_id"], "smoke": True},
        )
        smoke_detail = self._wait(project_id, smoke.json()["run_id"])
        self.assertEqual(smoke_detail["run"]["status"], "completed", smoke_detail)
        figure = next(item for item in smoke_detail["artifacts"] if item["kind"] == "figure")
        metrics = next(item for item in smoke_detail["artifacts"] if item["kind"] == "metrics")
        self.assertEqual(figure["visualization_profile_id"], profile["profile_id"])
        self.assertEqual(figure["generated_from_artifact_ids"], [metrics["artifact_id"]])
        logs = self.client.get(
            f"/api/projects/{project_id}/runs/{smoke_detail['run']['run_id']}/logs"
        )
        self.assertEqual(logs.status_code, 200, logs.text)
        self.assertEqual(logs.json()["run_id"], smoke_detail["run"]["run_id"])
        figure_content = self.client.get(
            f"/api/projects/{project_id}/artifacts/{figure['artifact_id']}/content"
        )
        self.assertEqual(figure_content.status_code, 200, figure_content.text)
        self.assertIn(b"<svg", figure_content.content)
        self.assertEqual(before, self._fingerprint(source))

        reference = next(item for item in plan["plan"]["runs"] if "reference" in item["parameters"].values())
        cancellable = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
            json={"run_spec_id": reference["run_spec_id"], "smoke": True},
        )
        cancel_id = cancellable.json()["run_id"]
        self._wait_for_status(project_id, cancel_id, {"running"})
        self.client.post(f"/api/projects/{project_id}/runs/{cancel_id}/cancel")
        cancelled = self._wait_for_status(project_id, cancel_id, {"cancelled"})
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(before, self._fingerprint(source))

    def test_semantic_implementation_is_preserved_and_returns_to_plan_revision(self):
        project_id, plan = self._approved_topic_plan(
            "Semantic gate", "Semantic divergence in a generic intervention experiment",
        )
        created = self.client.post(f"/api/projects/{project_id}/studies", json={
            "plan_revision_id": plan["plan_revision_id"],
        })
        self.assertEqual(created.status_code, 201, created.text)
        payload = created.json()
        self.assertIsNone(payload["study"])
        self.assertEqual(payload["implementation"]["status"], "requires_plan_revision")
        root = self.settings.runtime_root / "projects" / project_id / "workspace" / "implementations"
        self.assertFalse(root.exists(), "unapproved semantic implementation was materialized")

    def test_running_record_is_recovered_as_stale_after_restart(self):
        project_id, plan = self._approved_topic_plan(
            "Recovery", "Recovery behavior for a generic bounded simulation",
        )
        study = self.client.post(f"/api/projects/{project_id}/studies", json={
            "plan_revision_id": plan["plan_revision_id"],
        }).json()["study"]
        run_spec = plan["plan"]["runs"][0]
        smoke = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
            json={"run_spec_id": run_spec["run_spec_id"], "smoke": True},
        )
        completed = self._wait(project_id, smoke.json()["run_id"])["run"]
        model = self.app.state.services.experiment_repository.get_run(completed["run_id"])
        interrupted = model.model_copy(update={
            "run_id": "run_interrupted_restart", "status": ExperimentRunStatus.RUNNING,
            "parent_run_id": model.run_id, "artifact_ids": [], "finished_at": None,
        })
        self.app.state.services.experiment_repository.create_run(interrupted)
        with TestClient(create_app(self.settings)) as restarted:
            recovered = restarted.get(
                f"/api/projects/{project_id}/runs/{interrupted.run_id}"
            )
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()["run"]["status"], "stale")
            self.assertEqual(recovered.json()["run"]["termination_reason"], "service_restart")

    def _approved_topic_plan(self, title, topic):
        created = self.client.post("/api/projects", json={
            "title": title, "project_type": "topic_based", "topic": topic,
        })
        project_id = created.json()["project"]["project_id"]
        context = self.client.post(f"/api/projects/{project_id}/understanding", json={}).json()["context"]
        self._seed_literature(project_id, context["context_id"], topic)
        return project_id, self._approve_planning(project_id)

    def _approved_b_plan(self, source):
        created = self.client.post("/api/projects", json={
            "title": "B-mode synthetic project", "project_type": "existing_project",
            "source_root": str(source),
        })
        project_id = created.json()["project"]["project_id"]
        self.client.post(f"/api/projects/{project_id}/imports", json={"source_root": str(source)})
        bundle = self.client.post(f"/api/projects/{project_id}/understanding", json={}).json()
        context = bundle["context"]
        self._seed_literature(project_id, context["context_id"], context["research_questions"][0])
        plan = self._approve_planning(project_id)
        return project_id, plan, context, bundle["visualization_profiles"]

    def _approve_planning(self, project_id):
        hypothesis_response = self.client.post(f"/api/projects/{project_id}/hypotheses", json={})
        self.assertEqual(hypothesis_response.status_code, 201, hypothesis_response.text)
        hypothesis = hypothesis_response.json()["revision"]
        self.assertEqual(self.client.post(
            f"/api/projects/{project_id}/hypotheses/{hypothesis['hypothesis_revision_id']}/decision",
            json={"decision": "approved", "feedback": "Approve for runtime test.",
                  "selected_candidate_id": hypothesis["recommended_candidate_id"]},
        ).status_code, 201)
        plan_response = self.client.post(f"/api/projects/{project_id}/experiment-plans", json={
            "hypothesis_revision_id": hypothesis["hypothesis_revision_id"],
        })
        self.assertEqual(plan_response.status_code, 201, plan_response.text)
        plan = plan_response.json()["revision"]
        approved = self.client.post(
            f"/api/projects/{project_id}/experiment-plans/{plan['plan_revision_id']}/decision",
            json={"decision": "approved", "feedback": "Approve bounded runtime plan."},
        )
        self.assertEqual(approved.status_code, 201, approved.text)
        return plan

    def _seed_literature(self, project_id, context_id, topic):
        source = LiteratureSource(
            title=f"Prior work on {topic}", abstract="Background evidence.",
            access_level=AccessLevel.ABSTRACT_ONLY, origins=[LiteratureProvider.OPENALEX],
            provider_record_ids={"openalex": "W-RUNTIME"}, existence_verified=True,
            metadata_verified=True,
        )
        self.app.state.services.literature_repository.save_sources(project_id, context_id, [source])
        evidence = LiteratureEvidence(
            project_id=project_id, context_id=context_id, source_id=source.source_id,
            claim="Prior work motivates the bounded experiment.",
            support_summary="Background abstract only.", role=EvidenceRole.BACKGROUND,
            source_access_level=AccessLevel.ABSTRACT_ONLY,
        )
        queries = LiteratureQueryPlan(
            topic=topic, context_id=context_id,
            queries=[
                LiteratureQuery(query=topic + " mechanism", rationale="mechanism",
                                keyword_group=[topic], providers=[LiteratureProvider.ARXIV, LiteratureProvider.OPENALEX]),
                LiteratureQuery(query=topic + " test", rationale="test", keyword_group=[topic],
                                providers=[LiteratureProvider.OPENALEX, LiteratureProvider.CROSSREF]),
            ],
        )
        gap = ResearchGap(
            project_id=project_id, context_id=context_id,
            statement="A controlled test remains needed.", rationale="Evidence is background only.",
            supporting_source_ids=[source.source_id], uncertainty="Further reading may refine design.",
        )
        matrix = LiteratureEvidenceMatrix(
            project_id=project_id, context_id=context_id, query_plan=queries,
            source_ids=[source.source_id], evidence=[evidence], related_work="Background only.",
            research_gaps=[gap],
        )
        evidence.matrix_id = matrix.matrix_id
        gap.matrix_id = matrix.matrix_id
        self.app.state.services.literature_repository.save_matrix(
            LiteratureEvidenceMatrix.model_validate(matrix.model_dump(mode="json"))
        )

    def _wait(self, project_id, run_id, timeout=10):
        detail = self._wait_for_status(project_id, run_id, {
            "completed", "failed", "cancelled", "paused", "timed_out",
            "output_limit_exceeded", "stale",
        }, timeout=timeout)
        return self.client.get(f"/api/projects/{project_id}/runs/{run_id}").json()

    def _wait_for_status(self, project_id, run_id, statuses, timeout=10):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            response = self.client.get(f"/api/projects/{project_id}/runs/{run_id}")
            self.assertEqual(response.status_code, 200, response.text)
            last = response.json()["run"]
            if last["status"] in statuses:
                return last
            time.sleep(0.04)
        self.fail(f"run {run_id} did not reach {statuses}; last={last}")

    def _artifact_json(self, detail, kind):
        artifact = next(item for item in detail["artifacts"] if item["kind"] == kind)
        path = self.settings.runtime_root / "projects" / artifact["project_id"] / artifact["relative_path"]
        return json.loads(path.read_text(encoding="utf-8"))

    def _artifact_text(self, detail, kind):
        artifact = next(item for item in detail["artifacts"] if item["kind"] == kind)
        path = self.settings.runtime_root / "projects" / artifact["project_id"] / artifact["relative_path"]
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _fingerprint(source):
        import hashlib
        return {
            path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source.rglob("*") if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()

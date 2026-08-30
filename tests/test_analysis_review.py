# Purpose: Verifies deterministic multi-structure analysis, independent tamper audit, B fidelity, and preserved outcomes.
import json
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.analysis import (
    AnalysisPayload, AnalysisRecord, ReviewResponse, ScientificRecommendation,
    ScientificReviewDraft, ScientificReviewer,
)
from research_runtime.analysis.service import AnalysisReviewService
from research_runtime.analysis.statistics import DeterministicStatistics
from research_runtime.config import Settings
from research_runtime.experiments import (
    AgentResponse, EngineerCodePackage, ExperimentalLead, ImplementationFile,
    LegacyCodeMapping, ResearchEngineer,
)
from research_runtime.planning import PlannedModification, canonical_hash
from research_runtime.state import ResearchOutcome
from tests import test_study_runtime as study_helpers


ScriptedExperimentalLead = study_helpers.ScriptedExperimentalLead
TEST_TEMP_ROOT = study_helpers.TEST_TEMP_ROOT


ANALYSIS_RUNNER = r'''import json
import os
from pathlib import Path
import sys

config = json.loads(Path(os.environ["AUTORESEARCH_CONFIG_PATH"]).read_text(encoding="utf-8"))
artifact_dir = Path(os.environ["AUTORESEARCH_ARTIFACT_DIR"])
seeds = config["run_spec"]["seeds"]
condition = next(iter(config["run_spec"].get("parameters", {}).values()), "target")
mode = __ANALYSIS_MODE__
observations = []
for index, seed in enumerate(seeds):
    if mode == "independent_supported":
        value = (0.50 + index * 0.02) if condition == "reference" else (0.80 + index * 0.03)
    elif mode == "negative":
        value = [1.0, 2.0][index] if condition == "reference" else [1.1, 1.9][index]
    else:
        value = [10.0, 12.0][index] if condition == "reference" else [8.0, 10.0][index]
    observations.append({
        "value": value, "seed": seed, "replicate": 0,
        "pair_id": "unit-" + str(seed),
    })
(artifact_dir / "metrics.json").write_text(
    json.dumps({"observations": observations}, sort_keys=True), encoding="utf-8",
)
print(json.dumps({"observation_count": len(observations), "condition": condition}))
if mode == "failure" and not config.get("smoke") and condition == "reference":
    raise SystemExit(7)
'''


class AnalysisResearchEngineer(ResearchEngineer):
    def implement(self, context, hypothesis, plan, tasks, visualization_profile):
        topic = (context.topic or context.summary).casefold()
        if "failure" in topic:
            mode = "failure"
        elif "negative" in topic:
            mode = "negative"
        elif "archive" in topic or "manuscript" in topic:
            mode = "independent_supported"
        else:
            mode = "paired_supported"
        files = [ImplementationFile(
            relative_path="runner.py",
            content=ANALYSIS_RUNNER.replace("__ANALYSIS_MODE__", repr(mode)),
            purpose="Emit approved seed-level metric observations for deterministic analysis.",
        )]
        mappings = []
        binding = plan.plan.b_mode_binding
        if binding is not None:
            for decision in binding.code_reuse_decisions:
                target = "adapted/" + decision.source_relative_path
                suffix = Path(target).suffix.casefold()
                content = (
                    "def preserved_design_reference():\n    return 'approved-derived-design'\n"
                    if suffix == ".py" else json.dumps({"derived_from": decision.source_relative_path})
                )
                files.append(ImplementationFile(
                    relative_path=target, content=content,
                    purpose="Derived workspace copy bound to the approved legacy decision.",
                ))
                mappings.append(LegacyCodeMapping(
                    source_relative_path=decision.source_relative_path,
                    derived_relative_path=target, action=decision.action.value,
                    modifications=[PlannedModification.model_validate(
                        item.model_dump(mode="json")
                    ) for item in decision.modifications],
                ))
        return AgentResponse(EngineerCodePackage(
            entrypoint="runner.py", files=files, declared_dependencies=[],
            smoke_config={}, legacy_mappings=mappings,
            verification_notes=["Seed-level observations use the approved runtime config."],
        ), "3" * 64)


class ProceedingScientificReviewer(ScientificReviewer):
    def review(self, review_context):
        outcome = ResearchOutcome(review_context["analysis"]["outcome"])
        return ReviewResponse(
            ScientificReviewDraft(
                assessed_outcome=outcome,
                recommendation=ScientificRecommendation.PROCEED_TO_RESEARCH_REVIEW,
                summary="The conclusion is bounded to the deterministic outcome and retained failures.",
                claim_strength="Report only the verified effect and uncertainty boundary.",
                alternative_explanations=list(
                    review_context["approved_plan"]["plan"]["analysis"]["alternative_explanations"]
                ),
                confounders=list(
                    review_context["approved_plan"]["plan"]["analysis"]["confounders"]
                ),
                required_actions=[], may_enter_research_review=True,
            ),
            canonical_hash(review_context),
        )


class OutcomeUpgradingReviewer(ScientificReviewer):
    def review(self, review_context):
        return ReviewResponse(
            ScientificReviewDraft(
                assessed_outcome=ResearchOutcome.SUPPORTED,
                recommendation=ScientificRecommendation.PROCEED_TO_RESEARCH_REVIEW,
                summary="Attempted outcome upgrade.", claim_strength="Unsupported upgrade.",
                may_enter_research_review=True,
            ),
            canonical_hash(review_context),
        )


class DeterministicStatisticsTests(unittest.TestCase):
    def test_condition_keyed_metrics_are_extracted_for_the_current_run(self):
        run = type("Run", (), {"run_id": "run-1"})()
        run_spec = type("RunSpec", (), {
            "run_spec_id": "run_wd0",
            "condition_id": "cond_wd0",
            "parameters": {"output_condition_key": "wd_0"},
            "seeds": [7],
            "replicates_per_seed": 1,
            "expected_runs": 1,
        })()
        artifact = type("Artifact", (), {"artifact_id": "artifact-1"})()
        metric = type("Metric", (), {
            "metric_id": "final_unregularized_train_mse",
            "name": "Final unregularized training MSE",
            "primary": True,
        })()

        observations = DeterministicStatistics()._extract_observations(
            run, run_spec, artifact,
            {"final_unregularized_train_mse": {"wd_0": 1.25, "wd_0_01": 2.5}},
            [metric],
        )

        self.assertEqual([item.value for item in observations], [1.25])

    def test_large_epoch_series_are_reduced_for_scientific_review_context(self):
        class Analysis:
            def model_dump(self, mode):
                return {"payload": {"observations": [{"seed": None}] * 201}}

        context = AnalysisReviewService._review_analysis_context(Analysis())

        self.assertEqual(context["payload"]["observations"], [])
        self.assertEqual(context["payload"]["observation_digest"]["total_count"], 201)
        self.assertEqual(context["payload"]["observation_digest"]["series_point_count"], 201)


class AnalysisReviewTests(unittest.TestCase):
    _approved_topic_plan = study_helpers.StudyRuntimeTests._approved_topic_plan
    _approved_b_plan = study_helpers.StudyRuntimeTests._approved_b_plan
    _approve_planning = study_helpers.StudyRuntimeTests._approve_planning
    _seed_literature = study_helpers.StudyRuntimeTests._seed_literature
    _wait = study_helpers.StudyRuntimeTests._wait
    _wait_for_status = study_helpers.StudyRuntimeTests._wait_for_status
    _fingerprint = staticmethod(study_helpers.StudyRuntimeTests._fingerprint)

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
            research_design_lead=__import__(
                "tests.test_hypothesis_planning", fromlist=["ScriptedDesignLead"]
            ).ScriptedDesignLead(),
            critical_reviewer=__import__(
                "tests.test_hypothesis_planning", fromlist=["ScriptedCriticalReviewer"]
            ).ScriptedCriticalReviewer(),
            experimental_lead=ScriptedExperimentalLead(),
            research_engineer=AnalysisResearchEngineer(),
            scientific_reviewer=ProceedingScientificReviewer(),
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_independent_and_paired_analysis_structures_are_deterministic_and_traceable(self):
        cases = [
            ("Archive", "Archive manuscript feature intervention", "independent_welch_t"),
            ("Canopy", "Canopy exposure and pedestrian heat response", "paired_t"),
        ]
        for title, topic, expected_method in cases:
            with self.subTest(method=expected_method):
                project_id, plan, study, _ = self._completed_study(title, topic)
                response = self.client.post(
                    f"/api/projects/{project_id}/studies/{study['study_id']}/analyses"
                )
                self.assertEqual(response.status_code, 201, response.text)
                result = response.json()
                analysis = result["analysis"]
                self.assertEqual(analysis["status"], "completed")
                self.assertEqual(analysis["outcome"], "supported")
                comparison = analysis["payload"]["comparisons"][0]
                self.assertEqual(comparison["method"], expected_method)
                self.assertIsNotNone(comparison["effect_estimate"])
                self.assertIsNotNone(comparison["p_value"])
                self.assertIsNotNone(comparison["variance"])
                self.assertEqual(comparison["multiplicity_method"], "none")
                self.assertLess(comparison["adjusted_p_value"], 0.05)
                self.assertEqual(result["verification"]["passed"], True)
                self.assertEqual(result["review"]["policy_recommendation"],
                                 "proceed_to_research_review")
                self.assertEqual(
                    {item["kind"] for item in result["artifacts"]},
                    {"machine_json", "table_csv", "figure_svg"},
                )
                self.assertEqual(
                    {item["role"] for item in result["agent_runs"]},
                    {"statistical_analyst", "verification_auditor", "scientific_reviewer"},
                )
                source_ids = set(analysis["payload"]["source_artifact_ids"])
                for artifact in result["artifacts"]:
                    self.assertEqual(set(artifact["generated_from_artifact_ids"]), source_ids)
                    verified = self.client.get(
                        f"/api/projects/{project_id}/analysis-artifacts/{artifact['artifact_id']}/verification"
                    )
                    self.assertTrue(verified.json()["hash_matches"])
                    content = self.client.get(
                        f"/api/projects/{project_id}/analysis-artifacts/{artifact['artifact_id']}/content"
                    )
                    self.assertEqual(content.status_code, 200, content.text)
                    self.assertEqual(len(content.content), artifact["size_bytes"])
                histories = self.client.get(
                    f"/api/projects/{project_id}/analyses/{analysis['analysis_id']}/verifications"
                ).json()
                self.assertEqual(histories[0]["analysis_content_hash"], analysis["content_hash"])

    def test_wrong_seed_plan_hash_statistics_and_tampered_artifact_are_detected(self):
        project_id, _, study, formal = self._completed_study(
            "Archive audit", "Archive manuscript audit integrity",
        )
        result = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/analyses"
        ).json()
        analysis_id = result["analysis"]["analysis_id"]

        run = self.app.state.services.experiment_repository.get_run(formal[0]["run_id"])
        bad_config = json.loads(json.dumps(run.config))
        bad_config["run_spec"]["seeds"] = [999]
        tampered_run = run.model_copy(update={
            "plan_content_hash": "f" * 64,
            "config": bad_config,
            "config_sha256": canonical_hash(bad_config),
        })
        self.app.state.services.experiment_repository.update_run(tampered_run)

        repository = self.app.state.services.analysis_repository
        original = repository.get_analysis(analysis_id)
        payload_data = original.payload.model_dump(mode="json", exclude={"content_hash"})
        payload_data["comparisons"][0]["effect_estimate"] += 123.0
        forged_payload = AnalysisPayload.model_validate(payload_data)
        record_data = original.model_dump(mode="json", exclude={"content_hash"})
        record_data["payload"] = forged_payload.model_dump(mode="json")
        forged = AnalysisRecord.model_validate(record_data)
        with self.app.state.services.database.transaction() as connection:
            connection.execute(
                "UPDATE analysis_records SET content_hash=?,record_json=? WHERE analysis_id=?",
                (forged.content_hash, forged.model_dump_json(), forged.analysis_id),
            )

        verification = self.client.post(
            f"/api/projects/{project_id}/analyses/{analysis_id}/verifications"
        )
        self.assertEqual(verification.status_code, 201, verification.text)
        report = verification.json()
        codes = {item["code"] for item in report["findings"]}
        self.assertFalse(report["passed"])
        self.assertTrue({"RUN_BINDING", "RUN_SEED_MISMATCH", "STATISTIC_MISMATCH"} <= codes)
        review = self.client.post(
            f"/api/projects/{project_id}/analyses/{analysis_id}/scientific-reviews",
            json={"verification_id": report["verification_id"]},
        ).json()
        self.assertEqual(review["policy_recommendation"], "revise_plan")
        self.assertFalse(review["may_enter_research_review"])

        source_id = forged.payload.source_artifact_ids[0]
        source = self.app.state.services.experiment_repository.get_artifact(source_id)
        path = self.settings.runtime_root / "projects" / project_id / source.relative_path
        path.write_text('{"observations":[]}', encoding="utf-8")
        second = self.client.post(
            f"/api/projects/{project_id}/analyses/{analysis_id}/verifications"
        ).json()
        second_codes = {item["code"] for item in second["findings"]}
        self.assertIn("ARTIFACT_HASH", second_codes)
        self.assertIn("STATISTIC_SOURCE_UNVERIFIED", second_codes)
        failed_analysis = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/analyses"
        )
        self.assertEqual(failed_analysis.status_code, 422)
        history = self.client.get(
            f"/api/projects/{project_id}/studies/{study['study_id']}/analyses"
        ).json()
        self.assertIn("failed", {item["status"] for item in history})

    def test_negative_and_insufficient_evidence_are_preserved_and_can_proceed(self):
        negative_project, _, negative_study, _ = self._completed_study(
            "Negative archive", "Negative archive manuscript result",
        )
        negative = self.client.post(
            f"/api/projects/{negative_project}/studies/{negative_study['study_id']}/analyses"
        )
        self.assertEqual(negative.status_code, 201, negative.text)
        negative_result = negative.json()
        self.assertEqual(negative_result["analysis"]["outcome"], "negative_result")
        self.assertTrue(negative_result["verification"]["passed"])
        self.assertTrue(negative_result["review"]["may_enter_research_review"])
        source_id = negative_result["analysis"]["payload"]["source_artifact_ids"][0]
        source_before = self.client.get(
            f"/api/projects/{negative_project}/artifacts/{source_id}/verification"
        ).json()
        self.app.state.services.analysis_runtime.reviewer = OutcomeUpgradingReviewer()
        bounded = self.client.post(
            f"/api/projects/{negative_project}/analyses/{negative_result['analysis']['analysis_id']}/scientific-reviews",
            json={"verification_id": negative_result["verification"]["verification_id"]},
        )
        self.assertEqual(bounded.status_code, 201, bounded.text)
        self.assertEqual(bounded.json()["assessed_outcome"], "negative_result")
        self.assertEqual(bounded.json()["policy_recommendation"], "supplement_experiment")
        self.assertFalse(bounded.json()["may_enter_research_review"])
        source_after = self.client.get(
            f"/api/projects/{negative_project}/artifacts/{source_id}/verification"
        ).json()
        self.assertEqual(source_before["actual_sha256"], source_after["actual_sha256"])
        self.app.state.services.analysis_runtime.reviewer = ProceedingScientificReviewer()

        failure_project, _, failure_study, formal = self._completed_study(
            "Failure retention", "Failure and missing evidence in field comparison",
            allow_failure=True,
        )
        insufficient = self.client.post(
            f"/api/projects/{failure_project}/studies/{failure_study['study_id']}/analyses"
        )
        self.assertEqual(insufficient.status_code, 201, insufficient.text)
        insufficient_result = insufficient.json()
        self.assertEqual(insufficient_result["analysis"]["outcome"], "insufficient_evidence")
        missing = insufficient_result["analysis"]["payload"]["missing_runs"]
        failed_ids = {run["run_id"] for run in formal if run["status"] == "failed"}
        self.assertTrue(failed_ids)
        self.assertTrue(failed_ids <= {
            run_id for item in missing for run_id in item["failed_run_ids"]
        })
        self.assertTrue(insufficient_result["verification"]["passed"])
        self.assertTrue(insufficient_result["review"]["may_enter_research_review"])

    def test_b_mode_lineage_fidelity_and_visual_profile_bind_analysis_figure(self):
        source = self.allowed / "legacy_analysis"
        (source / "src").mkdir(parents=True)
        (source / "src" / "experiment.py").write_text(
            "def legacy_design(values):\n    return sum(values) / len(values)\n",
            encoding="utf-8",
        )
        (source / "src" / "plot.py").write_text(
            "import matplotlib.pyplot as plt\n"
            "def plot(values):\n"
            "    plt.plot(values, color='#336699')\n"
            "    plt.savefig('result.svg', dpi=180)\n",
            encoding="utf-8",
        )
        before = self._fingerprint(source)
        project_id, plan, _, profiles = self._approved_b_plan(source)
        profile = profiles[0]
        self.client.post(
            f"/api/projects/{project_id}/visualization-profiles/{profile['profile_id']}/decision",
            json={"approved": True, "feedback": "Approve inherited visual profile."},
        )
        created = self.client.post(f"/api/projects/{project_id}/studies", json={
            "plan_revision_id": plan["plan_revision_id"],
            "visualization_profile_id": profile["profile_id"],
        })
        self.assertEqual(created.status_code, 201, created.text)
        study = created.json()["study"]
        formal = self._execute_plan(project_id, study, plan)
        result = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/analyses"
        )
        self.assertEqual(result.status_code, 201, result.text)
        body = result.json()
        self.assertTrue(body["verification"]["lineage_verified"])
        figure = next(item for item in body["artifacts"] if item["kind"] == "figure_svg")
        self.assertEqual(figure["visualization_profile_id"], profile["profile_id"])
        self.assertEqual(figure["visualization_profile_hash"], study["visualization_profile_hash"])
        self.assertEqual(before, self._fingerprint(source))

    def _completed_study(self, title, topic, allow_failure=False):
        project_id, plan = self._approved_topic_plan(title, topic)
        created = self.client.post(f"/api/projects/{project_id}/studies", json={
            "plan_revision_id": plan["plan_revision_id"],
        })
        self.assertEqual(created.status_code, 201, created.text)
        study = created.json()["study"]
        formal = self._execute_plan(project_id, study, plan)
        if not allow_failure:
            self.assertTrue(all(item["status"] == "completed" for item in formal), formal)
        return project_id, plan, study, formal

    def _execute_plan(self, project_id, study, plan):
        first = plan["plan"]["runs"][0]
        smoke = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
            json={"run_spec_id": first["run_spec_id"], "smoke": True},
        )
        self.assertEqual(smoke.status_code, 202, smoke.text)
        self.assertEqual(self._wait(project_id, smoke.json()["run_id"])["run"]["status"], "completed")
        formal = []
        for spec in plan["plan"]["runs"]:
            started = self.client.post(
                f"/api/projects/{project_id}/studies/{study['study_id']}/runs",
                json={"run_spec_id": spec["run_spec_id"], "smoke": False},
            )
            self.assertEqual(started.status_code, 202, started.text)
            formal.append(self._wait(project_id, started.json()["run_id"])["run"])
        return formal


if __name__ == "__main__":
    unittest.main()

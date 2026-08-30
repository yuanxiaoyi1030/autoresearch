# Purpose: Verifies four-role independent review, hard policy priority, disagreements, five decisions, and feedback loops.
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import Settings
from research_runtime.planning import canonical_hash
from research_runtime.review import (
    ClaimType, EvidenceReproducibilityReviewer, MetaAssignmentPlan, MetaReviewDraft,
    MetaReviewer, MethodologyReviewer, ResearchReviewDecision, ResearchReviewRole,
    ReviewAssignment, ReviewerResponse, ReviewerVerdict, SpecialistReviewDraft,
    StatisticalReviewer,
)
from research_runtime.state import ResearchOutcome, ResearchStage
from research_runtime.workflow import WorkflowAction
from tests import test_analysis_review as analysis_helpers
from tests import test_study_runtime as study_helpers


class ScriptedMetaReviewer(MetaReviewer):
    def __init__(self):
        self.assignment_contexts = []
        self.synthesis_contexts = []

    def assign(self, assignment_context):
        self.assignment_contexts.append(assignment_context)
        plan = MetaAssignmentPlan(assignments=[
            ReviewAssignment(
                role=ResearchReviewRole.METHODOLOGY_REVIEWER,
                focus=["design", "baseline", "controls", "ablation", "alternatives"],
                required_record_types=["ExperimentPlanRevision", "HypothesisRevision"],
            ),
            ReviewAssignment(
                role=ResearchReviewRole.STATISTICAL_REVIEWER,
                focus=["estimand", "variance", "uncertainty", "missingness"],
                required_record_types=["AnalysisRecord", "VerificationReport"],
            ),
            ReviewAssignment(
                role=ResearchReviewRole.EVIDENCE_REPRODUCIBILITY_REVIEWER,
                focus=["claims", "artifacts", "citations", "lineage", "reproduction"],
                required_record_types=["EvidenceClaim", "Artifact", "ReproducibilitySpec"],
            ),
        ], coordination_note="Three isolated specialist scopes; Meta only dispatches and synthesizes.")
        return ReviewerResponse(plan, canonical_hash(assignment_context))

    def synthesize(self, synthesis_context):
        self.synthesis_contexts.append(synthesis_context)
        return ReviewerResponse(MetaReviewDraft(
            proposed_decision=ResearchReviewDecision.SUPPORTED,
            synthesis="Meta proposes passage while retaining specialist reports for policy adjudication.",
            disagreements=[], feedback=[],
        ), canonical_hash(synthesis_context))


class ScriptedMethodologyReviewer(MethodologyReviewer):
    def __init__(self):
        self.contexts = []

    def review(self, independent_context):
        self.contexts.append(independent_context)
        return ReviewerResponse(SpecialistReviewDraft(
            verdict=ReviewerVerdict.PASS,
            proposed_decision=ResearchReviewDecision.SUPPORTED,
            summary="Design, baseline, controls, and alternatives are reviewable as approved.",
            conclusion_boundary="No claim beyond the approved design.",
        ), canonical_hash(independent_context))


class ScriptedStatisticalReviewer(StatisticalReviewer):
    def __init__(self):
        self.contexts = []

    def review(self, independent_context):
        self.contexts.append(independent_context)
        return ReviewerResponse(SpecialistReviewDraft(
            verdict=ReviewerVerdict.CONCERNS,
            proposed_decision=ResearchReviewDecision.NEGATIVE_RESULT,
            summary="The minority statistical position interprets the evidence conservatively.",
            conclusion_boundary="Retain effect, interval, and missingness boundaries.",
        ), canonical_hash(independent_context))


class ScriptedEvidenceReviewer(EvidenceReproducibilityReviewer):
    def __init__(self):
        self.contexts = []

    def review(self, independent_context):
        self.contexts.append(independent_context)
        return ReviewerResponse(SpecialistReviewDraft(
            verdict=ReviewerVerdict.PASS,
            proposed_decision=ResearchReviewDecision.SUPPORTED,
            summary="Reviewer proposes passage based on the supplied provenance package.",
            conclusion_boundary="Only hash-bound claims and verified citations may pass.",
        ), canonical_hash(independent_context))


class IndependentResearchReviewTests(unittest.TestCase):
    _approved_topic_plan = study_helpers.StudyRuntimeTests._approved_topic_plan
    _approve_planning = study_helpers.StudyRuntimeTests._approve_planning
    _seed_literature = study_helpers.StudyRuntimeTests._seed_literature
    _wait = study_helpers.StudyRuntimeTests._wait
    _wait_for_status = study_helpers.StudyRuntimeTests._wait_for_status
    _completed_study = analysis_helpers.AnalysisReviewTests._completed_study
    _execute_plan = analysis_helpers.AnalysisReviewTests._execute_plan

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=study_helpers.TEST_TEMP_ROOT)
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.settings = Settings(
            runtime_root=self.root / "runtime", allowed_import_roots=[self.allowed],
        )
        self.meta = ScriptedMetaReviewer()
        self.methodology = ScriptedMethodologyReviewer()
        self.statistical = ScriptedStatisticalReviewer()
        self.evidence = ScriptedEvidenceReviewer()
        planning_helpers = __import__(
            "tests.test_hypothesis_planning", fromlist=[
                "ScriptedDesignLead", "ScriptedCriticalReviewer",
            ],
        )
        self.app = create_app(
            self.settings,
            research_design_lead=planning_helpers.ScriptedDesignLead(),
            critical_reviewer=planning_helpers.ScriptedCriticalReviewer(),
            experimental_lead=study_helpers.ScriptedExperimentalLead(),
            research_engineer=analysis_helpers.AnalysisResearchEngineer(),
            scientific_reviewer=analysis_helpers.ProceedingScientificReviewer(),
            meta_reviewer=self.meta, methodology_reviewer=self.methodology,
            statistical_reviewer=self.statistical,
            research_evidence_reviewer=self.evidence,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_independent_context_meta_disagreement_policy_and_supported_feedback(self):
        project_id, analysis = self._analysis(
            "Independent archive", "Archive manuscript independent review",
        )
        result = self._review(project_id, analysis)
        self.assertEqual(result["policy_decision"]["final_decision"], "supported")
        self.assertEqual(len(result["specialist_reviews"]), 3)
        self.assertEqual(len(result["agent_runs"]), 5)
        self.assertEqual(
            {item["role"] for item in result["agent_runs"]},
            {"meta_reviewer", "methodology_reviewer", "statistical_reviewer",
             "evidence_reproducibility_reviewer"},
        )
        hashes = {
            item["independent_context_hash"] for item in result["specialist_reviews"]
        }
        self.assertEqual(len(hashes), 3)
        for context in [self.methodology.contexts[-1], self.statistical.contexts[-1],
                        self.evidence.contexts[-1]]:
            self.assertTrue(context["review_contract"]["independent_context"])
            self.assertFalse(context["review_contract"]["peer_review_reports_included"])
            self.assertNotIn("specialist_reports", context)
        self.assertFalse(
            self.meta.assignment_contexts[-1]["review_contract"][
                "meta_participated_in_research_generation"
            ]
        )
        disagreement = result["meta_review"]["disagreements"]
        self.assertTrue(disagreement)
        self.assertEqual(
            {item["proposed_decision"] for item in disagreement[-1]["positions"]},
            {"supported", "negative_result"},
        )
        self.assertIn("Policy Guard", disagreement[-1]["resolution"])
        self.assertTrue(all(
            item["status"] == "pass"
            for item in result["policy_decision"]["rule_results"]
        ))

        self._advance_to_review(project_id, ResearchOutcome.SUPPORTED)
        state = self.client.get(f"/api/projects/{project_id}/state").json()
        applied = self.client.post(
            f"/api/projects/{project_id}/research-reviews/{result['record']['review_run_id']}/apply",
            json={"expected_state_revision": state["revision"]},
        )
        self.assertEqual(applied.status_code, 201, applied.text)
        self.assertEqual(applied.json()["to_stage"], "report_planning")
        updated = self.client.get(f"/api/projects/{project_id}/state").json()
        self.assertEqual(updated["outcome"], "supported")
        duplicate = self.client.post(
            f"/api/projects/{project_id}/research-reviews/{result['record']['review_run_id']}/apply",
            json={"expected_state_revision": updated["revision"]},
        )
        self.assertEqual(duplicate.status_code, 422)

    def test_all_five_decisions_hard_rules_and_feedback_paths(self):
        negative_project, negative_analysis = self._analysis(
            "Negative archive review", "Negative archive manuscript result for review",
        )
        negative = self._review(negative_project, negative_analysis)
        self.assertEqual(negative["policy_decision"]["final_decision"], "negative_result")
        self.assertTrue(negative["policy_decision"]["reviewer_decision_overridden"])
        negative_model = self.app.state.services.analysis_repository.get_analysis(
            negative_analysis["analysis_id"]
        )
        negative_artifact = self.app.state.services.experiment_repository.get_artifact(
            negative_model.payload.source_artifact_ids[0]
        )
        negative_path = (
            self.settings.runtime_root / "projects" / negative_project
            / negative_artifact.relative_path
        )
        negative_path.write_text('{"observations":[]}', encoding="utf-8")
        self._advance_to_review(negative_project, ResearchOutcome.NEGATIVE_RESULT)
        negative_state = self.client.get(f"/api/projects/{negative_project}/state").json()
        stale = self.client.post(
            f"/api/projects/{negative_project}/research-reviews/{negative['record']['review_run_id']}/apply",
            json={"expected_state_revision": negative_state["revision"]},
        )
        self.assertEqual(stale.status_code, 422)
        self.assertIn("stale", stale.text)
        self.assertEqual(
            self.client.get(f"/api/projects/{negative_project}/state").json()["stage"],
            "research_review",
        )

        citation_project, citation_analysis = self._analysis(
            "Citation boundary", "Archive manuscript citation boundary",
        )
        evidence = self.app.state.services.literature_repository.list_evidence(citation_project)[0]
        citation = self._review(citation_project, citation_analysis, claims=[{
            "claim_type": ClaimType.LITERATURE_CONTEXT.value,
            "statement": "An abstract-only source establishes the core mechanism.",
            "core_claim": True,
            "literature_evidence_ids": [evidence.evidence_id],
        }])
        self.assertEqual(citation["policy_decision"]["final_decision"], "insufficient_evidence")
        citation_rules = {item["rule_code"]: item for item in citation["policy_decision"]["rule_results"]}
        self.assertEqual(citation_rules["CITATION_ACCESS_LEVEL"]["status"], "fail")
        self._advance_to_review(citation_project, ResearchOutcome.SUPPORTED)
        citation_state = self.client.get(f"/api/projects/{citation_project}/state").json()
        citation_applied = self.client.post(
            f"/api/projects/{citation_project}/research-reviews/{citation['record']['review_run_id']}/apply",
            json={"expected_state_revision": citation_state["revision"]},
        )
        self.assertEqual(citation_applied.json()["to_stage"], "report_planning")
        self.assertEqual(
            self.client.get(f"/api/projects/{citation_project}/state").json()["outcome"],
            "insufficient_evidence",
        )

        missing_project, missing_analysis = self._analysis(
            "Missing experiment review", "Failure and missing evidence for formal review",
            allow_failure=True,
        )
        missing = self._review(missing_project, missing_analysis)
        self.assertEqual(missing["policy_decision"]["final_decision"], "return_to_experiment")
        missing_rules = {item["rule_code"]: item for item in missing["policy_decision"]["rule_results"]}
        self.assertEqual(missing_rules["COMPLETE_APPROVED_EXPERIMENTS"]["status"], "fail")
        self._advance_to_review(missing_project, ResearchOutcome.INSUFFICIENT_EVIDENCE)
        missing_state = self.client.get(f"/api/projects/{missing_project}/state").json()
        missing_applied = self.client.post(
            f"/api/projects/{missing_project}/research-reviews/{missing['record']['review_run_id']}/apply",
            json={"expected_state_revision": missing_state["revision"]},
        )
        self.assertEqual(missing_applied.json()["to_stage"], "experiment")

        broken_project, broken_analysis = self._analysis(
            "Broken binding", "Archive manuscript broken Plan and Artifact binding",
        )
        analysis_model = self.app.state.services.analysis_repository.get_analysis(
            broken_analysis["analysis_id"]
        )
        run_id = analysis_model.payload.source_run_ids[0]
        run = self.app.state.services.experiment_repository.get_run(run_id)
        self.app.state.services.experiment_repository.update_run(
            run.model_copy(update={"plan_content_hash": "f" * 64})
        )
        artifact_id = analysis_model.payload.source_artifact_ids[0]
        artifact = self.app.state.services.experiment_repository.get_artifact(artifact_id)
        artifact_path = (
            self.settings.runtime_root / "projects" / broken_project / artifact.relative_path
        )
        artifact_path.write_text('{"observations":[]}', encoding="utf-8")
        broken = self._review(broken_project, broken_analysis)
        self.assertEqual(broken["policy_decision"]["final_decision"], "revise_plan")
        broken_rules = {item["rule_code"]: item for item in broken["policy_decision"]["rule_results"]}
        self.assertEqual(broken_rules["PLAN_BINDING"]["status"], "fail")
        self.assertEqual(broken_rules["CLAIM_ARTIFACT_HASH"]["status"], "fail")
        self.assertTrue(broken["policy_decision"]["reviewer_decision_overridden"])
        self._advance_to_review(broken_project, ResearchOutcome.SUPPORTED)
        broken_state = self.client.get(f"/api/projects/{broken_project}/state").json()
        broken_applied = self.client.post(
            f"/api/projects/{broken_project}/research-reviews/{broken['record']['review_run_id']}/apply",
            json={"expected_state_revision": broken_state["revision"]},
        )
        self.assertEqual(broken_applied.status_code, 201, broken_applied.text)
        self.assertEqual(broken_applied.json()["to_stage"], "experiment_planning")

        observed = {
            "supported",
            negative["policy_decision"]["final_decision"],
            citation["policy_decision"]["final_decision"],
            missing["policy_decision"]["final_decision"],
            broken["policy_decision"]["final_decision"],
        }
        self.assertEqual(observed, {
            "supported", "negative_result", "insufficient_evidence",
            "return_to_experiment", "revise_plan",
        })

    def _analysis(self, title, topic, allow_failure=False):
        project_id, _, study, _ = self._completed_study(
            title, topic, allow_failure=allow_failure,
        )
        response = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/analyses"
        )
        self.assertEqual(response.status_code, 201, response.text)
        return project_id, response.json()["analysis"]

    def _review(self, project_id, analysis, claims=None):
        response = self.client.post(
            f"/api/projects/{project_id}/analyses/{analysis['analysis_id']}/research-reviews",
            json={"claims": claims or []},
        )
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        fetched = self.client.get(
            f"/api/projects/{project_id}/research-reviews/{result['record']['review_run_id']}"
        )
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["record"]["content_hash"], result["record"]["content_hash"])
        return result

    def _advance_to_review(self, project_id, outcome):
        actions = [
            WorkflowAction.INITIALIZATION_COMPLETED,
            WorkflowAction.PROJECT_UNDERSTANDING_COMPLETED,
            WorkflowAction.LITERATURE_COMPLETED,
            WorkflowAction.HYPOTHESIS_READY,
            WorkflowAction.HYPOTHESIS_APPROVED,
            WorkflowAction.PLAN_READY,
            WorkflowAction.PLAN_APPROVED,
            WorkflowAction.IMPLEMENTATION_READY,
        ]
        workflow = self.app.state.services.workflow
        state = self.app.state.services.projects.get_state(project_id)
        for action in actions:
            state = workflow.transition(project_id, action, expected_revision=state.revision)
        state = workflow.transition(
            project_id, WorkflowAction.EXPERIMENT_COMPLETED,
            expected_revision=state.revision, outcome=outcome,
        )
        state = workflow.transition(
            project_id, WorkflowAction.ANALYSIS_READY_FOR_REVIEW,
            expected_revision=state.revision,
        )
        self.assertEqual(state.stage, ResearchStage.RESEARCH_REVIEW)


if __name__ == "__main__":
    unittest.main()

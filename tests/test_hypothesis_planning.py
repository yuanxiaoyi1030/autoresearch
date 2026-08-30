# Purpose: Verifies cross-domain planning, immutable revisions, approvals, budgets, B-mode reuse, and experiment gates.
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import Settings
from research_runtime.literature import (
    AccessLevel, EvidenceRole, LiteratureEvidence, LiteratureEvidenceMatrix,
    LiteratureProvider, LiteratureQuery, LiteratureQueryPlan, LiteratureSource, ResearchGap,
)
from research_runtime.planning import (
    AgentResponse, AnalysisSpec, BModePlanBinding, CodeReuseAction, CodeReuseDecision,
    ConditionSpec, CriticalReviewer, ExperimentBudget, ExperimentPlanDraft, FeedbackSource,
    HypothesisCandidate, HypothesisDraft, HypothesisRevision, MetricDirection, MetricSpec, PlannedModification,
    PlanningDefect, PlanningDefectCategory, PlanningReviewDraft, ReproducibilitySpec,
    ResearchDesignLead, ResourceRequest, RunSpec, StudySpec, VariableRole, VariableSpec,
    canonical_hash,
)
from research_runtime.literature import DefectSeverity
from research_runtime.understanding import ModificationCategory, ModificationClass, ReuseDisposition


TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "planning_tests"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class ScriptedDesignLead(ResearchDesignLead):
    def generate_hypotheses(self, context, literature):
        return AgentResponse(self._hypotheses(context, literature, "initial"), "1" * 64)

    def revise_hypotheses(self, context, literature, parent, feedback, prior_review):
        return AgentResponse(self._hypotheses(context, literature, "revised"), "2" * 64)

    def generate_plan(self, context, literature, hypothesis, approval, reuse):
        return AgentResponse(self._plan(context, reuse, "initial"), "3" * 64)

    def revise_plan(self, context, literature, hypothesis, approval, parent, feedback,
                    prior_review, reuse):
        return AgentResponse(self._plan(context, reuse, "revised"), "4" * 64)

    @staticmethod
    def _hypotheses(context, literature, label):
        evidence_id = literature.evidence[0].evidence_id
        topic = context.topic or context.research_questions[0]
        candidates = [
            HypothesisCandidate(
                title=f"{label} direct-effect candidate",
                statement=f"For {topic}, the proposed exposure changes the primary outcome.",
                rationale=f"The {topic} literature leaves a direct-effect gap.",
                novelty_claim="Tests the target relationship under explicit controls.",
                falsification_criterion="The controlled effect interval includes the prespecified null region.",
                null_prediction="No practically relevant adjusted difference is observed.",
                alternative_prediction="A practically relevant adjusted difference is observed.",
                anticipated_variables=["target exposure", "primary outcome", "control factors"],
                supporting_evidence_ids=[evidence_id],
                feasibility_summary="Can be evaluated with the declared bounded study design.",
                known_risks=["Residual confounding"],
            ),
            HypothesisCandidate(
                title=f"{label} moderated-effect candidate",
                statement=f"For {topic}, contextual strata moderate the exposure-outcome relationship.",
                rationale=f"The {topic} evidence does not resolve heterogeneity.",
                novelty_claim="Separates average effects from prespecified heterogeneous effects.",
                falsification_criterion="The prespecified interaction estimate is inside the null region.",
                null_prediction="No reproducible moderation is detected.",
                alternative_prediction="The prespecified strata show reproducible moderation.",
                anticipated_variables=["target exposure", "primary outcome", "context stratum"],
                supporting_evidence_ids=[evidence_id],
                feasibility_summary="Uses the same bounded data with stratified analysis.",
                known_risks=["Low subgroup power"],
            ),
        ]
        return HypothesisDraft(
            research_question=f"Does the proposed exposure change the primary outcome for {topic}?",
            candidates=candidates, recommended_candidate_id=candidates[0].candidate_id,
            comparison="The direct-effect candidate is simpler; the moderated candidate probes heterogeneity.",
        )

    def _plan(self, context, reuse, label):
        topic = (context.topic or context.research_questions[0]).casefold()
        if "archive" in topic or "manuscript" in topic:
            variable_names = ("preservation feature set", "preservation outcome")
            design_type = "retrospective predictive comparison"
            unit = "archival manuscript record"
            population = "versioned archival catalogue"
            condition_names = ("catalogue-only baseline", "enhanced preservation features")
            metric_name = "held-out balanced accuracy"
        else:
            variable_names = ("canopy exposure", "pedestrian heat exposure")
            design_type = "matched field comparison"
            unit = "pedestrian route-time observation"
            population = "prespecified urban routes and observation windows"
            condition_names = ("low-canopy reference", "high-canopy matched route")
            metric_name = "adjusted mean heat-exposure difference"
        conditions = [
            ConditionSpec(
                name=condition_names[0], purpose="Reference comparison",
                variable_assignments={variable_names[0]: "reference"}, is_baseline=True,
            ),
            ConditionSpec(
                name=condition_names[1], purpose="Test the selected hypothesis",
                variable_assignments={variable_names[0]: "target"},
            ),
        ]
        study = StudySpec(
            name=f"{label} domain-specific study", objective=context.research_questions[0],
            design_type=design_type, experimental_unit=unit, population_or_dataset=population,
            inclusion_criteria=["Meets prespecified quality criteria"],
            exclusion_criteria=["Missing primary outcome"],
            variables=[
                VariableSpec(
                    name=variable_names[0], role=VariableRole.INDEPENDENT,
                    data_type="domain-defined", definition="Prespecified target exposure or feature set",
                    value_domain={"levels": ["reference", "target"]},
                    measurement_procedure="Versioned protocol",
                ),
                VariableSpec(
                    name=variable_names[1], role=VariableRole.DEPENDENT,
                    data_type="numeric", definition="Primary prespecified outcome",
                    value_domain={"scale": "domain-specific"},
                    measurement_procedure="Blind outcome extraction",
                ),
                VariableSpec(
                    name="matched control factors", role=VariableRole.CONTROL,
                    data_type="mixed", definition="Prespecified confounding controls",
                    measurement_procedure="Recorded before outcome analysis",
                ),
            ],
            conditions=conditions, baseline_condition_ids=[conditions[0].condition_id],
            ablation_condition_ids=[],
            ablation_rationale="No component ablation is meaningful; use nested control-set sensitivity analyses.",
            control_strategy=["Match or adjust prespecified control factors"],
            randomization_strategy="Deterministic split or matching fixed before outcome inspection",
            stopping_rule="Stop at the approved sample/run matrix without outcome-dependent extension",
        )
        runs = [RunSpec(
            condition_id=condition.condition_id,
            parameters={variable_names[0]: condition.variable_assignments[variable_names[0]]},
            seeds=[11, 29], replicates_per_seed=1,
            resource_request=ResourceRequest(
                cpu_cores=2, memory_gb=4, gpu_count=0,
                estimated_minutes_per_replicate=5,
            ),
            required_artifacts=["config", "row-level predictions", "metric inputs"],
        ) for condition in conditions]
        binding = None
        if reuse is not None:
            decisions = []
            for item in reuse.reuse_items:
                if not item.requires_workspace_copy:
                    continue
                action = (
                    CodeReuseAction.REIMPLEMENT
                    if item.disposition is ReuseDisposition.REIMPLEMENT
                    else CodeReuseAction.REFACTOR
                )
                decisions.append(CodeReuseDecision(
                    source_relative_path=item.relative_path, action=action,
                    rationale="Preserve scientific intent inside the controlled workspace.",
                    preserved_elements=item.preserved_scope,
                    modifications=[
                        PlannedModification(
                            classification=ModificationClass.NON_SEMANTIC,
                            category=ModificationCategory.PATH,
                            summary="Confine paths to the project workspace.",
                        ),
                        PlannedModification(
                            classification=ModificationClass.SEMANTIC,
                            category=ModificationCategory.METRIC,
                            summary="Add the approved primary metric and uncertainty calculation.",
                        ),
                    ],
                ))
            binding = BModePlanBinding(
                assessment_id=reuse.assessment_id, assessment_hash=canonical_hash(reuse),
                import_id=reuse.import_id, manifest_hash=context.manifest_hash,
                recommended_strategy=reuse.recommended_strategy,
                preserved_experiment_designs=context.detected_experiments or ["Preserve documented design intent"],
                code_reuse_decisions=decisions,
                unverified_observations=context.existing_result_summaries or ["No legacy result was verified"],
                supplemental_experiments=["Reproduce the legacy comparison under the approved protocol"],
                supplemental_figures=["Regenerate the main comparison from verified artifacts"],
            )
        return ExperimentPlanDraft(
            study=study, runs=runs,
            metrics=[MetricSpec(
                name=metric_name, definition="Prespecified primary outcome comparison",
                direction=MetricDirection.TARGET, aggregation="Across approved replicates",
                primary=True, uncertainty_report="95% interval and effect size",
            )],
            analysis=AnalysisSpec(
                estimands=["Adjusted target-versus-reference effect"],
                statistical_methods=["Domain-appropriate regression or matched estimator"],
                comparisons=["Target versus baseline"],
                uncertainty_methods=["Bootstrap or model-based 95% interval"],
                significance_level=0.05, multiplicity_correction="Not applicable to one primary comparison",
                missing_data_strategy="Report missingness and use prespecified complete-case sensitivity analysis",
                outlier_strategy="No outcome-driven exclusion; report robust sensitivity analysis",
                assumption_checks=["Residual diagnostics", "Overlap and balance checks"],
                planned_figures=["Primary effect with uncertainty", "Control-balance diagnostic"],
                alternative_explanations=["Measurement or selection differences"],
                confounders=["Time, location, collection, or catalogue quality as applicable"],
            ),
            reproducibility=ReproducibilitySpec(
                environment_requirements=["conda environment d2l"],
                dependency_lock_strategy="Record exact resolved dependency versions",
                data_version_strategy="Hash every input snapshot",
                code_version_strategy="Hash the immutable runner and source lineage",
                seed_policy="Use exactly the approved RunSpec seeds",
                artifact_provenance_strategy="Bind every output to run, config, code, and data hashes",
            ),
            budget=ExperimentBudget(
                max_total_runs=4, max_total_compute_minutes=20, max_gpu_hours=0,
                max_cost_usd=1,
            ),
            b_mode_binding=binding,
        )


class ScriptedCriticalReviewer(CriticalReviewer):
    def __init__(self, block_topics=None):
        self.block_topics = set(block_topics or [])
        self.contexts = []

    def review_hypothesis(self, independent_context):
        self.contexts.append(independent_context)
        topic = (independent_context["research_context"].get("topic") or "").casefold()
        defects = []
        if any(marker in topic for marker in self.block_topics):
            defects.append(PlanningDefect(
                category=PlanningDefectCategory.FALSIFIABILITY,
                severity=DefectSeverity.MAJOR,
                summary="The falsification threshold requires clarification.",
                suggested_action="Define a numerical smallest effect of interest.",
            ))
        return AgentResponse(PlanningReviewDraft(
            defects=defects, reviewer_summary="Independent hypothesis audit complete.",
        ), "a" * 64)

    def review_plan(self, independent_context):
        self.contexts.append(independent_context)
        return AgentResponse(PlanningReviewDraft(
            defects=[], reviewer_summary="Independent plan audit complete.",
        ), "b" * 64)


class HypothesisPlanningTests(unittest.TestCase):
    def setUp(self):
        # tempfile applies a restrictive chmod on Windows that can produce an
        # unreadable directory under some inherited workspace ACLs.
        self.root = TEST_TEMP_ROOT / f"case_{uuid4().hex}"
        self.root.mkdir()
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.settings = Settings(
            runtime_root=self.root / "runtime", allowed_import_roots=[self.allowed],
        )
        self.lead = ScriptedDesignLead()
        self.reviewer = ScriptedCriticalReviewer(block_topics={"blocking"})
        self.app = create_app(
            self.settings, research_design_lead=self.lead,
            critical_reviewer=self.reviewer,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        shutil.rmtree(self.root)

    def test_two_domains_produce_structurally_different_approved_plans(self):
        outputs = []
        project_ids = []
        for title, topic in [
            ("Urban heat", "Urban tree canopy effects on pedestrian heat exposure"),
            ("Archives", "Which archival features predict manuscript preservation outcomes"),
        ]:
            project_id = self._topic_project(title, topic)
            project_ids.append(project_id)
            hypothesis = self.client.post(
                f"/api/projects/{project_id}/hypotheses", json={},
            )
            self.assertEqual(hypothesis.status_code, 201, hypothesis.text)
            hypothesis_revision = hypothesis.json()["revision"]
            self.assertTrue(hypothesis_revision["research_question"].endswith("?"))
            selected = hypothesis_revision["recommended_candidate_id"]
            approval = self.client.post(
                f"/api/projects/{project_id}/hypotheses/{hypothesis_revision['hypothesis_revision_id']}/decision",
                json={"decision": "approved", "feedback": "Approve selected testable candidate.",
                      "selected_candidate_id": selected},
            )
            self.assertEqual(approval.status_code, 201, approval.text)
            self.assertEqual(approval.json()["artifact_content_hash"], hypothesis_revision["content_hash"])
            plan = self.client.post(f"/api/projects/{project_id}/experiment-plans", json={
                "hypothesis_revision_id": hypothesis_revision["hypothesis_revision_id"],
            })
            self.assertEqual(plan.status_code, 201, plan.text)
            plan_revision = plan.json()["revision"]
            gate_before = self.client.get(
                f"/api/projects/{project_id}/experiment-plans/{plan_revision['plan_revision_id']}/formal-experiment-gate"
            ).json()
            self.assertFalse(gate_before["allowed"])
            plan_approval = self.client.post(
                f"/api/projects/{project_id}/experiment-plans/{plan_revision['plan_revision_id']}/decision",
                json={"decision": "approved", "feedback": "Budget and design are acceptable."},
            )
            self.assertEqual(plan_approval.status_code, 201, plan_approval.text)
            gate_after = self.client.get(
                f"/api/projects/{project_id}/experiment-plans/{plan_revision['plan_revision_id']}/formal-experiment-gate"
            ).json()
            self.assertTrue(gate_after["allowed"], gate_after)
            outputs.append(plan_revision)

        first, second = outputs
        self.assertNotEqual(first["plan"]["study"]["design_type"], second["plan"]["study"]["design_type"])
        self.assertNotEqual(
            {item["name"] for item in first["plan"]["study"]["variables"]},
            {item["name"] for item in second["plan"]["study"]["variables"]},
        )
        self.assertEqual(len(first["content_hash"]), 64)
        self.assertEqual(len(second["content_hash"]), 64)
        self.assertTrue(all(
            context["review_contract"]["lead_chat_history_included"] is False
            and context["review_contract"]["reviewer_can_approve"] is False
            for context in self.reviewer.contexts
        ))
        with TestClient(create_app(self.settings)) as restarted:
            persisted_plans = restarted.get(
                f"/api/projects/{project_ids[-1]}/experiment-plans"
            )
            self.assertEqual(persisted_plans.status_code, 200, persisted_plans.text)
            self.assertEqual(persisted_plans.json()[0]["plan_revision_id"], second["plan_revision_id"])
            persisted_gate = restarted.get(
                f"/api/projects/{project_ids[-1]}/experiment-plans/{second['plan_revision_id']}/formal-experiment-gate"
            ).json()
            self.assertTrue(persisted_gate["allowed"], persisted_gate)
            with restarted.app.state.services.database.connect() as connection:
                version = connection.execute("SELECT version FROM schema_meta").fetchone()["version"]
            self.assertEqual(version, 9)

    def test_legacy_hypothesis_without_research_question_keeps_its_original_hash(self):
        project_id = self._topic_project(
            "Legacy question", "Whether calibrated sensing improves intermittent measurements",
        )
        revision = self.client.post(
            f"/api/projects/{project_id}/hypotheses", json={},
        ).json()["revision"]
        legacy_payload = {
            key: value for key, value in revision.items()
            if key not in {"content_hash", "created_at", "research_question"}
        }
        legacy_hash = canonical_hash(legacy_payload)
        legacy_record = {
            key: value for key, value in revision.items() if key != "research_question"
        }
        legacy_record["content_hash"] = legacy_hash

        loaded = HypothesisRevision.model_validate(legacy_record)

        self.assertIsNone(loaded.research_question)
        self.assertEqual(loaded.content_hash, legacy_hash)

    def test_rejection_revision_hash_budget_and_latest_plan_gate(self):
        project_id = self._topic_project(
            "Sensor network", "Adaptive error correction for intermittent sensor networks",
        )
        initial = self.client.post(f"/api/projects/{project_id}/hypotheses", json={}).json()["revision"]
        rejected = self.client.post(
            f"/api/projects/{project_id}/hypotheses/{initial['hypothesis_revision_id']}/decision",
            json={"decision": "rejected", "feedback": "Clarify the operational falsification threshold."},
        )
        self.assertEqual(rejected.status_code, 201, rejected.text)
        cannot_plan = self.client.post(f"/api/projects/{project_id}/experiment-plans", json={
            "hypothesis_revision_id": initial["hypothesis_revision_id"],
        })
        self.assertEqual(cannot_plan.status_code, 422)

        revised_response = self.client.post(f"/api/projects/{project_id}/hypotheses", json={
            "parent_revision_id": initial["hypothesis_revision_id"],
        })
        self.assertEqual(revised_response.status_code, 201, revised_response.text)
        revised = revised_response.json()["revision"]
        self.assertEqual(revised["revision"], 1)
        self.assertEqual(revised["parent_revision_id"], initial["hypothesis_revision_id"])
        self.assertTrue(any(item["source"] == FeedbackSource.USER.value for item in revised["feedback"]))
        self.assertTrue(any(item["relationship"] == "revises" for item in revised["provenance"]))
        selected = revised["recommended_candidate_id"]
        self.assertEqual(self.client.post(
            f"/api/projects/{project_id}/hypotheses/{revised['hypothesis_revision_id']}/decision",
            json={"decision": "approved", "feedback": "Revision resolves the concern.",
                  "selected_candidate_id": selected},
        ).status_code, 201)
        initial_plan = self.client.post(f"/api/projects/{project_id}/experiment-plans", json={
            "hypothesis_revision_id": revised["hypothesis_revision_id"],
        }).json()["revision"]
        self.assertEqual(self.client.post(
            f"/api/projects/{project_id}/experiment-plans/{initial_plan['plan_revision_id']}/decision",
            json={"decision": "rejected", "feedback": "Add a clearer sensitivity analysis."},
        ).status_code, 201)
        revised_plan_response = self.client.post(f"/api/projects/{project_id}/experiment-plans", json={
            "hypothesis_revision_id": revised["hypothesis_revision_id"],
            "parent_revision_id": initial_plan["plan_revision_id"],
        })
        self.assertEqual(revised_plan_response.status_code, 201, revised_plan_response.text)
        revised_plan = revised_plan_response.json()["revision"]
        self.assertEqual(revised_plan["revision"], 1)
        self.assertEqual(revised_plan["parent_revision_id"], initial_plan["plan_revision_id"])
        self.assertFalse(self.client.get(
            f"/api/projects/{project_id}/experiment-plans/{initial_plan['plan_revision_id']}/formal-experiment-gate"
        ).json()["allowed"])
        self.assertEqual(self.client.post(
            f"/api/projects/{project_id}/experiment-plans/{revised_plan['plan_revision_id']}/decision",
            json={"decision": "approved", "feedback": "Approve revised sensitivity design."},
        ).status_code, 201)
        self.assertTrue(self.client.get(
            f"/api/projects/{project_id}/experiment-plans/{revised_plan['plan_revision_id']}/formal-experiment-gate"
        ).json()["allowed"])
        duplicate = self.client.post(
            f"/api/projects/{project_id}/experiment-plans/{revised_plan['plan_revision_id']}/decision",
            json={"decision": "approved", "feedback": "Try duplicate."},
        )
        self.assertEqual(duplicate.status_code, 422)

        draft = self.lead._plan(
            self.app.state.services.understanding_repository.latest_context(project_id), None, "budget",
        )
        with self.assertRaisesRegex(ValueError, "max_total_runs"):
            ExperimentPlanDraft.model_validate(draft.model_copy(update={
                "budget": ExperimentBudget(
                    max_total_runs=3, max_total_compute_minutes=20,
                    max_gpu_hours=0, max_cost_usd=1,
                )
            }).model_dump(mode="json"))
        with self.assertRaisesRegex(ValueError, "compute"):
            ExperimentPlanDraft.model_validate(draft.model_copy(update={
                "budget": ExperimentBudget(
                    max_total_runs=4, max_total_compute_minutes=19,
                    max_gpu_hours=0, max_cost_usd=1,
                )
            }).model_dump(mode="json"))
        gpu_draft = draft.model_copy(deep=True)
        gpu_draft.runs[0].resource_request.gpu_count = 1
        with self.assertRaisesRegex(ValueError, "GPU"):
            ExperimentPlanDraft.model_validate(gpu_draft.model_dump(mode="json"))
        cost_draft = draft.model_copy(deep=True)
        cost_draft.runs[0].resource_request.estimated_cost_usd_per_replicate = 2
        cost_draft.budget.max_cost_usd = 3
        with self.assertRaisesRegex(ValueError, "cost"):
            ExperimentPlanDraft.model_validate(cost_draft.model_dump(mode="json"))
        stored = self.app.state.services.planning_repository.get_plan(revised_plan["plan_revision_id"])
        stored.plan.study.objective = "tampered after hashing"
        with self.assertRaisesRegex(ValueError, "content changed"):
            self.app.state.services.planning_repository.save_plan(stored)

    def test_persisted_plan_review_can_be_retried_idempotently(self):
        project_id = self._topic_project(
            "Interrupted review", "Recover a persisted plan after reviewer interruption",
        )
        hypothesis = self.client.post(
            f"/api/projects/{project_id}/hypotheses", json={},
        ).json()["revision"]
        self.assertEqual(self.client.post(
            f"/api/projects/{project_id}/hypotheses/{hypothesis['hypothesis_revision_id']}/decision",
            json={
                "decision": "approved",
                "feedback": "Approve hypothesis for review-recovery testing.",
                "selected_candidate_id": hypothesis["recommended_candidate_id"],
            },
        ).status_code, 201)
        generated = self.client.post(
            f"/api/projects/{project_id}/experiment-plans",
            json={"hypothesis_revision_id": hypothesis["hypothesis_revision_id"]},
        )
        self.assertEqual(generated.status_code, 201, generated.text)
        plan = generated.json()["revision"]

        # Simulate a transport interruption after the immutable Plan was saved but
        # before its independent review could be persisted.
        with self.app.state.services.database.transaction() as connection:
            connection.execute(
                "DELETE FROM planning_review_reports WHERE artifact_kind=? AND artifact_id=?",
                ("experiment_plan", plan["plan_revision_id"]),
            )

        retry = self.client.post(
            f"/api/projects/{project_id}/experiment-plans/{plan['plan_revision_id']}/review",
        )
        self.assertEqual(retry.status_code, 201, retry.text)
        report = retry.json()
        self.assertEqual(report["artifact_id"], plan["plan_revision_id"])
        self.assertEqual(report["artifact_content_hash"], plan["content_hash"])

        repeated = self.client.post(
            f"/api/projects/{project_id}/experiment-plans/{plan['plan_revision_id']}/review",
        )
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertEqual(repeated.json()["report_id"], report["report_id"])

    def test_critical_reviewer_blocks_user_approval_without_self_approval(self):
        project_id = self._topic_project(
            "Blocking review", "Blocking topic for falsifiability audit",
        )
        result = self.client.post(f"/api/projects/{project_id}/hypotheses", json={})
        self.assertEqual(result.status_code, 201, result.text)
        revision = result.json()["revision"]
        review = result.json()["review"]
        self.assertTrue(any(item["severity"] == "major" for item in review["defects"]))
        denied = self.client.post(
            f"/api/projects/{project_id}/hypotheses/{revision['hypothesis_revision_id']}/decision",
            json={"decision": "approved", "feedback": "Attempt approval.",
                  "selected_candidate_id": revision["recommended_candidate_id"]},
        )
        self.assertEqual(denied.status_code, 422)
        self.assertIn("unresolved", denied.text)
        self.assertEqual(
            self.client.get(f"/api/projects/{project_id}/planning/approvals").json(), [],
        )
        agent_runs = self.client.get(f"/api/projects/{project_id}/planning/agent-runs").json()
        self.assertEqual({item["role"] for item in agent_runs},
                         {"research_design_lead", "critical_reviewer"})

    def test_b_mode_plan_binds_reuse_and_declares_semantic_changes(self):
        source = self.allowed / "legacy_project"
        (source / "src").mkdir(parents=True)
        (source / "results").mkdir()
        (source / "figures").mkdir()
        (source / "src" / "experiment.py").write_text(
            "def run_experiment(data):\n    return {'accuracy': 0.7}\n", encoding="utf-8",
        )
        (source / "results" / "metrics.json").write_text(
            '{"accuracy": 0.7, "status": "legacy"}', encoding="utf-8",
        )
        (source / "figures" / "legacy.png").write_bytes(b"legacy-image")
        created = self.client.post("/api/projects", json={
            "title": "Legacy classifier", "project_type": "existing_project",
            "source_root": str(source),
        })
        project_id = created.json()["project"]["project_id"]
        self.assertEqual(self.client.post(
            f"/api/projects/{project_id}/imports", json={"source_root": str(source)},
        ).status_code, 201)
        understanding = self.client.post(
            f"/api/projects/{project_id}/understanding", json={},
        )
        self.assertEqual(understanding.status_code, 201, understanding.text)
        context = understanding.json()["context"]
        assessment = understanding.json()["legacy_reuse_assessment"]
        self._seed_literature(project_id, context["context_id"], context["research_questions"][0])
        hypothesis = self.client.post(f"/api/projects/{project_id}/hypotheses", json={}).json()["revision"]
        self.assertEqual(self.client.post(
            f"/api/projects/{project_id}/hypotheses/{hypothesis['hypothesis_revision_id']}/decision",
            json={"decision": "approved", "feedback": "Approve B-mode hypothesis.",
                  "selected_candidate_id": hypothesis["recommended_candidate_id"]},
        ).status_code, 201)
        plan_response = self.client.post(f"/api/projects/{project_id}/experiment-plans", json={
            "hypothesis_revision_id": hypothesis["hypothesis_revision_id"],
        })
        self.assertEqual(plan_response.status_code, 201, plan_response.text)
        plan = plan_response.json()["revision"]
        binding = plan["plan"]["b_mode_binding"]
        stored_assessment = self.app.state.services.understanding_repository.assessment_for_context(
            context["context_id"]
        )
        self.assertEqual(binding["assessment_id"], assessment["assessment_id"])
        self.assertEqual(binding["assessment_hash"], canonical_hash(stored_assessment))
        required_paths = {
            item["relative_path"] for item in assessment["reuse_items"]
            if item["requires_workspace_copy"]
        }
        self.assertEqual(
            {item["source_relative_path"] for item in binding["code_reuse_decisions"]},
            required_paths,
        )
        self.assertTrue(binding["unverified_observations"])
        self.assertTrue(binding["supplemental_experiments"])
        self.assertTrue(binding["supplemental_figures"])
        self.assertTrue(any(
            modification["classification"] == "semantic"
            for decision in binding["code_reuse_decisions"]
            for modification in decision["modifications"]
        ))
        self.assertTrue(any(
            item["record_type"] == "legacy_reuse_assessment"
            and item["content_hash"] == binding["assessment_hash"]
            for item in plan["provenance"]
        ))

    def _topic_project(self, title, topic):
        created = self.client.post("/api/projects", json={
            "title": title, "project_type": "topic_based", "topic": topic,
        })
        project_id = created.json()["project"]["project_id"]
        understood = self.client.post(
            f"/api/projects/{project_id}/understanding", json={},
        )
        self.assertEqual(understood.status_code, 201, understood.text)
        self._seed_literature(project_id, understood.json()["context"]["context_id"], topic)
        return project_id

    def _seed_literature(self, project_id, context_id, topic):
        source = LiteratureSource(
            title=f"Prior work on {topic}", abstract="A scoped prior study.",
            access_level=AccessLevel.ABSTRACT_ONLY, origins=[LiteratureProvider.OPENALEX],
            provider_record_ids={"openalex": "W-SEED"}, existence_verified=True,
            metadata_verified=True,
        )
        self.app.state.services.literature_repository.save_sources(project_id, context_id, [source])
        evidence = LiteratureEvidence(
            project_id=project_id, context_id=context_id, source_id=source.source_id,
            claim="Prior work motivates a testable but unresolved relationship.",
            support_summary="The indexed abstract establishes background only.",
            role=EvidenceRole.BACKGROUND, source_access_level=AccessLevel.ABSTRACT_ONLY,
        )
        plan = LiteratureQueryPlan(
            topic=topic, context_id=context_id,
            queries=[
                LiteratureQuery(
                    query=topic + " mechanism", rationale="mechanism",
                    keyword_group=[topic],
                    providers=[LiteratureProvider.ARXIV, LiteratureProvider.OPENALEX],
                ),
                LiteratureQuery(
                    query=topic + " empirical test", rationale="evaluation",
                    keyword_group=[topic],
                    providers=[LiteratureProvider.OPENALEX, LiteratureProvider.CROSSREF],
                ),
            ],
        )
        gap = ResearchGap(
            project_id=project_id, context_id=context_id,
            statement="The target question remains unresolved.",
            rationale="Available evidence is background-only.",
            supporting_source_ids=[source.source_id], uncertainty="Full-text review may narrow the gap.",
        )
        matrix = LiteratureEvidenceMatrix(
            project_id=project_id, context_id=context_id, query_plan=plan,
            source_ids=[source.source_id], evidence=[evidence],
            related_work="Prior work motivates but does not resolve the target question.",
            research_gaps=[gap],
        )
        evidence.matrix_id = matrix.matrix_id
        gap.matrix_id = matrix.matrix_id
        matrix = LiteratureEvidenceMatrix.model_validate(matrix.model_dump(mode="json"))
        self.app.state.services.literature_repository.save_matrix(matrix)


if __name__ == "__main__":
    unittest.main()

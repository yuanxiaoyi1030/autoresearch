# Purpose: Orchestrates independent specialist contexts, Meta disagreement synthesis, hard policy, and feedback transitions.
from __future__ import annotations

import os
from typing import Dict, List, Optional

from research_runtime.analysis import AnalysisStatus
from research_runtime.analysis.service import compact_analysis_context
from research_runtime.planning import canonical_hash
from research_runtime.state import ResearchOutcome, ResearchStage
from research_runtime.workflow import WorkflowAction

from .agents import (
    EvidenceReproducibilityReviewer, MetaReviewer, MethodologyReviewer,
    StatisticalReviewer,
)
from .models import (
    ClaimType, EvidenceClaim, EvidenceClaimDraft, MetaReviewReport,
    ResearchReviewAgentRun, ResearchReviewDecision, ResearchReviewRecord,
    ResearchReviewResult, ResearchReviewRole, ResearchReviewTransition,
    ReviewDisagreement, ReviewerPosition, SpecialistReviewReport,
)
from .policy import ResearchPolicyGuard


def _compact_implementation(implementation):
    """Keep reproducibility bindings while omitting code bodies from review input."""
    context = implementation.model_dump(mode="json")
    package = context.get("code_package")
    for item in package.get("files", []) if isinstance(package, dict) else []:
        if isinstance(item, dict) and "content" in item:
            item["content"] = (
                "[file content omitted; verify against implementation content_hash]"
            )
    return context


def _compact_run(run):
    """Expose run provenance without duplicating bulky runtime details."""
    context = run.model_dump(mode="json")
    environment = context.get("environment")
    if isinstance(environment, dict):
        environment["dependency_versions"] = environment.get("dependency_versions", {})
    return context


class IndependentResearchReviewService:
    def __init__(self, projects, planning, understanding, literature, experiments,
                 analyses, review_repository, analysis_runtime, study_runtime,
                 workflow, meta_reviewer: MetaReviewer,
                 methodology_reviewer: MethodologyReviewer,
                 statistical_reviewer: StatisticalReviewer,
                 evidence_reviewer: EvidenceReproducibilityReviewer,
                 events=None) -> None:
        self.projects = projects
        self.planning = planning
        self.understanding = understanding
        self.literature = literature
        self.experiments = experiments
        self.analyses = analyses
        self.repository = review_repository
        self.analysis_runtime = analysis_runtime
        self.study_runtime = study_runtime
        self.workflow = workflow
        self.meta_reviewer = meta_reviewer
        self.specialists = {
            ResearchReviewRole.METHODOLOGY_REVIEWER: methodology_reviewer,
            ResearchReviewRole.STATISTICAL_REVIEWER: statistical_reviewer,
            ResearchReviewRole.EVIDENCE_REPRODUCIBILITY_REVIEWER: evidence_reviewer,
        }
        self.policy = ResearchPolicyGuard(
            planning, experiments, analyses, literature, analysis_runtime, study_runtime,
        )
        self.events = events

    def run(self, project_id: str, analysis_id: str,
            scientific_review_id: Optional[str] = None,
            claim_drafts: Optional[List[EvidenceClaimDraft]] = None) -> ResearchReviewResult:
        inputs = self._inputs(project_id, analysis_id, scientific_review_id)
        analysis = inputs["analysis"]
        scientific = inputs["scientific_review"]
        verification = self.analysis_runtime.verify(analysis_id)
        review_run_id = "research_review_" + os.urandom(16).hex()
        claims = self._claims(project_id, inputs["context"].context_id, analysis, claim_drafts or [])

        assignment_context = {
            "review_contract": {
                "independent_team": True,
                "meta_participated_in_research_generation": False,
                "meta_can_edit_evidence": False,
                "required_specialists": [item.value for item in self.specialists],
            },
            "project_id": project_id,
            "analysis_id": analysis_id,
            "analysis_content_hash": analysis.content_hash,
            "scientific_review_id": scientific.review_id,
            "verification_id": verification.verification_id,
            "claim_ids": [item.claim_id for item in claims],
        }
        assignment_response = self.meta_reviewer.assign(assignment_context)
        self._require_context_hash(assignment_context, assignment_response.input_context_hash,
                                   "Meta Reviewer assignment")
        assignments = assignment_response.value
        self._validate_assignments(assignments)

        specialists = []
        agent_runs = [ResearchReviewAgentRun(
            review_run_id=review_run_id, project_id=project_id,
            context_id=inputs["context"].context_id,
            role=ResearchReviewRole.META_REVIEWER, operation="assign_independent_reviews",
            input_context_hash=assignment_response.input_context_hash,
            output_record_id=review_run_id + ":assignment",
            provider_id=assignment_response.provider_id, model=assignment_response.model,
            input_tokens=assignment_response.input_tokens,
            output_tokens=assignment_response.output_tokens,
        )]
        for assignment in assignments.assignments:
            context = self._specialist_context(assignment, inputs, verification, claims)
            response = self.specialists[assignment.role].review(context)
            self._require_context_hash(context, response.input_context_hash, assignment.role.value)
            draft = response.value
            report = SpecialistReviewReport(
                review_run_id=review_run_id, project_id=project_id,
                context_id=inputs["context"].context_id, analysis_id=analysis_id,
                role=assignment.role, assignment=assignment,
                verdict=draft.verdict, proposed_decision=draft.proposed_decision,
                findings=draft.findings, summary=draft.summary,
                conclusion_boundary=draft.conclusion_boundary,
                independent_context_hash=response.input_context_hash,
                provider_id=response.provider_id, model=response.model,
            )
            specialists.append(report)
            agent_runs.append(ResearchReviewAgentRun(
                review_run_id=review_run_id, project_id=project_id,
                context_id=inputs["context"].context_id, role=assignment.role,
                operation="independent_specialist_review",
                input_context_hash=response.input_context_hash,
                output_record_id=report.specialist_review_id,
                provider_id=response.provider_id, model=response.model,
                input_tokens=response.input_tokens, output_tokens=response.output_tokens,
            ))

        preflight = self.policy.inspect(
            project_id, analysis, scientific, verification, claims,
        )
        meta_context = {
            "review_contract": {
                "independent_meta_context": True,
                "original_generation_chat_included": False,
                "specialist_reports_are_immutable": True,
                "preserve_and_explain_disagreements": True,
                "policy_guard_has_priority": True,
            },
            "assignment_plan": assignments.model_dump(mode="json"),
            "analysis_outcome": analysis.outcome.value,
            "specialist_reports": [item.model_dump(mode="json") for item in specialists],
            "policy_guard_preflight": [item.model_dump(mode="json") for item in preflight],
        }
        meta_response = self.meta_reviewer.synthesize(meta_context)
        self._require_context_hash(meta_context, meta_response.input_context_hash,
                                   "Meta Reviewer synthesis")
        meta_draft = meta_response.value
        disagreements = self._preserve_disagreements(specialists, meta_draft.disagreements)
        meta = MetaReviewReport(
            review_run_id=review_run_id, project_id=project_id,
            context_id=inputs["context"].context_id, analysis_id=analysis_id,
            assignment_plan_hash=canonical_hash(assignments),
            specialist_review_ids=[item.specialist_review_id for item in specialists],
            specialist_review_hashes={
                item.specialist_review_id: item.content_hash for item in specialists
            },
            proposed_decision=meta_draft.proposed_decision,
            synthesis=meta_draft.synthesis, disagreements=disagreements,
            feedback=meta_draft.feedback,
            independent_context_hash=meta_response.input_context_hash,
            provider_id=meta_response.provider_id, model=meta_response.model,
        )
        agent_runs.append(ResearchReviewAgentRun(
            review_run_id=review_run_id, project_id=project_id,
            context_id=inputs["context"].context_id,
            role=ResearchReviewRole.META_REVIEWER, operation="synthesize_specialist_reviews",
            input_context_hash=meta_response.input_context_hash,
            output_record_id=meta.meta_review_id,
            provider_id=meta_response.provider_id, model=meta_response.model,
            input_tokens=meta_response.input_tokens, output_tokens=meta_response.output_tokens,
        ))
        policy = self.policy.decide(
            review_run_id, project_id, inputs["context"].context_id,
            analysis, verification, meta, specialists, preflight,
        )
        record = ResearchReviewRecord(
            review_run_id=review_run_id, project_id=project_id,
            context_id=inputs["context"].context_id, analysis_id=analysis_id,
            analysis_content_hash=analysis.content_hash,
            scientific_review_id=scientific.review_id,
            claim_ids=[item.claim_id for item in claims], assignment_plan=assignments,
            specialist_review_ids=[item.specialist_review_id for item in specialists],
            meta_review_id=meta.meta_review_id,
            policy_decision_id=policy.policy_decision_id,
            final_decision=policy.final_decision,
        )
        self.repository.save_bundle(record, claims, specialists, meta, policy, agent_runs)
        return ResearchReviewResult(
            record=record, claims=claims, specialist_reviews=specialists,
            meta_review=meta, policy_decision=policy,
            verification_id=verification.verification_id, agent_runs=agent_runs,
        )

    def get(self, review_run_id: str) -> ResearchReviewResult:
        record = self.repository.get_record(review_run_id)
        if record is None:
            raise KeyError(review_run_id)
        claims_by_id = {
            item.claim_id: item for item in self.repository.list_claims(record.analysis_id)
        }
        meta = self.repository.get_meta(record.meta_review_id)
        policy = self.repository.get_policy(record.policy_decision_id)
        specialists = self.repository.list_specialists(review_run_id)
        if meta is None or policy is None:
            raise ValueError("research review provenance is incomplete")
        runs = [
            item for item in self.repository.list_agent_runs(record.project_id)
            if item.review_run_id == review_run_id
        ]
        return ResearchReviewResult(
            record=record, claims=[claims_by_id[item] for item in record.claim_ids],
            specialist_reviews=specialists, meta_review=meta,
            policy_decision=policy, verification_id=policy.verification_id,
            agent_runs=runs,
        )

    def apply_feedback(self, review_run_id: str,
                       expected_state_revision: int) -> ResearchReviewTransition:
        if self.repository.get_transition(review_run_id) is not None:
            raise ValueError("research review feedback transition already applied")
        result = self.get(review_run_id)
        record, policy = result.record, result.policy_decision
        state = self.projects.get_state(record.project_id)
        if state is None or state.stage is not ResearchStage.RESEARCH_REVIEW:
            raise ValueError("project must be at RESEARCH_REVIEW to apply this decision")
        analysis = self.analyses.get_analysis(record.analysis_id)
        scientific = self.analyses.get_review(record.scientific_review_id)
        fresh = self.analysis_runtime.verify(record.analysis_id)
        current_rules = self.policy.inspect(
            record.project_id, analysis, scientific, fresh, result.claims,
        )
        current = self.policy.decide(
            review_run_id, record.project_id, record.context_id, analysis,
            fresh, result.meta_review, result.specialist_reviews, current_rules,
        )
        if current.final_decision is not policy.final_decision:
            raise ValueError("research review decision is stale after fresh Policy Guard verification")
        action, outcome = self._workflow_action(policy.final_decision)
        updated = self.workflow.transition(
            record.project_id, action, expected_revision=expected_state_revision,
            outcome=outcome,
        )
        transition = ResearchReviewTransition(
            review_run_id=review_run_id, project_id=record.project_id,
            policy_decision_id=policy.policy_decision_id,
            final_decision=policy.final_decision,
            from_stage=state.stage, to_stage=updated.stage,
            state_revision_before=state.revision,
            state_revision_after=updated.revision,
        )
        self.repository.save_transition(transition)
        return transition

    def _inputs(self, project_id, analysis_id, scientific_review_id):
        project = self.projects.get(project_id)
        analysis = self.analyses.get_analysis(analysis_id)
        if (project is None or analysis is None or analysis.project_id != project_id
                or analysis.status is not AnalysisStatus.COMPLETED or analysis.payload is None):
            raise ValueError("completed AnalysisRecord does not belong to project")
        study = self.experiments.get_study(analysis.study_id)
        context = self.understanding.get_context(analysis.context_id)
        plan = self.planning.repository.get_plan(analysis.plan_revision_id)
        implementation = self.experiments.get_implementation(analysis.implementation_revision_id)
        hypothesis = self.planning.repository.get_hypothesis(plan.hypothesis_revision_id) if plan else None
        reviews = self.analyses.list_reviews(analysis_id)
        scientific = (
            self.analyses.get_review(scientific_review_id)
            if scientific_review_id else (reviews[-1] if reviews else None)
        )
        if any(item is None for item in (study, context, plan, implementation, hypothesis, scientific)):
            raise ValueError("formal research-review provenance is incomplete")
        if (scientific.analysis_id != analysis_id
                or scientific.analysis_content_hash != analysis.content_hash):
            raise ValueError("ScientificReviewReport does not bind this AnalysisRecord")
        return {
            "project": project, "analysis": analysis, "study": study,
            "context": context, "plan": plan, "implementation": implementation,
            "hypothesis": hypothesis, "scientific_review": scientific,
            "runs": self.experiments.list_runs(study.study_id),
        }

    def _claims(self, project_id, context_id, analysis, drafts):
        artifacts = self.analyses.list_artifacts(analysis.analysis_id)
        auto = EvidenceClaimDraft(
            claim_type=ClaimType.EXPERIMENT_RESULT,
            statement=analysis.payload.outcome_rationale,
            outcome=analysis.outcome, core_claim=True,
            analysis_artifact_ids=[item.artifact_id for item in artifacts],
            experiment_artifact_ids=list(analysis.payload.source_artifact_ids),
            comparison_ids=[item.comparison_id for item in analysis.payload.comparisons],
        )
        return [EvidenceClaim(
            project_id=project_id, context_id=context_id,
            analysis_id=analysis.analysis_id,
            analysis_content_hash=analysis.content_hash,
            **draft.model_dump(mode="json"),
        ) for draft in [auto, *drafts]]

    @staticmethod
    def _validate_assignments(plan):
        requirements = {
            ResearchReviewRole.METHODOLOGY_REVIEWER: {
                "ExperimentPlanRevision", "HypothesisRevision",
            },
            ResearchReviewRole.STATISTICAL_REVIEWER: {
                "AnalysisRecord", "VerificationReport",
            },
            ResearchReviewRole.EVIDENCE_REPRODUCIBILITY_REVIEWER: {
                "EvidenceClaim", "Artifact", "ReproducibilitySpec",
            },
        }
        for assignment in plan.assignments:
            if not requirements[assignment.role] <= set(assignment.required_record_types):
                raise ValueError(f"Meta assignment omitted required records for {assignment.role.value}")

    def _specialist_context(self, assignment, inputs, verification, claims):
        common = {
            "review_contract": {
                "independent_context": True,
                "original_agent_chat_included": False,
                "peer_review_reports_included": False,
                "reviewer_can_modify_evidence": False,
                "role": assignment.role.value,
            },
            "assignment": assignment.model_dump(mode="json"),
            "evidence_claims": [item.model_dump(mode="json") for item in claims],
            "scientific_review": inputs["scientific_review"].model_dump(mode="json"),
        }
        if assignment.role is ResearchReviewRole.METHODOLOGY_REVIEWER:
            common.update({
                "approved_hypothesis": inputs["hypothesis"].model_dump(mode="json"),
                "approved_experiment_plan": inputs["plan"].model_dump(mode="json"),
                "implementation_tasks": inputs["implementation"].task_graph.model_dump(mode="json"),
            })
        elif assignment.role is ResearchReviewRole.STATISTICAL_REVIEWER:
            common.update({
                "approved_metrics": [item.model_dump(mode="json") for item in inputs["plan"].plan.metrics],
                "approved_analysis_spec": inputs["plan"].plan.analysis.model_dump(mode="json"),
                "approved_run_specs": [item.model_dump(mode="json") for item in inputs["plan"].plan.runs],
                "analysis_record": compact_analysis_context(inputs["analysis"]),
                "deterministic_verification": verification.model_dump(mode="json"),
            })
        else:
            source_artifacts = [
                item for run in inputs["runs"]
                for item in self.experiments.list_artifacts(run.run_id)
            ]
            analysis = inputs["analysis"]
            claims_artifact_ids = {
                artifact_id
                for claim in claims
                for artifact_id in claim.experiment_artifact_ids
            }
            source_artifacts = [
                item for item in source_artifacts
                if item.artifact_id in claims_artifact_ids
            ]
            literature_evidence_ids = {
                evidence_id
                for claim in claims
                for evidence_id in claim.literature_evidence_ids
            }
            literature_evidence = [
                item for item in self.literature.list_evidence(inputs["project"].project_id)
                if item.evidence_id in literature_evidence_ids
            ]
            literature_source_ids = {item.source_id for item in literature_evidence}
            common.update({
                "analysis_artifacts": [
                    item.model_dump(mode="json")
                    for item in self.analyses.list_artifacts(analysis.analysis_id)
                ],
                "experiment_artifacts": [item.model_dump(mode="json") for item in source_artifacts],
                "implementation": _compact_implementation(inputs["implementation"]),
                "run_records": [_compact_run(item) for item in inputs["runs"]],
                "code_lineage": [
                    item.model_dump(mode="json")
                    for item in self.understanding.list_lineage(inputs["project"].project_id)
                ],
                "reproducibility_spec": inputs["plan"].plan.reproducibility.model_dump(mode="json"),
                "literature_evidence": [
                    item.model_dump(mode="json")
                    for item in literature_evidence
                ],
                "literature_sources": [
                    item.model_dump(mode="json")
                    for item in self.literature.list_sources(inputs["project"].project_id)
                    if item.source_id in literature_source_ids
                ],
                "deterministic_verification": verification.model_dump(mode="json"),
            })
        return common

    @staticmethod
    def _preserve_disagreements(specialists, supplied):
        disagreements = list(supplied)
        decisions = {item.proposed_decision for item in specialists}
        if len(decisions) > 1:
            actual_positions = {
                item.role: item.proposed_decision for item in specialists
            }
            covered = any(
                {position.role: position.proposed_decision for position in item.positions}
                == actual_positions
                for item in disagreements
            )
            if not covered:
                disagreements.append(ReviewDisagreement(
                    issue="Specialist final-decision divergence",
                    positions=[ReviewerPosition(
                        role=item.role, proposed_decision=item.proposed_decision,
                        rationale=item.summary,
                    ) for item in specialists],
                    resolution=(
                        "All positions are retained; deterministic Policy Guard and the Meta synthesis "
                        "select the final workflow action without deleting minority views."
                    ),
                    unresolved=False,
                ))
        return disagreements

    @staticmethod
    def _workflow_action(decision):
        if decision is ResearchReviewDecision.RETURN_TO_EXPERIMENT:
            return WorkflowAction.REVIEW_RETURN_TO_EXPERIMENT, None
        if decision is ResearchReviewDecision.REVISE_PLAN:
            return WorkflowAction.REVIEW_REVISE_PLAN, None
        outcome = {
            ResearchReviewDecision.SUPPORTED: ResearchOutcome.SUPPORTED,
            ResearchReviewDecision.NEGATIVE_RESULT: ResearchOutcome.NEGATIVE_RESULT,
            ResearchReviewDecision.INSUFFICIENT_EVIDENCE: ResearchOutcome.INSUFFICIENT_EVIDENCE,
        }[decision]
        return WorkflowAction.REVIEW_APPROVED, outcome

    @staticmethod
    def _require_context_hash(context, actual, role):
        expected = canonical_hash(context)
        if actual != expected:
            raise ValueError(f"{role} independent context hash mismatch")

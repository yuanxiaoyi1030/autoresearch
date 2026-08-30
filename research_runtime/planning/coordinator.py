# Purpose: Deterministically validates, reviews, versions, approves, and gates generic research plans.
from __future__ import annotations

from typing import List, Optional

from research_runtime.state import ProjectType
from research_runtime.understanding import (
    LegacyReuseAssessment, MaterialKind, ResearchContext, ReuseDisposition,
)

from .agents import CriticalReviewer, ResearchDesignLead
from .models import (
    ApprovalDecision, BModePlanBinding, CodeReuseAction, ExperimentPlanDraft,
    ExperimentPlanRevision, FeedbackSource, FormalExperimentGate, HypothesisGenerationResult,
    HypothesisRevision, PlanGenerationResult, PlanningAgentRole, PlanningAgentRun,
    PlanningApproval, PlanningArtifactKind, PlanningReviewReport, ProvenanceLink,
    RevisionFeedback, canonical_hash,
)


class PlanningCoordinator:
    AGENT_COUNT = 2

    def __init__(self, projects, understanding, literature, repository,
                 lead: ResearchDesignLead, reviewer: CriticalReviewer) -> None:
        self.projects = projects
        self.understanding = understanding
        self.literature = literature
        self.repository = repository
        self.lead = lead
        self.reviewer = reviewer

    def generate_hypotheses(self, project_id: str, *, parent_revision_id: Optional[str] = None,
                            user_feedback: Optional[List[str]] = None) -> HypothesisGenerationResult:
        context, matrix = self._current_inputs(project_id)
        parent = None
        feedback: List[RevisionFeedback] = []
        latest = self.repository.latest_hypothesis(project_id)
        if latest is not None:
            if not parent_revision_id:
                raise ValueError("a hypothesis revision already exists; parent_revision_id is required")
            parent = self.repository.get_hypothesis(parent_revision_id)
            if parent is None or parent.project_id != project_id:
                raise ValueError("parent hypothesis revision does not belong to project")
            if parent.hypothesis_revision_id != latest.hypothesis_revision_id:
                raise ValueError("hypothesis revisions must descend from the latest revision")
            feedback = self._feedback(PlanningArtifactKind.HYPOTHESIS, parent_revision_id, user_feedback)
            if not feedback:
                raise ValueError("hypothesis revision requires reviewer or user feedback")
            prior_review = self.repository.latest_review(
                PlanningArtifactKind.HYPOTHESIS, parent_revision_id,
            )
            response = self.lead.revise_hypotheses(
                context, matrix, parent, feedback, prior_review,
            )
            revision_number = parent.revision + 1
        else:
            if parent_revision_id:
                raise ValueError("initial hypothesis generation cannot specify a parent")
            if user_feedback:
                raise ValueError("initial hypothesis generation cannot contain revision feedback")
            response = self.lead.generate_hypotheses(context, matrix)
            revision_number = 0

        self._validate_hypothesis_draft(context, matrix, response.value)
        provenance = self._base_provenance(context, matrix)
        if parent is not None:
            provenance.append(ProvenanceLink(
                record_type="hypothesis_revision", record_id=parent.hypothesis_revision_id,
                content_hash=parent.content_hash, relationship="revises",
            ))
        revision = HypothesisRevision(
            project_id=project_id, context_id=context.context_id,
            literature_matrix_id=matrix.matrix_id, revision=revision_number,
            parent_revision_id=parent.hypothesis_revision_id if parent else None,
            research_question=response.value.research_question,
            candidates=response.value.candidates,
            recommended_candidate_id=response.value.recommended_candidate_id,
            comparison=response.value.comparison, feedback=feedback, provenance=provenance,
        )
        self.repository.save_hypothesis(revision)
        lead_run = self._run(
            project_id, context.context_id, PlanningAgentRole.RESEARCH_DESIGN_LEAD,
            "revise_hypotheses" if parent else "generate_hypotheses",
            PlanningArtifactKind.HYPOTHESIS, revision.hypothesis_revision_id,
            revision.revision, response,
        )
        self.repository.save_agent_run(lead_run)
        review_context = self._hypothesis_review_context(context, matrix, revision)
        review_response = self.reviewer.review_hypothesis(review_context)
        review = self._review_report(
            project_id, context.context_id, PlanningArtifactKind.HYPOTHESIS,
            revision.hypothesis_revision_id, revision.content_hash, revision.revision,
            review_context, review_response,
        )
        self.repository.save_review(review)
        reviewer_run = self._run(
            project_id, context.context_id, PlanningAgentRole.CRITICAL_REVIEWER,
            "review_hypothesis", PlanningArtifactKind.HYPOTHESIS,
            revision.hypothesis_revision_id, revision.revision, review_response,
            input_hash=review.independent_context_hash,
        )
        self.repository.save_agent_run(reviewer_run)
        return HypothesisGenerationResult(
            revision=revision, review=review, agent_runs=[lead_run, reviewer_run],
        )

    def generate_plan(self, project_id: str, hypothesis_revision_id: str, *,
                      parent_revision_id: Optional[str] = None,
                      user_feedback: Optional[List[str]] = None) -> PlanGenerationResult:
        project = self.projects.get(project_id)
        context = self.understanding.latest_context(project_id)
        hypothesis = self.repository.get_hypothesis(hypothesis_revision_id)
        if project is None or context is None:
            raise ValueError("project understanding is missing")
        if hypothesis is None or hypothesis.project_id != project_id:
            raise ValueError("hypothesis revision does not belong to project")
        latest_hypothesis = self.repository.latest_hypothesis(project_id)
        if latest_hypothesis.hypothesis_revision_id != hypothesis_revision_id:
            raise ValueError("Experiment Plan must use the latest hypothesis revision")
        if hypothesis.content_hash != hypothesis.calculated_hash():
            raise ValueError("hypothesis hash verification failed")
        hypothesis_approval = self.repository.approval_for(
            PlanningArtifactKind.HYPOTHESIS, hypothesis_revision_id,
        )
        if hypothesis_approval is None or hypothesis_approval.decision is not ApprovalDecision.APPROVED:
            raise ValueError("Hypothesis requires user approval before Experiment Planning")
        if hypothesis_approval.artifact_content_hash != hypothesis.content_hash:
            raise ValueError("Hypothesis approval hash does not match revision")
        if not hypothesis_approval.selected_candidate_id:
            raise ValueError("Hypothesis approval must select a candidate")
        matrix = self.literature.get_matrix(hypothesis.literature_matrix_id)
        if matrix is None or matrix.context_id != context.context_id:
            raise ValueError("approved hypothesis literature provenance is unavailable")
        reuse = self._reuse_assessment(project.project_type, context)

        parent = None
        feedback: List[RevisionFeedback] = []
        latest_plan = self.repository.latest_plan(project_id)
        if latest_plan is not None:
            if not parent_revision_id:
                raise ValueError("an Experiment Plan revision already exists; parent_revision_id is required")
            parent = self.repository.get_plan(parent_revision_id)
            if parent is None or parent.project_id != project_id:
                raise ValueError("parent Experiment Plan does not belong to project")
            if parent.plan_revision_id != latest_plan.plan_revision_id:
                raise ValueError("Experiment Plan revisions must descend from the latest revision")
            feedback = self._feedback(PlanningArtifactKind.EXPERIMENT_PLAN, parent_revision_id, user_feedback)
            if not feedback:
                raise ValueError("Experiment Plan revision requires reviewer or user feedback")
            prior_review = self.repository.latest_review(
                PlanningArtifactKind.EXPERIMENT_PLAN, parent_revision_id,
            )
            response = self.lead.revise_plan(
                context, matrix, hypothesis, hypothesis_approval, parent, feedback,
                prior_review, reuse,
            )
            revision_number = parent.revision + 1
        else:
            if parent_revision_id:
                raise ValueError("initial Experiment Plan cannot specify a parent")
            if user_feedback:
                raise ValueError("initial Experiment Plan cannot contain revision feedback")
            response = self.lead.generate_plan(
                context, matrix, hypothesis, hypothesis_approval, reuse,
            )
            revision_number = 0

        plan_draft = self._validate_plan_draft(project.project_type, context, reuse, response.value)
        provenance = self._base_provenance(context, matrix)
        provenance.extend([
            ProvenanceLink(
                record_type="hypothesis_revision", record_id=hypothesis.hypothesis_revision_id,
                content_hash=hypothesis.content_hash, relationship="implements_selected_candidate",
            ),
            ProvenanceLink(
                record_type="hypothesis_approval", record_id=hypothesis_approval.approval_id,
                content_hash=canonical_hash(hypothesis_approval), relationship="authorized_by_user",
            ),
        ])
        if reuse is not None:
            provenance.append(ProvenanceLink(
                record_type="legacy_reuse_assessment", record_id=reuse.assessment_id,
                content_hash=canonical_hash(reuse), relationship="binds_legacy_reuse",
            ))
        if parent is not None:
            provenance.append(ProvenanceLink(
                record_type="experiment_plan_revision", record_id=parent.plan_revision_id,
                content_hash=parent.content_hash, relationship="revises",
            ))
        revision = ExperimentPlanRevision(
            project_id=project_id, context_id=context.context_id,
            literature_matrix_id=matrix.matrix_id,
            hypothesis_revision_id=hypothesis.hypothesis_revision_id,
            hypothesis_content_hash=hypothesis.content_hash,
            selected_candidate_id=hypothesis_approval.selected_candidate_id,
            hypothesis_approval_id=hypothesis_approval.approval_id,
            revision=revision_number, parent_revision_id=parent.plan_revision_id if parent else None,
            plan=plan_draft, feedback=feedback, provenance=provenance,
        )
        self.repository.save_plan(revision)
        lead_run = self._run(
            project_id, context.context_id, PlanningAgentRole.RESEARCH_DESIGN_LEAD,
            "revise_plan" if parent else "generate_plan",
            PlanningArtifactKind.EXPERIMENT_PLAN, revision.plan_revision_id,
            revision.revision, response,
        )
        self.repository.save_agent_run(lead_run)
        review_context = self._plan_review_context(context, matrix, hypothesis, revision, reuse)
        review_response = self.reviewer.review_plan(review_context)
        review = self._review_report(
            project_id, context.context_id, PlanningArtifactKind.EXPERIMENT_PLAN,
            revision.plan_revision_id, revision.content_hash, revision.revision,
            review_context, review_response,
        )
        self.repository.save_review(review)
        reviewer_run = self._run(
            project_id, context.context_id, PlanningAgentRole.CRITICAL_REVIEWER,
            "review_plan", PlanningArtifactKind.EXPERIMENT_PLAN,
            revision.plan_revision_id, revision.revision, review_response,
            input_hash=review.independent_context_hash,
        )
        self.repository.save_agent_run(reviewer_run)
        return PlanGenerationResult(
            revision=revision, review=review, agent_runs=[lead_run, reviewer_run],
        )

    def review_plan_revision(self, project_id: str,
                             plan_revision_id: str) -> PlanningReviewReport:
        """Idempotently review a persisted plan whose original request was interrupted."""
        plan = self.repository.get_plan(plan_revision_id)
        latest = self.repository.latest_plan(project_id)
        if plan is None or plan.project_id != project_id:
            raise ValueError("Experiment Plan revision does not belong to project")
        if latest is None or latest.plan_revision_id != plan_revision_id:
            raise ValueError("only the latest Experiment Plan revision can be reviewed")
        if plan.content_hash != plan.calculated_hash():
            raise ValueError("Experiment Plan hash verification failed")

        existing = self.repository.latest_review(
            PlanningArtifactKind.EXPERIMENT_PLAN, plan_revision_id,
        )
        if existing is not None and existing.artifact_content_hash == plan.content_hash:
            return existing

        project = self.projects.get(project_id)
        context = self.understanding.get_context(plan.context_id)
        hypothesis = self.repository.get_hypothesis(plan.hypothesis_revision_id)
        if project is None or context is None or hypothesis is None:
            raise ValueError("Experiment Plan review provenance is unavailable")
        matrix = self.literature.get_matrix(plan.literature_matrix_id)
        if matrix is None or matrix.context_id != context.context_id:
            raise ValueError("Experiment Plan literature provenance is unavailable")
        reuse = self._reuse_assessment(project.project_type, context)

        review_context = self._plan_review_context(context, matrix, hypothesis, plan, reuse)
        review_response = self.reviewer.review_plan(review_context)
        review = self._review_report(
            project_id, context.context_id, PlanningArtifactKind.EXPERIMENT_PLAN,
            plan.plan_revision_id, plan.content_hash, plan.revision,
            review_context, review_response,
        )
        self.repository.save_review(review)
        reviewer_run = self._run(
            project_id, context.context_id, PlanningAgentRole.CRITICAL_REVIEWER,
            "review_plan", PlanningArtifactKind.EXPERIMENT_PLAN,
            plan.plan_revision_id, plan.revision, review_response,
            input_hash=review.independent_context_hash,
        )
        self.repository.save_agent_run(reviewer_run)
        return review

    def decide(self, project_id: str, kind: PlanningArtifactKind, artifact_id: str,
               decision: ApprovalDecision, feedback: str, *, actor_id: str = "local_user",
               selected_candidate_id: Optional[str] = None) -> PlanningApproval:
        if not feedback.strip():
            raise ValueError("user approval/rejection requires feedback")
        if kind is PlanningArtifactKind.HYPOTHESIS:
            artifact = self.repository.get_hypothesis(artifact_id)
            latest = self.repository.latest_hypothesis(project_id)
            if artifact is None or artifact.project_id != project_id:
                raise ValueError("hypothesis revision does not belong to project")
            if latest is None or latest.hypothesis_revision_id != artifact_id:
                raise ValueError("only the latest hypothesis revision can receive a decision")
            if decision is ApprovalDecision.APPROVED:
                if selected_candidate_id not in {item.candidate_id for item in artifact.candidates}:
                    raise ValueError("Hypothesis approval must select an existing candidate")
            elif selected_candidate_id is not None:
                raise ValueError("rejected Hypothesis cannot select a candidate")
        else:
            artifact = self.repository.get_plan(artifact_id)
            latest = self.repository.latest_plan(project_id)
            if artifact is None or artifact.project_id != project_id:
                raise ValueError("Experiment Plan revision does not belong to project")
            if latest is None or latest.plan_revision_id != artifact_id:
                raise ValueError("only the latest Experiment Plan revision can receive a decision")
            if selected_candidate_id is not None:
                raise ValueError("Experiment Plan decisions do not select a hypothesis candidate")
        if artifact.content_hash != artifact.calculated_hash():
            raise ValueError("artifact hash verification failed")
        review = self.repository.latest_review(kind, artifact_id)
        if review is None or review.artifact_content_hash != artifact.content_hash:
            raise ValueError("artifact requires an independent Critical Review")
        if decision is ApprovalDecision.APPROVED and review.has_blocking_defects:
            raise ValueError("artifact has unresolved major or blocking Critical Reviewer defects")
        approval = PlanningApproval(
            project_id=project_id, artifact_kind=kind, artifact_id=artifact_id,
            artifact_content_hash=artifact.content_hash, decision=decision,
            selected_candidate_id=selected_candidate_id, feedback=feedback,
            actor_id=actor_id,
        )
        self.repository.save_approval(approval)
        return approval

    def formal_experiment_gate(self, project_id: str,
                               plan_revision_id: str) -> FormalExperimentGate:
        reasons = []
        plan = self.repository.get_plan(plan_revision_id)
        if plan is None or plan.project_id != project_id:
            return FormalExperimentGate(
                allowed=False, plan_revision_id=plan_revision_id,
                plan_content_hash="0" * 64, reasons=["Experiment Plan revision not found"],
            )
        latest = self.repository.latest_plan(project_id)
        if latest is None or latest.plan_revision_id != plan_revision_id:
            reasons.append("only the latest Experiment Plan revision is eligible")
        if plan.content_hash != plan.calculated_hash():
            reasons.append("Experiment Plan hash verification failed")
        approval = self.repository.approval_for(
            PlanningArtifactKind.EXPERIMENT_PLAN, plan_revision_id,
        )
        if approval is None or approval.decision is not ApprovalDecision.APPROVED:
            reasons.append("Experiment Plan has not been approved by the user")
        elif approval.artifact_content_hash != plan.content_hash:
            reasons.append("Experiment Plan approval hash mismatch")
        hypothesis = self.repository.get_hypothesis(plan.hypothesis_revision_id)
        latest_hypothesis = self.repository.latest_hypothesis(project_id)
        hypothesis_approval = self.repository.approval_for(
            PlanningArtifactKind.HYPOTHESIS, plan.hypothesis_revision_id,
        )
        if hypothesis is None or hypothesis.content_hash != plan.hypothesis_content_hash:
            reasons.append("approved Hypothesis provenance is invalid")
        elif latest_hypothesis is None or latest_hypothesis.hypothesis_revision_id != hypothesis.hypothesis_revision_id:
            reasons.append("bound Hypothesis is no longer the latest revision")
        elif hypothesis_approval is None or hypothesis_approval.decision is not ApprovalDecision.APPROVED:
            reasons.append("bound Hypothesis is not user-approved")
        elif hypothesis_approval.approval_id != plan.hypothesis_approval_id:
            reasons.append("bound Hypothesis approval record mismatch")
        elif hypothesis_approval.selected_candidate_id != plan.selected_candidate_id:
            reasons.append("selected Hypothesis candidate does not match its approval")
        plan_review = self.repository.latest_review(
            PlanningArtifactKind.EXPERIMENT_PLAN, plan_revision_id,
        )
        if plan_review is None or plan_review.artifact_content_hash != plan.content_hash:
            reasons.append("Experiment Plan Critical Review is missing or hash-mismatched")
        elif plan_review.has_blocking_defects:
            reasons.append("Experiment Plan has unresolved Critical Reviewer defects")
        project = self.projects.get(project_id)
        context = self.understanding.get_context(plan.context_id)
        if project is None or context is None:
            reasons.append("Experiment Plan ResearchContext provenance is unavailable")
        elif project.project_type is ProjectType.EXISTING_PROJECT:
            binding = plan.plan.b_mode_binding
            assessment = self.understanding.assessment_for_context(context.context_id)
            if binding is None or assessment is None:
                reasons.append("B-mode LegacyReuseAssessment binding is missing")
            elif (
                binding.assessment_id != assessment.assessment_id
                or binding.assessment_hash != canonical_hash(assessment)
                or binding.import_id != assessment.import_id
                or binding.manifest_hash != context.manifest_hash
            ):
                reasons.append("B-mode LegacyReuseAssessment binding failed verification")
        return FormalExperimentGate(
            allowed=not reasons, plan_revision_id=plan_revision_id,
            plan_content_hash=plan.content_hash,
            approval_id=approval.approval_id if approval else None, reasons=reasons,
        )

    def require_formal_experiment(self, project_id: str,
                                  plan_revision_id: str) -> ExperimentPlanRevision:
        gate = self.formal_experiment_gate(project_id, plan_revision_id)
        if not gate.allowed:
            raise ValueError("formal experiment gate denied: " + "; ".join(gate.reasons))
        return self.repository.get_plan(plan_revision_id)

    def _current_inputs(self, project_id: str):
        project = self.projects.get(project_id)
        context = self.understanding.latest_context(project_id)
        matrix = self.literature.latest_matrix(project_id)
        if project is None:
            raise ValueError("project not found")
        if context is None:
            raise ValueError("Project Understanding must complete first")
        if matrix is None or matrix.context_id != context.context_id:
            raise ValueError("current Literature Evidence Matrix is required")
        return context, matrix

    @staticmethod
    def _validate_hypothesis_draft(context, matrix, draft) -> None:
        evidence_ids = {item.evidence_id for item in matrix.evidence}
        for candidate in draft.candidates:
            unknown = set(candidate.supporting_evidence_ids) - evidence_ids
            if unknown:
                raise ValueError("Hypothesis references unknown Literature Evidence ids")
        context_text = " ".join(filter(None, [context.topic, context.summary, *context.research_questions])).casefold()
        candidate_text = " ".join(
            item.statement + " " + item.rationale for item in draft.candidates
        ).casefold()
        context_terms = {term for term in context_text.replace("?", " ").split() if len(term) > 2}
        if context_terms and not any(term in candidate_text for term in context_terms):
            raise ValueError("Hypothesis candidates are not traceably aligned with current Topic")

    def _validate_plan_draft(self, project_type, context, reuse, draft):
        if project_type is ProjectType.TOPIC_BASED:
            if draft.b_mode_binding is not None:
                raise ValueError("A-mode Experiment Plan cannot contain a legacy reuse binding")
            return draft
        if reuse is None or draft.b_mode_binding is None:
            raise ValueError("B-mode Experiment Plan requires LegacyReuseAssessment binding")
        binding = draft.b_mode_binding.model_copy(update={
            "assessment_id": reuse.assessment_id,
            "assessment_hash": canonical_hash(reuse),
            "import_id": reuse.import_id,
            "manifest_hash": context.manifest_hash,
            "recommended_strategy": reuse.recommended_strategy,
        })
        binding = BModePlanBinding.model_validate(binding.model_dump(mode="json"))
        known_paths = {item.relative_path for item in reuse.reuse_items}
        decision_paths = {item.source_relative_path for item in binding.code_reuse_decisions}
        if decision_paths - known_paths:
            raise ValueError("B-mode code reuse decision references unknown legacy path")
        required_code_paths = {
            item.relative_path for item in reuse.reuse_items if item.requires_workspace_copy
        }
        if required_code_paths - decision_paths:
            raise ValueError("B-mode Plan must decide adapt/refactor/reimplementation for every reusable code path")
        for decision in binding.code_reuse_decisions:
            reuse_item = next(item for item in reuse.reuse_items
                              if item.relative_path == decision.source_relative_path)
            if reuse_item.requires_workspace_copy and decision.action is CodeReuseAction.RETAIN_REFERENCE_ONLY:
                raise ValueError("reusable code requires adapt, refactor, or reimplementation decision")
            if reuse_item.disposition is ReuseDisposition.REIMPLEMENT and decision.action is not CodeReuseAction.REIMPLEMENT:
                raise ValueError("LegacyReuseAssessment reimplementation disposition must be preserved")
        if context.detected_experiments and not binding.preserved_experiment_designs:
            raise ValueError("B-mode Plan must explicitly identify preserved experiment designs")
        if context.existing_result_summaries and not binding.unverified_observations:
            raise ValueError("legacy results must be listed as unverified observations")
        if not binding.supplemental_experiments:
            raise ValueError("B-mode Plan must identify supplemental/reproduction experiments")
        has_legacy_figures = any(MaterialKind.FIGURE in item.kinds for item in context.materials)
        if has_legacy_figures and not binding.supplemental_figures:
            raise ValueError("B-mode Plan must identify supplemental or regenerated figures")
        return ExperimentPlanDraft.model_validate(
            draft.model_copy(update={"b_mode_binding": binding}).model_dump(mode="json")
        )

    def _feedback(self, kind, artifact_id, user_feedback) -> List[RevisionFeedback]:
        feedback = []
        review = self.repository.latest_review(kind, artifact_id)
        if review:
            feedback.extend(RevisionFeedback(
                source=FeedbackSource.CRITICAL_REVIEWER, reference_id=item.defect_id,
                message=item.summary + " Required action: " + item.suggested_action,
            ) for item in review.defects)
        decision = self.repository.approval_for(kind, artifact_id)
        if decision and decision.decision is ApprovalDecision.REJECTED:
            feedback.append(RevisionFeedback(
                source=FeedbackSource.USER, reference_id=decision.approval_id,
                message=decision.feedback,
            ))
        for index, message in enumerate(user_feedback or []):
            if message.strip():
                feedback.append(RevisionFeedback(
                    source=FeedbackSource.USER,
                    reference_id=f"request:{artifact_id}:{index}", message=message,
                ))
        return feedback

    @staticmethod
    def _base_provenance(context, matrix):
        return [
            ProvenanceLink(
                record_type="research_context", record_id=context.context_id,
                content_hash=canonical_hash(context), relationship="derived_from",
            ),
            ProvenanceLink(
                record_type="literature_evidence_matrix", record_id=matrix.matrix_id,
                content_hash=canonical_hash(matrix), relationship="evidence_basis",
            ),
        ]

    @staticmethod
    def _hypothesis_review_context(context, matrix, revision):
        return {
            "review_contract": {
                "independent_context": True, "lead_chat_history_included": False,
                "reviewer_can_approve": False,
                "checks": ["novelty", "falsifiability", "topic_alignment", "feasibility",
                           "confounding", "alternative_explanation"],
            },
            "research_context": context.model_dump(mode="json"),
            "literature_evidence_matrix": matrix.model_dump(mode="json"),
            "hypothesis_revision": revision.model_dump(mode="json"),
        }

    @staticmethod
    def _plan_review_context(context, matrix, hypothesis, revision, reuse):
        return {
            "review_contract": {
                "independent_context": True, "lead_chat_history_included": False,
                "reviewer_can_approve": False,
                "checks": ["baseline", "ablation", "control_variable", "statistical_design",
                           "executability", "resource_budget", "reproducibility", "confounding",
                           "alternative_explanation", "legacy_reuse"],
            },
            "research_context": context.model_dump(mode="json"),
            "literature_evidence_matrix": matrix.model_dump(mode="json"),
            "approved_hypothesis": hypothesis.model_dump(mode="json"),
            "experiment_plan_revision": revision.model_dump(mode="json"),
            "legacy_reuse_assessment": reuse.model_dump(mode="json") if reuse else None,
        }

    @staticmethod
    def _review_report(project_id, context_id, kind, artifact_id, artifact_hash,
                       revision, review_context, response):
        return PlanningReviewReport(
            project_id=project_id, context_id=context_id, artifact_kind=kind,
            artifact_id=artifact_id, artifact_content_hash=artifact_hash,
            revision=revision, defects=response.value.defects,
            reviewer_summary=response.value.reviewer_summary,
            independent_context_hash=canonical_hash(review_context),
        )

    @staticmethod
    def _run(project_id, context_id, role, operation, kind, artifact_id,
             revision, response, input_hash=None):
        return PlanningAgentRun(
            project_id=project_id, context_id=context_id, role=role,
            operation=operation, artifact_kind=kind, artifact_id=artifact_id,
            revision=revision, input_context_hash=input_hash or response.input_context_hash,
            provider_id=response.provider_id, model=response.model,
            input_tokens=response.input_tokens, output_tokens=response.output_tokens,
        )

    def _reuse_assessment(self, project_type, context) -> Optional[LegacyReuseAssessment]:
        if project_type is ProjectType.TOPIC_BASED:
            return None
        assessment = self.understanding.assessment_for_context(context.context_id)
        if assessment is None:
            raise ValueError("B-mode Experiment Plan requires LegacyReuseAssessment")
        return assessment

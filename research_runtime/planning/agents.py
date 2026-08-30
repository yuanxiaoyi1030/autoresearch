# Purpose: Implements independent Research Design Lead and Critical Reviewer LLM roles.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Generic, Optional, TypeVar

from research_runtime.literature import LiteratureEvidenceMatrix
from research_runtime.llm import LLMMessage, LLMRole, LLMRuntime, LLMStage
from research_runtime.llm.prompts.planning import (
    hypothesis_generation_prompt, hypothesis_review_prompt, hypothesis_revision_prompt,
    plan_generation_prompt, plan_review_prompt, plan_revision_prompt,
)
from research_runtime.understanding import LegacyReuseAssessment, ResearchContext

from .models import (
    ExistingProjectExperimentPlanDraft, ExperimentPlanDraft, ExperimentPlanRevision,
    HypothesisDraft, HypothesisRevision, PlanningApproval, PlanningReviewDraft,
    PlanningReviewReport, TopicExperimentPlanDraft,
    canonical_hash,
)


T = TypeVar("T")


@dataclass(frozen=True)
class AgentResponse(Generic[T]):
    value: T
    input_context_hash: str
    provider_id: str = "scripted"
    model: str = "scripted"
    input_tokens: int = 0
    output_tokens: int = 0


class ResearchDesignLead(ABC):
    @abstractmethod
    def generate_hypotheses(self, context: ResearchContext,
                            literature: LiteratureEvidenceMatrix) -> AgentResponse[HypothesisDraft]:
        raise NotImplementedError

    @abstractmethod
    def revise_hypotheses(self, context: ResearchContext, literature: LiteratureEvidenceMatrix,
                          parent: HypothesisRevision, feedback: list,
                          prior_review: Optional[PlanningReviewReport]) -> AgentResponse[HypothesisDraft]:
        raise NotImplementedError

    @abstractmethod
    def generate_plan(self, context: ResearchContext, literature: LiteratureEvidenceMatrix,
                      hypothesis: HypothesisRevision, approval: PlanningApproval,
                      reuse: Optional[LegacyReuseAssessment]) -> AgentResponse[ExperimentPlanDraft]:
        raise NotImplementedError

    @abstractmethod
    def revise_plan(self, context: ResearchContext, literature: LiteratureEvidenceMatrix,
                    hypothesis: HypothesisRevision, approval: PlanningApproval,
                    parent: ExperimentPlanRevision, feedback: list,
                    prior_review: Optional[PlanningReviewReport],
                    reuse: Optional[LegacyReuseAssessment]) -> AgentResponse[ExperimentPlanDraft]:
        raise NotImplementedError


class CriticalReviewer(ABC):
    @abstractmethod
    def review_hypothesis(self, independent_context: dict) -> AgentResponse[PlanningReviewDraft]:
        raise NotImplementedError

    @abstractmethod
    def review_plan(self, independent_context: dict) -> AgentResponse[PlanningReviewDraft]:
        raise NotImplementedError


class LLMResearchDesignLead(ResearchDesignLead):
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def generate_hypotheses(self, context, literature):
        payload = {
            "research_context": self._context(context),
            "literature_evidence_matrix": literature.model_dump(mode="json"),
        }
        return self._call(
            HypothesisDraft,
            hypothesis_generation_prompt(),
            payload,
        )

    def revise_hypotheses(self, context, literature, parent, feedback, prior_review):
        payload = {
            "research_context": self._context(context),
            "literature_evidence_matrix": literature.model_dump(mode="json"),
            "parent_revision": parent.model_dump(mode="json"),
            "revision_feedback": [item.model_dump(mode="json") for item in feedback],
            "critical_review": prior_review.model_dump(mode="json") if prior_review else None,
        }
        return self._call(
            HypothesisDraft,
            hypothesis_revision_prompt(),
            payload,
        )

    def generate_plan(self, context, literature, hypothesis, approval, reuse):
        payload = self._plan_payload(context, literature, hypothesis, approval, reuse)
        return self._call(
            ExistingProjectExperimentPlanDraft if reuse else TopicExperimentPlanDraft,
            plan_generation_prompt(bool(reuse)),
            payload,
        )

    def revise_plan(self, context, literature, hypothesis, approval, parent, feedback,
                    prior_review, reuse):
        payload = self._plan_payload(context, literature, hypothesis, approval, reuse)
        payload.update({
            "parent_plan_revision": parent.model_dump(mode="json"),
            "revision_feedback": [item.model_dump(mode="json") for item in feedback],
            "critical_review": prior_review.model_dump(mode="json") if prior_review else None,
        })
        return self._call(
            ExistingProjectExperimentPlanDraft if reuse else TopicExperimentPlanDraft,
            plan_revision_prompt(bool(reuse)),
            payload,
        )

    def _call(self, output_model, instruction: str, payload: dict):
        client, route, ledger = self.runtime.client_for(LLMStage.HYPOTHESIS_PLANNING)
        value, result = client.generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=instruction),
                LLMMessage(role=LLMRole.USER, content=json.dumps(payload, ensure_ascii=False)),
            ],
            output_model, route.budget, ledger=ledger,
            metadata={"stage": LLMStage.HYPOTHESIS_PLANNING.value,
                      "agent": "research_design_lead"},
        )
        return AgentResponse(
            value=value, input_context_hash=canonical_hash(payload),
            provider_id=result.provider_id, model=result.model,
            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
        )

    @staticmethod
    def _context(context: ResearchContext) -> dict:
        return {
            "context_id": context.context_id, "mode": context.mode.value,
            "topic": context.topic, "summary": context.summary,
            "research_questions": context.research_questions,
            "existing_claims": context.existing_claims,
            "existing_result_summaries": context.existing_result_summaries,
            "detected_experiments": context.detected_experiments,
            "detected_metrics": context.detected_metrics,
            "missing_evidence": context.missing_evidence,
            "user_constraints": context.user_constraints.model_dump(mode="json"),
        }

    def _plan_payload(self, context, literature, hypothesis, approval, reuse):
        candidate = next(
            item for item in hypothesis.candidates
            if item.candidate_id == approval.selected_candidate_id
        )
        return {
            "research_context": self._context(context),
            "literature_evidence_matrix": literature.model_dump(mode="json"),
            "approved_hypothesis_revision": hypothesis.model_dump(mode="json"),
            "selected_hypothesis": candidate.model_dump(mode="json"),
            "user_approval": approval.model_dump(mode="json"),
            "legacy_reuse_assessment": reuse.model_dump(mode="json") if reuse else None,
        }

class LLMCriticalReviewer(CriticalReviewer):
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def review_hypothesis(self, independent_context: dict):
        return self._review(independent_context, hypothesis_review_prompt())

    def review_plan(self, independent_context: dict):
        return self._review(independent_context, plan_review_prompt())

    def _review(self, payload: dict, instruction: str):
        client, route, ledger = self.runtime.client_for(LLMStage.HYPOTHESIS_PLANNING)
        value, result = client.generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=instruction),
                LLMMessage(role=LLMRole.USER, content=json.dumps(payload, ensure_ascii=False)),
            ],
            PlanningReviewDraft, route.budget, ledger=ledger,
            metadata={"stage": LLMStage.HYPOTHESIS_PLANNING.value,
                      "agent": "critical_reviewer"},
        )
        return AgentResponse(
            value=value, input_context_hash=canonical_hash(payload),
            provider_id=result.provider_id, model=result.model,
            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
        )

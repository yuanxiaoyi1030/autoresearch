# Purpose: Implements four isolated structured research-review roles with no evidence mutation capability.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Generic, TypeVar

from research_runtime.llm import LLMMessage, LLMRole, LLMRuntime, LLMStage
from research_runtime.llm.prompts.review import (
    evidence_reproducibility_review_prompt, meta_assignment_prompt, meta_synthesis_prompt,
    methodology_review_prompt, statistical_review_prompt,
)
from research_runtime.planning import canonical_hash

from .models import MetaAssignmentPlan, MetaReviewDraft, SpecialistReviewDraft


T = TypeVar("T")


@dataclass(frozen=True)
class ReviewerResponse(Generic[T]):
    value: T
    input_context_hash: str
    provider_id: str = "scripted"
    model: str = "scripted"
    input_tokens: int = 0
    output_tokens: int = 0


class MetaReviewer(ABC):
    @abstractmethod
    def assign(self, assignment_context: dict) -> ReviewerResponse[MetaAssignmentPlan]:
        raise NotImplementedError

    @abstractmethod
    def synthesize(self, synthesis_context: dict) -> ReviewerResponse[MetaReviewDraft]:
        raise NotImplementedError


class MethodologyReviewer(ABC):
    @abstractmethod
    def review(self, independent_context: dict) -> ReviewerResponse[SpecialistReviewDraft]:
        raise NotImplementedError


class StatisticalReviewer(ABC):
    @abstractmethod
    def review(self, independent_context: dict) -> ReviewerResponse[SpecialistReviewDraft]:
        raise NotImplementedError


class EvidenceReproducibilityReviewer(ABC):
    @abstractmethod
    def review(self, independent_context: dict) -> ReviewerResponse[SpecialistReviewDraft]:
        raise NotImplementedError


class _LLMStructuredReviewer:
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def _call(self, instruction, context, output_model, operation):
        client, route, ledger = self.runtime.client_for(LLMStage.RESEARCH_REVIEW)
        value, result = client.generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=instruction),
                LLMMessage(
                    role=LLMRole.USER,
                    content=json.dumps(context, ensure_ascii=False, sort_keys=True),
                ),
            ], output_model, route.budget, ledger=ledger,
            metadata={"stage": LLMStage.RESEARCH_REVIEW.value, "agent": operation},
        )
        return ReviewerResponse(
            value=value, input_context_hash=canonical_hash(context),
            provider_id=result.provider_id, model=result.model,
            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
        )


class LLMMetaReviewer(_LLMStructuredReviewer, MetaReviewer):
    def assign(self, assignment_context):
        return self._call(
            meta_assignment_prompt(),
            assignment_context, MetaAssignmentPlan, "meta_reviewer_assignment",
        )

    def synthesize(self, synthesis_context):
        return self._call(
            meta_synthesis_prompt(),
            synthesis_context, MetaReviewDraft, "meta_reviewer_synthesis",
        )


class LLMMethodologyReviewer(_LLMStructuredReviewer, MethodologyReviewer):
    def review(self, independent_context):
        return self._call(
            methodology_review_prompt(),
            independent_context, SpecialistReviewDraft, "methodology_reviewer",
        )


class LLMStatisticalReviewer(_LLMStructuredReviewer, StatisticalReviewer):
    def review(self, independent_context):
        return self._call(
            statistical_review_prompt(),
            independent_context, SpecialistReviewDraft, "statistical_reviewer",
        )


class LLMEvidenceReproducibilityReviewer(
        _LLMStructuredReviewer, EvidenceReproducibilityReviewer):
    def review(self, independent_context):
        return self._call(
            evidence_reproducibility_review_prompt(),
            independent_context, SpecialistReviewDraft, "evidence_reproducibility_reviewer",
        )

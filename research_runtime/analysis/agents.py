# Purpose: Limits Scientific Reviewer LLM work to structured qualitative judgment over verified records.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json

from research_runtime.llm import LLMMessage, LLMRole, LLMRuntime, LLMStage
from research_runtime.llm.prompts.analysis import scientific_review_prompt
from research_runtime.planning import canonical_hash

from .models import ScientificReviewDraft


@dataclass(frozen=True)
class ReviewResponse:
    value: ScientificReviewDraft
    input_context_hash: str
    provider_id: str = "scripted"
    model: str = "scripted"
    input_tokens: int = 0
    output_tokens: int = 0


class ScientificReviewer(ABC):
    @abstractmethod
    def review(self, review_context: dict) -> ReviewResponse:
        raise NotImplementedError


class LLMScientificReviewer(ScientificReviewer):
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def review(self, review_context: dict) -> ReviewResponse:
        client, route, ledger = self.runtime.client_for(LLMStage.ANALYSIS)
        value, result = client.generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=scientific_review_prompt()),
                LLMMessage(
                    role=LLMRole.USER,
                    content=json.dumps(review_context, ensure_ascii=False, sort_keys=True),
                ),
            ],
            ScientificReviewDraft, route.budget, ledger=ledger,
            metadata={"stage": LLMStage.ANALYSIS.value, "agent": "scientific_reviewer"},
        )
        return ReviewResponse(
            value=value, input_context_hash=canonical_hash(review_context),
            provider_id=result.provider_id, model=result.model,
            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
        )

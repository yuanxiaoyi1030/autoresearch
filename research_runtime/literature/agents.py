# Purpose: Provides two independent LLM agents for literature planning/synthesis and evidence review.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
import json
from typing import Generic, List, TypeVar

from research_runtime.llm import LLMMessage, LLMRole, LLMRuntime, LLMStage
from research_runtime.llm.prompts.literature import (
    evidence_review_prompt, query_planning_prompt, revision_prompt, synthesis_prompt,
)
from research_runtime.understanding import ResearchContext

from .models import (
    EvidenceReviewDraft, LiteratureEvidenceMatrix, LiteratureQueryPlan, LiteratureSource,
    LiteratureSynthesis, ReviewDefect,
)


T = TypeVar("T")


def canonical_hash(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentResponse(Generic[T]):
    value: T
    input_context_hash: str
    provider_id: str = "scripted"
    model: str = "scripted"
    input_tokens: int = 0
    output_tokens: int = 0


class LiteratureLead(ABC):
    @abstractmethod
    def plan_queries(self, context: ResearchContext) -> AgentResponse[LiteratureQueryPlan]:
        raise NotImplementedError

    @abstractmethod
    def synthesize(self, context: ResearchContext, plan: LiteratureQueryPlan,
                   sources: List[LiteratureSource]) -> AgentResponse[LiteratureSynthesis]:
        raise NotImplementedError

    @abstractmethod
    def revise(self, context: ResearchContext, matrix: LiteratureEvidenceMatrix,
               sources: List[LiteratureSource], defects: List[ReviewDefect]) -> AgentResponse[LiteratureSynthesis]:
        raise NotImplementedError


class EvidenceReviewer(ABC):
    @abstractmethod
    def review(self, independent_context: dict) -> AgentResponse[EvidenceReviewDraft]:
        raise NotImplementedError


class LLMLiteratureLead(LiteratureLead):
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def plan_queries(self, context: ResearchContext) -> AgentResponse[LiteratureQueryPlan]:
        payload = {
            "context_id": context.context_id,
            "topic": context.topic or context.summary,
            "research_questions": context.research_questions,
            "existing_claims": context.existing_claims,
            "missing_evidence": context.missing_evidence,
        }
        return self._call(
            LiteratureQueryPlan,
            query_planning_prompt(),
            payload,
        )

    def synthesize(self, context: ResearchContext, plan: LiteratureQueryPlan,
                   sources: List[LiteratureSource]) -> AgentResponse[LiteratureSynthesis]:
        payload = {
            "research_context": self._context_view(context),
            "query_plan": plan.model_dump(mode="json"),
            "sources": [source.model_dump(mode="json") for source in sources],
        }
        return self._call(
            LiteratureSynthesis,
            synthesis_prompt(),
            payload,
        )

    def revise(self, context: ResearchContext, matrix: LiteratureEvidenceMatrix,
               sources: List[LiteratureSource], defects: List[ReviewDefect]) -> AgentResponse[LiteratureSynthesis]:
        payload = {
            "research_context": self._context_view(context),
            "prior_matrix": matrix.model_dump(mode="json"),
            "source_facts": [source.model_dump(mode="json") for source in sources],
            "reviewer_defects": [defect.model_dump(mode="json") for defect in defects],
        }
        return self._call(
            LiteratureSynthesis,
            revision_prompt(),
            payload,
        )

    def _call(self, model, instruction: str, payload: dict):
        client, route, ledger = self.runtime.client_for(LLMStage.LITERATURE)
        input_hash = canonical_hash(payload)
        value, result = client.generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=instruction),
                LLMMessage(role=LLMRole.USER, content=json.dumps(payload, ensure_ascii=False)),
            ],
            model,
            route.budget,
            ledger=ledger,
            metadata={"stage": LLMStage.LITERATURE.value, "agent": "literature_lead"},
        )
        return AgentResponse(
            value=value, input_context_hash=input_hash, provider_id=result.provider_id,
            model=result.model, input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

    @staticmethod
    def _context_view(context: ResearchContext) -> dict:
        return {
            "context_id": context.context_id,
            "topic": context.topic,
            "summary": context.summary,
            "research_questions": context.research_questions,
            "existing_claims": context.existing_claims,
            "missing_evidence": context.missing_evidence,
            "constraints": context.user_constraints.model_dump(mode="json"),
        }


class LLMEvidenceReviewer(EvidenceReviewer):
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def review(self, independent_context: dict) -> AgentResponse[EvidenceReviewDraft]:
        client, route, ledger = self.runtime.client_for(LLMStage.LITERATURE)
        input_hash = canonical_hash(independent_context)
        value, result = client.generate_structured(
            [
                LLMMessage(
                    role=LLMRole.SYSTEM,
                    content=evidence_review_prompt(),
                ),
                LLMMessage(
                    role=LLMRole.USER,
                    content=json.dumps(independent_context, ensure_ascii=False),
                ),
            ],
            EvidenceReviewDraft,
            route.budget,
            ledger=ledger,
            metadata={"stage": LLMStage.LITERATURE.value, "agent": "evidence_reviewer"},
        )
        return AgentResponse(
            value=value, input_context_hash=input_hash, provider_id=result.provider_id,
            model=result.model, input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

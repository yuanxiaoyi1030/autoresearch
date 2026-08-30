# Purpose: Implements five structured, evidence-bounded paper-writing roles.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Generic, TypeVar

from research_runtime.llm import LLMMessage, LLMRole, LLMRuntime, LLMStage
from research_runtime.llm.prompts.writing import (
    citation_editor_prompt, lead_author_prompt, presentation_editor_prompt,
    technical_editor_prompt, top_conference_review_prompt,
)
from research_runtime.planning import canonical_hash

from .models import (
    CitationEditorDraft, LeadAuthorDraft, PresentationDraft, TechnicalContentDraft,
    TopConferenceReviewDraft,
)


T = TypeVar("T")


@dataclass(frozen=True)
class PaperAgentResponse(Generic[T]):
    value: T
    input_context_hash: str
    provider_id: str = "scripted"
    model: str = "scripted"
    input_tokens: int = 0
    output_tokens: int = 0


class LeadAuthor(ABC):
    @abstractmethod
    def author(self, context: dict) -> PaperAgentResponse[LeadAuthorDraft]:
        raise NotImplementedError


class TechnicalContentEditor(ABC):
    @abstractmethod
    def edit(self, context: dict) -> PaperAgentResponse[TechnicalContentDraft]:
        raise NotImplementedError


class RelatedWorkCitationEditor(ABC):
    @abstractmethod
    def edit(self, context: dict) -> PaperAgentResponse[CitationEditorDraft]:
        raise NotImplementedError


class PresentationLatexEditor(ABC):
    @abstractmethod
    def edit(self, context: dict) -> PaperAgentResponse[PresentationDraft]:
        raise NotImplementedError


class TopConferenceReviewer(ABC):
    @abstractmethod
    def review(self, context: dict) -> PaperAgentResponse[TopConferenceReviewDraft]:
        raise NotImplementedError


class _LLMPaperAgent:
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def _call(self, instruction, context, output_model, operation):
        client, route, ledger = self.runtime.client_for(LLMStage.WRITER)
        value, result = client.generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=instruction),
                LLMMessage(
                    role=LLMRole.USER,
                    content=json.dumps(context, ensure_ascii=False, sort_keys=True),
                ),
            ],
            output_model,
            route.budget,
            ledger=ledger,
            metadata={"stage": LLMStage.WRITER.value, "agent": operation},
        )
        return PaperAgentResponse(
            value=value,
            input_context_hash=canonical_hash(context),
            provider_id=result.provider_id,
            model=result.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )


class LLMLeadAuthor(_LLMPaperAgent, LeadAuthor):
    def author(self, context):
        return self._call(
            lead_author_prompt(),
            context, LeadAuthorDraft, "lead_author",
        )


class LLMTechnicalContentEditor(_LLMPaperAgent, TechnicalContentEditor):
    def edit(self, context):
        return self._call(
            technical_editor_prompt(),
            context, TechnicalContentDraft, "technical_content_editor",
        )


class LLMRelatedWorkCitationEditor(_LLMPaperAgent, RelatedWorkCitationEditor):
    def edit(self, context):
        return self._call(
            citation_editor_prompt(),
            context, CitationEditorDraft, "related_work_citation_editor",
        )


class LLMPresentationLatexEditor(_LLMPaperAgent, PresentationLatexEditor):
    def edit(self, context):
        return self._call(
            presentation_editor_prompt(),
            context, PresentationDraft, "presentation_latex_editor",
        )


class LLMTopConferenceReviewer(_LLMPaperAgent, TopConferenceReviewer):
    def review(self, context):
        return self._call(
            top_conference_review_prompt(),
            context, TopConferenceReviewDraft, "top_conference_reviewer",
        )

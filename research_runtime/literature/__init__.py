# Purpose: Exposes the literature Multi-Agent domain and orchestration API.
from .models import (
    AccessLevel, CitationLocator, DefectSeverity, EvidenceDraft, EvidenceReviewDraft,
    EvidenceReviewReport, EvidenceRole,
    LiteratureAgentRole, LiteratureAgentRun, LiteratureEvidence, LiteratureEvidenceMatrix,
    LiteratureProvider, LiteratureQuery, LiteratureQueryPlan, LiteratureRunResult,
    LiteratureSource, LiteratureSynthesis, ResearchGap, ResearchGapDraft, ReviewDefect,
    ReviewDefectCategory, SearchAttempt, SearchAttemptStatus,
)
from .agents import (
    AgentResponse, EvidenceReviewer, LLMEvidenceReviewer, LLMLiteratureLead, LiteratureLead,
)
from .clients import ArxivClient, CrossrefClient, LiteratureSearchClient, OpenAlexClient, default_clients
from .coordinator import LiteratureCoordinator
from .search import LiteratureSearchCoordinator

__all__ = [
    "AccessLevel", "CitationLocator", "DefectSeverity", "EvidenceDraft", "EvidenceReviewDraft",
    "EvidenceReviewReport", "EvidenceRole",
    "LiteratureAgentRole", "LiteratureAgentRun", "LiteratureEvidence",
    "LiteratureEvidenceMatrix", "LiteratureProvider", "LiteratureQuery",
    "LiteratureQueryPlan", "LiteratureRunResult", "LiteratureSource", "LiteratureSynthesis",
    "ResearchGap", "ResearchGapDraft", "ReviewDefect", "ReviewDefectCategory", "SearchAttempt",
    "SearchAttemptStatus",
    "AgentResponse", "ArxivClient", "CrossrefClient", "EvidenceReviewer",
    "LLMEvidenceReviewer", "LLMLiteratureLead", "LiteratureCoordinator", "LiteratureLead",
    "LiteratureSearchClient", "LiteratureSearchCoordinator", "OpenAlexClient", "default_clients",
]

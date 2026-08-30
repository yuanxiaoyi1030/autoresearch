# Purpose: Defines auditable literature search, evidence, review, and immutable revision contracts.
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, model_validator

from research_runtime.state import utc_now


def identifier(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


class LiteratureProvider(str, Enum):
    ARXIV = "arxiv"
    OPENALEX = "openalex"
    CROSSREF = "crossref"
    IMPORTED_PDF = "imported_pdf"


class SearchAttemptStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class AccessLevel(str, Enum):
    METADATA_ONLY = "metadata_only"
    ABSTRACT_ONLY = "abstract_only"
    FULL_TEXT = "full_text"
    IMPORTED_PDF = "imported_pdf"


class EvidenceRole(str, Enum):
    BACKGROUND = "background"
    METHOD = "method"
    CONTRAST = "contrast"
    CORE_SUPPORT = "core_support"


class DefectSeverity(str, Enum):
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    BLOCKING = "blocking"


class ReviewDefectCategory(str, Enum):
    EXISTENCE = "existence"
    DOI = "doi"
    VERSION = "version"
    LOCATOR = "locator"
    ACCESS_LEVEL = "access_level"
    CLAIM_SUPPORT = "claim_support"
    MISSING_LITERATURE = "missing_literature"
    SYNTHESIS = "synthesis"


class LiteratureAgentRole(str, Enum):
    LEAD = "literature_lead"
    EVIDENCE_REVIEWER = "evidence_reviewer"


class LiteratureQuery(BaseModel):
    query_id: str = Field(default_factory=lambda: identifier("query_"))
    query: str = Field(min_length=2)
    rationale: str = Field(min_length=1)
    keyword_group: List[str] = Field(min_length=1)
    providers: List[LiteratureProvider] = Field(
        default_factory=lambda: [
            LiteratureProvider.ARXIV,
            LiteratureProvider.OPENALEX,
            LiteratureProvider.CROSSREF,
        ],
        min_length=1,
    )


class LiteratureQueryPlan(BaseModel):
    topic: str = Field(min_length=2)
    context_id: str = Field(min_length=1)
    queries: List[LiteratureQuery] = Field(min_length=2)
    inclusion_criteria: List[str] = Field(default_factory=list)
    exclusion_criteria: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_distinct_queries(self) -> "LiteratureQueryPlan":
        normalized = {" ".join(item.query.casefold().split()) for item in self.queries}
        if len(normalized) < 2:
            raise ValueError("literature query plan requires at least two distinct queries")
        public = {
            provider for item in self.queries for provider in item.providers
            if provider is not LiteratureProvider.IMPORTED_PDF
        }
        if len(public) < 2:
            raise ValueError("literature query plan requires at least two public search providers")
        return self


class SearchAttempt(BaseModel):
    attempt_id: str = Field(default_factory=lambda: identifier("search_"))
    project_id: str
    context_id: str
    query_id: str
    provider: LiteratureProvider
    query: str
    status: SearchAttemptStatus
    result_count: int = Field(default=0, ge=0)
    request_parameters: Dict[str, object] = Field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)


class CitationLocator(BaseModel):
    version: Optional[str] = None
    pages: Optional[str] = None
    section: Optional[str] = None
    paragraph: Optional[str] = None
    figure: Optional[str] = None
    table: Optional[str] = None
    locator_text: Optional[str] = None

    @property
    def is_precise(self) -> bool:
        return any((self.pages, self.section, self.paragraph, self.figure, self.table))


class LiteratureSource(BaseModel):
    source_id: str = Field(default_factory=lambda: identifier("source_"))
    title: str = Field(min_length=1)
    authors: List[str] = Field(default_factory=list)
    publication_year: Optional[int] = Field(default=None, ge=1000, le=3000)
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    openalex_id: Optional[str] = None
    version: Optional[str] = None
    pages: Optional[str] = None
    sections: List[str] = Field(default_factory=list)
    abstract: Optional[str] = None
    landing_url: Optional[str] = None
    full_text_url: Optional[str] = None
    imported_relative_path: Optional[str] = None
    access_level: AccessLevel = AccessLevel.METADATA_ONLY
    origins: List[LiteratureProvider] = Field(min_length=1)
    provider_record_ids: Dict[str, str] = Field(default_factory=dict)
    cited_by_count: int = Field(default=0, ge=0)
    relevance_score: float = Field(default=0.0, ge=0.0)
    existence_verified: bool = False
    metadata_verified: bool = False

    @model_validator(mode="after")
    def validate_access(self) -> "LiteratureSource":
        if self.access_level is AccessLevel.METADATA_ONLY and self.abstract:
            self.access_level = AccessLevel.ABSTRACT_ONLY
        if self.access_level is AccessLevel.IMPORTED_PDF and not self.imported_relative_path:
            raise ValueError("imported_pdf access requires imported_relative_path")
        return self


class LiteratureEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: identifier("evidence_"))
    project_id: str
    context_id: str
    matrix_id: Optional[str] = None
    source_id: str
    claim: str = Field(min_length=1)
    support_summary: str = Field(min_length=1)
    role: EvidenceRole
    source_access_level: AccessLevel
    locator: CitationLocator = Field(default_factory=CitationLocator)

    @model_validator(mode="after")
    def enforce_core_evidence_boundary(self) -> "LiteratureEvidence":
        if self.role is EvidenceRole.CORE_SUPPORT:
            if self.source_access_level in {AccessLevel.METADATA_ONLY, AccessLevel.ABSTRACT_ONLY}:
                raise ValueError("metadata-only or abstract-only sources cannot support core scientific claims")
            if not self.locator.is_precise:
                raise ValueError("core scientific claim evidence requires a precise citation locator")
        return self


class ResearchGap(BaseModel):
    gap_id: str = Field(default_factory=lambda: identifier("gap_"))
    project_id: str
    context_id: str
    matrix_id: Optional[str] = None
    statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    supporting_source_ids: List[str] = Field(default_factory=list)
    uncertainty: str = Field(min_length=1)


class EvidenceDraft(BaseModel):
    source_id: str
    claim: str = Field(min_length=1)
    support_summary: str = Field(min_length=1)
    role: EvidenceRole
    locator: CitationLocator = Field(default_factory=CitationLocator)


class ResearchGapDraft(BaseModel):
    statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    supporting_source_ids: List[str] = Field(default_factory=list)
    uncertainty: str = Field(min_length=1)


class LiteratureSynthesis(BaseModel):
    related_work: str = Field(min_length=1)
    evidence: List[EvidenceDraft] = Field(default_factory=list)
    research_gaps: List[ResearchGapDraft] = Field(min_length=1)


class LiteratureEvidenceMatrix(BaseModel):
    matrix_id: str = Field(default_factory=lambda: identifier("matrix_"))
    project_id: str
    context_id: str
    revision: int = Field(default=0, ge=0)
    parent_matrix_id: Optional[str] = None
    query_plan: LiteratureQueryPlan
    source_ids: List[str] = Field(default_factory=list)
    evidence: List[LiteratureEvidence] = Field(default_factory=list)
    related_work: str = Field(min_length=1)
    research_gaps: List[ResearchGap] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)


class ReviewDefect(BaseModel):
    defect_id: str = Field(default_factory=lambda: identifier("defect_"))
    category: ReviewDefectCategory
    severity: DefectSeverity
    summary: str = Field(min_length=1)
    source_id: Optional[str] = None
    evidence_id: Optional[str] = None
    suggested_action: str = Field(min_length=1)


class EvidenceReviewReport(BaseModel):
    report_id: str = Field(default_factory=lambda: identifier("review_"))
    project_id: str
    context_id: str
    matrix_id: str
    revision: int = Field(ge=0)
    defects: List[ReviewDefect] = Field(default_factory=list)
    missing_key_literature_queries: List[str] = Field(default_factory=list)
    reviewer_summary: str = Field(min_length=1)
    independent_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def requires_revision(self) -> bool:
        return any(item.severity in {DefectSeverity.MAJOR, DefectSeverity.BLOCKING} for item in self.defects)


class EvidenceReviewDraft(BaseModel):
    defects: List[ReviewDefect] = Field(default_factory=list)
    missing_key_literature_queries: List[str] = Field(default_factory=list)
    reviewer_summary: str = Field(min_length=1)


class LiteratureAgentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: identifier("litrun_"))
    project_id: str
    context_id: str
    role: LiteratureAgentRole
    operation: str
    revision: int = Field(ge=0)
    input_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact_id: str
    provider_id: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class LiteratureRunResult(BaseModel):
    final_matrix: LiteratureEvidenceMatrix
    sources: List[LiteratureSource]
    search_attempts: List[SearchAttempt]
    review_reports: List[EvidenceReviewReport]
    agent_runs: List[LiteratureAgentRun]

# Purpose: Defines evidence-bound paper drafts, immutable revisions, conference review, artifacts, and QA records.
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Dict, List, Optional
import re
import uuid

from pydantic import BaseModel, Field, model_validator

from research_runtime.literature import AccessLevel, CitationLocator
from research_runtime.planning import canonical_hash
from research_runtime.state import ResearchOutcome, utc_now


def identifier(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("paper artifact path must be a confined relative path")
    return path.as_posix()


class ConferenceTarget(str, Enum):
    NEURIPS = "neurips"
    ICML = "icml"
    ICLR = "iclr"
    GENERIC_TOP_CONFERENCE = "generic_top_conference"


class PaperAgentRole(str, Enum):
    LEAD_AUTHOR = "lead_author"
    TECHNICAL_CONTENT_EDITOR = "technical_content_editor"
    RELATED_WORK_CITATION_EDITOR = "related_work_citation_editor"
    PRESENTATION_LATEX_EDITOR = "presentation_latex_editor"
    TOP_CONFERENCE_REVIEWER = "top_conference_reviewer"


class PaperSectionName(str, Enum):
    INTRODUCTION = "introduction"
    RELATED_WORK = "related_work"
    METHOD = "method"
    THEORY = "theory"
    EXPERIMENTAL_SETUP = "experimental_setup"
    RESULTS = "results"
    ANALYSIS = "analysis"
    LIMITATIONS = "limitations"
    BROADER_IMPACT = "broader_impact"
    CONCLUSION = "conclusion"
    APPENDIX = "appendix"


class PaperDefectSeverity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"
    BLOCKING = "blocking"


class PaperReviewRecommendation(str, Enum):
    READY = "ready"
    REVISE = "revise"
    RETURN_TO_RESEARCH_REVIEW = "return_to_research_review"


class PaperRevisionStatus(str, Enum):
    DRAFT = "draft"
    NEEDS_REVISION = "needs_revision"
    QUALITY_PASSED = "quality_passed"
    EVIDENCE_BLOCKED = "evidence_blocked"


class PaperArtifactKind(str, Enum):
    PAPER_TEX = "paper_tex"
    REFERENCES_BIB = "references_bib"
    FIGURE = "figure"
    TABLE = "table"
    APPENDIX = "appendix"
    REPRODUCIBILITY_STATEMENT = "reproducibility_statement"
    MARKDOWN_PREVIEW = "markdown_preview"
    PDF = "pdf"
    BUILD_LOG = "build_log"
    PDF_PAGE_RENDER = "pdf_page_render"


class PaperGateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class ConferenceTemplateConfig(BaseModel):
    target: ConferenceTarget
    template_version: str = Field(default="builtin-2026.1", min_length=1)
    anonymized: bool = True
    author_names: List[str] = Field(default_factory=lambda: ["Anonymous Authors"])
    max_parallel_agents: int = Field(default=2, ge=1, le=2)
    max_review_revisions: int = Field(default=2, ge=0, le=2)
    build_timeout_seconds: int = Field(default=120, ge=10, le=300)

    @model_validator(mode="after")
    def anonymous_authors(self) -> "ConferenceTemplateConfig":
        if self.anonymized:
            self.author_names = ["Anonymous Authors"]
        if not self.author_names:
            raise ValueError("paper requires at least one author label")
        return self


class PaperSectionDraft(BaseModel):
    section: PaperSectionName
    title: str = Field(min_length=1)
    paragraphs: List[str] = Field(min_length=1)

    @model_validator(mode="after")
    def plain_text_only(self) -> "PaperSectionDraft":
        forbidden = re.compile(
            r"\\(?:begin|end|input|include|write18|usepackage|documentclass|bibliography|bibliographystyle)\b",
            re.IGNORECASE,
        )
        if any(forbidden.search(item) for item in self.paragraphs):
            raise ValueError("Agent paper prose must be plain text with controlled markers, not raw LaTeX")
        return self


class ContributionDraft(BaseModel):
    statement: str = Field(min_length=1)
    claim_ids: List[str] = Field(min_length=1)


class LeadAuthorDraft(BaseModel):
    title: str = Field(min_length=1)
    abstract: str = Field(min_length=1)
    contributions: List[ContributionDraft] = Field(min_length=1)
    outline: List[PaperSectionName] = Field(min_length=1)
    narrative: str = Field(min_length=1)
    terminology: Dict[str, str] = Field(default_factory=dict)
    notation: Dict[str, str] = Field(default_factory=dict)
    sections: List[PaperSectionDraft] = Field(min_length=2)


class PaperNumberBindingDraft(BaseModel):
    binding_id: str = Field(default_factory=lambda: identifier("number_binding_"))
    literal: str = Field(min_length=1, max_length=128)
    artifact_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    section: PaperSectionName


class TechnicalContentDraft(BaseModel):
    sections: List[PaperSectionDraft] = Field(min_length=5)
    number_bindings: List[PaperNumberBindingDraft] = Field(default_factory=list)
    method_assumptions: List[str] = Field(default_factory=list)
    analysis_boundaries: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_technical_sections(self) -> "TechnicalContentDraft":
        required = {
            PaperSectionName.METHOD, PaperSectionName.THEORY,
            PaperSectionName.EXPERIMENTAL_SETUP, PaperSectionName.RESULTS,
            PaperSectionName.ANALYSIS,
        }
        if not required.issubset({item.section for item in self.sections}):
            raise ValueError("Technical Editor must cover Method, Theory, Setup, Results, and Analysis")
        return self


class CitationUseDraft(BaseModel):
    source_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    section: PaperSectionName
    purpose: str = Field(min_length=1)
    locator: CitationLocator


class NoveltyClaimDraft(BaseModel):
    statement: str = Field(min_length=1)
    supporting_evidence_ids: List[str] = Field(min_length=1)
    contrasting_source_ids: List[str] = Field(min_length=1)


class CitationEditorDraft(BaseModel):
    introduction: PaperSectionDraft
    related_work: PaperSectionDraft
    citation_uses: List[CitationUseDraft] = Field(min_length=1)
    novelty_claims: List[NoveltyClaimDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def section_ownership(self) -> "CitationEditorDraft":
        if self.introduction.section is not PaperSectionName.INTRODUCTION:
            raise ValueError("Citation Editor introduction section mismatch")
        if self.related_work.section is not PaperSectionName.RELATED_WORK:
            raise ValueError("Citation Editor related-work section mismatch")
        return self


class FigurePlacementDraft(BaseModel):
    label: str = Field(pattern=r"^fig:[a-z0-9_-]+$")
    caption: str = Field(min_length=1)
    source_artifact_id: Optional[str] = None
    legacy_relative_path: Optional[str] = None
    legacy_unverified: bool = False

    @model_validator(mode="after")
    def source_boundary(self) -> "FigurePlacementDraft":
        if bool(self.source_artifact_id) == bool(self.legacy_relative_path):
            raise ValueError("figure requires exactly one verified Artifact or legacy reference")
        if self.legacy_relative_path:
            self.legacy_relative_path = _safe_relative(self.legacy_relative_path)
            if not self.legacy_unverified:
                raise ValueError("legacy figures must be explicitly marked legacy/unverified")
        return self


class TableDraft(BaseModel):
    label: str = Field(pattern=r"^tab:[a-z0-9_-]+$")
    caption: str = Field(min_length=1)
    columns: List[str] = Field(min_length=1)
    rows: List[List[str]] = Field(min_length=1)
    source_artifact_ids: List[str] = Field(min_length=1)

    @model_validator(mode="after")
    def rectangular(self) -> "TableDraft":
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("paper table rows must match column count")
        return self


class AlgorithmDraft(BaseModel):
    label: str = Field(pattern=r"^alg:[a-z0-9_-]+$")
    caption: str = Field(min_length=1)
    steps: List[str] = Field(min_length=1)


class PresentationDraft(BaseModel):
    figures: List[FigurePlacementDraft] = Field(default_factory=list)
    tables: List[TableDraft] = Field(default_factory=list)
    algorithms: List[AlgorithmDraft] = Field(default_factory=list)
    appendix_sections: List[PaperSectionDraft] = Field(min_length=1)
    reproducibility_statement: str = Field(min_length=1)
    limitations: PaperSectionDraft
    broader_impact: PaperSectionDraft

    @model_validator(mode="after")
    def owned_sections(self) -> "PresentationDraft":
        if self.limitations.section is not PaperSectionName.LIMITATIONS:
            raise ValueError("Presentation Editor limitations section mismatch")
        if self.broader_impact.section is not PaperSectionName.BROADER_IMPACT:
            raise ValueError("Presentation Editor broader-impact section mismatch")
        if any(item.section is not PaperSectionName.APPENDIX for item in self.appendix_sections):
            raise ValueError("appendix_sections must use the appendix section type")
        return self


class PaperClaimBinding(BaseModel):
    claim_id: str
    claim_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    statement: str
    primary: bool = True
    sections: List[PaperSectionName] = Field(min_length=1)


class PaperNumberBinding(PaperNumberBindingDraft):
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PaperCitationBinding(BaseModel):
    citation_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    source_id: str
    evidence_id: str
    source_access_level: AccessLevel
    locator: CitationLocator
    section: PaperSectionName
    purpose: str


class PaperFigureBinding(FigurePlacementDraft):
    bundled_relative_path: str
    source_sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    visualization_profile_id: Optional[str] = None
    visualization_profile_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def paths_and_profile(self) -> "PaperFigureBinding":
        self.bundled_relative_path = _safe_relative(self.bundled_relative_path)
        if bool(self.visualization_profile_id) != bool(self.visualization_profile_hash):
            raise ValueError("figure VisualizationProfile id/hash must be bound together")
        return self


class PaperContent(BaseModel):
    title: str
    abstract: str
    contributions: List[ContributionDraft]
    narrative: str
    terminology: Dict[str, str] = Field(default_factory=dict)
    notation: Dict[str, str] = Field(default_factory=dict)
    sections: List[PaperSectionDraft]
    claim_bindings: List[PaperClaimBinding]
    number_bindings: List[PaperNumberBinding]
    citation_bindings: List[PaperCitationBinding]
    novelty_claims: List[NoveltyClaimDraft]
    figures: List[PaperFigureBinding]
    tables: List[TableDraft]
    algorithms: List[AlgorithmDraft]
    appendix_sections: List[PaperSectionDraft]
    reproducibility_statement: str
    outcome_boundary: str

    @model_validator(mode="after")
    def unique_sections_and_bindings(self) -> "PaperContent":
        sections = [item.section for item in self.sections]
        if len(sections) != len(set(sections)):
            raise ValueError("merged paper content must contain one section of each type")
        for values, label in (
            (self.claim_bindings, "claim"), (self.number_bindings, "number"),
            (self.citation_bindings, "citation"), (self.figures, "figure"),
        ):
            keys = [
                getattr(item, "claim_id", None) or getattr(item, "binding_id", None)
                or getattr(item, "citation_key", None) or item.label
                for item in values
            ]
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} binding")
        return self


class TopConferenceScores(BaseModel):
    novelty: int = Field(ge=1, le=10)
    correctness: int = Field(ge=1, le=10)
    rigor: int = Field(ge=1, le=10)
    significance: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    reproducibility: int = Field(ge=1, le=10)
    limitations: int = Field(ge=1, le=10)
    broader_impact: int = Field(ge=1, le=10)


class PaperReviewDefect(BaseModel):
    defect_id: str = Field(default_factory=lambda: identifier("paper_defect_"))
    category: str = Field(min_length=1)
    severity: PaperDefectSeverity
    summary: str = Field(min_length=1)
    section: Optional[PaperSectionName] = None
    record_ids: List[str] = Field(default_factory=list)
    required_change: str = Field(min_length=1)


class TopConferenceReviewDraft(BaseModel):
    scores: TopConferenceScores
    recommendation: PaperReviewRecommendation
    summary: str = Field(min_length=1)
    strengths: List[str] = Field(default_factory=list)
    defects: List[PaperReviewDefect] = Field(default_factory=list)
    admission_disclaimer: str = Field(
        default="Quality assessment only; this is not an acceptance or admission prediction.",
        min_length=1,
    )

    @model_validator(mode="after")
    def ready_has_no_major_defect(self) -> "TopConferenceReviewDraft":
        if self.recommendation is PaperReviewRecommendation.READY and any(
            item.severity in {PaperDefectSeverity.MAJOR, PaperDefectSeverity.BLOCKING}
            for item in self.defects
        ):
            raise ValueError("Reviewer cannot mark ready while major or blocking defects remain")
        return self


class TopConferenceReviewReport(TopConferenceReviewDraft):
    review_report_id: str = Field(default_factory=lambda: identifier("paper_review_"))
    paper_id: str
    project_id: str
    revision_id: str
    revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target: ConferenceTarget
    independent_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: str
    model: str
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def bind_hash(self) -> "TopConferenceReviewReport":
        expected = canonical_hash(self.model_dump(mode="json", exclude={"content_hash", "created_at"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("TopConferenceReviewReport hash mismatch")
        self.content_hash = expected
        return self


class PaperRevision(BaseModel):
    revision_id: str = Field(default_factory=lambda: identifier("paper_revision_"))
    paper_id: str
    project_id: str
    context_id: str
    research_review_run_id: str
    research_review_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(ge=0, le=2)
    parent_revision_id: Optional[str] = None
    config: ConferenceTemplateConfig
    research_outcome: ResearchOutcome
    content: PaperContent
    status: PaperRevisionStatus = PaperRevisionStatus.DRAFT
    source_review_report_id: Optional[str] = None
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def revision_chain_and_hash(self) -> "PaperRevision":
        if self.revision == 0 and self.parent_revision_id is not None:
            raise ValueError("initial paper revision cannot have a parent")
        if self.revision > 0 and not self.parent_revision_id:
            raise ValueError("paper revision requires a parent")
        expected = canonical_hash(self.model_dump(mode="json", exclude={"content_hash", "created_at"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("PaperRevision hash mismatch")
        self.content_hash = expected
        return self


class PaperGateResult(BaseModel):
    gate_code: str = Field(min_length=1)
    status: PaperGateStatus
    summary: str = Field(min_length=1)
    record_ids: List[str] = Field(default_factory=list)


class PaperQualityReport(BaseModel):
    quality_report_id: str = Field(default_factory=lambda: identifier("paper_quality_"))
    paper_id: str
    project_id: str
    revision_id: str
    revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    gates: List[PaperGateResult] = Field(min_length=1)
    passed: bool
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def report_consistency(self) -> "PaperQualityReport":
        expected_passed = all(item.status is PaperGateStatus.PASS for item in self.gates)
        if self.passed != expected_passed:
            raise ValueError("paper quality status disagrees with gate results")
        expected = canonical_hash(self.model_dump(mode="json", exclude={"content_hash", "created_at"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("PaperQualityReport hash mismatch")
        self.content_hash = expected
        return self


class PaperArtifact(BaseModel):
    paper_artifact_id: str = Field(default_factory=lambda: identifier("paper_artifact_"))
    paper_id: str
    project_id: str
    revision_id: str
    kind: PaperArtifactKind
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str
    generated_from_record_ids: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def confined(self) -> "PaperArtifact":
        self.relative_path = _safe_relative(self.relative_path)
        return self


class BuildCommandRecord(BaseModel):
    argv: List[str] = Field(min_length=1)
    exit_code: int
    stdout_tail: str = ""
    stderr_tail: str = ""


class PaperBuildRecord(BaseModel):
    build_id: str = Field(default_factory=lambda: identifier("paper_build_"))
    paper_id: str
    project_id: str
    revision_id: str
    revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    commands: List[BuildCommandRecord]
    success: bool
    page_count: int = Field(default=0, ge=0)
    paper_artifact_ids: List[str]
    pdf_artifact_id: Optional[str] = None
    rendered_page_artifact_ids: List[str] = Field(default_factory=list)
    visual_qa_passed: bool = False
    visual_qa_notes: List[str] = Field(default_factory=list)
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def build_consistency(self) -> "PaperBuildRecord":
        if self.success and (not self.pdf_artifact_id or self.page_count < 1 or not self.visual_qa_passed):
            raise ValueError("successful paper build requires a visually verified PDF")
        expected = canonical_hash(self.model_dump(mode="json", exclude={"content_hash", "created_at"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("PaperBuildRecord hash mismatch")
        self.content_hash = expected
        return self


class PaperAgentRun(BaseModel):
    agent_run_id: str = Field(default_factory=lambda: identifier("paper_agent_"))
    paper_id: str
    project_id: str
    revision: int = Field(ge=0, le=2)
    role: PaperAgentRole
    operation: str
    input_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_record_id: str
    provider_id: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class PaperRecord(BaseModel):
    paper_id: str = Field(default_factory=lambda: identifier("paper_"))
    project_id: str
    context_id: str
    research_review_run_id: str
    target: ConferenceTarget
    revision_ids: List[str] = Field(min_length=1, max_length=3)
    review_report_ids: List[str] = Field(min_length=1, max_length=3)
    final_revision_id: str
    quality_report_id: str
    build_id: str
    status: PaperRevisionStatus
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def bind_all(self) -> "PaperRecord":
        if self.final_revision_id not in self.revision_ids:
            raise ValueError("final paper revision must be in revision history")
        expected = canonical_hash(self.model_dump(mode="json", exclude={"content_hash", "created_at"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("PaperRecord hash mismatch")
        self.content_hash = expected
        return self


class PaperWritingResult(BaseModel):
    record: PaperRecord
    revisions: List[PaperRevision]
    reviews: List[TopConferenceReviewReport]
    quality_report: PaperQualityReport
    build: PaperBuildRecord
    artifacts: List[PaperArtifact]
    agent_runs: List[PaperAgentRun]

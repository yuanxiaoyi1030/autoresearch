# Purpose: Defines immutable deterministic analysis, independent verification, and scientific review records.
from __future__ import annotations

from datetime import datetime
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, computed_field, model_validator

from research_runtime.planning import canonical_hash
from research_runtime.state import ResearchOutcome, utc_now


def identifier(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


class AnalysisStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisMethod(str, Enum):
    INDEPENDENT_WELCH = "independent_welch_t"
    PAIRED_T = "paired_t"
    DESCRIPTIVE = "descriptive"


class AnalysisArtifactKind(str, Enum):
    MACHINE_JSON = "machine_json"
    TABLE_CSV = "table_csv"
    FIGURE_SVG = "figure_svg"


class AnalysisAgentRole(str, Enum):
    STATISTICAL_ANALYST = "statistical_analyst"
    VERIFICATION_AUDITOR = "verification_auditor"
    SCIENTIFIC_REVIEWER = "scientific_reviewer"


class VerificationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ScientificRecommendation(str, Enum):
    PROCEED_TO_RESEARCH_REVIEW = "proceed_to_research_review"
    SUPPLEMENT_EXPERIMENT = "supplement_experiment"
    REVISE_PLAN = "revise_plan"


class Observation(BaseModel):
    observation_id: str = Field(default_factory=lambda: identifier("obs_"))
    run_id: str
    run_spec_id: str
    artifact_id: str
    metric_id: str
    metric_name: str
    condition_id: str
    seed: Optional[int] = None
    replicate: Optional[int] = Field(default=None, ge=0)
    pair_id: Optional[str] = None
    value: float

    @model_validator(mode="after")
    def finite_value(self) -> "Observation":
        if not math.isfinite(self.value):
            raise ValueError("observation value must be finite")
        return self


class GroupSummary(BaseModel):
    metric_id: str
    condition_id: str
    n: int = Field(ge=0)
    mean: Optional[float] = None
    variance: Optional[float] = None
    standard_deviation: Optional[float] = None
    standard_error: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    confidence_level: Optional[float] = Field(default=None, gt=0, lt=1)
    confidence_interval: Optional[List[float]] = None


class StatisticalComparison(BaseModel):
    comparison_id: str = Field(default_factory=lambda: identifier("comparison_"))
    metric_id: str
    metric_name: str
    baseline_condition_id: str
    target_condition_id: str
    method: AnalysisMethod
    n_baseline: int = Field(ge=0)
    n_target: int = Field(ge=0)
    n_pairs: Optional[int] = Field(default=None, ge=0)
    baseline_mean: Optional[float] = None
    target_mean: Optional[float] = None
    effect_estimate: Optional[float] = None
    effect_size: Optional[float] = None
    effect_size_name: str = "hedges_g"
    variance: Optional[float] = None
    standard_error: Optional[float] = None
    statistic: Optional[float] = None
    degrees_of_freedom: Optional[float] = None
    p_value: Optional[float] = Field(default=None, ge=0, le=1)
    adjusted_p_value: Optional[float] = Field(default=None, ge=0, le=1)
    multiplicity_method: str = "unresolved"
    confidence_level: Optional[float] = Field(default=None, gt=0, lt=1)
    confidence_interval: Optional[List[float]] = None
    significant: Optional[bool] = None
    uncertainty_note: str
    deterministic_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class MissingRunFinding(BaseModel):
    run_spec_id: str
    metric_id: str
    expected_observations: int = Field(ge=1)
    observed_observations: int = Field(ge=0)
    missing_seeds: List[int] = Field(default_factory=list)
    failed_run_ids: List[str] = Field(default_factory=list)
    reason: str


class OutlierFinding(BaseModel):
    observation_id: str
    metric_id: str
    condition_id: str
    value: float
    lower_fence: float
    upper_fence: float
    action: str = Field(default="reported_not_excluded", pattern=r"^reported_not_excluded$")


class AnalysisPayload(BaseModel):
    analysis_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_run_ids: List[str]
    source_artifact_ids: List[str]
    source_artifact_hashes: Dict[str, str]
    observations: List[Observation] = Field(default_factory=list)
    group_summaries: List[GroupSummary] = Field(default_factory=list)
    comparisons: List[StatisticalComparison] = Field(default_factory=list)
    missing_runs: List[MissingRunFinding] = Field(default_factory=list)
    outliers: List[OutlierFinding] = Field(default_factory=list)
    method_selection: List[str] = Field(default_factory=list)
    assumption_checks: List[str] = Field(default_factory=list)
    outcome: ResearchOutcome
    outcome_rationale: str = Field(min_length=1)

    @computed_field
    @property
    def content_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude={"content_hash"}))


class AnalysisArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: identifier("analysis_artifact_"))
    project_id: str
    study_id: str
    analysis_id: str
    kind: AnalysisArtifactKind
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str
    generated_from_artifact_ids: List[str] = Field(default_factory=list)
    visualization_profile_id: Optional[str] = None
    visualization_profile_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def profile_binding(self) -> "AnalysisArtifact":
        if bool(self.visualization_profile_id) != bool(self.visualization_profile_hash):
            raise ValueError("analysis figure profile id/hash must be bound together")
        return self


class AnalysisRecord(BaseModel):
    analysis_id: str = Field(default_factory=lambda: identifier("analysis_run_"))
    project_id: str
    context_id: str
    study_id: str
    plan_revision_id: str
    plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_revision_id: str
    implementation_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AnalysisStatus
    payload: Optional[AnalysisPayload] = None
    outcome: ResearchOutcome
    artifact_ids: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def record_hash(self) -> "AnalysisRecord":
        if self.status is AnalysisStatus.COMPLETED and self.payload is None:
            raise ValueError("completed analysis requires a payload")
        if self.status is AnalysisStatus.FAILED and not self.error:
            raise ValueError("failed analysis requires an error")
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("AnalysisRecord hash mismatch")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude={"content_hash", "created_at"}))


class VerificationFinding(BaseModel):
    finding_id: str = Field(default_factory=lambda: identifier("verify_finding_"))
    code: str = Field(min_length=1)
    severity: VerificationSeverity
    summary: str = Field(min_length=1)
    record_type: str
    record_id: str
    expected: Optional[str] = None
    actual: Optional[str] = None


class VerificationReport(BaseModel):
    verification_id: str = Field(default_factory=lambda: identifier("verification_"))
    project_id: str
    context_id: str
    study_id: str
    analysis_id: str
    analysis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_verified: bool
    implementation_verified: bool
    lineage_verified: bool
    runs_verified: bool
    artifacts_verified: bool
    seeds_verified: bool
    environment_verified: bool
    statistics_verified: bool
    findings: List[VerificationFinding] = Field(default_factory=list)
    recomputed_payload_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def report_hash(self) -> "VerificationReport":
        expected = canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("VerificationReport hash mismatch")
        self.content_hash = expected
        return self

    @computed_field
    @property
    def passed(self) -> bool:
        checks = (
            self.plan_verified, self.implementation_verified, self.lineage_verified,
            self.runs_verified, self.artifacts_verified, self.seeds_verified,
            self.environment_verified, self.statistics_verified,
        )
        return all(checks) and not any(
            finding.severity is VerificationSeverity.ERROR for finding in self.findings
        )


class ScientificReviewDraft(BaseModel):
    assessed_outcome: ResearchOutcome
    recommendation: ScientificRecommendation
    summary: str = Field(min_length=1)
    claim_strength: str = Field(min_length=1)
    alternative_explanations: List[str] = Field(default_factory=list)
    confounders: List[str] = Field(default_factory=list)
    required_actions: List[str] = Field(default_factory=list)
    may_enter_research_review: bool


class ScientificReviewReport(BaseModel):
    review_id: str = Field(default_factory=lambda: identifier("scientific_review_"))
    project_id: str
    context_id: str
    study_id: str
    analysis_id: str
    analysis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_id: str
    verification_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessed_outcome: ResearchOutcome
    reviewer_recommendation: ScientificRecommendation
    policy_recommendation: ScientificRecommendation
    summary: str
    claim_strength: str
    alternative_explanations: List[str] = Field(default_factory=list)
    confounders: List[str] = Field(default_factory=list)
    required_actions: List[str] = Field(default_factory=list)
    may_enter_research_review: bool
    provider_id: str
    model: str
    input_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def report_hash(self) -> "ScientificReviewReport":
        expected = canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("ScientificReviewReport hash mismatch")
        self.content_hash = expected
        return self


class AnalysisAgentRun(BaseModel):
    agent_run_id: str = Field(default_factory=lambda: identifier("analysis_agent_"))
    project_id: str
    context_id: str
    analysis_id: str
    role: AnalysisAgentRole
    operation: str
    input_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_record_id: str
    provider_id: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class AnalysisWorkflowResult(BaseModel):
    analysis: AnalysisRecord
    verification: VerificationReport
    review: ScientificReviewReport
    artifacts: List[AnalysisArtifact]
    agent_runs: List[AnalysisAgentRun]


class AnalysisArtifactVerification(BaseModel):
    artifact: AnalysisArtifact
    exists: bool
    hash_matches: bool
    actual_sha256: Optional[str] = None
    actual_size_bytes: Optional[int] = None

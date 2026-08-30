# Purpose: Defines domain-neutral A/B project understanding, legacy reuse, lineage, and visualization contracts.
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, computed_field, model_validator

from research_runtime.state import EvidenceProvenance, VerificationStatus, utc_now


def _identifier(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


def _validate_relative_path(value: str, field_name: str) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if not value.strip() or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{field_name} must be a confined relative path")
    return candidate.as_posix()


class UnderstandingMode(str, Enum):
    TOPIC_BASED = "topic_based"
    EXISTING_PROJECT = "existing_project"


class MaterialKind(str, Enum):
    CODE = "code"
    NOTEBOOK = "notebook"
    CONFIG = "config"
    DATA_DESCRIPTION = "data_description"
    DATA = "data"
    EXPERIMENT = "experiment"
    METRIC = "metric"
    RESULT = "result"
    PAPER = "paper"
    FIGURE = "figure"
    PLOTTING_CODE = "plotting_code"
    DOCUMENTATION = "documentation"
    BINARY = "binary"


class LegacyReferenceUse(str, Enum):
    STYLE_REFERENCE = "style_reference"
    PRELIMINARY_OBSERVATION = "preliminary_observation"
    DESIGN_REFERENCE = "design_reference"
    REPRODUCTION_CANDIDATE = "reproduction_candidate"


class ReuseStrategy(str, Enum):
    ADAPT_EXISTING = "adapt_existing"
    PARTIAL_REFACTOR = "partial_refactor"
    SAFE_REIMPLEMENTATION = "safe_reimplementation"


class ReuseDisposition(str, Enum):
    REUSE = "reuse"
    ADAPT = "adapt"
    REIMPLEMENT = "reimplement"
    DO_NOT_EXECUTE = "do_not_execute"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKING = "blocking"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ModificationClass(str, Enum):
    NON_SEMANTIC = "non_semantic"
    SEMANTIC = "semantic"


class ModificationCategory(str, Enum):
    PATH = "path"
    LOGGING = "logging"
    ARTIFACT_OUTPUT = "artifact_output"
    CONFIG_LOADING = "config_loading"
    CHECKPOINT = "checkpoint"
    RECOVERY = "recovery"
    SECURITY_BOUNDARY = "security_boundary"
    FORMATTING = "formatting"
    RUNNER_STRUCTURE = "runner_structure"
    NOTEBOOK_STATE = "notebook_state"
    MODEL_ARCHITECTURE = "model_architecture"
    DATA = "data"
    LOSS = "loss"
    OPTIMIZER = "optimizer"
    HYPERPARAMETER = "hyperparameter"
    BASELINE = "baseline"
    METRIC = "metric"
    TRAINING_DURATION = "training_duration"
    STATISTICAL_METHOD = "statistical_method"
    OTHER_SEMANTIC = "other_semantic"


NON_SEMANTIC_CATEGORIES = {
    ModificationCategory.PATH,
    ModificationCategory.LOGGING,
    ModificationCategory.ARTIFACT_OUTPUT,
    ModificationCategory.CONFIG_LOADING,
    ModificationCategory.CHECKPOINT,
    ModificationCategory.RECOVERY,
    ModificationCategory.SECURITY_BOUNDARY,
    ModificationCategory.FORMATTING,
    ModificationCategory.RUNNER_STRUCTURE,
    ModificationCategory.NOTEBOOK_STATE,
}


class LineageVerification(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class UserResearchConstraints(BaseModel):
    research_objectives: List[str] = Field(default_factory=list)
    compute_budget: Optional[str] = None
    time_budget: Optional[str] = None
    network_allowed: bool = False
    allowed_dependencies: List[str] = Field(default_factory=list)
    forbidden_dependencies: List[str] = Field(default_factory=list)
    data_constraints: List[str] = Field(default_factory=list)
    methodological_constraints: List[str] = Field(default_factory=list)
    output_requirements: List[str] = Field(default_factory=list)
    additional_constraints: List[str] = Field(default_factory=list)


class ProvenanceRecord(BaseModel):
    provenance: EvidenceProvenance
    reference: str
    sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class ResearchMaterial(BaseModel):
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str
    kinds: List[MaterialKind] = Field(min_length=1)
    summary: str = ""
    legacy: bool = True
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    evidence_eligible: bool = False
    source_data_available: Optional[bool] = None
    allowed_uses: List[LegacyReferenceUse] = Field(default_factory=list)
    candidate_execution_allowed: bool = False

    @model_validator(mode="after")
    def validate_legacy_boundary(self) -> "ResearchMaterial":
        self.relative_path = _validate_relative_path(self.relative_path, "relative_path")
        if self.legacy and self.evidence_eligible:
            raise ValueError("legacy material cannot be evidence-eligible before reproduction")
        if self.legacy and self.candidate_execution_allowed:
            raise ValueError("legacy snapshot material cannot be executed directly")
        if MaterialKind.FIGURE in self.kinds and self.source_data_available is False:
            permitted = {
                LegacyReferenceUse.STYLE_REFERENCE,
                LegacyReferenceUse.PRELIMINARY_OBSERVATION,
            }
            if set(self.allowed_uses) - permitted:
                raise ValueError("legacy figure without source data is style/preliminary reference only")
        return self


class ResearchContext(BaseModel):
    context_id: str = Field(default_factory=lambda: _identifier("ctx_"))
    project_id: str
    mode: UnderstandingMode
    topic: Optional[str] = None
    user_constraints: UserResearchConstraints = Field(default_factory=UserResearchConstraints)
    import_id: Optional[str] = None
    manifest_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    summary: str
    research_questions: List[str] = Field(min_length=1)
    materials: List[ResearchMaterial] = Field(default_factory=list)
    detected_dependencies: List[str] = Field(default_factory=list)
    detected_experiments: List[str] = Field(default_factory=list)
    detected_metrics: List[str] = Field(default_factory=list)
    existing_result_summaries: List[str] = Field(default_factory=list)
    existing_claims: List[str] = Field(default_factory=list)
    known_issues: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    provenance: List[ProvenanceRecord] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_mode(self) -> "ResearchContext":
        if self.mode is UnderstandingMode.TOPIC_BASED:
            if not self.topic or not self.topic.strip():
                raise ValueError("topic-based context requires a user topic")
            if self.import_id is not None:
                raise ValueError("topic-based context cannot bind a legacy import")
        else:
            if not self.import_id or not self.manifest_hash:
                raise ValueError("existing-project context requires import provenance")
        return self


class ReuseRisk(BaseModel):
    level: RiskLevel
    category: str
    summary: str
    affected_paths: List[str] = Field(default_factory=list)
    mitigation: str


class ReuseItem(BaseModel):
    relative_path: str
    disposition: ReuseDisposition
    rationale: str
    preserved_scope: List[str] = Field(default_factory=list)
    required_changes: List[str] = Field(default_factory=list)
    requires_workspace_copy: bool = True

    @model_validator(mode="after")
    def validate_path(self) -> "ReuseItem":
        self.relative_path = _validate_relative_path(self.relative_path, "relative_path")
        return self


class LegacyReuseAssessment(BaseModel):
    assessment_id: str = Field(default_factory=lambda: _identifier("reuse_"))
    project_id: str
    context_id: str
    import_id: str
    recommended_strategy: ReuseStrategy
    reuse_items: List[ReuseItem] = Field(default_factory=list)
    preserved_research_scope: List[str] = Field(default_factory=list)
    required_adaptations: List[str] = Field(default_factory=list)
    excluded_scope: List[str] = Field(default_factory=list)
    risks: List[ReuseRisk] = Field(default_factory=list)
    risk_summary: str
    approval_summary: str
    requires_user_approval: bool = True
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)


class CodeModification(BaseModel):
    classification: ModificationClass
    category: ModificationCategory
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def category_matches_classification(self) -> "CodeModification":
        expected = (
            ModificationClass.NON_SEMANTIC
            if self.category in NON_SEMANTIC_CATEGORIES else ModificationClass.SEMANTIC
        )
        if self.classification is not expected:
            raise ValueError(
                f"{self.category.value} modifications must be classified as {expected.value}"
            )
        return self


class CodeLineageRecord(BaseModel):
    lineage_id: str = Field(default_factory=lambda: _identifier("lin_"))
    project_id: str
    context_id: str
    import_id: str
    source_relative_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_workspace_path: str
    derived_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy: ReuseStrategy
    modifications: List[CodeModification] = Field(default_factory=list)
    base_plan_revision: int = Field(default=0, ge=0)
    target_plan_revision: Optional[int] = Field(default=None, ge=0)
    legacy_baseline: bool = False
    plan_approval_status: ApprovalStatus = ApprovalStatus.PENDING
    workspace_confined: bool = True
    verification: LineageVerification = LineageVerification.PENDING
    auditor_notes: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def enforce_lineage_and_revision_gate(self) -> "CodeLineageRecord":
        self.source_relative_path = _validate_relative_path(
            self.source_relative_path, "source_relative_path",
        )
        self.derived_workspace_path = _validate_relative_path(
            self.derived_workspace_path, "derived_workspace_path",
        )
        if not self.workspace_confined:
            raise ValueError("derived code must be confined to the v0.2 Project Workspace")
        if self.has_semantic_changes:
            if self.target_plan_revision is None:
                raise ValueError("semantic modifications require a newer Experiment Plan revision")
            if self.legacy_baseline:
                if self.target_plan_revision != self.base_plan_revision:
                    raise ValueError("legacy-baseline semantic mapping must bind its defining Plan revision")
            elif self.target_plan_revision <= self.base_plan_revision:
                raise ValueError("semantic modifications require a newer Experiment Plan revision")
        elif self.target_plan_revision is None:
            self.target_plan_revision = self.base_plan_revision
        return self

    @computed_field
    @property
    def has_semantic_changes(self) -> bool:
        return any(item.classification is ModificationClass.SEMANTIC for item in self.modifications)

    @computed_field
    @property
    def execution_eligible(self) -> bool:
        revision_gate = not self.has_semantic_changes or self.plan_approval_status is ApprovalStatus.APPROVED
        return self.workspace_confined and revision_gate and self.verification is LineageVerification.VERIFIED


class VisualizationProfile(BaseModel):
    profile_id: str = Field(default_factory=lambda: _identifier("viz_"))
    project_id: str
    context_id: str
    source_paths: List[str] = Field(default_factory=list)
    colors: List[str] = Field(default_factory=list)
    fonts: List[str] = Field(default_factory=list)
    figure_sizes_inches: List[List[float]] = Field(default_factory=list)
    layouts: List[str] = Field(default_factory=list)
    line_styles: List[str] = Field(default_factory=list)
    markers: List[str] = Field(default_factory=list)
    dpi_values: List[int] = Field(default_factory=list)
    output_formats: List[str] = Field(default_factory=list)
    caption_style: Optional[str] = None
    extraction_notes: List[str] = Field(default_factory=list)
    legacy_reference_only: bool = True
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)


class FigurePanelSpec(BaseModel):
    panel_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    metrics: List[str] = Field(default_factory=list)
    input_artifact_ids: List[str] = Field(default_factory=list)


class FigureSpec(BaseModel):
    figure_spec_id: str = Field(default_factory=lambda: _identifier("figspec_"))
    project_id: str
    context_id: str
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    visualization_profile_id: Optional[str] = None
    panels: List[FigurePanelSpec] = Field(min_length=1)
    legacy_reference_paths: List[str] = Field(default_factory=list)
    caption: str = ""
    supplementary_requirements: List[str] = Field(default_factory=list)
    output_formats: List[str] = Field(default_factory=lambda: ["pdf", "png"])
    requires_verified_artifacts: bool = True
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)

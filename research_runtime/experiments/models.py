# Purpose: Defines generic implementation, Study registry, deterministic run, environment, and Artifact records.
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from research_runtime.planning import PlannedModification, canonical_hash
from research_runtime.state import utc_now


def identifier(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


def confined_path(value: str, *, suffixes=None) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if not value.strip() or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path must be a confined relative path")
    normalized = candidate.as_posix()
    if suffixes and candidate.suffix.casefold() not in suffixes:
        raise ValueError("file type is not allowed")
    return normalized


class ExperimentAgentRole(str, Enum):
    EXPERIMENTAL_LEAD = "experimental_lead"
    RESEARCH_ENGINEER = "research_engineer"


class ImplementationStatus(str, Enum):
    DRAFT = "draft"
    REQUIRES_PLAN_REVISION = "requires_plan_revision"
    VERIFIED = "verified"
    REJECTED = "rejected"


class StudyStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class ExperimentRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    STALE = "stale"


class RunControlRequest(str, Enum):
    NONE = "none"
    PAUSE = "pause"
    CANCEL = "cancel"


class ArtifactKind(str, Enum):
    CONFIG = "config"
    ENVIRONMENT = "environment"
    STDOUT = "stdout"
    STDERR = "stderr"
    METRICS = "metrics"
    FIGURE = "figure"
    CHECKPOINT = "checkpoint"
    ANALYSIS = "analysis"
    FIGURE_MANIFEST = "figure_manifest"
    OUTPUT = "output"


class ImplementationTask(BaseModel):
    task_id: str = Field(default_factory=lambda: identifier("impltask_"))
    title: str = Field(min_length=1)
    scientific_purpose: str = Field(min_length=1)
    implementation_requirements: List[str] = Field(min_length=1)
    plan_run_spec_ids: List[str] = Field(default_factory=list)
    expected_artifacts: List[str] = Field(default_factory=list)


class ImplementationTaskGraph(BaseModel):
    model_specification: str = Field(min_length=1)
    objective_function: str = Field(min_length=1)
    implementation_strategy: str = Field(min_length=1)
    tasks: List[ImplementationTask] = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    required_artifacts: List[str] = Field(min_length=1)
    plan_conformance_checks: List[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entrypoint(self) -> "ImplementationTaskGraph":
        self.entrypoint = confined_path(self.entrypoint, suffixes={".py"})
        return self


class ImplementationFile(BaseModel):
    relative_path: str
    content: str = Field(max_length=524_288)
    purpose: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_file(self) -> "ImplementationFile":
        self.relative_path = confined_path(
            self.relative_path, suffixes={".py", ".json", ".yaml", ".yml", ".toml", ".md"},
        )
        return self


class LegacyCodeMapping(BaseModel):
    source_relative_path: str
    derived_relative_path: str
    action: str = Field(pattern=r"^(adapt|refactor|reimplementation)$")
    modifications: List[PlannedModification] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_paths(self) -> "LegacyCodeMapping":
        self.source_relative_path = confined_path(self.source_relative_path)
        self.derived_relative_path = confined_path(self.derived_relative_path)
        return self


class SmokeConfig(BaseModel):
    """Provider-portable smoke-run overrides used by generated code packages."""

    model_config = ConfigDict(extra="forbid")

    max_epochs: Optional[int] = Field(default=None, ge=1)
    max_samples: Optional[int] = Field(default=None, ge=1)
    delay_seconds: Optional[float] = Field(default=None, ge=0)


class EngineerCodePackage(BaseModel):
    entrypoint: str
    files: List[ImplementationFile] = Field(min_length=1)
    declared_dependencies: List[str] = Field(default_factory=list)
    # A free-form Dict emits an object schema with no properties, which some
    # OpenAI-compatible providers reject before structured generation.
    smoke_config: SmokeConfig = Field(default_factory=SmokeConfig)
    legacy_mappings: List[LegacyCodeMapping] = Field(default_factory=list)
    implementation_modifications: List[PlannedModification] = Field(default_factory=list)
    verification_notes: List[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_package(self) -> "EngineerCodePackage":
        self.entrypoint = confined_path(self.entrypoint, suffixes={".py"})
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("implementation file paths must be unique")
        if self.entrypoint not in paths:
            raise ValueError("Engineer package must contain its entrypoint")
        return self


class ImplementationRevision(BaseModel):
    implementation_revision_id: str = Field(default_factory=lambda: identifier("implrev_"))
    project_id: str
    context_id: str
    plan_revision_id: str
    plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(default=0, ge=0)
    parent_revision_id: Optional[str] = None
    task_graph: ImplementationTaskGraph
    code_package: EngineerCodePackage
    status: ImplementationStatus = ImplementationStatus.DRAFT
    rejection_reasons: List[str] = Field(default_factory=list)
    workspace_relative_root: Optional[str] = None
    code_tree_sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_revision(self) -> "ImplementationRevision":
        if self.revision == 0 and self.parent_revision_id is not None:
            raise ValueError("initial Implementation Revision cannot have a parent")
        if self.revision > 0 and not self.parent_revision_id:
            raise ValueError("Implementation Revision requires a parent")
        if self.workspace_relative_root:
            self.workspace_relative_root = confined_path(self.workspace_relative_root)
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("Implementation Revision hash mismatch")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        return canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))

    @computed_field
    @property
    def has_unapproved_semantic_changes(self) -> bool:
        return any(
            item.classification.value == "semantic"
            for item in self.code_package.implementation_modifications
        )


class VisualizationProfileApproval(BaseModel):
    approval_id: str = Field(default_factory=lambda: identifier("vizapproval_"))
    project_id: str
    profile_id: str
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool
    feedback: str = Field(min_length=1)
    actor_type: str = Field(default="user", pattern=r"^user$")
    created_at: datetime = Field(default_factory=utc_now)


class StudyRecord(BaseModel):
    study_id: str = Field(default_factory=lambda: identifier("study_"))
    project_id: str
    context_id: str
    plan_revision_id: str
    plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_revision_id: str
    implementation_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    entrypoint: str
    workspace_relative_root: str
    code_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_spec_ids: List[str] = Field(min_length=1)
    visualization_profile_id: Optional[str] = None
    visualization_profile_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: StudyStatus = StudyStatus.READY
    builtin_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_paths_and_profile(self) -> "StudyRecord":
        self.entrypoint = confined_path(self.entrypoint, suffixes={".py"})
        self.workspace_relative_root = confined_path(self.workspace_relative_root)
        if bool(self.visualization_profile_id) != bool(self.visualization_profile_hash):
            raise ValueError("VisualizationProfile id and hash must be bound together")
        return self


class ExperimentEnvironment(BaseModel):
    python_interpreter: str
    conda_env: str
    python_version: str
    python_implementation: str
    platform: str
    dependency_versions: Dict[str, str] = Field(default_factory=dict)
    requested_device: str = "cpu"
    environment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResourceUsage(BaseModel):
    wall_seconds: float = Field(default=0.0, ge=0)
    stdout_bytes: int = Field(default=0, ge=0)
    stderr_bytes: int = Field(default=0, ge=0)
    observed_output_bytes: int = Field(default=0, ge=0)
    process_id: Optional[int] = Field(default=None, ge=1)


class ExperimentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: identifier("run_"))
    project_id: str
    study_id: str
    run_spec_id: str
    parent_run_id: Optional[str] = None
    attempt: int = Field(default=1, ge=1)
    status: ExperimentRunStatus = ExperimentRunStatus.QUEUED
    control_request: RunControlRequest = RunControlRequest.NONE
    smoke: bool = False
    evidence_eligible: bool = False
    plan_revision_id: str
    plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_revision_id: str
    implementation_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: Dict[str, Any] = Field(default_factory=dict)
    environment: ExperimentEnvironment
    command_arguments: List[str] = Field(min_length=1)
    cwd: str
    timeout_seconds: float = Field(gt=0)
    output_limit_bytes: int = Field(ge=1024)
    exit_code: Optional[int] = None
    termination_reason: Optional[str] = None
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)
    artifact_ids: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)


class Artifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: identifier("artifact_"))
    project_id: str
    study_id: str
    run_id: str
    kind: ArtifactKind
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str
    evidence_eligible: bool = False
    verification_status: str = Field(default="verified", pattern=r"^(verified|failed)$")
    visualization_profile_id: Optional[str] = None
    visualization_profile_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generated_from_artifact_ids: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ArtifactVerification(BaseModel):
    artifact: Artifact
    exists: bool
    hash_matches: bool
    actual_sha256: Optional[str] = None
    actual_size_bytes: Optional[int] = None


class ExperimentAgentRun(BaseModel):
    agent_run_id: str = Field(default_factory=lambda: identifier("exprunagent_"))
    project_id: str
    context_id: str
    role: ExperimentAgentRole
    operation: str
    input_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact_id: str
    provider_id: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class StudyCreationResult(BaseModel):
    implementation: ImplementationRevision
    study: Optional[StudyRecord] = None
    lineage_ids: List[str] = Field(default_factory=list)
    agent_runs: List[ExperimentAgentRun]


class ExperimentRunDetail(BaseModel):
    run: ExperimentRun
    artifacts: List[Artifact]

# Purpose: Defines compact Goal 0 project, state, import, and stage-attempt records.
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from pydantic import BaseModel, Field, model_validator

from .statuses import ImportStatus, ProjectStatus, ProjectType, ResearchOutcome, ResearchStage


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchProject(BaseModel):
    project_id: str = Field(default_factory=lambda: "prj_" + uuid.uuid4().hex)
    title: str = Field(min_length=1)
    project_type: ProjectType
    source_root: Optional[str] = None
    topic: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_entrypoint(self):
        if self.project_type is ProjectType.TOPIC_BASED:
            if not self.topic or not self.topic.strip():
                raise ValueError("topic_based projects require a topic")
            if self.source_root is not None:
                raise ValueError("topic_based projects cannot specify source_root")
        else:
            if not self.source_root or not self.source_root.strip():
                raise ValueError("existing_project projects require source_root")
            if self.topic is not None:
                raise ValueError("existing_project projects cannot specify topic")
        return self


class ResearchState(BaseModel):
    project_id: str
    stage: ResearchStage = ResearchStage.INITIALIZING
    status: ProjectStatus = ProjectStatus.ACTIVE
    current_attempt_id: Optional[str] = None
    latest_import_id: Optional[str] = None
    outcome: Optional[ResearchOutcome] = None
    revision: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)


class StageAttempt(BaseModel):
    attempt_id: str = Field(default_factory=lambda: "att_" + uuid.uuid4().hex)
    project_id: str
    stage: ResearchStage
    attempt_number: int = Field(ge=1)
    status: ProjectStatus = ProjectStatus.ACTIVE
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class SourceMaterial(BaseModel):
    relative_path: str
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str


class ExcludedMaterial(BaseModel):
    relative_path: str
    reason: str


class ImportManifest(BaseModel):
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_root: str
    files: List[SourceMaterial]
    total_files: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    excluded: List[ExcludedMaterial] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ImportSession(BaseModel):
    import_id: str = Field(default_factory=lambda: "imp_" + uuid.uuid4().hex)
    project_id: str
    source_root: str
    status: ImportStatus = ImportStatus.PENDING
    manifest_hash: Optional[str] = None
    snapshot_path: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


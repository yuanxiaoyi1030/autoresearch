# Purpose: Defines immutable, hash-bound v0.1 compatibility import and builtin regression records.
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field

from research_runtime.state import utc_now


HASH_PATTERN = r"^[0-9a-f]{64}$"


class CompatibilityImportStatus(str, Enum):
    VERIFIED = "verified"
    REJECTED = "rejected"


class BuiltinStudyDescriptor(BaseModel):
    builtin_id: str = Field(pattern=r"^builtin/[a-z0-9_]+$")
    display_name: str
    legacy_study_id: str
    source_version: str = "v0.1"
    execution_mode: str = "read_only_compatibility_regression"
    expected_conditions: List[Dict[str, Any]]
    evidence_policy: str = "legacy_hash_verified_not_reproduced"


class V01RunReference(BaseModel):
    legacy_run_id: str
    legacy_project_id: str
    legacy_job_id: str
    legacy_plan_hash: str = Field(pattern=HASH_PATTERN)
    condition: str = Field(pattern=r"^(baseline|treatment)$")
    seed: int = Field(ge=0)
    weight_decay: float = Field(ge=0)
    paired_initialization_key: str
    config_sha256: str = Field(pattern=HASH_PATTERN)
    status: str = Field(pattern=r"^completed$")
    finished_at: Optional[datetime] = None


class V01ArtifactReference(BaseModel):
    legacy_artifact_id: str
    legacy_run_id: str
    kind: str
    media_type: str
    source_relative_path: str
    source_sha256: str = Field(pattern=HASH_PATTERN)
    source_size_bytes: int = Field(ge=0)
    imported_relative_path: str
    imported_sha256: str = Field(pattern=HASH_PATTERN)
    imported_size_bytes: int = Field(ge=0)
    evidence_eligible: bool
    evidence_status: str = "legacy_hash_verified_not_reproduced"


class V01CompatibilityImport(BaseModel):
    compatibility_import_id: str = Field(
        default_factory=lambda: "compat_" + uuid.uuid4().hex
    )
    source_version: str = Field(default="v0.1", pattern=r"^v0\.1$")
    builtin_id: str = Field(default="builtin/weight_decay_v1", pattern=r"^builtin/weight_decay_v1$")
    legacy_study_id: str = Field(default="weight_decay_condensation_v1")
    source_runtime_root: str
    source_database_relative_path: str
    source_database_sha256_before: str = Field(pattern=HASH_PATTERN)
    source_database_sha256_after: str = Field(pattern=HASH_PATTERN)
    source_manifest_hash: str = Field(pattern=HASH_PATTERN)
    imported_manifest_relative_path: str
    source_integrity_unchanged: bool
    status: CompatibilityImportStatus = CompatibilityImportStatus.VERIFIED
    runs: List[V01RunReference] = Field(min_length=6, max_length=6)
    artifacts: List[V01ArtifactReference] = Field(min_length=1)
    warnings: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class CompatibilityArtifactCheck(BaseModel):
    legacy_artifact_id: str
    exists: bool
    hash_matches: bool
    expected_sha256: str = Field(pattern=HASH_PATTERN)
    actual_sha256: Optional[str] = Field(default=None, pattern=HASH_PATTERN)


class CompatibilityVerification(BaseModel):
    compatibility_import_id: str
    passed: bool
    manifest_exists: bool
    manifest_hash_matches: bool
    artifact_checks: List[CompatibilityArtifactCheck]
    findings: List[str] = Field(default_factory=list)


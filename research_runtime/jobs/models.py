# Purpose: Defines domain-neutral durable jobs and idempotency conflicts for the v0.2 foundation.
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import uuid

from pydantic import BaseModel, Field

from research_runtime.state import JobStatus, utc_now


class JobKind(str, Enum):
    INITIALIZE_TOPIC = "initialize_topic"
    IMPORT_EXISTING_PROJECT = "import_existing_project"
    RUN_RESEARCH_STAGE = "run_research_stage"
    REVISE_RESEARCH_STAGE = "revise_research_stage"


class DurableJob(BaseModel):
    job_id: str = Field(default_factory=lambda: "job_" + uuid.uuid4().hex)
    project_id: str
    kind: JobKind
    status: JobStatus = JobStatus.PENDING
    idempotency_key: str
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts: int = Field(default=0, ge=0)
    last_event_cursor: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IdempotencyConflict(ValueError):
    pass


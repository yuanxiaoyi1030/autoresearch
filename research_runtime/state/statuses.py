# Purpose: Defines domain-neutral v0.2 project, workflow, import, job, and evidence statuses.
from enum import Enum


class ProjectType(str, Enum):
    TOPIC_BASED = "topic_based"
    EXISTING_PROJECT = "existing_project"


class ResearchStage(str, Enum):
    INITIALIZING = "initializing"
    PROJECT_UNDERSTANDING = "project_understanding"
    LITERATURE = "literature"
    HYPOTHESIS = "hypothesis"
    WAIT_HYPOTHESIS_APPROVAL = "wait_hypothesis_approval"
    EXPERIMENT_PLANNING = "experiment_planning"
    WAIT_PLAN_APPROVAL = "wait_plan_approval"
    EXPERIMENT_IMPLEMENTATION = "experiment_implementation"
    EXPERIMENT = "experiment"
    ANALYSIS = "analysis"
    RESEARCH_REVIEW = "research_review"
    REPORT_PLANNING = "report_planning"
    REPORT_WRITING = "report_writing"
    REPORT_REVIEW = "report_review"
    COMPLETED = "completed"


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    WAITING_USER = "waiting_user"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchOutcome(str, Enum):
    SUPPORTED = "supported"
    NEGATIVE_RESULT = "negative_result"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ImportStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"
    CANCELLED = "cancelled"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceProvenance(str, Enum):
    USER_TOPIC = "user_topic"
    LEGACY_IMPORT = "legacy_import"
    AUTORESEARCH_RUN = "autoresearch_run"
    LITERATURE_SOURCE = "literature_source"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    REPRODUCED = "reproduced"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


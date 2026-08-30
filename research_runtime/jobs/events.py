# Purpose: Defines persisted cursor-addressed activity events and the v0.2 event journal.
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from research_runtime.state import ResearchStage, utc_now


class ActivityEvent(BaseModel):
    cursor: int = Field(ge=1)
    project_id: str
    job_id: Optional[str] = None
    event_type: str
    stage: Optional[ResearchStage] = None
    summary: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class EventJournal:
    def __init__(self, repository) -> None:
        self.repository = repository

    def append(self, project_id: str, event_type: str, summary: str,
               job_id: Optional[str] = None, stage: Optional[ResearchStage] = None,
               payload: Optional[Dict[str, Any]] = None) -> ActivityEvent:
        return self.repository.append(
            project_id=project_id,
            job_id=job_id,
            event_type=event_type,
            stage=stage,
            summary=summary,
            payload=payload or {},
        )

    def after(self, project_id: str, cursor: int = 0, limit: int = 100) -> List[ActivityEvent]:
        return self.repository.after(project_id, cursor, limit)


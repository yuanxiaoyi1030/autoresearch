# Purpose: Persists v0.2 project events and cursor-based retrieval.
import json
from datetime import datetime
from typing import Dict, List, Optional

from research_runtime.jobs.events import ActivityEvent
from research_runtime.security import assert_secret_free
from research_runtime.state import ResearchStage, utc_now


class EventRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def append(self, project_id: str, event_type: str, summary: str, payload: Dict,
               job_id: Optional[str] = None, stage: Optional[ResearchStage] = None) -> ActivityEvent:
        assert_secret_free(
            {"summary": summary, "payload": payload}, self.known_secrets(), context="ActivityEvent",
        )
        created_at = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO activity_events(project_id,job_id,event_type,stage,summary,payload_json,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    project_id, job_id, event_type, stage.value if stage else None, summary,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), created_at.isoformat(),
                ),
            ).lastrowid
        return ActivityEvent(
            cursor=cursor, project_id=project_id, job_id=job_id, event_type=event_type,
            stage=stage, summary=summary, payload=payload, created_at=created_at,
        )

    def after(self, project_id: str, cursor: int = 0, limit: int = 100) -> List[ActivityEvent]:
        safe_limit = min(max(int(limit), 1), 500)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM activity_events WHERE project_id=? AND cursor>? ORDER BY cursor LIMIT ?",
                (project_id, int(cursor), safe_limit),
            ).fetchall()
        return [ActivityEvent(
            cursor=row["cursor"], project_id=row["project_id"], job_id=row["job_id"],
            event_type=row["event_type"], stage=ResearchStage(row["stage"]) if row["stage"] else None,
            summary=row["summary"], payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        ) for row in rows]

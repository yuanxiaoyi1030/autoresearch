# Purpose: Persists v0.2 projects, current/history state, and stage attempts.
from datetime import datetime
from typing import List, Optional

from research_runtime.state import (
    ProjectStatus, ProjectType, ResearchOutcome, ResearchProject, ResearchStage, ResearchState,
    StageAttempt, utc_now,
)


class ProjectRepository:
    def __init__(self, database) -> None:
        self.database = database

    def create(self, project: ResearchProject, state: Optional[ResearchState] = None) -> None:
        state = state or ResearchState(project_id=project.project_id)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    project.project_id, project.title, project.project_type.value, project.source_root,
                    project.topic, project.created_at.isoformat(), project.updated_at.isoformat(),
                ),
            )
            connection.execute(
                "INSERT INTO research_states VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    state.project_id, state.stage.value, state.status.value, state.current_attempt_id,
                    state.latest_import_id, state.outcome.value if state.outcome else None,
                    state.revision, state.updated_at.isoformat(),
                ),
            )
            connection.execute(
                "INSERT INTO research_state_history VALUES (?, ?, ?, ?)",
                (state.project_id, state.revision, state.model_dump_json(), state.updated_at.isoformat()),
            )

    def list(self) -> List[ResearchProject]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY updated_at DESC, project_id").fetchall()
        return [self._project(row) for row in rows]

    def get(self, project_id: str) -> Optional[ResearchProject]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        return self._project(row) if row else None

    def get_state(self, project_id: str) -> Optional[ResearchState]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM research_states WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            return None
        return ResearchState(
            project_id=row["project_id"], stage=ResearchStage(row["stage"]),
            status=ProjectStatus(row["status"]), current_attempt_id=row["current_attempt_id"],
            latest_import_id=row["latest_import_id"],
            outcome=ResearchOutcome(row["outcome"]) if row["outcome"] else None,
            revision=row["revision"], updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_state(self, state: ResearchState, expected_revision: Optional[int] = None) -> ResearchState:
        base_revision = state.revision if expected_revision is None else expected_revision
        updated = state.model_copy(update={"revision": base_revision + 1, "updated_at": utc_now()})
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE research_states SET stage=?, status=?, current_attempt_id=?, latest_import_id=?,
                   outcome=?, revision=?, updated_at=? WHERE project_id=? AND revision=?""",
                (
                    updated.stage.value, updated.status.value, updated.current_attempt_id,
                    updated.latest_import_id, updated.outcome.value if updated.outcome else None,
                    updated.revision, updated.updated_at.isoformat(), updated.project_id, base_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"stale research state revision for {updated.project_id}")
            connection.execute(
                "INSERT INTO research_state_history VALUES (?, ?, ?, ?)",
                (updated.project_id, updated.revision, updated.model_dump_json(), updated.updated_at.isoformat()),
            )
            connection.execute(
                "UPDATE projects SET updated_at=? WHERE project_id=?",
                (updated.updated_at.isoformat(), updated.project_id),
            )
        return updated

    def list_state_history(self, project_id: str) -> List[ResearchState]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT snapshot_json FROM research_state_history WHERE project_id=? ORDER BY revision",
                (project_id,),
            ).fetchall()
        return [ResearchState.model_validate_json(row["snapshot_json"]) for row in rows]

    def set_current_attempt(self, project_id: str, attempt_id: str, expected_revision: int) -> ResearchState:
        state = self.get_state(project_id)
        if state is None:
            raise KeyError(project_id)
        return self.update_state(state.model_copy(update={"current_attempt_id": attempt_id}), expected_revision)

    def add_attempt(self, attempt: StageAttempt) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO stage_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.attempt_id, attempt.project_id, attempt.stage.value, attempt.attempt_number,
                    attempt.status.value, attempt.started_at.isoformat(),
                    attempt.finished_at.isoformat() if attempt.finished_at else None, attempt.error,
                ),
            )

    def next_attempt_number(self, project_id: str, stage: ResearchStage) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(attempt_number),0)+1 AS value FROM stage_attempts WHERE project_id=? AND stage=?",
                (project_id, stage.value),
            ).fetchone()
        return int(row["value"])

    def finish_attempt(self, attempt_id: str, status: ProjectStatus, error: Optional[str] = None) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE stage_attempts SET status=?, finished_at=?, error=? WHERE attempt_id=? AND finished_at IS NULL",
                (status.value, utc_now().isoformat(), error, attempt_id),
            )

    def list_attempts(self, project_id: str) -> List[StageAttempt]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM stage_attempts WHERE project_id=? ORDER BY started_at, attempt_number",
                (project_id,),
            ).fetchall()
        return [StageAttempt(
            attempt_id=row["attempt_id"], project_id=row["project_id"], stage=ResearchStage(row["stage"]),
            attempt_number=row["attempt_number"], status=ProjectStatus(row["status"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            error=row["error"],
        ) for row in rows]

    @staticmethod
    def _project(row) -> ResearchProject:
        return ResearchProject(
            project_id=row["project_id"], title=row["title"], project_type=ProjectType(row["project_type"]),
            source_root=row["source_root"], topic=row["topic"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


# Purpose: Persists immutable implementations/studies/artifacts and durable mutable run control/status.
from __future__ import annotations

import sqlite3
from typing import List, Optional

from research_runtime.experiments import (
    Artifact, ExperimentAgentRun, ExperimentRun, ExperimentRunStatus,
    ImplementationRevision, RunControlRequest, StudyRecord, VisualizationProfileApproval,
)
from research_runtime.security import assert_secret_free
from research_runtime.state import utc_now


class ExperimentRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def save_implementation(self, revision: ImplementationRevision) -> None:
        if revision.content_hash != revision.calculated_hash():
            raise ValueError("Implementation Revision changed after hashing")
        self._safe(revision, "ImplementationRevision")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO implementation_revisions(
                   implementation_revision_id,project_id,context_id,plan_revision_id,revision,
                   parent_revision_id,status,content_hash,revision_json,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (revision.implementation_revision_id, revision.project_id, revision.context_id,
                 revision.plan_revision_id, revision.revision, revision.parent_revision_id,
                 revision.status.value, revision.content_hash, revision.model_dump_json(),
                 revision.created_at.isoformat()),
            )

    def get_implementation(self, revision_id: str) -> Optional[ImplementationRevision]:
        return self._one(ImplementationRevision,
            "SELECT revision_json FROM implementation_revisions WHERE implementation_revision_id=?",
            (revision_id,), "revision_json")

    def latest_implementation(self, project_id: str) -> Optional[ImplementationRevision]:
        return self._one(ImplementationRevision,
            """SELECT revision_json FROM implementation_revisions WHERE project_id=?
               ORDER BY revision DESC, created_at DESC LIMIT 1""", (project_id,), "revision_json")

    def list_implementations(self, project_id: str) -> List[ImplementationRevision]:
        return self._many(ImplementationRevision,
            """SELECT revision_json FROM implementation_revisions WHERE project_id=?
               ORDER BY revision, created_at""", (project_id,), "revision_json")

    def save_study(self, study: StudyRecord) -> None:
        self._safe(study, "StudyRecord")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO studies(study_id,project_id,plan_revision_id,
                   implementation_revision_id,status,study_json,created_at) VALUES (?,?,?,?,?,?,?)""",
                (study.study_id, study.project_id, study.plan_revision_id,
                 study.implementation_revision_id, study.status.value,
                 study.model_dump_json(), study.created_at.isoformat()),
            )

    def get_study(self, study_id: str) -> Optional[StudyRecord]:
        return self._one(StudyRecord, "SELECT study_json FROM studies WHERE study_id=?",
                         (study_id,), "study_json")

    def list_studies(self, project_id: str) -> List[StudyRecord]:
        return self._many(StudyRecord,
            "SELECT study_json FROM studies WHERE project_id=? ORDER BY created_at,study_id",
            (project_id,), "study_json")

    def create_run(self, run: ExperimentRun) -> None:
        self._safe(run, "ExperimentRun")
        now = utc_now().isoformat()
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO experiment_runs(run_id,project_id,study_id,run_spec_id,
                   parent_run_id,status,control_request,run_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (run.run_id, run.project_id, run.study_id, run.run_spec_id, run.parent_run_id,
                 run.status.value, run.control_request.value, run.model_dump_json(),
                 run.created_at.isoformat(), now),
            )

    def update_run(self, run: ExperimentRun) -> None:
        self._safe(run, "ExperimentRun")
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE experiment_runs SET status=?,control_request=?,run_json=?,updated_at=?
                   WHERE run_id=?""",
                (run.status.value, run.control_request.value, run.model_dump_json(),
                 utc_now().isoformat(), run.run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run.run_id)

    def request_control(self, run_id: str, control: RunControlRequest) -> ExperimentRun:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT run_json FROM experiment_runs WHERE run_id=?", (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = ExperimentRun.model_validate_json(row["run_json"])
            updated = run.model_copy(update={"control_request": control})
            connection.execute(
                """UPDATE experiment_runs SET control_request=?,run_json=?,updated_at=?
                   WHERE run_id=?""",
                (control.value, updated.model_dump_json(), utc_now().isoformat(), run_id),
            )
        return updated

    def get_run(self, run_id: str) -> Optional[ExperimentRun]:
        return self._one(ExperimentRun, "SELECT run_json FROM experiment_runs WHERE run_id=?",
                         (run_id,), "run_json")

    def list_runs(self, study_id: str) -> List[ExperimentRun]:
        return self._many(ExperimentRun,
            "SELECT run_json FROM experiment_runs WHERE study_id=? ORDER BY created_at,run_id",
            (study_id,), "run_json")

    def count_runs(self, study_id: str) -> int:
        with self.database.connect() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) AS count FROM experiment_runs WHERE study_id=?", (study_id,),
            ).fetchone()["count"])

    def recover_running(self) -> List[ExperimentRun]:
        recovered = []
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT run_json FROM experiment_runs WHERE status=?",
                (ExperimentRunStatus.RUNNING.value,),
            ).fetchall()
            for row in rows:
                run = ExperimentRun.model_validate_json(row["run_json"])
                stale = run.model_copy(update={
                    "status": ExperimentRunStatus.STALE,
                    "control_request": RunControlRequest.NONE,
                    "termination_reason": "service_restart",
                    "error": "Run interrupted by service restart; immutable attempt preserved.",
                    "finished_at": utc_now(),
                })
                connection.execute(
                    """UPDATE experiment_runs SET status=?,control_request=?,run_json=?,updated_at=?
                       WHERE run_id=?""",
                    (stale.status.value, stale.control_request.value, stale.model_dump_json(),
                     utc_now().isoformat(), stale.run_id),
                )
                recovered.append(stale)
        return recovered

    def add_artifact(self, artifact: Artifact) -> Artifact:
        self._safe(artifact, "Artifact")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO experiment_artifacts(artifact_id,project_id,study_id,run_id,
                       relative_path,sha256,artifact_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (artifact.artifact_id, artifact.project_id, artifact.study_id,
                     artifact.run_id, artifact.relative_path, artifact.sha256,
                     artifact.model_dump_json(), artifact.created_at.isoformat()),
                )
        except sqlite3.IntegrityError:
            raise ValueError("Artifact path is already registered and immutable") from None
        return artifact

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        return self._one(Artifact,
            "SELECT artifact_json FROM experiment_artifacts WHERE artifact_id=?",
            (artifact_id,), "artifact_json")

    def list_artifacts(self, run_id: str) -> List[Artifact]:
        return self._many(Artifact,
            """SELECT artifact_json FROM experiment_artifacts WHERE run_id=?
               ORDER BY created_at,artifact_id""", (run_id,), "artifact_json")

    def save_agent_run(self, run: ExperimentAgentRun) -> None:
        self._safe(run, "ExperimentAgentRun")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO experiment_agent_runs(agent_run_id,project_id,context_id,role,
                   run_json,created_at) VALUES (?,?,?,?,?,?)""",
                (run.agent_run_id, run.project_id, run.context_id, run.role.value,
                 run.model_dump_json(), run.created_at.isoformat()),
            )

    def list_agent_runs(self, project_id: str) -> List[ExperimentAgentRun]:
        return self._many(ExperimentAgentRun,
            """SELECT run_json FROM experiment_agent_runs WHERE project_id=?
               ORDER BY created_at,agent_run_id""", (project_id,), "run_json")

    def save_profile_approval(self, approval: VisualizationProfileApproval) -> None:
        self._safe(approval, "VisualizationProfileApproval")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO visualization_profile_approvals(approval_id,project_id,profile_id,
                       profile_hash,approved,approval_json,created_at) VALUES (?,?,?,?,?,?,?)""",
                    (approval.approval_id, approval.project_id, approval.profile_id,
                     approval.profile_hash, int(approval.approved), approval.model_dump_json(),
                     approval.created_at.isoformat()),
                )
        except sqlite3.IntegrityError:
            raise ValueError("VisualizationProfile already has a user decision") from None

    def profile_approval(self, profile_id: str) -> Optional[VisualizationProfileApproval]:
        return self._one(VisualizationProfileApproval,
            "SELECT approval_json FROM visualization_profile_approvals WHERE profile_id=?",
            (profile_id,), "approval_json")

    def _safe(self, value, context):
        assert_secret_free(value.model_dump(mode="json"), self.known_secrets(), context=context)

    def _one(self, model, sql, params, column):
        with self.database.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return model.model_validate_json(row[column]) if row else None

    def _many(self, model, sql, params, column):
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [model.model_validate_json(row[column]) for row in rows]


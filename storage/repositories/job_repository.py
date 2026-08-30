# Purpose: Persists v0.2 durable jobs, idempotency keys, attempts, and recovery state.
import json
from datetime import datetime
from typing import List, Optional

from research_runtime.jobs.models import DurableJob, JobKind
from research_runtime.security import assert_secret_free
from research_runtime.state import JobStatus, utc_now


class JobRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def create(self, job: DurableJob) -> None:
        assert_secret_free(job.payload, self.known_secrets(), context="Job payload")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO durable_jobs(job_id,project_id,kind,status,idempotency_key,payload_hash,
                   payload_json,result_json,error,attempts,last_event_cursor,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                self._values(job),
            )

    def get(self, job_id: str) -> Optional[DurableJob]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM durable_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def by_idempotency(self, project_id: str, kind: JobKind, key: str) -> Optional[DurableJob]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM durable_jobs WHERE project_id=? AND kind=? AND idempotency_key=?",
                (project_id, kind.value, key),
            ).fetchone()
        return self._job(row) if row else None

    def list_project(self, project_id: str) -> List[DurableJob]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM durable_jobs WHERE project_id=? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [self._job(row) for row in rows]

    def claim_next(self) -> Optional[DurableJob]:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM durable_jobs WHERE status=? ORDER BY created_at LIMIT 1",
                (JobStatus.PENDING.value,),
            ).fetchone()
            if row is None:
                return None
            now = utc_now()
            cursor = connection.execute(
                """UPDATE durable_jobs SET status=?, attempts=attempts+1, error=NULL, updated_at=?
                   WHERE job_id=? AND status=?""",
                (JobStatus.RUNNING.value, now.isoformat(), row["job_id"], JobStatus.PENDING.value),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute("SELECT * FROM durable_jobs WHERE job_id=?", (row["job_id"],)).fetchone()
        return self._job(row)

    def set_status(self, job_id: str, status: JobStatus, result=None,
                   error: Optional[str] = None) -> DurableJob:
        assert_secret_free({"result": result, "error": error}, self.known_secrets(), context="Job result")
        now = utc_now()
        result_json = json.dumps(result, ensure_ascii=False, sort_keys=True) if result is not None else None
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE durable_jobs SET status=?, result_json=?, error=?, updated_at=? WHERE job_id=?",
                (status.value, result_json, error, now.isoformat(), job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
            row = connection.execute("SELECT * FROM durable_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._job(row)

    def update_last_cursor(self, job_id: str, cursor: int) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE durable_jobs SET last_event_cursor=?, updated_at=? WHERE job_id=?",
                (cursor, utc_now().isoformat(), job_id),
            )

    def recover_running(self) -> List[DurableJob]:
        now = utc_now()
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM durable_jobs WHERE status=? ORDER BY created_at", (JobStatus.RUNNING.value,)
            ).fetchall()
            connection.execute(
                "UPDATE durable_jobs SET status=?, error=?, updated_at=? WHERE status=?",
                (
                    JobStatus.PENDING.value, "service restarted; retry scheduled", now.isoformat(),
                    JobStatus.RUNNING.value,
                ),
            )
        recovered = []
        for row in rows:
            values = dict(row)
            values.update({
                "status": JobStatus.PENDING.value,
                "error": "service restarted; retry scheduled",
                "updated_at": now.isoformat(),
            })
            recovered.append(self._job(values))
        return recovered

    @staticmethod
    def _values(job: DurableJob):
        return (
            job.job_id, job.project_id, job.kind.value, job.status.value, job.idempotency_key,
            job.payload_hash, json.dumps(job.payload, ensure_ascii=False, sort_keys=True),
            json.dumps(job.result, ensure_ascii=False, sort_keys=True) if job.result is not None else None,
            job.error, job.attempts, job.last_event_cursor,
            job.created_at.isoformat(), job.updated_at.isoformat(),
        )

    @staticmethod
    def _job(row) -> DurableJob:
        return DurableJob(
            job_id=row["job_id"], project_id=row["project_id"], kind=JobKind(row["kind"]),
            status=JobStatus(row["status"]), idempotency_key=row["idempotency_key"],
            payload_hash=row["payload_hash"], payload=json.loads(row["payload_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"], attempts=row["attempts"], last_event_cursor=row["last_event_cursor"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

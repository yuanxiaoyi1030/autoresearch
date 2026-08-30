# Purpose: Creates and controls generic idempotent v0.2 durable jobs without Study-specific kinds.
import hashlib
import json
from typing import Callable, Dict, List, Optional

from research_runtime.state import JobStatus

from .events import EventJournal
from .models import DurableJob, IdempotencyConflict, JobKind


TERMINAL_JOB_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


class DurableJobManager:
    def __init__(self, repository, events: EventJournal) -> None:
        self.repository = repository
        self.events = events
        self._notify: Callable[[], None] = lambda: None

    def set_notifier(self, notify: Callable[[], None]) -> None:
        self._notify = notify

    def create(self, project_id: str, kind: JobKind, payload: Dict,
               idempotency_key: Optional[str] = None) -> DurableJob:
        payload_hash = self.payload_hash(payload)
        key = idempotency_key or f"{kind.value}:{payload_hash}"
        existing = self.repository.by_idempotency(project_id, kind, key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise IdempotencyConflict("idempotency key was already used with a different payload")
            return existing
        job = DurableJob(
            project_id=project_id,
            kind=kind,
            idempotency_key=key,
            payload_hash=payload_hash,
            payload=payload,
        )
        self.repository.create(job)
        self._event(job, "job.created", f"{kind.value} job queued", {"kind": kind.value})
        self._notify()
        return self.repository.get(job.job_id)

    def claim_next(self) -> Optional[DurableJob]:
        job = self.repository.claim_next()
        if job is not None:
            self._event(job, "job.started", f"{job.kind.value} job started", {"attempt": job.attempts})
        return job

    def complete(self, job: DurableJob, result: Dict) -> DurableJob:
        current = self.repository.get(job.job_id)
        if current is not None and current.status is JobStatus.CANCELLED:
            return current
        completed = self.repository.set_status(job.job_id, JobStatus.COMPLETED, result=result)
        self._event(completed, "job.completed", f"{completed.kind.value} job completed", result)
        return self.repository.get(job.job_id)

    def fail(self, job: DurableJob, error: str) -> DurableJob:
        current = self.repository.get(job.job_id)
        if current is not None and current.status is JobStatus.CANCELLED:
            return current
        failed = self.repository.set_status(job.job_id, JobStatus.FAILED, error=error)
        self._event(failed, "job.failed", f"{failed.kind.value} job failed", {"error": error})
        return self.repository.get(job.job_id)

    def pause(self, job_id: str) -> DurableJob:
        job = self._job(job_id)
        if job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
            raise ValueError(f"cannot pause job with status {job.status.value}")
        paused = self.repository.set_status(job_id, JobStatus.PAUSED)
        self._event(paused, "job.paused", "Job paused by user", {})
        return self.repository.get(job_id)

    def resume(self, job_id: str) -> DurableJob:
        job = self._job(job_id)
        if job.status is not JobStatus.PAUSED:
            raise ValueError("only paused jobs can be resumed")
        resumed = self.repository.set_status(job_id, JobStatus.PENDING)
        self._event(resumed, "job.resumed", "Job resumed", {})
        self._notify()
        return self.repository.get(job_id)

    def cancel(self, job_id: str) -> DurableJob:
        job = self._job(job_id)
        if job.status in TERMINAL_JOB_STATUSES:
            raise ValueError(f"cannot cancel job with status {job.status.value}")
        cancelled = self.repository.set_status(job_id, JobStatus.CANCELLED)
        self._event(cancelled, "job.cancelled", "Job cancelled by user", {})
        return self.repository.get(job_id)

    def recover(self) -> List[DurableJob]:
        jobs = self.repository.recover_running()
        for job in jobs:
            self._event(job, "job.recovered", "Interrupted job re-queued after service restart", {
                "attempts": job.attempts,
            })
        if jobs:
            self._notify()
        return jobs

    @staticmethod
    def payload_hash(payload: Dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _job(self, job_id: str) -> DurableJob:
        job = self.repository.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _event(self, job: DurableJob, event_type: str, summary: str, payload: Dict) -> None:
        event = self.events.append(job.project_id, event_type, summary, job_id=job.job_id, payload=payload)
        self.repository.update_last_cursor(job.job_id, event.cursor)


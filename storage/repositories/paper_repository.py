# Purpose: Persists immutable paper revisions, defects, QA, builds, artifacts, and agent audit records.
from __future__ import annotations

from typing import List, Optional

from research_runtime.security import assert_secret_free
from research_runtime.writing.models import (
    PaperAgentRun, PaperArtifact, PaperBuildRecord, PaperQualityReport, PaperRecord,
    PaperRevision, TopConferenceReviewReport,
)


class PaperRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def save_revision(self, revision: PaperRevision, agent_runs: List[PaperAgentRun]) -> None:
        self._safe([revision, *agent_runs], "Paper revision bundle")
        if any(item.paper_id != revision.paper_id or item.revision != revision.revision for item in agent_runs):
            raise ValueError("paper AgentRun does not bind the saved revision")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO paper_revisions(
                   revision_id,paper_id,project_id,context_id,research_review_run_id,revision,
                   parent_revision_id,status,content_hash,revision_json,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    revision.revision_id, revision.paper_id, revision.project_id,
                    revision.context_id, revision.research_review_run_id, revision.revision,
                    revision.parent_revision_id, revision.status.value, revision.content_hash,
                    revision.model_dump_json(), revision.created_at.isoformat(),
                ),
            )
            for run in agent_runs:
                self._insert_agent(connection, run)

    def save_review(self, report: TopConferenceReviewReport, agent_run: PaperAgentRun) -> None:
        self._safe([report, agent_run], "Paper review bundle")
        if agent_run.paper_id != report.paper_id or agent_run.revision < 0:
            raise ValueError("Reviewer AgentRun does not bind paper review")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO paper_review_reports(
                   review_report_id,paper_id,project_id,revision_id,recommendation,
                   content_hash,report_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    report.review_report_id, report.paper_id, report.project_id,
                    report.revision_id, report.recommendation.value, report.content_hash,
                    report.model_dump_json(), report.created_at.isoformat(),
                ),
            )
            self._insert_agent(connection, agent_run)

    def save_final(self, record: PaperRecord, quality: PaperQualityReport,
                   build: PaperBuildRecord, artifacts: List[PaperArtifact]) -> None:
        self._safe([record, quality, build, *artifacts], "Final paper bundle")
        if quality.paper_id != record.paper_id or build.paper_id != record.paper_id:
            raise ValueError("final paper records disagree on paper_id")
        if quality.revision_id != record.final_revision_id or build.revision_id != record.final_revision_id:
            raise ValueError("final paper QA/build do not bind final revision")
        if set(build.paper_artifact_ids) != {item.paper_artifact_id for item in artifacts}:
            raise ValueError("PaperBuildRecord must bind every materialized paper Artifact")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO paper_quality_reports(
                   quality_report_id,paper_id,project_id,revision_id,passed,content_hash,
                   report_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    quality.quality_report_id, quality.paper_id, quality.project_id,
                    quality.revision_id, int(quality.passed), quality.content_hash,
                    quality.model_dump_json(), quality.created_at.isoformat(),
                ),
            )
            connection.execute(
                """INSERT INTO paper_builds(
                   build_id,paper_id,project_id,revision_id,success,content_hash,
                   build_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    build.build_id, build.paper_id, build.project_id, build.revision_id,
                    int(build.success), build.content_hash, build.model_dump_json(),
                    build.created_at.isoformat(),
                ),
            )
            for artifact in artifacts:
                connection.execute(
                    """INSERT INTO paper_artifacts(
                       paper_artifact_id,paper_id,project_id,revision_id,kind,relative_path,
                       sha256,artifact_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        artifact.paper_artifact_id, artifact.paper_id, artifact.project_id,
                        artifact.revision_id, artifact.kind.value, artifact.relative_path,
                        artifact.sha256, artifact.model_dump_json(), artifact.created_at.isoformat(),
                    ),
                )
            connection.execute(
                """INSERT INTO paper_records(
                   paper_id,project_id,context_id,research_review_run_id,target,
                   final_revision_id,quality_report_id,build_id,status,content_hash,
                   record_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.paper_id, record.project_id, record.context_id,
                    record.research_review_run_id, record.target.value,
                    record.final_revision_id, record.quality_report_id, record.build_id,
                    record.status.value, record.content_hash, record.model_dump_json(),
                    record.created_at.isoformat(),
                ),
            )

    def get_record(self, paper_id: str) -> Optional[PaperRecord]:
        return self._one(PaperRecord, "SELECT record_json FROM paper_records WHERE paper_id=?",
                         (paper_id,), "record_json")

    def list_records(self, project_id: str) -> List[PaperRecord]:
        return self._many(PaperRecord,
            """SELECT record_json FROM paper_records WHERE project_id=?
               ORDER BY created_at,paper_id""", (project_id,), "record_json")

    def list_revisions(self, paper_id: str) -> List[PaperRevision]:
        return self._many(PaperRevision,
            """SELECT revision_json FROM paper_revisions WHERE paper_id=?
               ORDER BY revision,revision_id""", (paper_id,), "revision_json")

    def list_reviews(self, paper_id: str) -> List[TopConferenceReviewReport]:
        return self._many(TopConferenceReviewReport,
            """SELECT report_json FROM paper_review_reports WHERE paper_id=?
               ORDER BY created_at,review_report_id""", (paper_id,), "report_json")

    def get_quality(self, quality_report_id: str) -> Optional[PaperQualityReport]:
        return self._one(PaperQualityReport,
            "SELECT report_json FROM paper_quality_reports WHERE quality_report_id=?",
            (quality_report_id,), "report_json")

    def get_build(self, build_id: str) -> Optional[PaperBuildRecord]:
        return self._one(PaperBuildRecord, "SELECT build_json FROM paper_builds WHERE build_id=?",
                         (build_id,), "build_json")

    def list_artifacts(self, paper_id: str) -> List[PaperArtifact]:
        return self._many(PaperArtifact,
            """SELECT artifact_json FROM paper_artifacts WHERE paper_id=?
               ORDER BY created_at,paper_artifact_id""", (paper_id,), "artifact_json")

    def list_agent_runs(self, project_id: str) -> List[PaperAgentRun]:
        return self._many(PaperAgentRun,
            """SELECT run_json FROM paper_agent_runs WHERE project_id=?
               ORDER BY created_at,agent_run_id""", (project_id,), "run_json")

    def _insert_agent(self, connection, run):
        connection.execute(
            """INSERT INTO paper_agent_runs(
               agent_run_id,paper_id,project_id,revision,role,run_json,created_at
               ) VALUES (?,?,?,?,?,?,?)""",
            (
                run.agent_run_id, run.paper_id, run.project_id, run.revision,
                run.role.value, run.model_dump_json(), run.created_at.isoformat(),
            ),
        )

    def _safe(self, values, context):
        payload = [item.model_dump(mode="json") for item in values]
        assert_secret_free(payload, self.known_secrets(), context=context)

    def _one(self, model, sql, params, column):
        with self.database.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return model.model_validate_json(row[column]) if row else None

    def _many(self, model, sql, params, column):
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [model.model_validate_json(row[column]) for row in rows]

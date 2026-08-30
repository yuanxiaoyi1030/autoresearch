# Purpose: Persists immutable analysis, verification, review, and provenance records.
from __future__ import annotations

import sqlite3
from typing import List, Optional

from research_runtime.analysis import (
    AnalysisAgentRun, AnalysisArtifact, AnalysisRecord, ScientificReviewReport,
    VerificationReport,
)
from research_runtime.security import assert_secret_free


class AnalysisRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def save_analysis(self, record: AnalysisRecord) -> None:
        if record.content_hash != record.calculated_hash():
            raise ValueError("AnalysisRecord changed after hashing")
        self._safe(record, "AnalysisRecord")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO analysis_records(
                   analysis_id,project_id,context_id,study_id,status,outcome,content_hash,
                   record_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (record.analysis_id, record.project_id, record.context_id, record.study_id,
                 record.status.value, record.outcome.value, record.content_hash,
                 record.model_dump_json(), record.created_at.isoformat()),
            )

    def save_analysis_bundle(self, record: AnalysisRecord,
                             artifacts: List[AnalysisArtifact]) -> None:
        if record.content_hash != record.calculated_hash():
            raise ValueError("AnalysisRecord changed after hashing")
        self._safe(record, "AnalysisRecord")
        for artifact in artifacts:
            if artifact.analysis_id != record.analysis_id:
                raise ValueError("Analysis Artifact belongs to another analysis")
            self._safe(artifact, "AnalysisArtifact")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO analysis_records(
                       analysis_id,project_id,context_id,study_id,status,outcome,content_hash,
                       record_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (record.analysis_id, record.project_id, record.context_id, record.study_id,
                     record.status.value, record.outcome.value, record.content_hash,
                     record.model_dump_json(), record.created_at.isoformat()),
                )
                for artifact in artifacts:
                    connection.execute(
                        """INSERT INTO analysis_artifacts(
                           artifact_id,project_id,study_id,analysis_id,relative_path,sha256,
                           artifact_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                        (artifact.artifact_id, artifact.project_id, artifact.study_id,
                         artifact.analysis_id, artifact.relative_path, artifact.sha256,
                         artifact.model_dump_json(), artifact.created_at.isoformat()),
                    )
        except sqlite3.IntegrityError:
            raise ValueError("Analysis bundle is immutable or already registered") from None

    def get_analysis(self, analysis_id: str) -> Optional[AnalysisRecord]:
        return self._one(AnalysisRecord,
            "SELECT record_json FROM analysis_records WHERE analysis_id=?",
            (analysis_id,), "record_json")

    def list_analyses(self, study_id: str) -> List[AnalysisRecord]:
        return self._many(AnalysisRecord,
            """SELECT record_json FROM analysis_records WHERE study_id=?
               ORDER BY created_at,analysis_id""", (study_id,), "record_json")

    def add_artifact(self, artifact: AnalysisArtifact) -> AnalysisArtifact:
        self._safe(artifact, "AnalysisArtifact")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO analysis_artifacts(
                       artifact_id,project_id,study_id,analysis_id,relative_path,sha256,
                       artifact_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (artifact.artifact_id, artifact.project_id, artifact.study_id,
                     artifact.analysis_id, artifact.relative_path, artifact.sha256,
                     artifact.model_dump_json(), artifact.created_at.isoformat()),
                )
        except sqlite3.IntegrityError:
            raise ValueError("Analysis Artifact path is already registered and immutable") from None
        return artifact

    def get_artifact(self, artifact_id: str) -> Optional[AnalysisArtifact]:
        return self._one(AnalysisArtifact,
            "SELECT artifact_json FROM analysis_artifacts WHERE artifact_id=?",
            (artifact_id,), "artifact_json")

    def list_artifacts(self, analysis_id: str) -> List[AnalysisArtifact]:
        return self._many(AnalysisArtifact,
            """SELECT artifact_json FROM analysis_artifacts WHERE analysis_id=?
               ORDER BY created_at,artifact_id""", (analysis_id,), "artifact_json")

    def save_verification(self, report: VerificationReport) -> None:
        expected = report.__class__.model_validate(
            report.model_dump(mode="json", exclude={"content_hash"})
        ).content_hash
        if report.content_hash != expected:
            raise ValueError("VerificationReport changed after hashing")
        self._safe(report, "VerificationReport")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO verification_reports(
                   verification_id,project_id,context_id,study_id,analysis_id,passed,
                   report_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (report.verification_id, report.project_id, report.context_id,
                 report.study_id, report.analysis_id, int(report.passed),
                 report.model_dump_json(), report.created_at.isoformat()),
            )

    def list_verifications(self, analysis_id: str) -> List[VerificationReport]:
        return self._many(VerificationReport,
            """SELECT report_json FROM verification_reports WHERE analysis_id=?
               ORDER BY created_at,verification_id""", (analysis_id,), "report_json")

    def get_verification(self, verification_id: str) -> Optional[VerificationReport]:
        return self._one(VerificationReport,
            "SELECT report_json FROM verification_reports WHERE verification_id=?",
            (verification_id,), "report_json")

    def save_review(self, report: ScientificReviewReport) -> None:
        expected = report.__class__.model_validate(
            report.model_dump(mode="json", exclude={"content_hash"})
        ).content_hash
        if report.content_hash != expected:
            raise ValueError("ScientificReviewReport changed after hashing")
        self._safe(report, "ScientificReviewReport")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO scientific_review_reports(
                   review_id,project_id,context_id,study_id,analysis_id,verification_id,
                   recommendation,report_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (report.review_id, report.project_id, report.context_id, report.study_id,
                 report.analysis_id, report.verification_id,
                 report.policy_recommendation.value, report.model_dump_json(),
                 report.created_at.isoformat()),
            )

    def list_reviews(self, analysis_id: str) -> List[ScientificReviewReport]:
        return self._many(ScientificReviewReport,
            """SELECT report_json FROM scientific_review_reports WHERE analysis_id=?
               ORDER BY created_at,review_id""", (analysis_id,), "report_json")

    def get_review(self, review_id: str) -> Optional[ScientificReviewReport]:
        return self._one(ScientificReviewReport,
            "SELECT report_json FROM scientific_review_reports WHERE review_id=?",
            (review_id,), "report_json")

    def save_agent_run(self, run: AnalysisAgentRun) -> None:
        self._safe(run, "AnalysisAgentRun")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO analysis_agent_runs(
                   agent_run_id,project_id,context_id,analysis_id,role,run_json,created_at
                   ) VALUES (?,?,?,?,?,?,?)""",
                (run.agent_run_id, run.project_id, run.context_id, run.analysis_id,
                 run.role.value, run.model_dump_json(), run.created_at.isoformat()),
            )

    def list_agent_runs(self, project_id: str) -> List[AnalysisAgentRun]:
        return self._many(AnalysisAgentRun,
            """SELECT run_json FROM analysis_agent_runs WHERE project_id=?
               ORDER BY created_at,agent_run_id""", (project_id,), "run_json")

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

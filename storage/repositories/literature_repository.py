# Purpose: Persists every literature attempt, immutable matrix revision, source, evidence, gap, review, and agent run.
from __future__ import annotations

from typing import List, Optional

from research_runtime.literature import (
    EvidenceReviewReport, LiteratureAgentRun, LiteratureEvidence, LiteratureEvidenceMatrix,
    LiteratureSource, ResearchGap, SearchAttempt,
)
from research_runtime.security import assert_secret_free


class LiteratureRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def save_attempt(self, attempt: SearchAttempt) -> None:
        self._safe(attempt, "SearchAttempt")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO literature_search_attempts(
                   attempt_id,project_id,context_id,provider,status,attempt_json,created_at
                   ) VALUES (?,?,?,?,?,?,?)""",
                (attempt.attempt_id, attempt.project_id, attempt.context_id, attempt.provider.value,
                 attempt.status.value, attempt.model_dump_json(), attempt.started_at.isoformat()),
            )

    def save_sources(self, project_id: str, context_id: str,
                     sources: List[LiteratureSource]) -> None:
        self._safe(sources, "LiteratureSource")
        with self.database.transaction() as connection:
            for source in sources:
                connection.execute(
                    """INSERT INTO literature_sources(
                       source_id,project_id,context_id,doi,arxiv_id,access_level,source_json,created_at
                       ) VALUES (?,?,?,?,?,?,?,?)""",
                    (source.source_id, project_id, context_id, source.doi, source.arxiv_id,
                     source.access_level.value, source.model_dump_json(), self._created(source)),
                )

    def save_matrix(self, matrix: LiteratureEvidenceMatrix) -> None:
        self._safe(matrix, "LiteratureEvidenceMatrix")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO literature_matrices(
                   matrix_id,project_id,context_id,revision,parent_matrix_id,matrix_json,created_at
                   ) VALUES (?,?,?,?,?,?,?)""",
                (matrix.matrix_id, matrix.project_id, matrix.context_id, matrix.revision,
                 matrix.parent_matrix_id, matrix.model_dump_json(), matrix.created_at.isoformat()),
            )
            for evidence in matrix.evidence:
                connection.execute(
                    """INSERT INTO literature_evidence(
                       evidence_id,matrix_id,project_id,context_id,source_id,evidence_json,created_at
                       ) VALUES (?,?,?,?,?,?,?)""",
                    (evidence.evidence_id, matrix.matrix_id, matrix.project_id, matrix.context_id,
                     evidence.source_id, evidence.model_dump_json(), matrix.created_at.isoformat()),
                )
            for gap in matrix.research_gaps:
                connection.execute(
                    """INSERT INTO research_gaps(
                       gap_id,matrix_id,project_id,context_id,gap_json,created_at
                       ) VALUES (?,?,?,?,?,?)""",
                    (gap.gap_id, matrix.matrix_id, matrix.project_id, matrix.context_id,
                     gap.model_dump_json(), matrix.created_at.isoformat()),
                )

    def save_review(self, report: EvidenceReviewReport) -> None:
        self._safe(report, "EvidenceReviewReport")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO evidence_review_reports(
                   report_id,project_id,context_id,matrix_id,revision,report_json,created_at
                   ) VALUES (?,?,?,?,?,?,?)""",
                (report.report_id, report.project_id, report.context_id, report.matrix_id,
                 report.revision, report.model_dump_json(), report.created_at.isoformat()),
            )

    def save_agent_run(self, run: LiteratureAgentRun) -> None:
        self._safe(run, "LiteratureAgentRun")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO literature_agent_runs(
                   run_id,project_id,context_id,role,revision,run_json,created_at
                   ) VALUES (?,?,?,?,?,?,?)""",
                (run.run_id, run.project_id, run.context_id, run.role.value, run.revision,
                 run.model_dump_json(), run.created_at.isoformat()),
            )

    def latest_matrix(self, project_id: str) -> Optional[LiteratureEvidenceMatrix]:
        return self._one(
            LiteratureEvidenceMatrix,
            """SELECT matrix_json FROM literature_matrices WHERE project_id=?
               ORDER BY created_at DESC, revision DESC LIMIT 1""", (project_id,), "matrix_json",
        )

    def get_matrix(self, matrix_id: str) -> Optional[LiteratureEvidenceMatrix]:
        return self._one(
            LiteratureEvidenceMatrix,
            "SELECT matrix_json FROM literature_matrices WHERE matrix_id=?",
            (matrix_id,), "matrix_json",
        )

    def list_matrices(self, project_id: str) -> List[LiteratureEvidenceMatrix]:
        return self._many(
            LiteratureEvidenceMatrix,
            """SELECT matrix_json FROM literature_matrices WHERE project_id=?
               ORDER BY created_at, revision""", (project_id,), "matrix_json",
        )

    def list_attempts(self, project_id: str) -> List[SearchAttempt]:
        return self._many(
            SearchAttempt,
            """SELECT attempt_json FROM literature_search_attempts WHERE project_id=?
               ORDER BY created_at, attempt_id""", (project_id,), "attempt_json",
        )

    def list_sources(self, project_id: str) -> List[LiteratureSource]:
        return self._many(
            LiteratureSource,
            """SELECT source_json FROM literature_sources WHERE project_id=?
               ORDER BY created_at, source_id""", (project_id,), "source_json",
        )

    def list_evidence(self, project_id: str) -> List[LiteratureEvidence]:
        return self._many(
            LiteratureEvidence,
            """SELECT evidence_json FROM literature_evidence WHERE project_id=?
               ORDER BY created_at, evidence_id""", (project_id,), "evidence_json",
        )

    def list_gaps(self, project_id: str) -> List[ResearchGap]:
        return self._many(
            ResearchGap,
            """SELECT gap_json FROM research_gaps WHERE project_id=?
               ORDER BY created_at, gap_id""", (project_id,), "gap_json",
        )

    def list_reviews(self, project_id: str) -> List[EvidenceReviewReport]:
        return self._many(
            EvidenceReviewReport,
            """SELECT report_json FROM evidence_review_reports WHERE project_id=?
               ORDER BY created_at, revision, report_id""", (project_id,), "report_json",
        )

    def list_agent_runs(self, project_id: str) -> List[LiteratureAgentRun]:
        return self._many(
            LiteratureAgentRun,
            """SELECT run_json FROM literature_agent_runs WHERE project_id=?
               ORDER BY created_at, run_id""", (project_id,), "run_json",
        )

    def _safe(self, value, context: str) -> None:
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else [
            item.model_dump(mode="json") for item in value
        ]
        assert_secret_free(payload, self.known_secrets(), context=context)

    @staticmethod
    def _created(source: LiteratureSource) -> str:
        # Source models intentionally carry bibliographic time, not mutable persistence time.
        from research_runtime.state import utc_now
        return utc_now().isoformat()

    def _one(self, model, sql, params, column):
        with self.database.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return model.model_validate_json(row[column]) if row else None

    def _many(self, model, sql, params, column):
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [model.model_validate_json(row[column]) for row in rows]

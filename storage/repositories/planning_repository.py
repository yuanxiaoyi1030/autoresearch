# Purpose: Persists immutable hypothesis/plan revisions, independent reviews, user approvals, and agent runs.
from __future__ import annotations

import sqlite3
from typing import List, Optional

from research_runtime.planning import (
    ExperimentPlanRevision, HypothesisRevision, PlanningAgentRun, PlanningApproval,
    PlanningArtifactKind, PlanningReviewReport,
)
from research_runtime.security import assert_secret_free


class PlanningRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def save_hypothesis(self, revision: HypothesisRevision) -> None:
        self._verify_hash(revision)
        self._safe(revision, "HypothesisRevision")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO hypothesis_revisions(
                   hypothesis_revision_id,project_id,context_id,literature_matrix_id,revision,
                   parent_revision_id,content_hash,revision_json,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (revision.hypothesis_revision_id, revision.project_id, revision.context_id,
                 revision.literature_matrix_id, revision.revision, revision.parent_revision_id,
                 revision.content_hash, revision.model_dump_json(), revision.created_at.isoformat()),
            )

    def save_plan(self, revision: ExperimentPlanRevision) -> None:
        self._verify_hash(revision)
        self._safe(revision, "ExperimentPlanRevision")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO experiment_plan_revisions(
                   plan_revision_id,project_id,context_id,literature_matrix_id,
                   hypothesis_revision_id,revision,parent_revision_id,content_hash,
                   revision_json,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (revision.plan_revision_id, revision.project_id, revision.context_id,
                 revision.literature_matrix_id, revision.hypothesis_revision_id,
                 revision.revision, revision.parent_revision_id, revision.content_hash,
                 revision.model_dump_json(), revision.created_at.isoformat()),
            )

    def save_review(self, report: PlanningReviewReport) -> None:
        self._safe(report, "PlanningReviewReport")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO planning_review_reports(
                   report_id,project_id,context_id,artifact_kind,artifact_id,
                   artifact_content_hash,revision,report_json,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (report.report_id, report.project_id, report.context_id,
                 report.artifact_kind.value, report.artifact_id,
                 report.artifact_content_hash, report.revision,
                 report.model_dump_json(), report.created_at.isoformat()),
            )

    def save_approval(self, approval: PlanningApproval) -> None:
        self._safe(approval, "PlanningApproval")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO planning_approvals(
                       approval_id,project_id,artifact_kind,artifact_id,artifact_content_hash,
                       decision,approval_json,created_at
                       ) VALUES (?,?,?,?,?,?,?,?)""",
                    (approval.approval_id, approval.project_id, approval.artifact_kind.value,
                     approval.artifact_id, approval.artifact_content_hash,
                     approval.decision.value, approval.model_dump_json(),
                     approval.created_at.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("this artifact revision already has a user decision") from None
            raise

    def save_agent_run(self, run: PlanningAgentRun) -> None:
        self._safe(run, "PlanningAgentRun")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO planning_agent_runs(
                   run_id,project_id,context_id,role,artifact_kind,artifact_id,
                   revision,run_json,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (run.run_id, run.project_id, run.context_id, run.role.value,
                 run.artifact_kind.value, run.artifact_id, run.revision,
                 run.model_dump_json(), run.created_at.isoformat()),
            )

    def get_hypothesis(self, revision_id: str) -> Optional[HypothesisRevision]:
        return self._one(HypothesisRevision,
            "SELECT revision_json FROM hypothesis_revisions WHERE hypothesis_revision_id=?",
            (revision_id,), "revision_json")

    def latest_hypothesis(self, project_id: str) -> Optional[HypothesisRevision]:
        return self._one(HypothesisRevision,
            """SELECT revision_json FROM hypothesis_revisions WHERE project_id=?
               ORDER BY revision DESC, created_at DESC LIMIT 1""",
            (project_id,), "revision_json")

    def list_hypotheses(self, project_id: str) -> List[HypothesisRevision]:
        return self._many(HypothesisRevision,
            """SELECT revision_json FROM hypothesis_revisions WHERE project_id=?
               ORDER BY revision, created_at""", (project_id,), "revision_json")

    def get_plan(self, revision_id: str) -> Optional[ExperimentPlanRevision]:
        return self._one(ExperimentPlanRevision,
            "SELECT revision_json FROM experiment_plan_revisions WHERE plan_revision_id=?",
            (revision_id,), "revision_json")

    def latest_plan(self, project_id: str) -> Optional[ExperimentPlanRevision]:
        return self._one(ExperimentPlanRevision,
            """SELECT revision_json FROM experiment_plan_revisions WHERE project_id=?
               ORDER BY revision DESC, created_at DESC LIMIT 1""",
            (project_id,), "revision_json")

    def list_plans(self, project_id: str) -> List[ExperimentPlanRevision]:
        return self._many(ExperimentPlanRevision,
            """SELECT revision_json FROM experiment_plan_revisions WHERE project_id=?
               ORDER BY revision, created_at""", (project_id,), "revision_json")

    def latest_review(self, kind: PlanningArtifactKind, artifact_id: str) -> Optional[PlanningReviewReport]:
        return self._one(PlanningReviewReport,
            """SELECT report_json FROM planning_review_reports
               WHERE artifact_kind=? AND artifact_id=? ORDER BY created_at DESC LIMIT 1""",
            (kind.value, artifact_id), "report_json")

    def list_reviews(self, project_id: str) -> List[PlanningReviewReport]:
        return self._many(PlanningReviewReport,
            """SELECT report_json FROM planning_review_reports WHERE project_id=?
               ORDER BY created_at, report_id""", (project_id,), "report_json")

    def approval_for(self, kind: PlanningArtifactKind, artifact_id: str) -> Optional[PlanningApproval]:
        return self._one(PlanningApproval,
            "SELECT approval_json FROM planning_approvals WHERE artifact_kind=? AND artifact_id=?",
            (kind.value, artifact_id), "approval_json")

    def list_approvals(self, project_id: str) -> List[PlanningApproval]:
        return self._many(PlanningApproval,
            """SELECT approval_json FROM planning_approvals WHERE project_id=?
               ORDER BY created_at, approval_id""", (project_id,), "approval_json")

    def list_agent_runs(self, project_id: str) -> List[PlanningAgentRun]:
        return self._many(PlanningAgentRun,
            """SELECT run_json FROM planning_agent_runs WHERE project_id=?
               ORDER BY created_at, run_id""", (project_id,), "run_json")

    @staticmethod
    def _verify_hash(revision) -> None:
        if revision.content_hash != revision.calculated_hash():
            raise ValueError("revision content changed after its hash was computed")

    def _safe(self, value, context: str) -> None:
        assert_secret_free(value.model_dump(mode="json"), self.known_secrets(), context=context)

    def _one(self, model, sql, params, column):
        with self.database.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return model.model_validate_json(row[column]) if row else None

    def _many(self, model, sql, params, column):
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [model.model_validate_json(row[column]) for row in rows]


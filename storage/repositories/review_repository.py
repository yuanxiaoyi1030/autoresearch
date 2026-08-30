# Purpose: Persists immutable independent-review evidence, reports, policy decisions, and feedback transitions.
from __future__ import annotations

import sqlite3
from typing import List, Optional

from research_runtime.review import (
    EvidenceClaim, MetaReviewReport, ResearchPolicyDecision, ResearchReviewAgentRun,
    ResearchReviewRecord, ResearchReviewTransition, SpecialistReviewReport,
)
from research_runtime.security import assert_secret_free


class ResearchReviewRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def save_bundle(self, record: ResearchReviewRecord, claims: List[EvidenceClaim],
                    specialists: List[SpecialistReviewReport], meta: MetaReviewReport,
                    policy: ResearchPolicyDecision,
                    agent_runs: List[ResearchReviewAgentRun]) -> None:
        values = [record, *claims, *specialists, meta, policy, *agent_runs]
        for value in values:
            self._safe(value, value.__class__.__name__)
        for value in [record, *claims, *specialists, meta, policy]:
            if value.content_hash != value.calculated_hash():
                raise ValueError(f"{value.__class__.__name__} changed after hashing")
        if any(item.review_run_id != record.review_run_id for item in specialists + agent_runs):
            raise ValueError("review bundle contains a foreign review_run_id")
        if meta.review_run_id != record.review_run_id or policy.review_run_id != record.review_run_id:
            raise ValueError("review bundle meta/policy belongs to another run")
        try:
            with self.database.transaction() as connection:
                for claim in claims:
                    connection.execute(
                        """INSERT INTO evidence_claims(
                           claim_id,project_id,context_id,analysis_id,claim_type,content_hash,
                           claim_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                        (claim.claim_id, claim.project_id, claim.context_id, claim.analysis_id,
                         claim.claim_type.value, claim.content_hash, claim.model_dump_json(),
                         claim.created_at.isoformat()),
                    )
                for report in specialists:
                    connection.execute(
                        """INSERT INTO research_specialist_reviews(
                           specialist_review_id,review_run_id,project_id,context_id,analysis_id,
                           role,proposed_decision,content_hash,report_json,created_at
                           ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (report.specialist_review_id, report.review_run_id, report.project_id,
                         report.context_id, report.analysis_id, report.role.value,
                         report.proposed_decision.value, report.content_hash,
                         report.model_dump_json(), report.created_at.isoformat()),
                    )
                connection.execute(
                    """INSERT INTO research_meta_reviews(
                       meta_review_id,review_run_id,project_id,context_id,analysis_id,
                       proposed_decision,content_hash,report_json,created_at
                       ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (meta.meta_review_id, meta.review_run_id, meta.project_id, meta.context_id,
                     meta.analysis_id, meta.proposed_decision.value, meta.content_hash,
                     meta.model_dump_json(), meta.created_at.isoformat()),
                )
                connection.execute(
                    """INSERT INTO research_policy_decisions(
                       policy_decision_id,review_run_id,project_id,context_id,analysis_id,
                       final_decision,content_hash,decision_json,created_at
                       ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (policy.policy_decision_id, policy.review_run_id, policy.project_id,
                     policy.context_id, policy.analysis_id, policy.final_decision.value,
                     policy.content_hash, policy.model_dump_json(), policy.created_at.isoformat()),
                )
                connection.execute(
                    """INSERT INTO research_review_records(
                       review_run_id,project_id,context_id,analysis_id,final_decision,
                       content_hash,record_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (record.review_run_id, record.project_id, record.context_id,
                     record.analysis_id, record.final_decision.value, record.content_hash,
                     record.model_dump_json(), record.created_at.isoformat()),
                )
                for run in agent_runs:
                    connection.execute(
                        """INSERT INTO research_review_agent_runs(
                           agent_run_id,review_run_id,project_id,context_id,role,run_json,created_at
                           ) VALUES (?,?,?,?,?,?,?)""",
                        (run.agent_run_id, run.review_run_id, run.project_id, run.context_id,
                         run.role.value, run.model_dump_json(), run.created_at.isoformat()),
                    )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"research review bundle is immutable or invalid: {exc}") from None

    def get_record(self, review_run_id: str) -> Optional[ResearchReviewRecord]:
        return self._one(ResearchReviewRecord,
            "SELECT record_json FROM research_review_records WHERE review_run_id=?",
            (review_run_id,), "record_json")

    def list_records(self, project_id: str) -> List[ResearchReviewRecord]:
        return self._many(ResearchReviewRecord,
            """SELECT record_json FROM research_review_records WHERE project_id=?
               ORDER BY created_at,review_run_id""", (project_id,), "record_json")

    def list_claims(self, analysis_id: str) -> List[EvidenceClaim]:
        return self._many(EvidenceClaim,
            """SELECT claim_json FROM evidence_claims WHERE analysis_id=?
               ORDER BY created_at,claim_id""", (analysis_id,), "claim_json")

    def list_specialists(self, review_run_id: str) -> List[SpecialistReviewReport]:
        return self._many(SpecialistReviewReport,
            """SELECT report_json FROM research_specialist_reviews WHERE review_run_id=?
               ORDER BY created_at,specialist_review_id""", (review_run_id,), "report_json")

    def get_meta(self, meta_review_id: str) -> Optional[MetaReviewReport]:
        return self._one(MetaReviewReport,
            "SELECT report_json FROM research_meta_reviews WHERE meta_review_id=?",
            (meta_review_id,), "report_json")

    def get_policy(self, policy_decision_id: str) -> Optional[ResearchPolicyDecision]:
        return self._one(ResearchPolicyDecision,
            "SELECT decision_json FROM research_policy_decisions WHERE policy_decision_id=?",
            (policy_decision_id,), "decision_json")

    def list_agent_runs(self, project_id: str) -> List[ResearchReviewAgentRun]:
        return self._many(ResearchReviewAgentRun,
            """SELECT run_json FROM research_review_agent_runs WHERE project_id=?
               ORDER BY created_at,agent_run_id""", (project_id,), "run_json")

    def save_transition(self, transition: ResearchReviewTransition) -> None:
        self._safe(transition, "ResearchReviewTransition")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO research_review_transitions(
                       transition_id,review_run_id,project_id,policy_decision_id,
                       transition_json,created_at) VALUES (?,?,?,?,?,?)""",
                    (transition.transition_id, transition.review_run_id,
                     transition.project_id, transition.policy_decision_id,
                     transition.model_dump_json(), transition.created_at.isoformat()),
                )
        except sqlite3.IntegrityError:
            raise ValueError("research review transition already applied") from None

    def get_transition(self, review_run_id: str) -> Optional[ResearchReviewTransition]:
        return self._one(ResearchReviewTransition,
            "SELECT transition_json FROM research_review_transitions WHERE review_run_id=?",
            (review_run_id,), "transition_json")

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

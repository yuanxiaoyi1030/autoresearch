# Purpose: Persists and queries immutable project understanding, reuse, lineage, and visualization records.
from __future__ import annotations

from typing import List, Optional

from research_runtime.security import assert_secret_free
from research_runtime.understanding import (
    CodeLineageRecord, FigureSpec, LegacyReuseAssessment, ResearchContext, VisualizationProfile,
)


class UnderstandingRepository:
    def __init__(self, database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def save_understanding(
        self,
        context: ResearchContext,
        assessment: Optional[LegacyReuseAssessment] = None,
        profiles: Optional[List[VisualizationProfile]] = None,
    ) -> None:
        profiles = profiles or []
        payload = {
            "context": context.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json") if assessment else None,
            "profiles": [profile.model_dump(mode="json") for profile in profiles],
        }
        assert_secret_free(payload, self.known_secrets(), context="Project Understanding records")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO research_contexts(
                   context_id,project_id,import_id,manifest_hash,context_json,created_at
                   ) VALUES (?,?,?,?,?,?)""",
                (
                    context.context_id, context.project_id, context.import_id, context.manifest_hash,
                    context.model_dump_json(), context.created_at.isoformat(),
                ),
            )
            if assessment is not None:
                connection.execute(
                    """INSERT INTO legacy_reuse_assessments(
                       assessment_id,project_id,context_id,assessment_json,created_at
                       ) VALUES (?,?,?,?,?)""",
                    (
                        assessment.assessment_id, assessment.project_id, assessment.context_id,
                        assessment.model_dump_json(), assessment.created_at.isoformat(),
                    ),
                )
            for profile in profiles:
                connection.execute(
                    """INSERT INTO visualization_profiles(
                       profile_id,project_id,context_id,profile_json,created_at
                       ) VALUES (?,?,?,?,?)""",
                    (
                        profile.profile_id, profile.project_id, profile.context_id,
                        profile.model_dump_json(), profile.created_at.isoformat(),
                    ),
                )

    def get_context(self, context_id: str) -> Optional[ResearchContext]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT context_json FROM research_contexts WHERE context_id=?", (context_id,),
            ).fetchone()
        return ResearchContext.model_validate_json(row["context_json"]) if row else None

    def latest_context(self, project_id: str) -> Optional[ResearchContext]:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT context_json FROM research_contexts WHERE project_id=?
                   ORDER BY created_at DESC, context_id DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
        return ResearchContext.model_validate_json(row["context_json"]) if row else None

    def list_contexts(self, project_id: str) -> List[ResearchContext]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT context_json FROM research_contexts WHERE project_id=?
                   ORDER BY created_at, context_id""",
                (project_id,),
            ).fetchall()
        return [ResearchContext.model_validate_json(row["context_json"]) for row in rows]

    def assessment_for_context(self, context_id: str) -> Optional[LegacyReuseAssessment]:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT assessment_json FROM legacy_reuse_assessments WHERE context_id=?
                   ORDER BY created_at DESC, assessment_id DESC LIMIT 1""",
                (context_id,),
            ).fetchone()
        return LegacyReuseAssessment.model_validate_json(row["assessment_json"]) if row else None

    def save_lineage(self, record: CodeLineageRecord) -> None:
        assert_secret_free(record.model_dump(mode="json"), self.known_secrets(), context="CodeLineageRecord")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO code_lineage_records(
                   lineage_id,project_id,context_id,import_id,source_relative_path,
                   derived_workspace_path,record_json,created_at
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    record.lineage_id, record.project_id, record.context_id, record.import_id,
                    record.source_relative_path, record.derived_workspace_path,
                    record.model_dump_json(), record.created_at.isoformat(),
                ),
            )

    def get_lineage(self, lineage_id: str) -> Optional[CodeLineageRecord]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM code_lineage_records WHERE lineage_id=?", (lineage_id,),
            ).fetchone()
        return CodeLineageRecord.model_validate_json(row["record_json"]) if row else None

    def list_lineage(self, project_id: str) -> List[CodeLineageRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT record_json FROM code_lineage_records WHERE project_id=?
                   ORDER BY created_at, lineage_id""",
                (project_id,),
            ).fetchall()
        return [CodeLineageRecord.model_validate_json(row["record_json"]) for row in rows]

    def get_profile(self, profile_id: str) -> Optional[VisualizationProfile]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT profile_json FROM visualization_profiles WHERE profile_id=?", (profile_id,),
            ).fetchone()
        return VisualizationProfile.model_validate_json(row["profile_json"]) if row else None

    def list_profiles(self, project_id: str) -> List[VisualizationProfile]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT profile_json FROM visualization_profiles WHERE project_id=?
                   ORDER BY created_at, profile_id""",
                (project_id,),
            ).fetchall()
        return [VisualizationProfile.model_validate_json(row["profile_json"]) for row in rows]

    def save_figure_spec(self, spec: FigureSpec) -> None:
        assert_secret_free(spec.model_dump(mode="json"), self.known_secrets(), context="FigureSpec")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO figure_specs(
                   figure_spec_id,project_id,context_id,spec_json,created_at
                   ) VALUES (?,?,?,?,?)""",
                (
                    spec.figure_spec_id, spec.project_id, spec.context_id,
                    spec.model_dump_json(), spec.created_at.isoformat(),
                ),
            )

    def get_figure_spec(self, figure_spec_id: str) -> Optional[FigureSpec]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT spec_json FROM figure_specs WHERE figure_spec_id=?", (figure_spec_id,),
            ).fetchone()
        return FigureSpec.model_validate_json(row["spec_json"]) if row else None

    def list_figure_specs(self, project_id: str) -> List[FigureSpec]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT spec_json FROM figure_specs WHERE project_id=?
                   ORDER BY created_at, figure_spec_id""",
                (project_id,),
            ).fetchall()
        return [FigureSpec.model_validate_json(row["spec_json"]) for row in rows]

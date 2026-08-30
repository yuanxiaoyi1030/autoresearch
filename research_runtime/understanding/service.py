# Purpose: Builds generic A/B ResearchContext records and approval-ready legacy reuse assessments.
from __future__ import annotations

from pathlib import Path
import shutil
from typing import List, Optional

from pydantic import BaseModel, Field

from research_runtime.imports import sha256_file
from research_runtime.state import (
    EvidenceProvenance, ImportStatus, ProjectType, VerificationStatus,
)

from .inspector import InspectionResult, StaticProjectInspector
from .models import (
    ApprovalStatus, CodeLineageRecord, CodeModification, FigureSpec, LegacyReuseAssessment,
    LineageVerification, MaterialKind, ModificationCategory, ModificationClass,
    ProvenanceRecord, ResearchContext, ReuseDisposition, ReuseItem, ReuseRisk, ReuseStrategy,
    RiskLevel, UnderstandingMode, UserResearchConstraints, VisualizationProfile,
)


class UnderstandingBundle(BaseModel):
    context: ResearchContext
    legacy_reuse_assessment: Optional[LegacyReuseAssessment] = None
    visualization_profiles: List[VisualizationProfile] = Field(default_factory=list)


class ProjectUnderstandingService:
    def __init__(self, projects, imports, understanding, workspace,
                 inspector: Optional[StaticProjectInspector] = None) -> None:
        self.projects = projects
        self.imports = imports
        self.understanding = understanding
        self.workspace = workspace
        self.inspector = inspector or StaticProjectInspector()

    def understand(
        self,
        project_id: str,
        constraints: Optional[UserResearchConstraints] = None,
        import_id: Optional[str] = None,
    ) -> UnderstandingBundle:
        project = self.projects.get(project_id)
        if project is None:
            raise KeyError(project_id)
        constraints = constraints or UserResearchConstraints()
        if project.project_type is ProjectType.TOPIC_BASED:
            if import_id is not None:
                raise ValueError("topic-based understanding cannot select a legacy import")
            context = self._topic_context(project, constraints)
            self.understanding.save_understanding(context)
            return UnderstandingBundle(context=context)
        return self._existing_context(project, constraints, import_id)

    def latest_bundle(self, project_id: str) -> Optional[UnderstandingBundle]:
        context = self.understanding.latest_context(project_id)
        if context is None:
            return None
        return UnderstandingBundle(
            context=context,
            legacy_reuse_assessment=self.understanding.assessment_for_context(context.context_id),
            visualization_profiles=[
                profile for profile in self.understanding.list_profiles(project_id)
                if profile.context_id == context.context_id
            ],
        )

    @staticmethod
    def _topic_context(project, constraints: UserResearchConstraints) -> ResearchContext:
        topic = project.topic.strip()
        known_issues = []
        if not constraints.research_objectives:
            known_issues.append("Detailed research objectives have not yet been supplied by the user.")
        missing = [
            "Literature evidence has not yet been collected.",
            "No hypothesis, experiment plan, metric definition, or result exists yet.",
        ]
        return ResearchContext(
            project_id=project.project_id,
            mode=UnderstandingMode.TOPIC_BASED,
            topic=topic,
            user_constraints=constraints,
            summary=f"User-defined research topic: {topic}",
            research_questions=[topic],
            known_issues=known_issues,
            missing_evidence=missing,
            provenance=[ProvenanceRecord(
                provenance=EvidenceProvenance.USER_TOPIC,
                reference=f"project:{project.project_id}:topic",
                verification_status=VerificationStatus.UNVERIFIED,
            )],
        )

    def _existing_context(self, project, constraints, import_id: Optional[str]) -> UnderstandingBundle:
        selected_import_id = import_id
        if selected_import_id is None:
            state = self.projects.get_state(project.project_id)
            selected_import_id = state.latest_import_id if state else None
        if not selected_import_id:
            raise ValueError("existing-project understanding requires a completed import snapshot")
        session = self.imports.get(selected_import_id)
        if session is None or session.project_id != project.project_id:
            raise ValueError("selected import does not belong to this project")
        if session.status is not ImportStatus.COMPLETED or not session.snapshot_path:
            raise ValueError("selected import is not complete")
        manifest = self.imports.get_manifest(selected_import_id)
        if manifest is None:
            raise ValueError("completed import is missing its immutable manifest")
        expected_snapshot = (
            self.workspace.import_root(project.project_id, selected_import_id) / "snapshot"
        ).resolve(strict=True)
        snapshot = Path(session.snapshot_path).resolve(strict=True)
        if snapshot != expected_snapshot:
            raise ValueError("import snapshot path is outside the project import workspace")
        inspection = self.inspector.inspect(snapshot, manifest)
        context = ResearchContext(
            project_id=project.project_id,
            mode=UnderstandingMode.EXISTING_PROJECT,
            user_constraints=constraints,
            import_id=selected_import_id,
            manifest_hash=manifest.manifest_hash,
            summary=inspection.summary,
            research_questions=inspection.research_questions,
            materials=inspection.materials,
            detected_dependencies=inspection.dependencies,
            detected_experiments=inspection.experiments,
            detected_metrics=inspection.metrics,
            existing_result_summaries=inspection.result_summaries,
            existing_claims=inspection.claims,
            known_issues=inspection.known_issues,
            missing_evidence=inspection.missing_evidence,
            provenance=[ProvenanceRecord(
                provenance=EvidenceProvenance.LEGACY_IMPORT,
                reference=f"import:{selected_import_id}:manifest",
                sha256=manifest.manifest_hash,
                verification_status=VerificationStatus.UNVERIFIED,
            )],
        )
        assessment = self._reuse_assessment(context, inspection)
        profiles = self._visualization_profiles(context, inspection)
        self.understanding.save_understanding(context, assessment, profiles)
        return UnderstandingBundle(
            context=context,
            legacy_reuse_assessment=assessment,
            visualization_profiles=profiles,
        )

    @staticmethod
    def _reuse_assessment(
        context: ResearchContext, inspection: InspectionResult,
    ) -> LegacyReuseAssessment:
        code = [
            item for item in context.materials
            if MaterialKind.CODE in item.kinds or MaterialKind.NOTEBOOK in item.kinds
        ]
        notebooks = [item for item in code if MaterialKind.NOTEBOOK in item.kinds]
        static_failures = [issue for issue in context.known_issues if "syntax" in issue.casefold()]
        safety_dependencies = {
            dependency for dependency in context.detected_dependencies
            if dependency.casefold() in {"subprocess", "multiprocessing", "socket", "requests", "docker"}
        }
        if not code:
            strategy = ReuseStrategy.SAFE_REIMPLEMENTATION
        elif len(notebooks) == len(code) or static_failures or safety_dependencies:
            strategy = ReuseStrategy.PARTIAL_REFACTOR
        else:
            strategy = ReuseStrategy.ADAPT_EXISTING

        items: List[ReuseItem] = []
        for material in context.materials:
            kinds = set(material.kinds)
            if kinds & {MaterialKind.CODE, MaterialKind.PLOTTING_CODE, MaterialKind.CONFIG}:
                disposition = (
                    ReuseDisposition.REIMPLEMENT
                    if strategy is ReuseStrategy.SAFE_REIMPLEMENTATION else ReuseDisposition.ADAPT
                )
                changes = [
                    "Copy into the v0.2 Project Workspace before any execution.",
                    "Replace external paths and outputs with workspace-confined configuration.",
                ]
            elif kinds & {MaterialKind.RESULT, MaterialKind.FIGURE}:
                disposition = ReuseDisposition.INSUFFICIENT_EVIDENCE
                changes = ["Reproduce from approved code and verified source artifacts."]
            elif kinds & {MaterialKind.DATA, MaterialKind.DATA_DESCRIPTION, MaterialKind.PAPER}:
                disposition = ReuseDisposition.REUSE
                changes = ["Retain as read-only design/provenance input; independently verify before evidence use."]
            else:
                disposition = ReuseDisposition.DO_NOT_EXECUTE
                changes = ["Keep as legacy reference only."]
            items.append(ReuseItem(
                relative_path=material.relative_path,
                disposition=disposition,
                rationale=(
                    "Legacy material is unverified and must remain read-only; disposition follows its static type."
                ),
                preserved_scope=[kind.value for kind in material.kinds],
                required_changes=changes,
                requires_workspace_copy=bool(kinds & {
                    MaterialKind.CODE, MaterialKind.NOTEBOOK, MaterialKind.PLOTTING_CODE, MaterialKind.CONFIG,
                }),
            ))

        risks: List[ReuseRisk] = [ReuseRisk(
            level=RiskLevel.HIGH,
            category="legacy_verification",
            summary="Imported results and claims have not been reproduced by v0.2.",
            affected_paths=[
                item.relative_path for item in context.materials
                if set(item.kinds) & {MaterialKind.RESULT, MaterialKind.FIGURE, MaterialKind.PAPER}
            ],
            mitigation="Keep legacy/unverified status until an approved deterministic run reproduces them.",
        )]
        if notebooks:
            risks.append(ReuseRisk(
                level=RiskLevel.MEDIUM,
                category="notebook_state",
                summary="Notebook outputs may depend on hidden execution order or interactive state.",
                affected_paths=[item.relative_path for item in notebooks],
                mitigation="Extract approved logic into deterministic workspace modules and runners.",
            ))
        if safety_dependencies:
            risks.append(ReuseRisk(
                level=RiskLevel.HIGH,
                category="execution_boundary",
                summary="Static source references process, network, or external runtime capabilities.",
                affected_paths=[item.relative_path for item in code],
                mitigation="Refactor behind explicit policy-controlled tools; never execute the legacy snapshot.",
            ))
        missing_figure_data = [
            item.relative_path for item in context.materials
            if MaterialKind.FIGURE in item.kinds and item.source_data_available is False
        ]
        if missing_figure_data:
            risks.append(ReuseRisk(
                level=RiskLevel.HIGH,
                category="figure_without_source_data",
                summary="Legacy figures have no located source data and cannot support formal evidence claims.",
                affected_paths=missing_figure_data,
                mitigation="Use only as style/preliminary references and regenerate formal figures from new artifacts.",
            ))
        high_count = sum(risk.level in {RiskLevel.HIGH, RiskLevel.BLOCKING} for risk in risks)
        reusable_count = sum(item.disposition in {ReuseDisposition.REUSE, ReuseDisposition.ADAPT} for item in items)
        risk_summary = (
            f"{len(risks)} reuse risks ({high_count} high/blocking); all legacy evidence remains unverified."
        )
        approval_summary = (
            f"Approve strategy={strategy.value}; scope includes {reusable_count}/{len(items)} reusable/adaptable "
            "materials. Executable candidates must be copied into the project workspace. Non-semantic changes "
            "may use an implementation revision; semantic changes require a newer approved Experiment Plan revision."
        )
        return LegacyReuseAssessment(
            project_id=context.project_id,
            context_id=context.context_id,
            import_id=context.import_id,
            recommended_strategy=strategy,
            reuse_items=items,
            preserved_research_scope=context.research_questions + context.detected_experiments,
            required_adaptations=[
                "Workspace-confined paths and artifact outputs",
                "Explicit configuration, seed, logging, recovery, and safety boundaries",
                "Reproduction of legacy metrics, results, and figures before evidence use",
            ],
            excluded_scope=[
                "Direct execution from the original source or immutable import snapshot",
                "Treating legacy results or images as verified AutoResearch evidence",
            ],
            risks=risks,
            risk_summary=risk_summary,
            approval_summary=approval_summary,
        )

    @staticmethod
    def _visualization_profiles(
        context: ResearchContext, inspection: InspectionResult,
    ) -> List[VisualizationProfile]:
        values = inspection.visualization
        if not values.get("source_paths"):
            return []
        return [VisualizationProfile(
            project_id=context.project_id,
            context_id=context.context_id,
            **values,
        )]


class CodeLineageService:
    def __init__(self, projects, imports, understanding, workspace) -> None:
        self.projects = projects
        self.imports = imports
        self.understanding = understanding
        self.workspace = workspace

    def record_candidate(
        self,
        project_id: str,
        context_id: str,
        source_relative_path: str,
        derived_workspace_path: str,
        strategy: ReuseStrategy,
        modifications: Optional[List[CodeModification]] = None,
        *,
        copy_from_snapshot: bool = True,
        base_plan_revision: int = 0,
        target_plan_revision: Optional[int] = None,
        legacy_baseline: bool = False,
        plan_approval_status: ApprovalStatus = ApprovalStatus.PENDING,
        verification: LineageVerification = LineageVerification.PENDING,
        auditor_notes: Optional[List[str]] = None,
    ) -> CodeLineageRecord:
        project = self.projects.get(project_id)
        context = self.understanding.get_context(context_id)
        if project is None or context is None or context.project_id != project_id:
            raise ValueError("context does not belong to this project")
        if context.mode is not UnderstandingMode.EXISTING_PROJECT or not context.import_id:
            raise ValueError("code lineage requires an existing-project import context")
        source_material = next(
            (item for item in context.materials if item.relative_path == source_relative_path), None,
        )
        if source_material is None:
            raise ValueError("source path is not present in the immutable ResearchContext")
        if not set(source_material.kinds) & {
            MaterialKind.CODE, MaterialKind.NOTEBOOK, MaterialKind.PLOTTING_CODE, MaterialKind.CONFIG,
        }:
            raise ValueError("only code, notebook, plotting, or config material can create code lineage")
        source = self.workspace.resolve_import_file(
            project_id, context.import_id, source_relative_path,
        )
        if sha256_file(source) != source_material.sha256:
            raise ValueError("immutable source snapshot hash no longer matches ResearchContext")
        target = self.workspace.resolve_workspace_file(
            project_id, derived_workspace_path, must_exist=not copy_from_snapshot,
            create_parent=copy_from_snapshot,
        )
        modifications = list(modifications or [])
        if strategy is ReuseStrategy.SAFE_REIMPLEMENTATION and not modifications:
            raise ValueError("safe_reimplementation requires an explicit source-to-derived modification mapping")
        if copy_from_snapshot:
            if strategy is ReuseStrategy.SAFE_REIMPLEMENTATION:
                raise ValueError("safe_reimplementation must register a separately implemented workspace file")
            if target.exists():
                raise FileExistsError("workspace candidate already exists; existing research is never overwritten")
            if any(item.classification is ModificationClass.SEMANTIC for item in modifications):
                raise ValueError("a byte-for-byte snapshot copy cannot declare semantic modifications")
            created_target = False
            try:
                with source.open("rb") as input_stream, target.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                created_target = True
                shutil.copystat(source, target, follow_symlinks=False)
                if sha256_file(target) != source_material.sha256:
                    raise OSError("workspace candidate hash mismatch during copy")
            except Exception:
                if created_target and target.exists():
                    target.unlink()
                raise
            if not modifications:
                modifications = [CodeModification(
                    classification=ModificationClass.NON_SEMANTIC,
                    category=ModificationCategory.PATH,
                    summary="Copied unchanged into the controlled v0.2 Project Workspace.",
                )]
        derived_hash = sha256_file(target)
        record = CodeLineageRecord(
            project_id=project_id,
            context_id=context_id,
            import_id=context.import_id,
            source_relative_path=source_relative_path,
            source_sha256=source_material.sha256,
            derived_workspace_path=derived_workspace_path,
            derived_sha256=derived_hash,
            strategy=strategy,
            modifications=modifications,
            base_plan_revision=base_plan_revision,
            target_plan_revision=target_plan_revision,
            legacy_baseline=legacy_baseline,
            plan_approval_status=plan_approval_status,
            verification=verification,
            auditor_notes=auditor_notes or [],
        )
        try:
            self.understanding.save_lineage(record)
        except Exception:
            if copy_from_snapshot and target.exists():
                target.unlink()
            raise
        return record

    def save_figure_spec(self, project_id: str, spec: FigureSpec) -> FigureSpec:
        context = self.understanding.get_context(spec.context_id)
        if context is None or context.project_id != project_id or spec.project_id != project_id:
            raise ValueError("FigureSpec context does not belong to this project")
        if spec.visualization_profile_id:
            profile = self.understanding.get_profile(spec.visualization_profile_id)
            if profile is None or profile.project_id != project_id or profile.context_id != spec.context_id:
                raise ValueError("VisualizationProfile does not belong to this project/context")
        legacy_paths = {item.relative_path for item in context.materials if MaterialKind.FIGURE in item.kinds}
        if set(spec.legacy_reference_paths) - legacy_paths:
            raise ValueError("FigureSpec contains an unknown legacy figure reference")
        self.understanding.save_figure_spec(spec)
        return spec

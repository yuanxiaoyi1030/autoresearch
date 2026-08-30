# Purpose: Creates the loopback API foundation, secure LLM boundary, and generic A/B understanding services.
from pathlib import Path
from typing import Any, Dict, List, Optional
import difflib
import os
import sqlite3

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr

from research_runtime.analysis import (
    AnalysisAgentRun, AnalysisArtifact, AnalysisArtifactVerification, AnalysisRecord,
    AnalysisReviewService, AnalysisWorkflowResult, LLMScientificReviewer,
    ScientificReviewReport, ScientificReviewer, StatisticalAnalyst, VerificationReport,
)
from research_runtime.config import Settings
from research_runtime.compatibility import (
    BuiltinStudyDescriptor, CompatibilityVerification, V01CompatibilityImport,
    V01CompatibilityImporter,
)
from research_runtime.experiments import (
    ArtifactVerification, ExperimentAgentRun, ExperimentRun, ExperimentRunDetail,
    ExperimentalLead, ImplementationRevision, ImplementationStatus, LLMExperimentalLead, LLMResearchEngineer,
    LocalStudyExecutor, ResearchEngineer, StudyCreationResult, StudyImplementationService,
    StudyRecord, VisualizationProfileApproval,
)
from research_runtime.imports import ExistingProjectImporter
from research_runtime.jobs import DurableJobManager, EventJournal
from research_runtime.literature import (
    EvidenceReviewReport, EvidenceReviewer, LLMEvidenceReviewer, LLMLiteratureLead,
    LiteratureAgentRun, LiteratureCoordinator, LiteratureEvidence, LiteratureEvidenceMatrix,
    LiteratureLead, LiteratureRunResult, LiteratureSearchClient, LiteratureSearchCoordinator,
    LiteratureSource, ResearchGap, SearchAttempt, default_clients,
)
from research_runtime.llm import (
    CredentialStatus, LLMConfigurationStatus, LLMError, LLMRuntime, LLMRuntimeConfig, LLMStage,
    ProviderDescriptor,
)
from research_runtime.planning import (
    ApprovalDecision, CriticalReviewer, ExperimentPlanRevision, FormalExperimentGate,
    HypothesisGenerationResult, HypothesisRevision, LLMCriticalReviewer,
    LLMResearchDesignLead, PlanGenerationResult, PlanningAgentRun, PlanningApproval,
    PlanningArtifactKind, PlanningCoordinator, PlanningReviewReport, ResearchDesignLead,
)
from research_runtime.review import (
    EvidenceClaim, EvidenceClaimDraft, EvidenceReproducibilityReviewer,
    IndependentResearchReviewService, LLMEvidenceReproducibilityReviewer,
    LLMMetaReviewer, LLMMethodologyReviewer, LLMStatisticalReviewer, MetaReviewer,
    MethodologyReviewer, ResearchReviewAgentRun, ResearchReviewRecord,
    ResearchReviewResult, ResearchReviewTransition, StatisticalReviewer,
)
from research_runtime.state import ProjectType, ResearchProject, ResearchStage, ResearchState
from research_runtime.understanding import (
    CodeLineageRecord, CodeLineageService, CodeModification, FigurePanelSpec,
    FigureSpec, LegacyReuseAssessment, ProjectUnderstandingService, ReuseStrategy,
    ResearchContext, UnderstandingBundle, UserResearchConstraints, VisualizationProfile,
)
from research_runtime.workflow import InvalidTransition, WorkflowAction, WorkflowManager
from research_runtime.workspace import WorkspaceManager
from research_runtime.writing import (
    ConferenceTemplateConfig, LeadAuthor, LLMLeadAuthor, LLMPresentationLatexEditor,
    LLMRelatedWorkCitationEditor, LLMTechnicalContentEditor, LLMTopConferenceReviewer,
    PaperAgentRun, PaperArtifact, PaperRecord, PaperWritingResult, PaperWritingService,
    PresentationLatexEditor, RelatedWorkCitationEditor, TechnicalContentEditor,
    TopConferenceReviewer,
)
from storage import Database
from storage.repositories import (
    AnalysisRepository, CompatibilityRepository, EventRepository, ExperimentRepository, ImportRepository, JobRepository,
    LiteratureRepository, PaperRepository, PlanningRepository, ProjectRepository, ResearchReviewRepository,
    UnderstandingRepository,
)


class CreateProjectRequest(BaseModel):
    title: str = Field(min_length=1)
    project_type: ProjectType
    source_root: Optional[str] = None
    topic: Optional[str] = None


class ImportRequest(BaseModel):
    source_root: str = Field(min_length=1)


class ProjectDetail(BaseModel):
    project: ResearchProject
    state: ResearchState


class WorkflowReconcileResult(BaseModel):
    state: ResearchState
    applied_actions: List[WorkflowAction] = Field(default_factory=list)


class CredentialInput(BaseModel):
    api_key: SecretStr = Field(min_length=1)


class ConnectionTestRequest(BaseModel):
    stage: LLMStage


class LLMConfigView(BaseModel):
    config: LLMRuntimeConfig
    status: LLMConfigurationStatus
    providers: List[ProviderDescriptor]


class UnderstandProjectRequest(BaseModel):
    constraints: UserResearchConstraints = Field(default_factory=UserResearchConstraints)
    import_id: Optional[str] = None


class CodeLineageRequest(BaseModel):
    context_id: str = Field(min_length=1)
    source_relative_path: str = Field(min_length=1)
    derived_workspace_path: str = Field(min_length=1)
    strategy: ReuseStrategy
    modifications: List[CodeModification] = Field(default_factory=list)
    copy_from_snapshot: bool = True
    base_plan_revision: int = Field(default=0, ge=0)
    target_plan_revision: Optional[int] = Field(default=None, ge=0)


class CreateFigureSpecRequest(BaseModel):
    context_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    visualization_profile_id: Optional[str] = None
    panels: List[FigurePanelSpec] = Field(min_length=1)
    legacy_reference_paths: List[str] = Field(default_factory=list)
    caption: str = ""
    supplementary_requirements: List[str] = Field(default_factory=list)
    output_formats: List[str] = Field(default_factory=lambda: ["pdf", "png"])


class LiteratureRunRequest(BaseModel):
    allow_network: Optional[bool] = None


class GenerateHypothesesRequest(BaseModel):
    parent_revision_id: Optional[str] = None
    feedback: List[str] = Field(default_factory=list)


class GeneratePlanRequest(BaseModel):
    hypothesis_revision_id: str = Field(min_length=1)
    parent_revision_id: Optional[str] = None
    feedback: List[str] = Field(default_factory=list)


class PlanningDecisionRequest(BaseModel):
    decision: ApprovalDecision
    feedback: str = Field(min_length=1)
    actor_id: str = Field(default="local_user", min_length=1)
    selected_candidate_id: Optional[str] = None


class VisualizationProfileDecisionRequest(BaseModel):
    approved: bool
    feedback: str = Field(min_length=1)


class CreateStudyRequest(BaseModel):
    plan_revision_id: str = Field(min_length=1)
    visualization_profile_id: Optional[str] = None
    parent_implementation_id: Optional[str] = None


class CreateExperimentRunRequest(BaseModel):
    run_spec_id: str = Field(min_length=1)
    smoke: bool = False


class ScientificReviewRequest(BaseModel):
    verification_id: str = Field(min_length=1)


class CreateResearchReviewRequest(BaseModel):
    scientific_review_id: Optional[str] = None
    claims: List[EvidenceClaimDraft] = Field(default_factory=list)


class ApplyResearchReviewRequest(BaseModel):
    expected_state_revision: int = Field(ge=0)


class CreatePaperRequest(BaseModel):
    research_review_run_id: str = Field(min_length=1)
    config: ConferenceTemplateConfig
    expected_state_revision: int = Field(ge=0)


class RunLogView(BaseModel):
    run_id: str
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False


class ImplementationDiffEntry(BaseModel):
    source_relative_path: Optional[str] = None
    derived_relative_path: str
    strategy: str
    modifications: List[Dict[str, Any]] = Field(default_factory=list)
    unified_diff: str


class ImplementationDiffView(BaseModel):
    implementation_revision_id: str
    content_hash: str
    entries: List[ImplementationDiffEntry]


class Services:
    def __init__(self, settings: Settings, llm_runtime: Optional[LLMRuntime] = None,
                 literature_clients: Optional[dict] = None,
                 literature_lead: Optional[LiteratureLead] = None,
                 evidence_reviewer: Optional[EvidenceReviewer] = None,
                 research_design_lead: Optional[ResearchDesignLead] = None,
                 critical_reviewer: Optional[CriticalReviewer] = None,
                 experimental_lead: Optional[ExperimentalLead] = None,
                 research_engineer: Optional[ResearchEngineer] = None,
                 study_executor: Optional[LocalStudyExecutor] = None,
                 statistical_analyst: Optional[StatisticalAnalyst] = None,
                 scientific_reviewer: Optional[ScientificReviewer] = None,
                 meta_reviewer: Optional[MetaReviewer] = None,
                 methodology_reviewer: Optional[MethodologyReviewer] = None,
                 statistical_reviewer: Optional[StatisticalReviewer] = None,
                 research_evidence_reviewer: Optional[EvidenceReproducibilityReviewer] = None,
                 lead_author: Optional[LeadAuthor] = None,
                 technical_content_editor: Optional[TechnicalContentEditor] = None,
                 citation_editor: Optional[RelatedWorkCitationEditor] = None,
                 presentation_editor: Optional[PresentationLatexEditor] = None,
                 top_conference_reviewer: Optional[TopConferenceReviewer] = None) -> None:
        self.settings = settings
        self.workspace = WorkspaceManager(settings.runtime_root)
        self.workspace.ensure_runtime()
        self.database = Database(settings.runtime_root / "autoresearch_v0_2.sqlite3")
        self.database.initialize()
        self.llm = llm_runtime or LLMRuntime.from_environment()
        self.projects = ProjectRepository(self.database)
        self.compatibility_repository = CompatibilityRepository(
            self.database, self.llm.credentials.known_secrets,
        )
        self.v0_1_compatibility = V01CompatibilityImporter(
            self.compatibility_repository, settings.runtime_root,
            settings.v0_1_runtime_root,
        )
        self.imports = ImportRepository(self.database)
        self.events = EventJournal(EventRepository(
            self.database, self.llm.credentials.known_secrets,
        ))
        self.job_repository = JobRepository(self.database, self.llm.credentials.known_secrets)
        self.understanding_repository = UnderstandingRepository(
            self.database, self.llm.credentials.known_secrets,
        )
        self.literature_repository = LiteratureRepository(
            self.database, self.llm.credentials.known_secrets,
        )
        self.planning_repository = PlanningRepository(
            self.database, self.llm.credentials.known_secrets,
        )
        self.experiment_repository = ExperimentRepository(
            self.database, self.llm.credentials.known_secrets,
        )
        self.analysis_repository = AnalysisRepository(
            self.database, self.llm.credentials.known_secrets,
        )
        self.research_review_repository = ResearchReviewRepository(
            self.database, self.llm.credentials.known_secrets,
        )
        self.paper_repository = PaperRepository(
            self.database, self.llm.credentials.known_secrets,
        )
        self.jobs = DurableJobManager(self.job_repository, self.events)
        self.workflow = WorkflowManager(self.projects, self.events)
        self.importer = ExistingProjectImporter(
            self.projects, self.imports, self.workspace, settings.allowed_import_roots,
        )
        self.project_understanding = ProjectUnderstandingService(
            self.projects, self.imports, self.understanding_repository, self.workspace,
        )
        self.code_lineage = CodeLineageService(
            self.projects, self.imports, self.understanding_repository, self.workspace,
        )
        search = LiteratureSearchCoordinator(
            literature_clients or default_clients(), max_workers=2,
        )
        self.literature = LiteratureCoordinator(
            self.literature_repository, search,
            literature_lead or LLMLiteratureLead(self.llm),
            evidence_reviewer or LLMEvidenceReviewer(self.llm),
            max_parallel_agents=2, max_revision_rounds=2,
        )
        self.planning = PlanningCoordinator(
            self.projects, self.understanding_repository, self.literature_repository,
            self.planning_repository,
            research_design_lead or LLMResearchDesignLead(self.llm),
            critical_reviewer or LLMCriticalReviewer(self.llm),
        )
        executor = study_executor or LocalStudyExecutor(self.llm.credentials.known_secrets)
        self.study_runtime = StudyImplementationService(
            self.projects, self.understanding_repository, self.planning,
            self.experiment_repository, self.workspace, self.code_lineage,
            experimental_lead or LLMExperimentalLead(self.llm),
            research_engineer or LLMResearchEngineer(self.llm),
            executor, self.events,
        )
        self.analysis_runtime = AnalysisReviewService(
            self.projects, self.understanding_repository, self.planning,
            self.experiment_repository, self.analysis_repository, self.workspace,
            scientific_reviewer or LLMScientificReviewer(self.llm),
            analyst=statistical_analyst, events=self.events,
        )
        self.research_review = IndependentResearchReviewService(
            self.projects, self.planning, self.understanding_repository,
            self.literature_repository, self.experiment_repository,
            self.analysis_repository, self.research_review_repository,
            self.analysis_runtime, self.study_runtime, self.workflow,
            meta_reviewer or LLMMetaReviewer(self.llm),
            methodology_reviewer or LLMMethodologyReviewer(self.llm),
            statistical_reviewer or LLMStatisticalReviewer(self.llm),
            research_evidence_reviewer or LLMEvidenceReproducibilityReviewer(self.llm),
            self.events,
        )
        self.paper_writing = PaperWritingService(
            self.projects, self.understanding_repository, self.literature_repository,
            self.planning_repository, self.experiment_repository, self.analysis_repository,
            self.research_review_repository, self.paper_repository, self.workspace,
            self.analysis_runtime, self.workflow,
            lead_author or LLMLeadAuthor(self.llm),
            technical_content_editor or LLMTechnicalContentEditor(self.llm),
            citation_editor or LLMRelatedWorkCitationEditor(self.llm),
            presentation_editor or LLMPresentationLatexEditor(self.llm),
            top_conference_reviewer or LLMTopConferenceReviewer(self.llm),
            self.events,
        )
        self.importer.recover_interrupted()
        self.jobs.recover()


def create_app(settings: Optional[Settings] = None,
               llm_runtime: Optional[LLMRuntime] = None,
               literature_clients: Optional[dict] = None,
               literature_lead: Optional[LiteratureLead] = None,
               evidence_reviewer: Optional[EvidenceReviewer] = None,
               research_design_lead: Optional[ResearchDesignLead] = None,
               critical_reviewer: Optional[CriticalReviewer] = None,
               experimental_lead: Optional[ExperimentalLead] = None,
               research_engineer: Optional[ResearchEngineer] = None,
               study_executor: Optional[LocalStudyExecutor] = None,
               statistical_analyst: Optional[StatisticalAnalyst] = None,
               scientific_reviewer: Optional[ScientificReviewer] = None,
               meta_reviewer: Optional[MetaReviewer] = None,
               methodology_reviewer: Optional[MethodologyReviewer] = None,
               statistical_reviewer: Optional[StatisticalReviewer] = None,
               research_evidence_reviewer: Optional[EvidenceReproducibilityReviewer] = None,
               lead_author: Optional[LeadAuthor] = None,
               technical_content_editor: Optional[TechnicalContentEditor] = None,
               citation_editor: Optional[RelatedWorkCitationEditor] = None,
               presentation_editor: Optional[PresentationLatexEditor] = None,
               top_conference_reviewer: Optional[TopConferenceReviewer] = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    services = Services(
        resolved, llm_runtime=llm_runtime, literature_clients=literature_clients,
        literature_lead=literature_lead, evidence_reviewer=evidence_reviewer,
        research_design_lead=research_design_lead, critical_reviewer=critical_reviewer,
        experimental_lead=experimental_lead, research_engineer=research_engineer,
        study_executor=study_executor, statistical_analyst=statistical_analyst,
        scientific_reviewer=scientific_reviewer,
        meta_reviewer=meta_reviewer, methodology_reviewer=methodology_reviewer,
        statistical_reviewer=statistical_reviewer,
        research_evidence_reviewer=research_evidence_reviewer,
        lead_author=lead_author, technical_content_editor=technical_content_editor,
        citation_editor=citation_editor, presentation_editor=presentation_editor,
        top_conference_reviewer=top_conference_reviewer,
    )
    app = FastAPI(title="AutoResearch", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.state.services = services

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "version": "0.2.0",
            "runtime_root": str(resolved.runtime_root),
            "host": resolved.host,
            "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
            "foundation_only": False,
            "llm_status": services.llm.status().status,
            "compatibility_builtins": len(services.v0_1_compatibility.builtins()),
        }

    @app.get("/api/builtins", response_model=List[BuiltinStudyDescriptor])
    def list_builtin_studies():
        return services.v0_1_compatibility.builtins()

    @app.post(
        "/api/compatibility/v0.1/imports/weight-decay-v1",
        response_model=V01CompatibilityImport,
        status_code=status.HTTP_201_CREATED,
    )
    def import_v0_1_weight_decay():
        try:
            return services.v0_1_compatibility.import_weight_decay_v1()
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/compatibility/v0.1/imports",
        response_model=List[V01CompatibilityImport],
    )
    def list_v0_1_compatibility_imports():
        return services.compatibility_repository.list()

    @app.get(
        "/api/compatibility/v0.1/imports/{compatibility_import_id}",
        response_model=V01CompatibilityImport,
    )
    def get_v0_1_compatibility_import(compatibility_import_id: str):
        record = services.compatibility_repository.get(compatibility_import_id)
        if record is None:
            raise HTTPException(status_code=404, detail="compatibility import not found")
        return record

    @app.post(
        "/api/compatibility/v0.1/imports/{compatibility_import_id}/verify",
        response_model=CompatibilityVerification,
    )
    def verify_v0_1_compatibility_import(compatibility_import_id: str):
        try:
            return services.v0_1_compatibility.verify(compatibility_import_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="compatibility import not found") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/compatibility/v0.1/imports/{compatibility_import_id}/artifacts/"
        "{legacy_artifact_id}/content"
    )
    def get_v0_1_compatibility_artifact(
        compatibility_import_id: str, legacy_artifact_id: str,
    ):
        record = services.compatibility_repository.get(compatibility_import_id)
        if record is None:
            raise HTTPException(status_code=404, detail="compatibility import not found")
        artifact = next(
            (item for item in record.artifacts if item.legacy_artifact_id == legacy_artifact_id),
            None,
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail="compatibility Artifact not found")
        try:
            path = services.v0_1_compatibility.artifact_path(
                compatibility_import_id, legacy_artifact_id,
            )
        except (KeyError, OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(path, media_type=artifact.media_type)

    @app.get("/api/llm/providers", response_model=List[ProviderDescriptor])
    def list_llm_providers():
        return services.llm.registry.descriptors()

    @app.get("/api/llm/config", response_model=LLMConfigView)
    def get_llm_config():
        return LLMConfigView(
            config=services.llm.config(),
            status=services.llm.status(),
            providers=services.llm.registry.descriptors(),
        )

    @app.put("/api/llm/config", response_model=LLMConfigView)
    def put_llm_config(payload: LLMRuntimeConfig):
        services.llm.configure(payload)
        return LLMConfigView(
            config=services.llm.config(),
            status=services.llm.status(),
            providers=services.llm.registry.descriptors(),
        )

    @app.put("/api/llm/credentials/{provider_id}", response_model=CredentialStatus)
    def put_llm_credential(provider_id: str, payload: CredentialInput):
        if provider_id not in services.llm.configured_provider_ids():
            raise HTTPException(status_code=404, detail="provider_id is not configured")
        return services.llm.set_credential(provider_id, payload.api_key.get_secret_value())

    @app.delete("/api/llm/credentials/{provider_id}", response_model=CredentialStatus)
    def delete_llm_credential(provider_id: str):
        return services.llm.clear_credential(provider_id)

    @app.post("/api/llm/connection-tests")
    def test_llm_connection(payload: ConnectionTestRequest):
        return services.llm.test_connection(payload.stage)

    @app.get("/api/llm/usage")
    def get_llm_usage():
        return services.llm.usage()

    @app.post("/api/projects", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
    def create_project(payload: CreateProjectRequest):
        try:
            project = ResearchProject(**payload.model_dump())
            state = ResearchState(project_id=project.project_id)
            services.projects.create(project, state)
            services.workflow.ensure_initial_attempt(project.project_id)
            services.events.append(
                project.project_id, "project.created", "Research project foundation created",
                stage=state.stage, payload={"project_type": project.project_type.value},
            )
            return ProjectDetail(project=project, state=services.projects.get_state(project.project_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects", response_model=List[ProjectDetail])
    def list_projects():
        return [
            ProjectDetail(project=project, state=services.projects.get_state(project.project_id))
            for project in services.projects.list()
        ]

    @app.get("/api/projects/{project_id}/state", response_model=ResearchState)
    def get_state(project_id: str):
        state_record = services.projects.get_state(project_id)
        if state_record is None:
            raise HTTPException(status_code=404, detail="project not found")
        return state_record

    @app.post(
        "/api/projects/{project_id}/workflow/reconcile",
        response_model=WorkflowReconcileResult,
    )
    def reconcile_workflow(project_id: str):
        """Advance only across stages already proven by persisted artifacts.

        Earlier v0.2 endpoints persisted their outputs but did not advance the
        workflow state machine, leaving otherwise valid projects stuck at
        ``initializing``.  Reconciliation is explicit, deterministic, and
        idempotent: it never invents an artifact or skips a user approval.
        """
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        applied: List[WorkflowAction] = []
        for _ in range(8):
            state_record = services.projects.get_state(project_id)
            action: Optional[WorkflowAction] = None
            if state_record.stage is ResearchStage.INITIALIZING:
                action = WorkflowAction.INITIALIZATION_COMPLETED
            elif state_record.stage is ResearchStage.PROJECT_UNDERSTANDING:
                if services.understanding_repository.latest_context(project_id) is not None:
                    action = WorkflowAction.PROJECT_UNDERSTANDING_COMPLETED
            elif state_record.stage is ResearchStage.LITERATURE:
                if services.literature_repository.latest_matrix(project_id) is not None:
                    action = WorkflowAction.LITERATURE_COMPLETED
            elif state_record.stage is ResearchStage.HYPOTHESIS:
                if services.planning_repository.latest_hypothesis(project_id) is not None:
                    action = WorkflowAction.HYPOTHESIS_READY
            elif state_record.stage is ResearchStage.WAIT_HYPOTHESIS_APPROVAL:
                hypothesis = services.planning_repository.latest_hypothesis(project_id)
                approval = (
                    services.planning_repository.approval_for(
                        PlanningArtifactKind.HYPOTHESIS,
                        hypothesis.hypothesis_revision_id,
                    ) if hypothesis else None
                )
                if approval is not None:
                    action = (
                        WorkflowAction.HYPOTHESIS_APPROVED
                        if approval.decision is ApprovalDecision.APPROVED
                        else WorkflowAction.HYPOTHESIS_REJECTED
                    )
            elif state_record.stage is ResearchStage.EXPERIMENT_PLANNING:
                if services.planning_repository.latest_plan(project_id) is not None:
                    action = WorkflowAction.PLAN_READY
            elif state_record.stage is ResearchStage.WAIT_PLAN_APPROVAL:
                plan = services.planning_repository.latest_plan(project_id)
                approval = (
                    services.planning_repository.approval_for(
                        PlanningArtifactKind.EXPERIMENT_PLAN,
                        plan.plan_revision_id,
                    ) if plan else None
                )
                if approval is not None:
                    action = (
                        WorkflowAction.PLAN_APPROVED
                        if approval.decision is ApprovalDecision.APPROVED
                        else WorkflowAction.PLAN_REJECTED
                    )
            elif state_record.stage is ResearchStage.EXPERIMENT_IMPLEMENTATION:
                implementations = services.experiment_repository.list_implementations(project_id)
                implementation = implementations[-1] if implementations else None
                if implementation and implementation.status is ImplementationStatus.VERIFIED:
                    action = WorkflowAction.IMPLEMENTATION_READY
                elif implementation and implementation.status is ImplementationStatus.REQUIRES_PLAN_REVISION:
                    action = WorkflowAction.IMPLEMENTATION_REQUIRES_PLAN_REVISION
            if action is None:
                return WorkflowReconcileResult(state=state_record, applied_actions=applied)
            services.workflow.transition(
                project_id, action, expected_revision=state_record.revision,
            )
            applied.append(action)
        return WorkflowReconcileResult(
            state=services.projects.get_state(project_id), applied_actions=applied,
        )

    @app.post("/api/projects/{project_id}/imports", status_code=status.HTTP_201_CREATED)
    def import_project(project_id: str, payload: ImportRequest):
        project = services.projects.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        if project.project_type is not ProjectType.EXISTING_PROJECT:
            raise HTTPException(status_code=409, detail="only existing_project projects can import")
        if Path(payload.source_root).resolve(strict=False) != Path(project.source_root).resolve(strict=False):
            raise HTTPException(status_code=409, detail="import source must match the project source_root")
        try:
            session = services.importer.import_project(
                project_id, Path(payload.source_root),
                progress=lambda event_type, summary, event_payload: services.events.append(
                    project_id, event_type, summary, payload=event_payload,
                ),
            )
            return session
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/imports")
    def list_imports(project_id: str):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        return services.imports.list_project(project_id)

    @app.get("/api/projects/{project_id}/imports/{import_id}/files/{relative_path:path}")
    def get_import_file(project_id: str, import_id: str, relative_path: str):
        session = services.imports.get(import_id)
        if session is None or session.project_id != project_id:
            raise HTTPException(status_code=404, detail="Import file not found")
        try:
            path = services.workspace.resolve_import_file(project_id, import_id, relative_path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Import file not found") from exc
        return FileResponse(path)

    @app.get("/api/projects/{project_id}/events")
    def list_events(project_id: str, cursor: int = 0, limit: int = 100):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        return services.events.after(project_id, cursor, limit)

    @app.get("/api/projects/{project_id}/jobs")
    def list_jobs(project_id: str):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        return services.job_repository.list_project(project_id)

    @app.post(
        "/api/projects/{project_id}/understanding",
        response_model=UnderstandingBundle,
        status_code=status.HTTP_201_CREATED,
    )
    def understand_project(project_id: str, payload: UnderstandProjectRequest):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        try:
            bundle = services.project_understanding.understand(
                project_id, payload.constraints, payload.import_id,
            )
            services.events.append(
                project_id,
                "project_understanding.completed",
                "Generic Project Understanding completed",
                payload={
                    "context_id": bundle.context.context_id,
                    "mode": bundle.context.mode.value,
                    "materials": len(bundle.context.materials),
                    "reuse_strategy": (
                        bundle.legacy_reuse_assessment.recommended_strategy.value
                        if bundle.legacy_reuse_assessment else None
                    ),
                },
            )
            return bundle
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/understanding", response_model=UnderstandingBundle)
    def get_latest_understanding(project_id: str):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        bundle = services.project_understanding.latest_bundle(project_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail="project understanding not found")
        return bundle

    @app.get("/api/projects/{project_id}/understanding/history", response_model=List[ResearchContext])
    def list_understanding_history(project_id: str):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        return services.understanding_repository.list_contexts(project_id)

    @app.get(
        "/api/projects/{project_id}/understanding/{context_id}/reuse-assessment",
        response_model=LegacyReuseAssessment,
    )
    def get_reuse_assessment(project_id: str, context_id: str):
        context = services.understanding_repository.get_context(context_id)
        if context is None or context.project_id != project_id:
            raise HTTPException(status_code=404, detail="research context not found")
        assessment = services.understanding_repository.assessment_for_context(context_id)
        if assessment is None:
            raise HTTPException(status_code=404, detail="legacy reuse assessment not found")
        return assessment

    @app.post(
        "/api/projects/{project_id}/code-lineage",
        response_model=CodeLineageRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def create_code_lineage(project_id: str, payload: CodeLineageRequest):
        try:
            record = services.code_lineage.record_candidate(
                project_id=project_id,
                context_id=payload.context_id,
                source_relative_path=payload.source_relative_path,
                derived_workspace_path=payload.derived_workspace_path,
                strategy=payload.strategy,
                modifications=payload.modifications,
                copy_from_snapshot=payload.copy_from_snapshot,
                base_plan_revision=payload.base_plan_revision,
                target_plan_revision=payload.target_plan_revision,
            )
            services.events.append(
                project_id,
                "code_lineage.created",
                "Workspace-confined code lineage recorded",
                payload={
                    "lineage_id": record.lineage_id,
                    "strategy": record.strategy.value,
                    "has_semantic_changes": record.has_semantic_changes,
                    "execution_eligible": record.execution_eligible,
                },
            )
            return record
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/code-lineage", response_model=List[CodeLineageRecord])
    def list_code_lineage(project_id: str):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        return services.understanding_repository.list_lineage(project_id)

    @app.get(
        "/api/projects/{project_id}/visualization-profiles",
        response_model=List[VisualizationProfile],
    )
    def list_visualization_profiles(project_id: str):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        return services.understanding_repository.list_profiles(project_id)

    @app.post(
        "/api/projects/{project_id}/figure-specs",
        response_model=FigureSpec,
        status_code=status.HTTP_201_CREATED,
    )
    def create_figure_spec(project_id: str, payload: CreateFigureSpecRequest):
        try:
            spec = FigureSpec(project_id=project_id, **payload.model_dump())
            return services.code_lineage.save_figure_spec(project_id, spec)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/figure-specs", response_model=List[FigureSpec])
    def list_figure_specs(project_id: str):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        return services.understanding_repository.list_figure_specs(project_id)

    @app.post(
        "/api/projects/{project_id}/literature",
        response_model=LiteratureRunResult,
        status_code=status.HTTP_201_CREATED,
    )
    def run_literature(project_id: str, payload: LiteratureRunRequest):
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        context = services.understanding_repository.latest_context(project_id)
        if context is None:
            raise HTTPException(status_code=409, detail="Project Understanding must complete first")
        allow_network = (
            context.user_constraints.network_allowed
            if payload.allow_network is None else payload.allow_network
        )
        try:
            result = services.literature.run(
                project_id, context, allow_network=allow_network,
            )
            services.events.append(
                project_id, "literature.completed", "Literature Multi-Agent review completed",
                payload={
                    "context_id": context.context_id,
                    "matrix_id": result.final_matrix.matrix_id,
                    "revision": result.final_matrix.revision,
                    "sources": len(result.sources),
                    "search_attempts": len(result.search_attempts),
                    "review_rounds": len(result.review_reports),
                    "max_parallel_agents": services.literature.max_parallel_agents,
                },
            )
            return result
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def require_project(project_id: str) -> None:
        if services.projects.get(project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")

    @app.get("/api/projects/{project_id}/literature", response_model=LiteratureEvidenceMatrix)
    def get_latest_literature(project_id: str):
        require_project(project_id)
        matrix = services.literature_repository.latest_matrix(project_id)
        if matrix is None:
            raise HTTPException(status_code=404, detail="literature matrix not found")
        return matrix

    @app.get("/api/projects/{project_id}/literature/history", response_model=List[LiteratureEvidenceMatrix])
    def list_literature_history(project_id: str):
        require_project(project_id)
        return services.literature_repository.list_matrices(project_id)

    @app.get("/api/projects/{project_id}/literature/search-attempts", response_model=List[SearchAttempt])
    def list_literature_attempts(project_id: str):
        require_project(project_id)
        return services.literature_repository.list_attempts(project_id)

    @app.get("/api/projects/{project_id}/literature/sources", response_model=List[LiteratureSource])
    def list_literature_sources(project_id: str):
        require_project(project_id)
        return services.literature_repository.list_sources(project_id)

    @app.get("/api/projects/{project_id}/literature/evidence", response_model=List[LiteratureEvidence])
    def list_literature_evidence(project_id: str):
        require_project(project_id)
        return services.literature_repository.list_evidence(project_id)

    @app.get("/api/projects/{project_id}/literature/gaps", response_model=List[ResearchGap])
    def list_research_gaps(project_id: str):
        require_project(project_id)
        return services.literature_repository.list_gaps(project_id)

    @app.get("/api/projects/{project_id}/literature/reviews", response_model=List[EvidenceReviewReport])
    def list_evidence_reviews(project_id: str):
        require_project(project_id)
        return services.literature_repository.list_reviews(project_id)

    @app.get("/api/projects/{project_id}/literature/agent-runs", response_model=List[LiteratureAgentRun])
    def list_literature_agent_runs(project_id: str):
        require_project(project_id)
        return services.literature_repository.list_agent_runs(project_id)

    @app.post(
        "/api/projects/{project_id}/hypotheses",
        response_model=HypothesisGenerationResult,
        status_code=status.HTTP_201_CREATED,
    )
    def generate_hypotheses(project_id: str, payload: GenerateHypothesesRequest):
        require_project(project_id)
        try:
            result = services.planning.generate_hypotheses(
                project_id, parent_revision_id=payload.parent_revision_id,
                user_feedback=payload.feedback,
            )
            services.events.append(
                project_id, "hypothesis.reviewed", "Hypothesis revision independently reviewed",
                payload={
                    "hypothesis_revision_id": result.revision.hypothesis_revision_id,
                    "revision": result.revision.revision,
                    "content_hash": result.revision.content_hash,
                    "blocking_defects": result.review.has_blocking_defects,
                },
            )
            return result
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/hypotheses", response_model=List[HypothesisRevision])
    def list_hypotheses(project_id: str):
        require_project(project_id)
        return services.planning_repository.list_hypotheses(project_id)

    @app.post(
        "/api/projects/{project_id}/hypotheses/{revision_id}/decision",
        response_model=PlanningApproval,
        status_code=status.HTTP_201_CREATED,
    )
    def decide_hypothesis(project_id: str, revision_id: str, payload: PlanningDecisionRequest):
        require_project(project_id)
        try:
            approval = services.planning.decide(
                project_id, PlanningArtifactKind.HYPOTHESIS, revision_id,
                payload.decision, payload.feedback, actor_id=payload.actor_id,
                selected_candidate_id=payload.selected_candidate_id,
            )
            services.events.append(
                project_id, f"hypothesis.{approval.decision.value}",
                "User decision recorded for exact Hypothesis revision/hash",
                payload=approval.model_dump(mode="json"),
            )
            return approval
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/api/projects/{project_id}/experiment-plans",
        response_model=PlanGenerationResult,
        status_code=status.HTTP_201_CREATED,
    )
    def generate_experiment_plan(project_id: str, payload: GeneratePlanRequest):
        require_project(project_id)
        try:
            result = services.planning.generate_plan(
                project_id, payload.hypothesis_revision_id,
                parent_revision_id=payload.parent_revision_id,
                user_feedback=payload.feedback,
            )
            services.events.append(
                project_id, "experiment_plan.reviewed",
                "Experiment Plan revision independently reviewed",
                payload={
                    "plan_revision_id": result.revision.plan_revision_id,
                    "revision": result.revision.revision,
                    "content_hash": result.revision.content_hash,
                    "blocking_defects": result.review.has_blocking_defects,
                    "expected_total_runs": result.revision.plan.expected_total_runs,
                },
            )
            return result
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/experiment-plans",
        response_model=List[ExperimentPlanRevision],
    )
    def list_experiment_plans(project_id: str):
        require_project(project_id)
        return services.planning_repository.list_plans(project_id)

    @app.post(
        "/api/projects/{project_id}/experiment-plans/{revision_id}/review",
        response_model=PlanningReviewReport,
        status_code=status.HTTP_201_CREATED,
    )
    def review_experiment_plan(project_id: str, revision_id: str):
        require_project(project_id)
        try:
            review = services.planning.review_plan_revision(project_id, revision_id)
            services.events.append(
                project_id, "experiment_plan.reviewed",
                "Persisted Experiment Plan revision independently reviewed",
                payload={
                    "plan_revision_id": revision_id,
                    "report_id": review.report_id,
                    "blocking_defects": review.has_blocking_defects,
                },
            )
            return review
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/api/projects/{project_id}/experiment-plans/{revision_id}/decision",
        response_model=PlanningApproval,
        status_code=status.HTTP_201_CREATED,
    )
    def decide_experiment_plan(project_id: str, revision_id: str,
                               payload: PlanningDecisionRequest):
        require_project(project_id)
        try:
            approval = services.planning.decide(
                project_id, PlanningArtifactKind.EXPERIMENT_PLAN, revision_id,
                payload.decision, payload.feedback, actor_id=payload.actor_id,
                selected_candidate_id=payload.selected_candidate_id,
            )
            services.events.append(
                project_id, f"experiment_plan.{approval.decision.value}",
                "User decision recorded for exact Experiment Plan revision/hash",
                payload=approval.model_dump(mode="json"),
            )
            return approval
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/experiment-plans/{revision_id}/formal-experiment-gate",
        response_model=FormalExperimentGate,
    )
    def formal_experiment_gate(project_id: str, revision_id: str):
        require_project(project_id)
        return services.planning.formal_experiment_gate(project_id, revision_id)

    @app.get(
        "/api/projects/{project_id}/planning/reviews",
        response_model=List[PlanningReviewReport],
    )
    def list_planning_reviews(project_id: str):
        require_project(project_id)
        return services.planning_repository.list_reviews(project_id)

    @app.get(
        "/api/projects/{project_id}/planning/approvals",
        response_model=List[PlanningApproval],
    )
    def list_planning_approvals(project_id: str):
        require_project(project_id)
        return services.planning_repository.list_approvals(project_id)

    @app.get(
        "/api/projects/{project_id}/planning/agent-runs",
        response_model=List[PlanningAgentRun],
    )
    def list_planning_agent_runs(project_id: str):
        require_project(project_id)
        return services.planning_repository.list_agent_runs(project_id)

    @app.post(
        "/api/projects/{project_id}/visualization-profiles/{profile_id}/decision",
        response_model=VisualizationProfileApproval,
        status_code=status.HTTP_201_CREATED,
    )
    def decide_visualization_profile(project_id: str, profile_id: str,
                                     payload: VisualizationProfileDecisionRequest):
        require_project(project_id)
        try:
            return services.study_runtime.decide_visualization_profile(
                project_id, profile_id, payload.approved, payload.feedback,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/api/projects/{project_id}/studies",
        response_model=StudyCreationResult,
        status_code=status.HTTP_201_CREATED,
    )
    def create_study(project_id: str, payload: CreateStudyRequest):
        require_project(project_id)
        try:
            result = services.study_runtime.create_study(
                project_id, payload.plan_revision_id,
                visualization_profile_id=payload.visualization_profile_id,
                parent_implementation_id=payload.parent_implementation_id,
            )
            services.events.append(
                project_id, "study.implementation.created",
                "Experimental Lead and Research Engineer implementation recorded",
                payload={
                    "implementation_revision_id": result.implementation.implementation_revision_id,
                    "implementation_status": result.implementation.status.value,
                    "study_id": result.study.study_id if result.study else None,
                    "code_tree_sha256": result.implementation.code_tree_sha256,
                    "lineage_ids": result.lineage_ids,
                },
            )
            return result
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/studies", response_model=List[StudyRecord])
    def list_studies(project_id: str):
        require_project(project_id)
        return services.experiment_repository.list_studies(project_id)

    @app.get("/api/projects/{project_id}/studies/{study_id}", response_model=StudyRecord)
    def get_study(project_id: str, study_id: str):
        require_project(project_id)
        study = services.experiment_repository.get_study(study_id)
        if study is None or study.project_id != project_id:
            raise HTTPException(status_code=404, detail="Study not found")
        return study

    @app.get(
        "/api/projects/{project_id}/implementation-revisions",
        response_model=List[ImplementationRevision],
    )
    def list_implementation_revisions(project_id: str):
        require_project(project_id)
        return services.experiment_repository.list_implementations(project_id)

    @app.get(
        "/api/projects/{project_id}/implementation-revisions/{implementation_revision_id}/diff",
        response_model=ImplementationDiffView,
    )
    def get_implementation_diff(project_id: str, implementation_revision_id: str):
        require_project(project_id)
        revision = services.experiment_repository.get_implementation(implementation_revision_id)
        if revision is None or revision.project_id != project_id:
            raise HTTPException(status_code=404, detail="Implementation Revision not found")
        context = services.understanding_repository.get_context(revision.context_id)
        mappings = {
            item.derived_relative_path: item
            for item in revision.code_package.legacy_mappings
        }
        entries = []
        for implementation_file in revision.code_package.files:
            mapping = mappings.get(implementation_file.relative_path)
            source_text = ""
            source_path = mapping.source_relative_path if mapping else None
            if mapping is not None and context is not None and context.import_id:
                try:
                    source_file = services.workspace.resolve_import_file(
                        project_id, context.import_id, mapping.source_relative_path,
                    )
                    source_text = source_file.read_text(encoding="utf-8", errors="replace")
                except (FileNotFoundError, OSError, ValueError):
                    source_text = ""
            before_label = f"legacy/{source_path}" if source_path else "/dev/null"
            after_label = f"workspace/{implementation_file.relative_path}"
            unified = "".join(difflib.unified_diff(
                source_text.splitlines(keepends=True),
                implementation_file.content.splitlines(keepends=True),
                fromfile=before_label,
                tofile=after_label,
                n=3,
            ))
            entries.append(ImplementationDiffEntry(
                source_relative_path=source_path,
                derived_relative_path=implementation_file.relative_path,
                strategy=mapping.action if mapping else "new_file",
                modifications=[
                    item.model_dump(mode="json")
                    for item in (mapping.modifications if mapping else [])
                ],
                unified_diff=unified,
            ))
        return ImplementationDiffView(
            implementation_revision_id=revision.implementation_revision_id,
            content_hash=revision.content_hash,
            entries=entries,
        )

    @app.post(
        "/api/projects/{project_id}/studies/{study_id}/runs",
        response_model=ExperimentRun,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_experiment_run(project_id: str, study_id: str,
                              payload: CreateExperimentRunRequest):
        require_project(project_id)
        try:
            return services.study_runtime.start_run(
                project_id, study_id, payload.run_spec_id, smoke=payload.smoke,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/studies/{study_id}/runs",
        response_model=List[ExperimentRun],
    )
    def list_experiment_runs(project_id: str, study_id: str):
        study = services.experiment_repository.get_study(study_id)
        if study is None or study.project_id != project_id:
            raise HTTPException(status_code=404, detail="Study not found")
        return services.experiment_repository.list_runs(study_id)

    @app.get("/api/projects/{project_id}/runs/{run_id}", response_model=ExperimentRunDetail)
    def get_experiment_run(project_id: str, run_id: str):
        try:
            detail = services.study_runtime.detail(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ExperimentRun not found") from exc
        if detail.run.project_id != project_id:
            raise HTTPException(status_code=404, detail="ExperimentRun not found")
        return detail

    @app.get("/api/projects/{project_id}/runs/{run_id}/logs", response_model=RunLogView)
    def get_experiment_run_logs(project_id: str, run_id: str):
        run = services.experiment_repository.get_run(run_id)
        if run is None or run.project_id != project_id:
            raise HTTPException(status_code=404, detail="ExperimentRun not found")
        project_root = services.workspace.project_root(project_id).resolve(strict=True)
        log_root = (project_root / "runs" / run.run_id / "logs").resolve(strict=False)
        try:
            log_root.relative_to(project_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Run logs escaped project") from exc
        limit = min(run.output_limit_bytes, 1_000_000)

        def read_log(name: str):
            path = log_root / name
            if not path.exists() or not path.is_file():
                return "", False
            payload = path.read_bytes()
            truncated = len(payload) > limit
            return payload[-limit:].decode("utf-8", errors="replace"), truncated

        stdout, stdout_truncated = read_log("stdout.log")
        stderr, stderr_truncated = read_log("stderr.log")
        return RunLogView(
            run_id=run_id, stdout=stdout, stderr=stderr,
            truncated=stdout_truncated or stderr_truncated,
        )

    @app.get("/api/projects/{project_id}/artifacts/{artifact_id}/content")
    def get_experiment_artifact_content(project_id: str, artifact_id: str):
        artifact = services.experiment_repository.get_artifact(artifact_id)
        if artifact is None or artifact.project_id != project_id:
            raise HTTPException(status_code=404, detail="Artifact not found")
        root = services.workspace.project_root(project_id).resolve(strict=True)
        try:
            path = (root / artifact.relative_path).resolve(strict=True)
            path.relative_to(root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Artifact content not found") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Artifact content not found")
        return FileResponse(path, media_type=artifact.media_type)

    @app.post("/api/projects/{project_id}/runs/{run_id}/pause", response_model=ExperimentRun)
    def pause_experiment_run(project_id: str, run_id: str):
        try:
            run = services.study_runtime.pause_run(run_id)
            if run.project_id != project_id:
                raise KeyError(run_id)
            return run
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ExperimentRun not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/runs/{run_id}/resume", response_model=ExperimentRun)
    def resume_experiment_run(project_id: str, run_id: str):
        try:
            parent = services.experiment_repository.get_run(run_id)
            if parent is None or parent.project_id != project_id:
                raise KeyError(run_id)
            return services.study_runtime.resume_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ExperimentRun not found") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/runs/{run_id}/cancel", response_model=ExperimentRun)
    def cancel_experiment_run(project_id: str, run_id: str):
        try:
            run = services.study_runtime.cancel_run(run_id)
            if run.project_id != project_id:
                raise KeyError(run_id)
            return run
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ExperimentRun not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/artifacts/{artifact_id}/verification",
        response_model=ArtifactVerification,
    )
    def verify_experiment_artifact(project_id: str, artifact_id: str):
        try:
            result = services.study_runtime.verify_artifact(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        if result.artifact.project_id != project_id:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return result

    @app.get(
        "/api/projects/{project_id}/experiment-agent-runs",
        response_model=List[ExperimentAgentRun],
    )
    def list_experiment_agent_runs(project_id: str):
        require_project(project_id)
        return services.experiment_repository.list_agent_runs(project_id)

    @app.post(
        "/api/projects/{project_id}/studies/{study_id}/analyses",
        response_model=AnalysisWorkflowResult,
        status_code=status.HTTP_201_CREATED,
    )
    def create_analysis(project_id: str, study_id: str):
        require_project(project_id)
        try:
            result = services.analysis_runtime.run(project_id, study_id)
            services.events.append(
                project_id, "analysis.review.completed",
                "Deterministic analysis, independent verification, and scientific review recorded",
                payload={
                    "analysis_id": result.analysis.analysis_id,
                    "outcome": result.analysis.outcome.value,
                    "verification_id": result.verification.verification_id,
                    "verification_passed": result.verification.passed,
                    "scientific_review_id": result.review.review_id,
                    "policy_recommendation": result.review.policy_recommendation.value,
                },
            )
            return result
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/studies/{study_id}/analyses",
        response_model=List[AnalysisRecord],
    )
    def list_analyses(project_id: str, study_id: str):
        study = services.experiment_repository.get_study(study_id)
        if study is None or study.project_id != project_id:
            raise HTTPException(status_code=404, detail="Study not found")
        return services.analysis_repository.list_analyses(study_id)

    @app.get(
        "/api/projects/{project_id}/analyses/{analysis_id}",
        response_model=AnalysisRecord,
    )
    def get_analysis(project_id: str, analysis_id: str):
        analysis = services.analysis_repository.get_analysis(analysis_id)
        if analysis is None or analysis.project_id != project_id:
            raise HTTPException(status_code=404, detail="AnalysisRecord not found")
        return analysis

    @app.get(
        "/api/projects/{project_id}/analyses/{analysis_id}/artifacts",
        response_model=List[AnalysisArtifact],
    )
    def list_analysis_artifacts(project_id: str, analysis_id: str):
        analysis = services.analysis_repository.get_analysis(analysis_id)
        if analysis is None or analysis.project_id != project_id:
            raise HTTPException(status_code=404, detail="AnalysisRecord not found")
        return services.analysis_repository.list_artifacts(analysis_id)

    @app.get("/api/projects/{project_id}/analysis-artifacts/{artifact_id}/content")
    def get_analysis_artifact_content(project_id: str, artifact_id: str):
        artifact = services.analysis_repository.get_artifact(artifact_id)
        if artifact is None or artifact.project_id != project_id:
            raise HTTPException(status_code=404, detail="Analysis Artifact not found")
        root = services.workspace.project_root(project_id).resolve(strict=True)
        try:
            path = (root / artifact.relative_path).resolve(strict=True)
            path.relative_to(root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Analysis Artifact content not found") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Analysis Artifact content not found")
        return FileResponse(path, media_type=artifact.media_type)

    @app.post(
        "/api/projects/{project_id}/analyses/{analysis_id}/verifications",
        response_model=VerificationReport,
        status_code=status.HTTP_201_CREATED,
    )
    def verify_analysis(project_id: str, analysis_id: str):
        analysis = services.analysis_repository.get_analysis(analysis_id)
        if analysis is None or analysis.project_id != project_id:
            raise HTTPException(status_code=404, detail="AnalysisRecord not found")
        try:
            return services.analysis_runtime.verify(analysis_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/analyses/{analysis_id}/verifications",
        response_model=List[VerificationReport],
    )
    def list_analysis_verifications(project_id: str, analysis_id: str):
        analysis = services.analysis_repository.get_analysis(analysis_id)
        if analysis is None or analysis.project_id != project_id:
            raise HTTPException(status_code=404, detail="AnalysisRecord not found")
        return services.analysis_repository.list_verifications(analysis_id)

    @app.post(
        "/api/projects/{project_id}/analyses/{analysis_id}/scientific-reviews",
        response_model=ScientificReviewReport,
        status_code=status.HTTP_201_CREATED,
    )
    def create_scientific_review(project_id: str, analysis_id: str,
                                 payload: ScientificReviewRequest):
        analysis = services.analysis_repository.get_analysis(analysis_id)
        if analysis is None or analysis.project_id != project_id:
            raise HTTPException(status_code=404, detail="AnalysisRecord not found")
        try:
            report, _ = services.analysis_runtime.review(
                analysis_id, payload.verification_id,
            )
            return report
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/analyses/{analysis_id}/scientific-reviews",
        response_model=List[ScientificReviewReport],
    )
    def list_scientific_reviews(project_id: str, analysis_id: str):
        analysis = services.analysis_repository.get_analysis(analysis_id)
        if analysis is None or analysis.project_id != project_id:
            raise HTTPException(status_code=404, detail="AnalysisRecord not found")
        return services.analysis_repository.list_reviews(analysis_id)

    @app.get(
        "/api/projects/{project_id}/analysis-artifacts/{artifact_id}/verification",
        response_model=AnalysisArtifactVerification,
    )
    def verify_analysis_artifact(project_id: str, artifact_id: str):
        try:
            result = services.analysis_runtime.verify_artifact(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Analysis Artifact not found") from exc
        if result.artifact.project_id != project_id:
            raise HTTPException(status_code=404, detail="Analysis Artifact not found")
        return result

    @app.get(
        "/api/projects/{project_id}/analysis-agent-runs",
        response_model=List[AnalysisAgentRun],
    )
    def list_analysis_agent_runs(project_id: str):
        require_project(project_id)
        return services.analysis_repository.list_agent_runs(project_id)

    @app.post(
        "/api/projects/{project_id}/analyses/{analysis_id}/research-reviews",
        response_model=ResearchReviewResult,
        status_code=status.HTTP_201_CREATED,
    )
    def create_research_review(project_id: str, analysis_id: str,
                               payload: CreateResearchReviewRequest):
        require_project(project_id)
        try:
            result = services.research_review.run(
                project_id, analysis_id,
                scientific_review_id=payload.scientific_review_id,
                claim_drafts=payload.claims,
            )
            services.events.append(
                project_id, "research_review.completed",
                "Independent specialist, Meta, and Policy Guard review recorded",
                payload={
                    "review_run_id": result.record.review_run_id,
                    "analysis_id": analysis_id,
                    "final_decision": result.policy_decision.final_decision.value,
                    "reviewer_overridden": result.policy_decision.reviewer_decision_overridden,
                    "disagreement_count": len(result.meta_review.disagreements),
                },
            )
            return result
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/research-reviews",
        response_model=List[ResearchReviewRecord],
    )
    def list_research_reviews(project_id: str):
        require_project(project_id)
        return services.research_review_repository.list_records(project_id)

    @app.get(
        "/api/projects/{project_id}/research-reviews/{review_run_id}",
        response_model=ResearchReviewResult,
    )
    def get_research_review(project_id: str, review_run_id: str):
        try:
            result = services.research_review.get(review_run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ResearchReview not found") from exc
        if result.record.project_id != project_id:
            raise HTTPException(status_code=404, detail="ResearchReview not found")
        return result

    @app.get(
        "/api/projects/{project_id}/analyses/{analysis_id}/evidence-claims",
        response_model=List[EvidenceClaim],
    )
    def list_evidence_claims(project_id: str, analysis_id: str):
        analysis = services.analysis_repository.get_analysis(analysis_id)
        if analysis is None or analysis.project_id != project_id:
            raise HTTPException(status_code=404, detail="AnalysisRecord not found")
        return services.research_review_repository.list_claims(analysis_id)

    @app.post(
        "/api/projects/{project_id}/research-reviews/{review_run_id}/apply",
        response_model=ResearchReviewTransition,
        status_code=status.HTTP_201_CREATED,
    )
    def apply_research_review(project_id: str, review_run_id: str,
                              payload: ApplyResearchReviewRequest):
        record = services.research_review_repository.get_record(review_run_id)
        if record is None or record.project_id != project_id:
            raise HTTPException(status_code=404, detail="ResearchReview not found")
        try:
            return services.research_review.apply_feedback(
                review_run_id, payload.expected_state_revision,
            )
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/research-reviews/{review_run_id}/transition",
        response_model=Optional[ResearchReviewTransition],
    )
    def get_research_review_transition(project_id: str, review_run_id: str):
        record = services.research_review_repository.get_record(review_run_id)
        if record is None or record.project_id != project_id:
            raise HTTPException(status_code=404, detail="ResearchReview not found")
        return services.research_review_repository.get_transition(review_run_id)

    @app.get(
        "/api/projects/{project_id}/research-review-agent-runs",
        response_model=List[ResearchReviewAgentRun],
    )
    def list_research_review_agent_runs(project_id: str):
        require_project(project_id)
        return services.research_review_repository.list_agent_runs(project_id)

    @app.post(
        "/api/projects/{project_id}/papers",
        response_model=PaperWritingResult,
        status_code=status.HTTP_201_CREATED,
    )
    def create_paper(project_id: str, payload: CreatePaperRequest):
        require_project(project_id)
        try:
            return services.paper_writing.write(
                project_id, payload.research_review_run_id, payload.config,
                payload.expected_state_revision,
            )
        except LLMError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/projects/{project_id}/papers",
        response_model=List[PaperRecord],
    )
    def list_papers(project_id: str):
        require_project(project_id)
        return services.paper_repository.list_records(project_id)

    @app.get(
        "/api/projects/{project_id}/papers/{paper_id}",
        response_model=PaperWritingResult,
    )
    def get_paper(project_id: str, paper_id: str):
        try:
            result = services.paper_writing.get(paper_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Paper not found") from exc
        if result.record.project_id != project_id:
            raise HTTPException(status_code=404, detail="Paper not found")
        return result

    @app.get(
        "/api/projects/{project_id}/papers/{paper_id}/artifacts",
        response_model=List[PaperArtifact],
    )
    def list_paper_artifacts(project_id: str, paper_id: str):
        record = services.paper_repository.get_record(paper_id)
        if record is None or record.project_id != project_id:
            raise HTTPException(status_code=404, detail="Paper not found")
        return services.paper_repository.list_artifacts(paper_id)

    @app.get("/api/projects/{project_id}/papers/{paper_id}/artifacts/{artifact_id}/content")
    def get_paper_artifact_content(project_id: str, paper_id: str, artifact_id: str,
                                   download: bool = False):
        record = services.paper_repository.get_record(paper_id)
        artifacts = services.paper_repository.list_artifacts(paper_id) if record else []
        artifact = next((item for item in artifacts if item.paper_artifact_id == artifact_id), None)
        if record is None or record.project_id != project_id or artifact is None:
            raise HTTPException(status_code=404, detail="Paper Artifact not found")
        project_root = services.workspace.project_root(project_id).resolve(strict=True)
        path = (project_root / artifact.relative_path).resolve(strict=True)
        try:
            path.relative_to(project_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Paper Artifact escaped project") from exc
        return FileResponse(
            path, media_type=artifact.media_type,
            filename=path.name if download else None,
        )

    @app.get(
        "/api/projects/{project_id}/paper-agent-runs",
        response_model=List[PaperAgentRun],
    )
    def list_paper_agent_runs(project_id: str):
        require_project(project_id)
        return services.paper_repository.list_agent_runs(project_id)

    return app

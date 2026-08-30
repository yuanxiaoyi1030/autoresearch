# Purpose: Defines generic hypothesis, experiment-plan, review, provenance, budget, and approval contracts.
from __future__ import annotations

from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, model_validator

from research_runtime.literature import DefectSeverity
from research_runtime.state import utc_now
from research_runtime.understanding import (
    ModificationCategory, ModificationClass, ReuseStrategy,
)


def identifier(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


def canonical_hash(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PlanningArtifactKind(str, Enum):
    HYPOTHESIS = "hypothesis"
    EXPERIMENT_PLAN = "experiment_plan"


class PlanningAgentRole(str, Enum):
    RESEARCH_DESIGN_LEAD = "research_design_lead"
    CRITICAL_REVIEWER = "critical_reviewer"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class FeedbackSource(str, Enum):
    USER = "user"
    CRITICAL_REVIEWER = "critical_reviewer"


class VariableRole(str, Enum):
    INDEPENDENT = "independent"
    DEPENDENT = "dependent"
    CONTROL = "control"
    COVARIATE = "covariate"
    NUISANCE = "nuisance"
    GROUPING = "grouping"


class MetricDirection(str, Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"
    TARGET = "target"
    DESCRIPTIVE = "descriptive"


class CodeReuseAction(str, Enum):
    ADAPT = "adapt"
    REFACTOR = "refactor"
    REIMPLEMENT = "reimplementation"
    RETAIN_REFERENCE_ONLY = "retain_reference_only"


class PlanningDefectCategory(str, Enum):
    NOVELTY = "novelty"
    FALSIFIABILITY = "falsifiability"
    TOPIC_ALIGNMENT = "topic_alignment"
    BASELINE = "baseline"
    ABLATION = "ablation"
    CONTROL_VARIABLE = "control_variable"
    STATISTICAL_DESIGN = "statistical_design"
    EXECUTABILITY = "executability"
    RESOURCE_BUDGET = "resource_budget"
    REPRODUCIBILITY = "reproducibility"
    CONFOUNDING = "confounding"
    ALTERNATIVE_EXPLANATION = "alternative_explanation"
    LEGACY_REUSE = "legacy_reuse"
    PROVENANCE = "provenance"


class ProvenanceLink(BaseModel):
    record_type: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    relationship: str = Field(min_length=1)


class RevisionFeedback(BaseModel):
    source: FeedbackSource
    reference_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class HypothesisCandidate(BaseModel):
    candidate_id: str = Field(default_factory=lambda: identifier("hypcand_"))
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    novelty_claim: str = Field(min_length=1)
    falsification_criterion: str = Field(min_length=1)
    null_prediction: str = Field(min_length=1)
    alternative_prediction: str = Field(min_length=1)
    anticipated_variables: List[str] = Field(min_length=2)
    supporting_evidence_ids: List[str] = Field(min_length=1)
    feasibility_summary: str = Field(min_length=1)
    known_risks: List[str] = Field(default_factory=list)


class HypothesisDraft(BaseModel):
    research_question: str = Field(min_length=1)
    candidates: List[HypothesisCandidate] = Field(min_length=2)
    recommended_candidate_id: str
    comparison: str = Field(min_length=1)

    @model_validator(mode="after")
    def recommendation_exists(self) -> "HypothesisDraft":
        if self.recommended_candidate_id not in {item.candidate_id for item in self.candidates}:
            raise ValueError("recommended hypothesis candidate is not present")
        return self


class HypothesisRevision(BaseModel):
    hypothesis_revision_id: str = Field(default_factory=lambda: identifier("hyprev_"))
    project_id: str
    context_id: str
    literature_matrix_id: str
    revision: int = Field(default=0, ge=0)
    parent_revision_id: Optional[str] = None
    research_question: Optional[str] = Field(default=None, min_length=1)
    candidates: List[HypothesisCandidate] = Field(min_length=2)
    recommended_candidate_id: str
    comparison: str = Field(min_length=1)
    feedback: List[RevisionFeedback] = Field(default_factory=list)
    provenance: List[ProvenanceLink] = Field(min_length=2)
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_revision_and_hash(self) -> "HypothesisRevision":
        if self.recommended_candidate_id not in {item.candidate_id for item in self.candidates}:
            raise ValueError("recommended hypothesis candidate is not present")
        if self.revision == 0 and self.parent_revision_id is not None:
            raise ValueError("initial hypothesis revision cannot have a parent")
        if self.revision > 0 and (not self.parent_revision_id or not self.feedback):
            raise ValueError("hypothesis revision requires parent and feedback")
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("hypothesis content_hash does not match revision content")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        if self.research_question is None:
            payload.pop("research_question")
        return canonical_hash(payload)


class VariableSpec(BaseModel):
    name: str = Field(min_length=1)
    role: VariableRole
    data_type: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    value_domain: Dict[str, Any] = Field(default_factory=dict)
    measurement_procedure: str = Field(min_length=1)


class ConditionSpec(BaseModel):
    condition_id: str = Field(default_factory=lambda: identifier("condition_"))
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    variable_assignments: Dict[str, Any] = Field(default_factory=dict)
    is_baseline: bool = False
    is_ablation: bool = False


class StudySpec(BaseModel):
    study_id: str = Field(default_factory=lambda: identifier("study_"))
    name: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    design_type: str = Field(min_length=1)
    experimental_unit: str = Field(min_length=1)
    population_or_dataset: str = Field(min_length=1)
    inclusion_criteria: List[str] = Field(default_factory=list)
    exclusion_criteria: List[str] = Field(default_factory=list)
    variables: List[VariableSpec] = Field(min_length=2)
    conditions: List[ConditionSpec] = Field(min_length=2)
    baseline_condition_ids: List[str] = Field(min_length=1)
    ablation_condition_ids: List[str] = Field(default_factory=list)
    ablation_rationale: str = Field(min_length=1)
    control_strategy: List[str] = Field(min_length=1)
    randomization_strategy: str = Field(min_length=1)
    stopping_rule: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_generic_design(self) -> "StudySpec":
        condition_ids = {item.condition_id for item in self.conditions}
        if len(condition_ids) != len(self.conditions):
            raise ValueError("condition ids must be unique")
        if set(self.baseline_condition_ids) - condition_ids:
            raise ValueError("baseline references unknown condition")
        if set(self.ablation_condition_ids) - condition_ids:
            raise ValueError("ablation references unknown condition")
        if not any(item.role is VariableRole.DEPENDENT for item in self.variables):
            raise ValueError("StudySpec requires at least one dependent variable")
        if not any(item.role in {VariableRole.INDEPENDENT, VariableRole.GROUPING} for item in self.variables):
            raise ValueError("StudySpec requires an independent or grouping variable")
        return self


class ResourceRequest(BaseModel):
    cpu_cores: int = Field(default=1, ge=1)
    memory_gb: float = Field(default=1.0, gt=0)
    gpu_count: int = Field(default=0, ge=0)
    estimated_minutes_per_replicate: float = Field(gt=0)
    estimated_cost_usd_per_replicate: float = Field(default=0.0, ge=0)


class RunSpec(BaseModel):
    run_spec_id: str = Field(default_factory=lambda: identifier("runspec_"))
    condition_id: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    seeds: List[int] = Field(min_length=1)
    replicates_per_seed: int = Field(default=1, ge=1)
    resource_request: ResourceRequest
    required_artifacts: List[str] = Field(min_length=1)

    @property
    def expected_runs(self) -> int:
        return len(self.seeds) * self.replicates_per_seed


class MetricSpec(BaseModel):
    metric_id: str = Field(default_factory=lambda: identifier("metric_"))
    name: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    direction: MetricDirection
    aggregation: str = Field(min_length=1)
    unit: Optional[str] = None
    primary: bool = False
    uncertainty_report: str = Field(min_length=1)


class AnalysisSpec(BaseModel):
    analysis_id: str = Field(default_factory=lambda: identifier("analysis_"))
    estimands: List[str] = Field(min_length=1)
    statistical_methods: List[str] = Field(min_length=1)
    comparisons: List[str] = Field(min_length=1)
    uncertainty_methods: List[str] = Field(min_length=1)
    significance_level: Optional[float] = Field(default=None, gt=0, lt=1)
    multiplicity_correction: str = Field(min_length=1)
    missing_data_strategy: str = Field(min_length=1)
    outlier_strategy: str = Field(min_length=1)
    assumption_checks: List[str] = Field(min_length=1)
    planned_figures: List[str] = Field(min_length=1)
    alternative_explanations: List[str] = Field(min_length=1)
    confounders: List[str] = Field(min_length=1)


class ReproducibilitySpec(BaseModel):
    environment_requirements: List[str] = Field(min_length=1)
    dependency_lock_strategy: str = Field(min_length=1)
    data_version_strategy: str = Field(min_length=1)
    code_version_strategy: str = Field(min_length=1)
    seed_policy: str = Field(min_length=1)
    artifact_provenance_strategy: str = Field(min_length=1)


class ExperimentBudget(BaseModel):
    max_total_runs: int = Field(ge=1)
    max_total_compute_minutes: float = Field(gt=0)
    max_gpu_hours: float = Field(default=0.0, ge=0)
    max_cost_usd: Optional[float] = Field(default=None, gt=0)


class PlannedModification(BaseModel):
    classification: ModificationClass
    category: ModificationCategory
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_classification(self) -> "PlannedModification":
        non_semantic = {
            ModificationCategory.PATH, ModificationCategory.LOGGING,
            ModificationCategory.ARTIFACT_OUTPUT, ModificationCategory.CONFIG_LOADING,
            ModificationCategory.CHECKPOINT, ModificationCategory.RECOVERY,
            ModificationCategory.SECURITY_BOUNDARY, ModificationCategory.FORMATTING,
            ModificationCategory.RUNNER_STRUCTURE, ModificationCategory.NOTEBOOK_STATE,
        }
        expected = ModificationClass.NON_SEMANTIC if self.category in non_semantic else ModificationClass.SEMANTIC
        if self.classification is not expected:
            raise ValueError(f"{self.category.value} must be classified as {expected.value}")
        return self


class CodeReuseDecision(BaseModel):
    source_relative_path: str = Field(min_length=1)
    action: CodeReuseAction
    rationale: str = Field(min_length=1)
    preserved_elements: List[str] = Field(default_factory=list)
    modifications: List[PlannedModification] = Field(default_factory=list)


class BModePlanBinding(BaseModel):
    assessment_id: str
    assessment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    import_id: str
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    recommended_strategy: ReuseStrategy
    preserved_experiment_designs: List[str] = Field(default_factory=list)
    code_reuse_decisions: List[CodeReuseDecision] = Field(default_factory=list)
    unverified_observations: List[str] = Field(default_factory=list)
    supplemental_experiments: List[str] = Field(default_factory=list)
    supplemental_figures: List[str] = Field(default_factory=list)

    @property
    def has_semantic_modifications(self) -> bool:
        return any(
            modification.classification is ModificationClass.SEMANTIC
            for decision in self.code_reuse_decisions for modification in decision.modifications
        )


class ExperimentPlanDraft(BaseModel):
    study: StudySpec
    runs: List[RunSpec] = Field(min_length=1)
    metrics: List[MetricSpec] = Field(min_length=1)
    analysis: AnalysisSpec
    reproducibility: ReproducibilitySpec
    budget: ExperimentBudget
    b_mode_binding: Optional[BModePlanBinding] = None

    @model_validator(mode="after")
    def validate_plan_matrix_and_budget(self) -> "ExperimentPlanDraft":
        condition_ids = {item.condition_id for item in self.study.conditions}
        if set(item.condition_id for item in self.runs) - condition_ids:
            raise ValueError("RunSpec references an unknown StudySpec condition")
        if set(item.condition_id for item in self.runs) != condition_ids:
            raise ValueError("every StudySpec condition requires at least one RunSpec")
        if not any(item.primary for item in self.metrics):
            raise ValueError("Experiment Plan requires at least one primary metric")
        total_runs = sum(item.expected_runs for item in self.runs)
        total_minutes = sum(
            item.expected_runs * item.resource_request.estimated_minutes_per_replicate
            for item in self.runs
        )
        gpu_hours = sum(
            item.expected_runs * item.resource_request.estimated_minutes_per_replicate
            * item.resource_request.gpu_count / 60.0 for item in self.runs
        )
        total_cost = sum(
            item.expected_runs * item.resource_request.estimated_cost_usd_per_replicate
            for item in self.runs
        )
        if total_runs > self.budget.max_total_runs:
            raise ValueError("planned runs exceed max_total_runs")
        if total_minutes > self.budget.max_total_compute_minutes:
            raise ValueError("planned compute exceeds max_total_compute_minutes")
        if gpu_hours > self.budget.max_gpu_hours:
            raise ValueError("planned GPU usage exceeds max_gpu_hours")
        if self.budget.max_cost_usd is not None and total_cost > self.budget.max_cost_usd:
            raise ValueError("planned cost exceeds max_cost_usd")
        return self

    @property
    def expected_total_runs(self) -> int:
        return sum(item.expected_runs for item in self.runs)


class TopicExperimentPlanDraft(ExperimentPlanDraft):
    """Provider response contract for A-mode plans."""
    b_mode_binding: None = None


class ExistingProjectExperimentPlanDraft(ExperimentPlanDraft):
    """Provider response contract for B-mode plans."""
    b_mode_binding: BModePlanBinding


class ExperimentPlanRevision(BaseModel):
    plan_revision_id: str = Field(default_factory=lambda: identifier("planrev_"))
    project_id: str
    context_id: str
    literature_matrix_id: str
    hypothesis_revision_id: str
    hypothesis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_candidate_id: str
    hypothesis_approval_id: str
    revision: int = Field(default=0, ge=0)
    parent_revision_id: Optional[str] = None
    plan: ExperimentPlanDraft
    feedback: List[RevisionFeedback] = Field(default_factory=list)
    provenance: List[ProvenanceLink] = Field(min_length=3)
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_revision_and_hash(self) -> "ExperimentPlanRevision":
        if self.revision == 0 and self.parent_revision_id is not None:
            raise ValueError("initial plan revision cannot have a parent")
        if self.revision > 0 and (not self.parent_revision_id or not self.feedback):
            raise ValueError("plan revision requires parent and feedback")
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("plan content_hash does not match revision content")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        return canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))


class PlanningDefect(BaseModel):
    defect_id: str = Field(default_factory=lambda: identifier("plandefect_"))
    category: PlanningDefectCategory
    severity: DefectSeverity
    summary: str = Field(min_length=1)
    suggested_action: str = Field(min_length=1)


class PlanningReviewDraft(BaseModel):
    defects: List[PlanningDefect] = Field(default_factory=list)
    reviewer_summary: str = Field(min_length=1)


class PlanningReviewReport(BaseModel):
    report_id: str = Field(default_factory=lambda: identifier("planreview_"))
    project_id: str
    context_id: str
    artifact_kind: PlanningArtifactKind
    artifact_id: str
    artifact_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(ge=0)
    defects: List[PlanningDefect] = Field(default_factory=list)
    reviewer_summary: str = Field(min_length=1)
    independent_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def has_blocking_defects(self) -> bool:
        return any(item.severity in {DefectSeverity.MAJOR, DefectSeverity.BLOCKING} for item in self.defects)


class PlanningApproval(BaseModel):
    approval_id: str = Field(default_factory=lambda: identifier("approval_"))
    project_id: str
    artifact_kind: PlanningArtifactKind
    artifact_id: str
    artifact_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: ApprovalDecision
    selected_candidate_id: Optional[str] = None
    feedback: str = Field(min_length=1)
    actor_type: str = Field(default="user", pattern=r"^user$")
    actor_id: str = Field(default="local_user", min_length=1)
    created_at: datetime = Field(default_factory=utc_now)


class PlanningAgentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: identifier("planningrun_"))
    project_id: str
    context_id: str
    role: PlanningAgentRole
    operation: str
    artifact_kind: PlanningArtifactKind
    artifact_id: str
    revision: int = Field(ge=0)
    input_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class HypothesisGenerationResult(BaseModel):
    revision: HypothesisRevision
    review: PlanningReviewReport
    agent_runs: List[PlanningAgentRun]


class PlanGenerationResult(BaseModel):
    revision: ExperimentPlanRevision
    review: PlanningReviewReport
    agent_runs: List[PlanningAgentRun]


class FormalExperimentGate(BaseModel):
    allowed: bool
    plan_revision_id: str
    plan_content_hash: str
    approval_id: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)

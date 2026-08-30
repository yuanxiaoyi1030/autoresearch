# Purpose: Defines the deterministic v0.2 workflow graph without domain-specific Study assumptions.
from enum import Enum
from typing import Dict, Tuple

from research_runtime.state import ProjectStatus, ResearchStage


class WorkflowAction(str, Enum):
    INITIALIZATION_COMPLETED = "initialization_completed"
    PROJECT_UNDERSTANDING_COMPLETED = "project_understanding_completed"
    LITERATURE_COMPLETED = "literature_completed"
    HYPOTHESIS_READY = "hypothesis_ready"
    HYPOTHESIS_APPROVED = "hypothesis_approved"
    HYPOTHESIS_REJECTED = "hypothesis_rejected"
    PLAN_READY = "plan_ready"
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    IMPLEMENTATION_READY = "implementation_ready"
    IMPLEMENTATION_REQUIRES_PLAN_REVISION = "implementation_requires_plan_revision"
    EXPERIMENT_COMPLETED = "experiment_completed"
    ANALYSIS_CONTINUE = "analysis_continue"
    ANALYSIS_READY_FOR_REVIEW = "analysis_ready_for_review"
    REVIEW_RETURN_TO_EXPERIMENT = "review_return_to_experiment"
    REVIEW_REVISE_PLAN = "review_revise_plan"
    REVIEW_APPROVED = "review_approved"
    REPORT_PLAN_READY = "report_plan_ready"
    REPORT_DRAFT_READY = "report_draft_ready"
    REPORT_REVISION_REQUIRED = "report_revision_required"
    REPORT_EVIDENCE_REVIEW = "report_evidence_review"
    REPORT_COMPLETED = "report_completed"


Transition = Tuple[ResearchStage, ProjectStatus]

TRANSITIONS: Dict[Tuple[ResearchStage, WorkflowAction], Transition] = {
    (ResearchStage.INITIALIZING, WorkflowAction.INITIALIZATION_COMPLETED):
        (ResearchStage.PROJECT_UNDERSTANDING, ProjectStatus.ACTIVE),
    (ResearchStage.PROJECT_UNDERSTANDING, WorkflowAction.PROJECT_UNDERSTANDING_COMPLETED):
        (ResearchStage.LITERATURE, ProjectStatus.ACTIVE),
    (ResearchStage.LITERATURE, WorkflowAction.LITERATURE_COMPLETED):
        (ResearchStage.HYPOTHESIS, ProjectStatus.ACTIVE),
    (ResearchStage.HYPOTHESIS, WorkflowAction.HYPOTHESIS_READY):
        (ResearchStage.WAIT_HYPOTHESIS_APPROVAL, ProjectStatus.WAITING_USER),
    (ResearchStage.WAIT_HYPOTHESIS_APPROVAL, WorkflowAction.HYPOTHESIS_APPROVED):
        (ResearchStage.EXPERIMENT_PLANNING, ProjectStatus.ACTIVE),
    (ResearchStage.WAIT_HYPOTHESIS_APPROVAL, WorkflowAction.HYPOTHESIS_REJECTED):
        (ResearchStage.HYPOTHESIS, ProjectStatus.ACTIVE),
    (ResearchStage.EXPERIMENT_PLANNING, WorkflowAction.PLAN_READY):
        (ResearchStage.WAIT_PLAN_APPROVAL, ProjectStatus.WAITING_USER),
    (ResearchStage.WAIT_PLAN_APPROVAL, WorkflowAction.PLAN_APPROVED):
        (ResearchStage.EXPERIMENT_IMPLEMENTATION, ProjectStatus.ACTIVE),
    (ResearchStage.WAIT_PLAN_APPROVAL, WorkflowAction.PLAN_REJECTED):
        (ResearchStage.EXPERIMENT_PLANNING, ProjectStatus.ACTIVE),
    (ResearchStage.EXPERIMENT_IMPLEMENTATION, WorkflowAction.IMPLEMENTATION_READY):
        (ResearchStage.EXPERIMENT, ProjectStatus.ACTIVE),
    (ResearchStage.EXPERIMENT_IMPLEMENTATION, WorkflowAction.IMPLEMENTATION_REQUIRES_PLAN_REVISION):
        (ResearchStage.EXPERIMENT_PLANNING, ProjectStatus.ACTIVE),
    (ResearchStage.EXPERIMENT, WorkflowAction.EXPERIMENT_COMPLETED):
        (ResearchStage.ANALYSIS, ProjectStatus.ACTIVE),
    (ResearchStage.ANALYSIS, WorkflowAction.ANALYSIS_CONTINUE):
        (ResearchStage.EXPERIMENT, ProjectStatus.ACTIVE),
    (ResearchStage.ANALYSIS, WorkflowAction.ANALYSIS_READY_FOR_REVIEW):
        (ResearchStage.RESEARCH_REVIEW, ProjectStatus.ACTIVE),
    (ResearchStage.RESEARCH_REVIEW, WorkflowAction.REVIEW_RETURN_TO_EXPERIMENT):
        (ResearchStage.EXPERIMENT, ProjectStatus.ACTIVE),
    (ResearchStage.RESEARCH_REVIEW, WorkflowAction.REVIEW_REVISE_PLAN):
        (ResearchStage.EXPERIMENT_PLANNING, ProjectStatus.ACTIVE),
    (ResearchStage.RESEARCH_REVIEW, WorkflowAction.REVIEW_APPROVED):
        (ResearchStage.REPORT_PLANNING, ProjectStatus.ACTIVE),
    (ResearchStage.REPORT_PLANNING, WorkflowAction.REPORT_PLAN_READY):
        (ResearchStage.REPORT_WRITING, ProjectStatus.ACTIVE),
    (ResearchStage.REPORT_WRITING, WorkflowAction.REPORT_DRAFT_READY):
        (ResearchStage.REPORT_REVIEW, ProjectStatus.ACTIVE),
    (ResearchStage.REPORT_REVIEW, WorkflowAction.REPORT_REVISION_REQUIRED):
        (ResearchStage.REPORT_WRITING, ProjectStatus.ACTIVE),
    (ResearchStage.REPORT_REVIEW, WorkflowAction.REPORT_EVIDENCE_REVIEW):
        (ResearchStage.RESEARCH_REVIEW, ProjectStatus.ACTIVE),
    (ResearchStage.REPORT_REVIEW, WorkflowAction.REPORT_COMPLETED):
        (ResearchStage.COMPLETED, ProjectStatus.COMPLETED),
}


class InvalidTransition(ValueError):
    pass


def resolve_transition(stage: ResearchStage, action: WorkflowAction) -> Transition:
    try:
        return TRANSITIONS[(stage, action)]
    except KeyError as exc:
        raise InvalidTransition(f"action {action.value} is not allowed from {stage.value}") from exc


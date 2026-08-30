# Purpose: Applies deterministic v0.2 transitions, revision guards, pause/resume, and terminal states.
from typing import Optional

from research_runtime.state import ProjectStatus, ResearchOutcome, ResearchStage, ResearchState, StageAttempt

from .transitions import InvalidTransition, WorkflowAction, resolve_transition


WAITING_STAGES = {ResearchStage.WAIT_HYPOTHESIS_APPROVAL, ResearchStage.WAIT_PLAN_APPROVAL}
TERMINAL_STATUSES = {ProjectStatus.COMPLETED, ProjectStatus.FAILED, ProjectStatus.CANCELLED}


class WorkflowManager:
    def __init__(self, projects, events=None) -> None:
        self.projects = projects
        self.events = events

    def transition(self, project_id: str, action: WorkflowAction,
                   expected_revision: Optional[int] = None,
                   outcome: Optional[ResearchOutcome] = None) -> ResearchState:
        state = self._state(project_id)
        self._require_revision(state, expected_revision)
        if state.status is ProjectStatus.PAUSED:
            raise InvalidTransition("paused projects must be resumed before transitioning")
        if state.status in TERMINAL_STATUSES:
            raise InvalidTransition(f"project status {state.status.value} is terminal")
        if outcome is not None and action not in {
            WorkflowAction.EXPERIMENT_COMPLETED, WorkflowAction.REVIEW_APPROVED,
        }:
            raise InvalidTransition(
                "a research outcome can only be recorded after experiment or independent review"
            )
        target_stage, target_status = resolve_transition(state.stage, action)
        self._finish_current_attempt(state, ProjectStatus.COMPLETED)
        attempt = self._new_attempt(project_id, target_stage)
        updated = self.projects.update_state(state.model_copy(update={
            "stage": target_stage,
            "status": target_status,
            "current_attempt_id": attempt.attempt_id,
            "outcome": outcome if outcome is not None else state.outcome,
        }), expected_revision=state.revision)
        self._emit(project_id, "workflow.transition", f"{state.stage.value} -> {target_stage.value}", {
            "action": action.value,
            "from_stage": state.stage.value,
            "to_stage": target_stage.value,
            "revision": updated.revision,
            "outcome": updated.outcome.value if updated.outcome else None,
        })
        return updated

    def pause(self, project_id: str, reason: str = "paused by user",
              expected_revision: Optional[int] = None) -> ResearchState:
        state = self._state(project_id)
        self._require_revision(state, expected_revision)
        if state.status in TERMINAL_STATUSES or state.status is ProjectStatus.PAUSED:
            raise InvalidTransition(f"cannot pause project with status {state.status.value}")
        updated = self.projects.update_state(
            state.model_copy(update={"status": ProjectStatus.PAUSED}), expected_revision=state.revision
        )
        self._emit(project_id, "workflow.paused", reason, {"stage": state.stage.value})
        return updated

    def resume(self, project_id: str, expected_revision: Optional[int] = None) -> ResearchState:
        state = self._state(project_id)
        self._require_revision(state, expected_revision)
        if state.status is not ProjectStatus.PAUSED:
            raise InvalidTransition("only paused projects can be resumed")
        status = ProjectStatus.WAITING_USER if state.stage in WAITING_STAGES else ProjectStatus.ACTIVE
        updated = self.projects.update_state(
            state.model_copy(update={"status": status}), expected_revision=state.revision
        )
        self._emit(project_id, "workflow.resumed", "Project resumed", {"stage": state.stage.value})
        return updated

    def fail(self, project_id: str, reason: str,
             expected_revision: Optional[int] = None) -> ResearchState:
        return self._terminate(project_id, ProjectStatus.FAILED, reason, expected_revision)

    def cancel(self, project_id: str, reason: str = "cancelled by user",
               expected_revision: Optional[int] = None) -> ResearchState:
        return self._terminate(project_id, ProjectStatus.CANCELLED, reason, expected_revision)

    def ensure_initial_attempt(self, project_id: str) -> StageAttempt:
        attempts = self.projects.list_attempts(project_id)
        if attempts:
            return attempts[-1]
        state = self.projects.get_state(project_id)
        if state is None:
            raise KeyError(project_id)
        attempt = self._new_attempt(project_id, state.stage)
        self.projects.set_current_attempt(project_id, attempt.attempt_id, state.revision)
        return attempt

    def _terminate(self, project_id: str, status: ProjectStatus, reason: str,
                   expected_revision: Optional[int]) -> ResearchState:
        state = self._state(project_id)
        self._require_revision(state, expected_revision)
        if state.status in TERMINAL_STATUSES:
            raise InvalidTransition(f"project status {state.status.value} is terminal")
        self._finish_current_attempt(state, status, reason)
        updated = self.projects.update_state(
            state.model_copy(update={"status": status}), expected_revision=state.revision
        )
        self._emit(project_id, f"workflow.{status.value}", reason, {"stage": state.stage.value})
        return updated

    def _new_attempt(self, project_id: str, stage: ResearchStage) -> StageAttempt:
        attempt = StageAttempt(
            project_id=project_id,
            stage=stage,
            attempt_number=self.projects.next_attempt_number(project_id, stage),
        )
        self.projects.add_attempt(attempt)
        return attempt

    def _finish_current_attempt(self, state: ResearchState, status: ProjectStatus,
                                error: Optional[str] = None) -> None:
        if state.current_attempt_id:
            self.projects.finish_attempt(state.current_attempt_id, status, error)

    def _state(self, project_id: str) -> ResearchState:
        state = self.projects.get_state(project_id)
        if state is None:
            raise KeyError(project_id)
        if not state.current_attempt_id:
            self.ensure_initial_attempt(project_id)
            state = self.projects.get_state(project_id)
        return state

    @staticmethod
    def _require_revision(state: ResearchState, expected_revision: Optional[int]) -> None:
        if expected_revision is not None and expected_revision != state.revision:
            raise InvalidTransition(f"stale revision: expected {expected_revision}, current {state.revision}")

    def _emit(self, project_id: str, event_type: str, summary: str, payload: dict) -> None:
        if self.events is not None:
            self.events.append(project_id, event_type, summary, payload=payload)

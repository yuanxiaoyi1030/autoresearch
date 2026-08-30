# Purpose: Verifies persisted workflow revisions and generic durable job/event behavior.
import tempfile
import unittest
from pathlib import Path

from research_runtime.jobs import DurableJobManager, EventJournal, IdempotencyConflict, JobKind
from research_runtime.state import JobStatus, ProjectType, ResearchProject, ResearchStage, ResearchState
from research_runtime.workflow import InvalidTransition, WorkflowAction, WorkflowManager
from storage import Database
from storage.repositories import EventRepository, JobRepository, ProjectRepository


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


class WorkflowJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        database = Database(Path(self.temporary.name) / "test.sqlite3")
        database.initialize()
        self.projects = ProjectRepository(database)
        self.events = EventJournal(EventRepository(database))
        self.jobs = DurableJobManager(JobRepository(database), self.events)
        self.workflow = WorkflowManager(self.projects, self.events)
        self.project = ResearchProject(title="Generic research", project_type=ProjectType.TOPIC_BASED,
                                       topic="Does intervention A change outcome B?")
        self.projects.create(self.project, ResearchState(project_id=self.project.project_id))

    def tearDown(self):
        self.temporary.cleanup()

    def test_workflow_revision_and_pause_guards(self):
        self.workflow.ensure_initial_attempt(self.project.project_id)
        state = self.projects.get_state(self.project.project_id)
        state = self.workflow.transition(self.project.project_id, WorkflowAction.INITIALIZATION_COMPLETED,
                                         expected_revision=state.revision)
        self.assertEqual(state.stage, ResearchStage.PROJECT_UNDERSTANDING)
        with self.assertRaises(InvalidTransition):
            self.workflow.transition(self.project.project_id, WorkflowAction.LITERATURE_COMPLETED,
                                     expected_revision=state.revision)
        paused = self.workflow.pause(self.project.project_id, expected_revision=state.revision)
        resumed = self.workflow.resume(self.project.project_id, expected_revision=paused.revision)
        self.assertEqual(resumed.stage, ResearchStage.PROJECT_UNDERSTANDING)
        self.assertGreaterEqual(len(self.projects.list_state_history(self.project.project_id)), 4)

    def test_generic_jobs_are_idempotent_and_emit_events(self):
        job = self.jobs.create(self.project.project_id, JobKind.RUN_RESEARCH_STAGE,
                               {"stage": "literature"}, "same-key")
        reused = self.jobs.create(self.project.project_id, JobKind.RUN_RESEARCH_STAGE,
                                  {"stage": "literature"}, "same-key")
        self.assertEqual(job.job_id, reused.job_id)
        with self.assertRaises(IdempotencyConflict):
            self.jobs.create(self.project.project_id, JobKind.RUN_RESEARCH_STAGE,
                             {"stage": "hypothesis"}, "same-key")
        claimed = self.jobs.claim_next()
        self.jobs.complete(claimed, {"status": "foundation-only"})
        events = self.events.after(self.project.project_id)
        self.assertEqual([item.event_type for item in events], [
            "job.created", "job.started", "job.completed",
        ])

    def test_running_job_is_recovered_after_worker_restart_and_retried_idempotently(self):
        original = self.jobs.create(
            self.project.project_id,
            JobKind.RUN_RESEARCH_STAGE,
            {"stage": "experiment", "study_id": "study-recovery"},
            "worker-crash-key",
        )
        running = self.jobs.claim_next()
        self.assertEqual(running.job_id, original.job_id)
        self.assertEqual(running.status, JobStatus.RUNNING)
        self.assertEqual(running.attempts, 1)

        notifications = []
        restarted = DurableJobManager(self.jobs.repository, self.events)
        restarted.set_notifier(lambda: notifications.append("wake"))
        recovered = restarted.recover()

        self.assertEqual([job.job_id for job in recovered], [original.job_id])
        self.assertEqual(recovered[0].status, JobStatus.PENDING)
        self.assertEqual(recovered[0].attempts, 1)
        self.assertEqual(recovered[0].error, "service restarted; retry scheduled")
        self.assertEqual(notifications, ["wake"])

        retried = restarted.claim_next()
        self.assertEqual(retried.job_id, original.job_id)
        self.assertEqual(retried.status, JobStatus.RUNNING)
        self.assertEqual(retried.attempts, 2)
        completed = restarted.complete(retried, {"status": "recovered"})
        self.assertEqual(completed.status, JobStatus.COMPLETED)

        idempotent = restarted.create(
            self.project.project_id,
            JobKind.RUN_RESEARCH_STAGE,
            {"stage": "experiment", "study_id": "study-recovery"},
            "worker-crash-key",
        )
        self.assertEqual(idempotent.job_id, original.job_id)
        self.assertEqual(idempotent.status, JobStatus.COMPLETED)
        event_types = [item.event_type for item in self.events.after(self.project.project_id)]
        self.assertEqual(event_types, [
            "job.created", "job.started", "job.recovered", "job.started", "job.completed",
        ])

    def test_primary_stage_path_is_complete_and_domain_neutral(self):
        self.workflow.ensure_initial_attempt(self.project.project_id)
        actions = [
            WorkflowAction.INITIALIZATION_COMPLETED,
            WorkflowAction.PROJECT_UNDERSTANDING_COMPLETED,
            WorkflowAction.LITERATURE_COMPLETED,
            WorkflowAction.HYPOTHESIS_READY,
            WorkflowAction.HYPOTHESIS_APPROVED,
            WorkflowAction.PLAN_READY,
            WorkflowAction.PLAN_APPROVED,
            WorkflowAction.IMPLEMENTATION_READY,
            WorkflowAction.EXPERIMENT_COMPLETED,
            WorkflowAction.ANALYSIS_READY_FOR_REVIEW,
            WorkflowAction.REVIEW_APPROVED,
            WorkflowAction.REPORT_PLAN_READY,
            WorkflowAction.REPORT_DRAFT_READY,
            WorkflowAction.REPORT_COMPLETED,
        ]
        state = self.projects.get_state(self.project.project_id)
        for action in actions:
            state = self.workflow.transition(
                self.project.project_id, action, expected_revision=state.revision,
            )
        self.assertEqual(state.stage, ResearchStage.COMPLETED)


if __name__ == "__main__":
    unittest.main()

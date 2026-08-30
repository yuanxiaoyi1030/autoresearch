# Purpose: Creates the isolated v0.2 SQLite connection, schema, and transaction boundary.
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL);
INSERT INTO schema_meta(version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_meta);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    project_type TEXT NOT NULL,
    source_root TEXT,
    topic TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_states (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    current_attempt_id TEXT,
    latest_import_id TEXT,
    outcome TEXT,
    revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_state_history (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    revision INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(project_id, revision)
);
CREATE TABLE IF NOT EXISTS stage_attempts (
    attempt_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    stage TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS import_sessions (
    import_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    source_root TEXT NOT NULL,
    status TEXT NOT NULL,
    manifest_hash TEXT,
    snapshot_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS imports_project_idx ON import_sessions(project_id, created_at);
CREATE TABLE IF NOT EXISTS import_manifests (
    import_id TEXT PRIMARY KEY REFERENCES import_sessions(import_id),
    manifest_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS durable_jobs (
    job_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_event_cursor INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, kind, idempotency_key)
);
CREATE INDEX IF NOT EXISTS jobs_status_created_idx ON durable_jobs(status, created_at);
CREATE TABLE IF NOT EXISTS activity_events (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    job_id TEXT,
    event_type TEXT NOT NULL,
    stage TEXT,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_project_cursor_idx ON activity_events(project_id, cursor);

CREATE TABLE IF NOT EXISTS research_contexts (
    context_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    import_id TEXT,
    manifest_hash TEXT,
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS contexts_project_created_idx
    ON research_contexts(project_id, created_at, context_id);
CREATE TABLE IF NOT EXISTS legacy_reuse_assessments (
    assessment_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    assessment_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reuse_context_idx ON legacy_reuse_assessments(context_id, created_at);
CREATE TABLE IF NOT EXISTS code_lineage_records (
    lineage_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    import_id TEXT NOT NULL,
    source_relative_path TEXT NOT NULL,
    derived_workspace_path TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lineage_project_created_idx
    ON code_lineage_records(project_id, created_at, lineage_id);
CREATE TABLE IF NOT EXISTS visualization_profiles (
    profile_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS visualization_project_created_idx
    ON visualization_profiles(project_id, created_at, profile_id);
CREATE TABLE IF NOT EXISTS figure_specs (
    figure_spec_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    spec_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS figure_specs_project_created_idx
    ON figure_specs(project_id, created_at, figure_spec_id);

CREATE TABLE IF NOT EXISTS literature_search_attempts (
    attempt_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS literature_attempts_project_created_idx
    ON literature_search_attempts(project_id, created_at, attempt_id);
CREATE TABLE IF NOT EXISTS literature_sources (
    source_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    doi TEXT,
    arxiv_id TEXT,
    access_level TEXT NOT NULL,
    source_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS literature_sources_project_idx
    ON literature_sources(project_id, context_id, source_id);
CREATE TABLE IF NOT EXISTS literature_matrices (
    matrix_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    revision INTEGER NOT NULL,
    parent_matrix_id TEXT,
    matrix_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS literature_matrices_project_revision_idx
    ON literature_matrices(project_id, context_id, revision);
CREATE TABLE IF NOT EXISTS literature_evidence (
    evidence_id TEXT PRIMARY KEY,
    matrix_id TEXT NOT NULL REFERENCES literature_matrices(matrix_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    source_id TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS literature_evidence_matrix_idx
    ON literature_evidence(matrix_id, evidence_id);
CREATE TABLE IF NOT EXISTS research_gaps (
    gap_id TEXT PRIMARY KEY,
    matrix_id TEXT NOT NULL REFERENCES literature_matrices(matrix_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    gap_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_gaps_matrix_idx ON research_gaps(matrix_id, gap_id);
CREATE TABLE IF NOT EXISTS evidence_review_reports (
    report_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    matrix_id TEXT NOT NULL REFERENCES literature_matrices(matrix_id),
    revision INTEGER NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_reviews_project_idx
    ON evidence_review_reports(project_id, context_id, revision, report_id);
CREATE TABLE IF NOT EXISTS literature_agent_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    role TEXT NOT NULL,
    revision INTEGER NOT NULL,
    run_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS literature_agent_runs_project_idx
    ON literature_agent_runs(project_id, context_id, created_at, run_id);

CREATE TABLE IF NOT EXISTS hypothesis_revisions (
    hypothesis_revision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    literature_matrix_id TEXT NOT NULL REFERENCES literature_matrices(matrix_id),
    revision INTEGER NOT NULL,
    parent_revision_id TEXT,
    content_hash TEXT NOT NULL,
    revision_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS hypothesis_revisions_project_idx
    ON hypothesis_revisions(project_id, context_id, revision, created_at);
CREATE TABLE IF NOT EXISTS experiment_plan_revisions (
    plan_revision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    literature_matrix_id TEXT NOT NULL REFERENCES literature_matrices(matrix_id),
    hypothesis_revision_id TEXT NOT NULL REFERENCES hypothesis_revisions(hypothesis_revision_id),
    revision INTEGER NOT NULL,
    parent_revision_id TEXT,
    content_hash TEXT NOT NULL,
    revision_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS experiment_plan_revisions_project_idx
    ON experiment_plan_revisions(project_id, context_id, revision, created_at);
CREATE TABLE IF NOT EXISTS planning_review_reports (
    report_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    artifact_kind TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_content_hash TEXT NOT NULL,
    revision INTEGER NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS planning_reviews_artifact_idx
    ON planning_review_reports(artifact_kind, artifact_id, created_at);
CREATE TABLE IF NOT EXISTS planning_approvals (
    approval_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    artifact_kind TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_content_hash TEXT NOT NULL,
    decision TEXT NOT NULL,
    approval_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(artifact_kind, artifact_id)
);
CREATE INDEX IF NOT EXISTS planning_approvals_project_idx
    ON planning_approvals(project_id, artifact_kind, created_at);
CREATE TABLE IF NOT EXISTS planning_agent_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    role TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    run_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS planning_agent_runs_project_idx
    ON planning_agent_runs(project_id, context_id, created_at, run_id);

CREATE TABLE IF NOT EXISTS implementation_revisions (
    implementation_revision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    plan_revision_id TEXT NOT NULL REFERENCES experiment_plan_revisions(plan_revision_id),
    revision INTEGER NOT NULL,
    parent_revision_id TEXT,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    revision_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS implementation_revisions_project_idx
    ON implementation_revisions(project_id, revision, created_at);
CREATE TABLE IF NOT EXISTS studies (
    study_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    plan_revision_id TEXT NOT NULL REFERENCES experiment_plan_revisions(plan_revision_id),
    implementation_revision_id TEXT NOT NULL REFERENCES implementation_revisions(implementation_revision_id),
    status TEXT NOT NULL,
    study_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS studies_project_idx ON studies(project_id, created_at, study_id);
CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    study_id TEXT NOT NULL REFERENCES studies(study_id),
    run_spec_id TEXT NOT NULL,
    parent_run_id TEXT,
    status TEXT NOT NULL,
    control_request TEXT NOT NULL,
    run_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS experiment_runs_study_idx
    ON experiment_runs(study_id, created_at, run_id);
CREATE INDEX IF NOT EXISTS experiment_runs_status_idx
    ON experiment_runs(status, updated_at);
CREATE TABLE IF NOT EXISTS experiment_artifacts (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    study_id TEXT NOT NULL REFERENCES studies(study_id),
    run_id TEXT NOT NULL REFERENCES experiment_runs(run_id),
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, relative_path)
);
CREATE INDEX IF NOT EXISTS experiment_artifacts_run_idx
    ON experiment_artifacts(run_id, created_at, artifact_id);
CREATE TABLE IF NOT EXISTS experiment_agent_runs (
    agent_run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    role TEXT NOT NULL,
    run_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS experiment_agent_runs_project_idx
    ON experiment_agent_runs(project_id, created_at, agent_run_id);
CREATE TABLE IF NOT EXISTS visualization_profile_approvals (
    approval_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    profile_id TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    approved INTEGER NOT NULL,
    approval_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(profile_id)
);

CREATE TABLE IF NOT EXISTS analysis_records (
    analysis_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    study_id TEXT NOT NULL REFERENCES studies(study_id),
    status TEXT NOT NULL,
    outcome TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analysis_records_study_idx
    ON analysis_records(study_id, created_at, analysis_id);
CREATE TABLE IF NOT EXISTS analysis_artifacts (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    study_id TEXT NOT NULL REFERENCES studies(study_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(analysis_id, relative_path)
);
CREATE INDEX IF NOT EXISTS analysis_artifacts_analysis_idx
    ON analysis_artifacts(analysis_id, created_at, artifact_id);
CREATE TABLE IF NOT EXISTS verification_reports (
    verification_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    study_id TEXT NOT NULL REFERENCES studies(study_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    passed INTEGER NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS verification_reports_analysis_idx
    ON verification_reports(analysis_id, created_at, verification_id);
CREATE TABLE IF NOT EXISTS scientific_review_reports (
    review_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    study_id TEXT NOT NULL REFERENCES studies(study_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    verification_id TEXT NOT NULL REFERENCES verification_reports(verification_id),
    recommendation TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS scientific_reviews_analysis_idx
    ON scientific_review_reports(analysis_id, created_at, review_id);
CREATE TABLE IF NOT EXISTS analysis_agent_runs (
    agent_run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    role TEXT NOT NULL,
    run_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analysis_agent_runs_project_idx
    ON analysis_agent_runs(project_id, created_at, agent_run_id);

CREATE TABLE IF NOT EXISTS evidence_claims (
    claim_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    claim_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    claim_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_claims_analysis_idx
    ON evidence_claims(analysis_id, created_at, claim_id);
CREATE TABLE IF NOT EXISTS research_specialist_reviews (
    specialist_review_id TEXT PRIMARY KEY,
    review_run_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    role TEXT NOT NULL,
    proposed_decision TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_specialist_reviews_run_idx
    ON research_specialist_reviews(review_run_id, created_at, specialist_review_id);
CREATE TABLE IF NOT EXISTS research_meta_reviews (
    meta_review_id TEXT PRIMARY KEY,
    review_run_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    proposed_decision TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_meta_reviews_run_idx
    ON research_meta_reviews(review_run_id, created_at, meta_review_id);
CREATE TABLE IF NOT EXISTS research_policy_decisions (
    policy_decision_id TEXT PRIMARY KEY,
    review_run_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    final_decision TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_policy_decisions_run_idx
    ON research_policy_decisions(review_run_id, created_at, policy_decision_id);
CREATE TABLE IF NOT EXISTS research_review_records (
    review_run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    analysis_id TEXT NOT NULL REFERENCES analysis_records(analysis_id),
    final_decision TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_review_records_project_idx
    ON research_review_records(project_id, created_at, review_run_id);
CREATE TABLE IF NOT EXISTS research_review_agent_runs (
    agent_run_id TEXT PRIMARY KEY,
    review_run_id TEXT NOT NULL REFERENCES research_review_records(review_run_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    role TEXT NOT NULL,
    run_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_review_agent_runs_project_idx
    ON research_review_agent_runs(project_id, created_at, agent_run_id);
CREATE TABLE IF NOT EXISTS research_review_transitions (
    transition_id TEXT PRIMARY KEY,
    review_run_id TEXT NOT NULL REFERENCES research_review_records(review_run_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    policy_decision_id TEXT NOT NULL REFERENCES research_policy_decisions(policy_decision_id),
    transition_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(review_run_id)
);

CREATE TABLE IF NOT EXISTS paper_revisions (
    revision_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    research_review_run_id TEXT NOT NULL REFERENCES research_review_records(review_run_id),
    revision INTEGER NOT NULL,
    parent_revision_id TEXT,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    revision_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(paper_id, revision)
);
CREATE INDEX IF NOT EXISTS paper_revisions_project_idx
    ON paper_revisions(project_id, paper_id, revision);
CREATE TABLE IF NOT EXISTS paper_review_reports (
    review_report_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    revision_id TEXT NOT NULL REFERENCES paper_revisions(revision_id),
    recommendation TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_reviews_paper_idx
    ON paper_review_reports(paper_id, created_at, review_report_id);
CREATE TABLE IF NOT EXISTS paper_quality_reports (
    quality_report_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    revision_id TEXT NOT NULL REFERENCES paper_revisions(revision_id),
    passed INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_builds (
    build_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    revision_id TEXT NOT NULL REFERENCES paper_revisions(revision_id),
    success INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    build_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_artifacts (
    paper_artifact_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    revision_id TEXT NOT NULL REFERENCES paper_revisions(revision_id),
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(revision_id, relative_path)
);
CREATE INDEX IF NOT EXISTS paper_artifacts_paper_idx
    ON paper_artifacts(paper_id, created_at, paper_artifact_id);
CREATE TABLE IF NOT EXISTS paper_agent_runs (
    agent_run_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    revision INTEGER NOT NULL,
    role TEXT NOT NULL,
    run_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_agent_runs_project_idx
    ON paper_agent_runs(project_id, created_at, agent_run_id);
CREATE TABLE IF NOT EXISTS paper_records (
    paper_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    context_id TEXT NOT NULL REFERENCES research_contexts(context_id),
    research_review_run_id TEXT NOT NULL REFERENCES research_review_records(review_run_id),
    target TEXT NOT NULL,
    final_revision_id TEXT NOT NULL REFERENCES paper_revisions(revision_id),
    quality_report_id TEXT NOT NULL REFERENCES paper_quality_reports(quality_report_id),
    build_id TEXT NOT NULL REFERENCES paper_builds(build_id),
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_records_project_idx
    ON paper_records(project_id, created_at, paper_id);

CREATE TABLE IF NOT EXISTS compatibility_imports (
    compatibility_import_id TEXT PRIMARY KEY,
    source_version TEXT NOT NULL,
    builtin_id TEXT NOT NULL,
    legacy_study_id TEXT NOT NULL,
    source_manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    import_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_version, builtin_id, source_manifest_hash)
);
CREATE INDEX IF NOT EXISTS compatibility_imports_builtin_idx
    ON compatibility_imports(builtin_id, created_at, compatibility_import_id);

UPDATE schema_meta SET version=2 WHERE version < 2;
UPDATE schema_meta SET version=3 WHERE version < 3;
UPDATE schema_meta SET version=4 WHERE version < 4;
UPDATE schema_meta SET version=5 WHERE version < 5;
UPDATE schema_meta SET version=6 WHERE version < 6;
UPDATE schema_meta SET version=7 WHERE version < 7;
UPDATE schema_meta SET version=8 WHERE version < 8;
UPDATE schema_meta SET version=9 WHERE version < 9;
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve(strict=False)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

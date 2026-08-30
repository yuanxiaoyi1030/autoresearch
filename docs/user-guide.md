# User guide

## A mode: new topic

Create a Topic project, enter an unrestricted research question and constraints, then run Project Understanding
and Literature. Review the persisted sources, search failures, evidence locators, and gaps. Generate hypotheses,
approve one exact revision, generate the Experiment Plan, and approve that exact revision. Create a Study, run a
smoke attempt before formal runs, analyze completed formal runs, run independent Research Review, apply its
decision, and create the paper. A negative or insufficient outcome is valid and remains visible in the paper.

## B mode: existing project

Choose a directory within an allowed import root. v0.2 makes a read-only snapshot and shows the detected code,
notebooks, configurations, experiments, old results, figures, reuse assessment, and VisualizationProfiles. Review
the Plan's per-file adapt/refactor/reimplementation decisions, semantic classifications, supplemental experiments,
and supplemental figures. Approve the visual profile if new figures should inherit it. Execution uses only the
derived workspace copy; compare implementation diffs and Code Lineage before running.

## Models and credentials

Open “模型与预算”, select the default Provider/model and optional per-stage routes, set budgets, then submit the
API key. The password input is cleared after submission and only configured/missing status returns. Use the
bounded connection test before starting LLM stages.

## v0.1 result access

In the same settings page, use “v0.1 兼容导入”. The operation is read-only and idempotent. Re-run verification
to check the copied manifest and Artifact hashes. Treat these results as legacy verified bytes, not reproduced
v0.2 evidence.

If a run is paused, cancelled, failed, or interrupted, keep the original record. Resume creates or schedules a
new attempt. Never edit Artifact files directly; a hash mismatch intentionally blocks evidence use.

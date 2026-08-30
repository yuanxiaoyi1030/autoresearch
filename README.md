<!-- Purpose: Documents AutoResearch v0.2 through the complete loopback research console. -->
# AutoResearch v0.2

This directory is an isolated implementation of the design in [plan.md](plan.md). Goal 0 provides
the domain-neutral foundation; Goal 1 adds the secure LLM boundary; Goal 2 adds generic A/B Project
Understanding, legacy reuse assessment, code lineage, and visualization planning; Goal 3 adds
auditable multi-source literature research; Goal 4 adds independently reviewed Hypothesis and
Experiment Plan revisions with separate user approvals; Milestone 5 adds domain-neutral Study
implementation and deterministic execution; Milestone 6 adds deterministic statistical analysis,
independent verification, and scientific experiment review; Milestone 7 adds the independent formal
research-review team and deterministic Policy Guard; Milestone 8 adds the five-role, evidence-bound
top-conference paper writing and independent revision loop; Milestone 9 adds the loopback-only frontend
for the complete persisted workflow.

Anthropic and Gemini registry entries are extension points
and report unavailable; the Fake Provider is never a default and requires explicit offline mode.

Python commands must run after `conda activate d2l`. Runtime data defaults to
`D:\code\work\autoresearch\v_0_2_runtime_data` and never shares the v0.1 database or artifacts.

Run the checks from this directory:

```powershell
conda activate d2l
python -m unittest discover -s tests -v
```

Start the API and frontend in separate terminals. Python commands still require `d2l`; both services bind
only to loopback:

```powershell
conda activate d2l
python scripts/run_api.py

cd apps/frontend
npm run dev
```

The frontend defaults to `127.0.0.1:3000` and proxies only to the loopback API at `127.0.0.1:8100`.
See [docs/frontend-console.md](docs/frontend-console.md) for the complete capability and security contract.

## LLM configuration

The loopback API exposes `GET/PUT /api/llm/config`, `GET /api/llm/providers`,
`GET /api/llm/usage`, `PUT/DELETE /api/llm/credentials/{provider_id}`, and
`POST /api/llm/connection-tests`.
The credential endpoint accepts the key separately from non-secret configuration and returns only
configured state, source, and a one-way fingerprint.

Default-route environment configuration uses:

- `AUTORESEARCH_V0_2_LLM_PROVIDER_ID`
- `AUTORESEARCH_V0_2_LLM_PROVIDER`
- `AUTORESEARCH_V0_2_LLM_MODEL`
- `AUTORESEARCH_V0_2_LLM_BASE_URL`
- `AUTORESEARCH_V0_2_LLM_PROTOCOL`
- `AUTORESEARCH_V0_2_LLM_API_KEY`

Temperature, output-token limit, timeout, retry count, stage call/token/cost budgets can also be
set through the API or corresponding `AUTORESEARCH_V0_2_LLM_*` environment variables. API keys
remain only in the backend process (or their source environment), never in SQLite, events, jobs,
artifacts, API responses, or child-process environments.

## Generic Project Understanding

`POST /api/projects/{project_id}/understanding` builds a `ResearchContext` from either an arbitrary
user Topic (A mode) or a completed immutable import snapshot (B mode). B-mode inspection reads files
as data, uses Python AST and Notebook JSON parsing only, and never imports or executes source code.

The loopback API also exposes:

- latest/history Context and approval-ready `LegacyReuseAssessment` queries;
- workspace-confined `CodeLineageRecord` creation/query;
- extracted `VisualizationProfile` query;
- `FigureSpec` creation/query.

Legacy results and figures are always `legacy/unverified`. A legacy figure without located source
data is limited by model validation to style and preliminary-observation use. Candidate executable
files can only be materialized inside the v0.2 Project Workspace. Semantic modifications require a
newer Experiment Plan revision and remain execution-ineligible until that revision and lineage are
independently approved and verified.

## Literature Multi-Agent

`POST /api/projects/{project_id}/literature` runs a deterministic Coordinator around exactly two
LLM roles: `Literature Lead` and an independent `Evidence Reviewer`. The Lead creates at least two
distinct Topic/ResearchContext-derived queries, searches arXiv, OpenAlex, and Crossref through
replaceable stdlib clients, then produces Related Work, evidence bindings, and Research Gaps.
The Reviewer gets a fresh formal context without Lead chat history and returns structured defects;
it never edits the Lead record. Major defects create an immutable Lead revision, capped at two.

Every provider/query call is persisted as a `SearchAttempt`, including failures and explicit network
denials. One provider failure does not discard other results. Sources are deduplicated by normalized
DOI, version-neutral arXiv ID, then normalized title, and distinguish `metadata_only`,
`abstract_only`, `full_text`, and `imported_pdf`. A PDF URL is not treated as read full text. Model
validation forbids metadata/abstract-only records from supporting core scientific claims; core
evidence also requires a precise page, section, paragraph, figure, or table locator.

Read APIs under `/api/projects/{project_id}/literature/` expose history, search attempts, sources,
evidence, gaps, reviews, and agent runs. SQLite keeps every matrix revision, defect report, independent
context hash, provider/model identity, and token usage for audit. External search follows the stored
`network_allowed` constraint unless the run request explicitly supplies `allow_network`.

## Hypothesis and Experiment Planning

The planning stage has exactly two LLM roles: `Research Design Lead` generates or revises artifacts,
while an independent `Critical Reviewer` can only return structured defects. The Reviewer schema has
no approval decision, receives no Lead chat history, and cannot mutate the reviewed revision.

`POST /api/projects/{project_id}/hypotheses` creates at least two evidence-bound, falsifiable
candidates. An exact Hypothesis revision/hash must receive a user decision at
`POST /api/projects/{project_id}/hypotheses/{revision_id}/decision`; approval also selects one
candidate. Only then can `POST /api/projects/{project_id}/experiment-plans` create a generic
`StudySpec`, condition-linked `RunSpec`, `MetricSpec`, and `AnalysisSpec`.

Plans use domain-neutral variable roles and parameter dictionaries rather than a fixed scientific
variable. Deterministic validation covers baseline/condition references, run coverage, a primary
metric, reproducibility fields, and total runs/compute/GPU/cost against hard numeric budgets.
Every revision has a parent, content hash, feedback, and provenance links. Rejected artifacts are
immutable and can only be superseded by a child revision.

B-mode Plans hash-bind the exact `LegacyReuseAssessment`, import manifest, and ResearchContext. They
must decide adapt/refactor/reimplementation for every reusable code path, classify every planned
modification as semantic or non-semantic, retain old results only as unverified observations, and
declare supplemental/reproduction experiments and regenerated figures.

Plan approval is separate from Hypothesis approval. The formal-experiment gate at
`GET /api/projects/{project_id}/experiment-plans/{revision_id}/formal-experiment-gate` re-verifies
the latest revisions, both user approvals, hashes, selected candidate, Critical Review, and B-mode
reuse binding. Unapproved, rejected, stale, tampered, or reviewer-blocked Plans cannot pass.

## Generic Study implementation and execution

An approved Experiment Plan can enter `POST /api/projects/{project_id}/studies`. The
`Experimental Lead / Modeling Scientist` first turns the approved Plan into a structured task graph;
the `Research Engineer` then returns a bounded code package. Both agents produce data only: they
cannot submit commands. Static validation rejects undeclared dependencies, process/network/package
capabilities, credential-like literals, destructive calls, escaped paths, and unapproved semantic
changes. A semantic change is preserved as `requires_plan_revision` and is never materialized.

Verified code is exclusively materialized below the Project Workspace and hash-bound to an immutable
`ImplementationRevision` and `Study`. B-mode implementations must map every Plan-approved legacy reuse
decision to a derived workspace file and create complete `CodeLineageRecord` entries. Imported source
snapshots are read-only data and are never used as execution roots.

Runs use a fixed argv and the active `d2l` Python interpreter with `shell=False`. A runtime-owned
bootstrap confines reads/writes, disables child processes and network access, strips credentials,
captures bounded stdout/stderr, records the environment, hashes configuration/code/output, and retains
failed, timed-out, paused, cancelled, or interrupted attempts. Formal runs require a completed smoke
run. Resume creates a new child attempt; it never overwrites the paused attempt.

New figures are eligible only when their `figure_manifest.json` binds the approved
`VisualizationProfile` hash and names the new input Artifacts. Artifact rows are finalized before their
append-only insert and can be re-verified against the current file hash through the API. There is no
weight-decay dependency in the generic production workflow. The legacy domain is isolated behind the explicit
`builtin/weight_decay_v1` read-only compatibility importer.

## Deterministic analysis and experiment review

`POST /api/projects/{project_id}/studies/{study_id}/analyses` runs three bounded roles. The
`Statistical Analyst` reads only completed formal Run metrics and the approved `AnalysisSpec`, then
uses deterministic standard-library code for group summaries, sample variance, standard errors,
Student-t intervals/tests, effect sizes, multiplicity correction, missing seed/replicate detection,
and reported-but-not-excluded IQR outliers. It currently supports independent Welch and paired/matched
experimental structures. Unsupported thresholds or corrections yield `insufficient_evidence`; they do
not trigger an implicit 0.05 default.

The Analyst writes append-only machine JSON, CSV, and SVG Artifacts. Their source Artifact IDs are
explicit, and SVG/table contents are regenerated byte-for-byte during verification. If the Study has
an approved `VisualizationProfile`, the new figure is hash-bound to it. Analysis failures are retained
as failed `AnalysisRecord` entries.

The `Verification Auditor` receives a fresh, hash-addressed context and independently verifies the
approved Plan gate, implementation and run code trees, B-mode source-to-derived mappings, Run configs,
seeds, environments, every Run/Analysis Artifact, metric coverage, and all computed statistics. It is
read-only with respect to evidence. Re-verification creates another immutable report, allowing later
tampering to be detected without rewriting prior findings.

The `Scientific Reviewer` sees the complete model/implementation/result/audit package but cannot change
the deterministic outcome. A policy layer converts its structured recommendation to
`proceed_to_research_review`, `supplement_experiment`, or `revise_plan`. `supported`, `negative_result`,
and `insufficient_evidence` remain first-class outcomes; any of them can proceed when verification passes
and the reviewer keeps the conclusion appropriately bounded.

## Independent formal research review

`POST /api/projects/{project_id}/analyses/{analysis_id}/research-reviews` creates a fresh formal
review run. The Meta Reviewer first assigns three isolated scopes, but does not receive an authoring or
specialist role. Methodology Reviewer checks design, baselines, controls, ablations, confounding, and
alternative explanations. Statistical Reviewer independently checks the approved analysis and deterministic
recalculation. Evidence & Reproducibility Reviewer checks EvidenceClaims, every cited Artifact, code/config/
environment bindings, CodeLineage, citations, and reproduction requirements.

Specialists receive different hash-addressed contexts with no peer reports or original Agent chat. Meta sees
their immutable reports only after all three finish. Material decision divergence is recorded with each
reviewer position and an explicit resolution; Meta output cannot erase the minority report.

The deterministic Policy Guard always runs last and has priority over Reviewer prose. It freshly re-runs
verification and applies hard rules for Plan binding, B-mode lineage design, missing approved experiments,
Artifact hashes, numerical recomputation, EvidenceClaim scope, citation access level, and precise locators.
Its decisions are `supported`, `negative_result`, `insufficient_evidence`, `return_to_experiment`, or
`revise_plan`.

Applying an immutable review decision maps to the Workflow only from `RESEARCH_REVIEW`: the first three
decisions enter report planning with the bounded outcome, `return_to_experiment` goes to experiment execution,
and `revise_plan` goes to experiment planning. A fresh Policy Guard check is required immediately before the
transition, and one review decision can be applied only once.

## Evidence-bound top-conference paper writing

`POST /api/projects/{project_id}/papers` starts only from an applied, eligible Research Review decision and
the exact reviewed Analysis. Five bounded roles collaborate: `Lead Author`, `Technical Content Editor`,
`Related Work & Citation Editor`, `Presentation & LaTeX Editor`, and an independent
`Top-Conference Reviewer`. The two specialist editors may run concurrently, but the default and hard maximum
are two simultaneous paper agents. Reviewer-requested revisions are immutable and capped at two rounds.

Deterministic quality gates require every primary claim to bind an `EvidenceClaim`, every reported primary
number to bind a hash-verified Analysis or Experiment Artifact, and every citation to bind a real verified
`LiteratureSource`, evidence record, and precise locator. Negative or insufficient evidence is retained and
automatically produces a bounded conclusion. B-mode generated figures must inherit the exact approved
`VisualizationProfile`; retained legacy figures are explicitly labeled as legacy/unverified.

Built-in configurations are available for `neurips`, `icml`, `iclr`, and `generic_top_conference`. They encode
the expected manuscript structure and review criteria without claiming to be official venue style packages or
promising acceptance. The safe LaTeX build uses fixed commands with shell escape disabled, then checks citations,
unresolved references, PDF metadata/text extraction, and a rendered PNG for every page.

Successful revisions persist `paper.tex`, `references.bib`, figures, tables, appendix,
reproducibility statement, Markdown preview, build log, PDF, rendered QA pages, Reviewer defects, and revision
history under `v_0_2_runtime_data/projects/{project_id}/papers/{paper_id}/revision-{n}`. See
[docs/paper-writing.md](docs/paper-writing.md) for the exact contracts and APIs.

## Final operator documentation

- [Final architecture](docs/final-architecture.md)
- [Runtime operations](docs/runtime-operations.md)
- [Configuration](docs/configuration.md)
- [Security hardening](docs/security-hardening.md)
- [v0.1 compatibility and migration](docs/v01-migration.md)
- [User guide](docs/user-guide.md)
- [Section 23 acceptance report](docs/acceptance-report.md)

<!-- Purpose: Defines the v0.2 end-to-end research, review, and evidence-bound paper architecture. -->
# v0.2 research and paper architecture boundaries

```text
loopback browser console (127.0.0.1:3000)
    ├── no browser-side API-key persistence
    ├── backend-rehydrated ProjectSnapshot after refresh/restart
    └── same-origin /api and /health proxy only
    ↓
loopback API (127.0.0.1:8100)
    ├── non-secret route/stage-budget config
    ├── process-memory CredentialStore ──→ Provider Registry ──→ OpenAI-compatible endpoint
    │                                      ├── OpenAI-compatible/OpenAI/local: available
    │                                      ├── Anthropic/Gemini: reserved, unavailable
    │                                      └── Fake: explicit offline/test only
    ↓
secret guard → repositories ── SQLite (v0_2_runtime_data only)
    ↓
deterministic Workflow / durable Job and Event journal
    ↓
project-confined Workspace / read-only source snapshot importer
    ↓
static Project Understanding (AST/JSON/text only; never import/execute)
    ├── ResearchContext + LegacyReuseAssessment
    ├── CodeLineageRecord → workspace candidate only
    └── VisualizationProfile + FigureSpec
    ↓
approved Hypothesis + Experiment Plan gate
    ↓
Experimental Lead task graph → Research Engineer code package
    ↓
static validator → immutable ImplementationRevision → Study Registry
    ↓
d2l fixed-argv Study Runtime → ExperimentRun + append-only Artifacts
    ↓
deterministic Statistical Analyst → AnalysisRecord + JSON/CSV/SVG
    ↓
fresh-context Verification Auditor → immutable VerificationReport
    ↓
Scientific Reviewer + deterministic policy → formal Research Review gate
    ↓
Meta dispatch → 3 isolated specialist reviews → Meta disagreement synthesis
    ↓
deterministic Research Policy Guard → report / experiment / Plan feedback transition
    ↓ eligible reviewed outcome
Lead Author → Technical + Citation Editors (maximum two concurrent)
    ↓
Presentation & LaTeX Editor → immutable PaperRevision
    ↓
independent Top-Conference Reviewer → bounded revision loop (maximum two)
    ↓
claim / number / citation / visualization gates → safe LaTeX build → PDF visual QA
    ↓
append-only paper history + project-confined paper Artifacts
```

The API process owns the database, foundation services, LLM routing config, stage usage ledgers, and credentials.
Raw credentials exist only in `InMemoryCredentialStore` and ephemeral outbound authorization headers. The standard
library HTTP adapter supports Chat Completions and Responses payloads, JSON Schema outputs, tool calls, streaming,
timeouts, retries, normalized errors, and usage/cost accounting.

## Trust boundaries

1. The source import root is user-selected but must resolve below `allowed_import_roots`.
2. Source files are scanned and copied as data. They are never imported as Python or executed.
3. Symlinks, junctions, caches, runtime data, build output, and generated dependencies are excluded.
4. Every copied file is hash-verified in a project/import-specific runtime directory.
5. Workspace file resolution rejects absolute paths, parent traversal, symlinks, and junctions.
6. The HTTP listener accepts loopback hosts only.
7. Credentials are configured separately from serializable route config and APIs never return raw values.
8. Event and Job repositories reject credential-like fields and configured secret values before persistence.
9. Child-process environments are constructed with all credential-like variables removed.
10. Imported code and Notebook cells are parsed as data only; no legacy source is imported or executed.
11. Reparse points are excluded from imports and rejected during Project Workspace resolution.
12. Legacy results/images are unverified; figures without source data are style/preliminary references only.
13. Semantic lineage changes require a newer Plan revision and cannot become execution-eligible before approval.
14. Agent outputs are structured task/code records only; neither experiment Agent controls a shell.
15. Only a hash-verified Project Workspace implementation is snapshotted as executable code.
16. Study child processes receive no API credentials, have network/process creation blocked, and write only to
    run-specific Artifact or volatile roots.
17. Every attempt is preserved; pause/resume creates parent/child attempts and restart recovery marks orphaned
    running records stale instead of rewriting history.
18. Figure provenance is bound to an approved VisualizationProfile and new input Artifact IDs before insertion.
19. Statistical values are produced and independently reproduced by deterministic code; the Reviewer cannot
    supply or edit numerical results.
20. Verification reads but never mutates Run or Analysis Artifacts, and each re-verification is append-only.
21. Negative results, incomplete evidence, failed Runs, and failed analyses remain queryable and cannot be
    upgraded by reviewer prose.
22. Formal specialist reviewers receive mutually isolated contexts; only Meta receives their completed reports.
23. Policy Guard re-verifies evidence after all LLM work and immediately before any Workflow transition.
24. Reviewer passage cannot override missing experiments, invalid Plan/lineage bindings, hash failures, numerical
    mismatch, or a core citation supported only by metadata/abstract text.
25. Paper agents produce structured content only; deterministic code escapes and renders LaTeX, generates BibTeX
    from verified source metadata, and invokes a fixed no-shell-escape build.
26. Primary paper claims, numbers, citations, and generated B-mode figures must retain exact immutable provenance.
27. The Top-Conference Reviewer receives a fresh context, cannot rewrite a revision, and can request at most two
    append-only revision rounds.
28. A completed paper requires a successful exact-revision build plus PDF metadata, text, and every-page render QA.
29. The browser never receives a general execution primitive and exposes only bounded workflow actions implemented
    by the API, including approval decisions and Run pause/resume/cancel.
30. Browser refresh and process restart recovery are reconstructed from persisted backend state; localStorage,
    sessionStorage, IndexedDB, cookies, and browser-side API-key persistence are not part of the design.
31. Project state, imports, logs, experiment/analysis artifacts, reviews, and paper revisions are isolated below
    `D:\code\work\autoresearch\v_0_2_runtime_data`; v0.1 runtime data is never shared or migrated implicitly.

## Goal 0 persistence

- projects and current/history ResearchState;
- stage attempts;
- durable jobs with idempotency and recovery;
- cursor-addressed activity events;
- import sessions and immutable JSON manifests.

No LLM credentials or raw model prompts belong in the SQLite schema. Experiment records contain only
structured task/code metadata, hashes, non-secret configuration/environment data, bounded logs, and Artifact
provenance. Project Understanding JSON records store inventory and provenance, not executable runtime state.

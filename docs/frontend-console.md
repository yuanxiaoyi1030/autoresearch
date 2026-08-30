<!-- Purpose: Specifies the complete loopback-only UI, persistence recovery, and browser security contract. -->
# Loopback research console

The v0.2 frontend is a Next.js App Router application under `apps/frontend`. It is a view and control surface
over backend persistence; it does not maintain a competing scientific state machine in the browser.

## Research surfaces

The console provides:

- Provider registry, default and per-stage model routes, protocol, pricing, token/call/cost budgets, process-memory
  API-key submission, credential clearing, and bounded connection tests;
- generic A-mode Topic and B-mode existing-project creation, followed by immutable B-mode import;
- Project Understanding constraints, ResearchContext history, Legacy Reuse Assessment, Code Lineage, immutable
  implementation diff, VisualizationProfile approval, and FigureSpec creation;
- literature network policy, SearchAttempts, real LiteratureSources, Evidence Matrix, locators, gaps, Reviewer
  defects, and Agent history;
- evidence-bound Hypothesis candidates, user selection/approval/rejection, immutable revisions, Experiment Plan,
  B-mode reuse and semantic-change details, formal gate, Critical Review, and approval history;
- Study implementation, smoke/formal Run creation, pause/resume/cancel, attempt status, bounded stdout/stderr,
  metrics and Artifact preview/download, deterministic Analysis, and legacy/new figure comparison;
- independent Verification, Scientific Review, formal Research Review, specialist reports, Policy Guard,
  EvidenceClaims, and exact review-decision application;
- five-role paper generation, outline, immutable revision history, Reviewer defects, quality gates, Artifact
  manifest, inline PDF preview, and LaTeX/Markdown/PDF downloads;
- combined Multi-Agent activity, provider/model identity, token usage, runtime usage/cost ledger, durable Jobs,
  failures, and cursor-addressed Events.

## Refresh and restart recovery

The selected project ID may appear in the URL for navigation, but all project state and research content is
reloaded from backend APIs. `loadProjectSnapshot` reconstructs every stage from SQLite-backed records. The UI polls
the durable Event journal and periodically refreshes persisted Run status, so a page refresh or worker restart
does not depend on transient React state. Stale, failed, cancelled, negative, and insufficient-evidence records
remain visible.

## Security boundary

- Development and production scripts bind to `127.0.0.1`; `next.config.ts` rejects non-loopback API origins and
  credential-bearing origins.
- The API key is held only in a React input state long enough for one same-origin request, cleared before awaiting
  the response, and never written to localStorage, sessionStorage, IndexedDB, cookies, URLs, or project records.
- The UI has no arbitrary shell, Python, interpreter, command, dependency installation, or file-path execution
  surface. Run actions reference persisted Study and RunSpec IDs only.
- Imported files, implementation diffs, logs, and Artifact contents are served only after backend ownership and
  project-confined path checks. Imported source remains read-only.
- The frontend reuses v0.1 framework choices and dependency versions only. It does not copy v0.1 `.next`,
  `node_modules`, caches, or generated output.

## Validation

`npm run test:contract` checks loopback binding, volatile API-key handling, full API coverage, backend-based state
restoration, absence of an arbitrary execution form, and absence of v0.1 build-output references. The completion
gate also requires `npm run typecheck`, `npm run build`, the Python backend suite in Conda `d2l`, and live HTTP 200
responses through the frontend proxy.

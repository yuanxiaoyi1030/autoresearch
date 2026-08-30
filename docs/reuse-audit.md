<!-- Purpose: Records the v0.1-to-v0.2 reuse decisions made before copying foundation code. -->
# v0.1 reuse audit

## Reuse after v0.2 adaptation

| v0.1 area | v0.2 decision | Required adaptation |
|---|---|---|
| `research_runtime/config.py` | Reuse design | Use the v0.2 runtime root and v0.2 environment prefix; keep loopback validation. |
| `state/statuses.py`, compact state entities | Reuse design | Add every v0.2 stage and remove Study-specific assumptions. |
| `workflow/transitions.py`, `workflow/workflow.py` | Reuse design | Expand the deterministic state graph to implementation and report-review stages. |
| SQLite transaction and repository pattern | Reuse design | Start with a clean schema version 1 containing only Goal 0 entities. |
| durable job/event models and repositories | Reuse design | Replace weight-decay and paper-specific job kinds with domain-neutral stage jobs. |
| `workspace/manager.py` | Reuse with small changes | Preserve traversal/reparse protection and add an explicit runtime-root guard. |
| import manifest and snapshot boundary | Reuse after generalization | Exclude build/runtime caches; remove preferred `condense*` filenames and ResearchSeed creation. |
| project/import/job API conventions | Reuse design | Expose only Goal 0 endpoints and keep loopback-only startup. |
| state/workflow/import safety tests | Reuse test intent | Rewrite against the v0.2 stage graph, runtime root, and neutral fixtures. |

## Defer for later generalization

- LLM client and deterministic test provider: Goal 1 will retain the provider protocol and redaction ideas,
  but production must not silently use the hard-coded research provider.
- literature adapters: Goal 3 reused only transport/source-normalization ideas, then implemented
  independent arXiv/OpenAlex/Crossref stdlib clients, failure-preserving SearchAttempts, access labels,
  immutable Lead revisions, and a separately audited Evidence Reviewer context.
- local experiment executor and artifact capture: Milestone 5 reused the fixed-argv, bounded-capture intent but
  implemented a new generic `StudySpec`/`ImplementationRevision` runtime with workspace-only execution,
  d2l enforcement, credential stripping, audit-hook confinement, append-only Artifacts, and run controls.
- approvals: Goal 4 adapted hash-bound revisions into separate generic Hypothesis and Experiment Plan
  decisions, with parent/feedback/provenance chains and a formal-experiment gate.
- frontend source: Goal 9 may reuse layout and API patterns, but not the acceptance-study content.

## Keep only as builtin compatibility material

- `research_runtime/studies/weight_decay/**`
- weight-decay metrics, validators, workspace runner, service, UI action, API route, Job kind, Critic checks,
  Writer text, acceptance scripts, and Study-specific tests.

These files are not copied into the Goal 0 production path. A future compatibility package may expose them
as `builtin/weight_decay_v1` without making them the default workflow.

## Never copy

- `v_0_1_runtime_data`, SQLite databases, Project Workspace contents, imports, Artifacts, logs, and reports;
- `.next`, `node_modules`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, compiled files, and caches;
- generated acceptance output or user research data;
- credentials, environment secrets, or local configuration containing credentials.

## Coupling conclusion

The reusable core is the persistence and safety architecture, not the v0.1 research behavior. Goal 0 therefore
ports only domain-neutral infrastructure and uses generic stages and job kinds. A source scan must find no
unexplained `weight_decay`, `/experiments/weight-decay`, `condense.ipynb`, or fixed scientific question outside
this audit and `plan.md`.

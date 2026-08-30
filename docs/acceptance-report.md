# v0.2 acceptance report

Validated on 2026-08-27. Backend: 52/52 `unittest` cases passed after `conda activate d2l`. Frontend: TypeScript,
5/5 security contracts, and the Next.js production build passed. No dependency install, removal, or upgrade was
performed.

## Plan section 23 matrix

| # | Result | Automated evidence |
|---|---|---|
| 1 | Pass | `test_paper_writing.test_five_role_revision_evidence_latex_pdf_and_visual_qa` completes a generic A-mode topic and asserts project/Plan contain no `weight_decay`. |
| 2 | Pass | `test_project_understanding` covers allowed Python, notebook, and document-only projects. |
| 3 | Pass | B-mode planning records approved adapt/refactor/reimplementation choices; runtime tests execute approved derived workspace mappings. |
| 4 | Pass | B runtime source fingerprints remain unchanged and a source sentinel proves legacy code was not executed. |
| 5 | Pass | B runtime and analysis tests require Code Lineage, source/derived hashes, modification class, and execution eligibility. |
| 6 | Pass | B analysis and paper tests bind new figures to new metrics Artifacts and the approved VisualizationProfile hash. |
| 7 | Pass | LLM configuration/security API tests cover provider/model routes, volatile key submission, and bounded connection tests. Live external transmission was intentionally not used. |
| 8 | Pass | LLM security and Study runtime tests scan persistence, logs, metadata, API responses, and child environments for secrets. |
| 9 | Pass | Literature tests use arXiv/OpenAlex/Crossref doubles, multiple queries, partial failure, version deduplication, access levels, and locators. |
| 10 | Pass | Hypothesis/Planning tests require Lead output, isolated Critical Review, and separate exact-revision user approvals. |
| 11 | Pass | Generic A end-to-end assertion plus typed Study models prove no weight-decay field dependency. |
| 12 | Pass | Study/Analysis tests cover Research Engineer implementation and independent Verification Auditor recomputation. |
| 13 | Pass | Analysis verification regenerates JSON, CSV, SVG, statistical summaries, intervals, tests, and effect estimates. |
| 14 | Pass | Independent review tests cover isolated Methodology, Statistical, Evidence reviewers and Meta synthesis. |
| 15 | Pass | Scientific Review and Policy Guard consume generic Plan metrics and EvidenceClaims rather than domain fields. |
| 16 | Pass | Paper tests produce LaTeX, BibTeX, figures, tables, appendix, reproducibility statement, PDF, logs, and page renders. |
| 17 | Pass | Two bounded immutable Top-Conference Reviewer rounds progress from revise to ready. |
| 18 | Pass | Paper quality tests bind primary claims and every number to hash-verified Evidence/Artifacts and reject an invented `999`. |
| 19 | Pass | Study, Analysis, Review, and Paper tests preserve failed runs, negative results, and insufficient evidence. |
| 20 | Pass | Compatibility tests import the real v0.1 six-run weight-decay cohort via `builtin/weight_decay_v1`. |
| 21 | Pass | Workflow/Study tests cover persistence, pause/resume/cancel, stale recovery, durable worker recovery, attempts, and idempotency keys. |
| 22 | Pass | Compile and all backend tests were executed only after activating Conda `d2l`. |
| 23 | Pass | No package command that installs, removes, or upgrades dependencies was executed; pinned manifests were retained. |

## Read-only integrity evidence

Before and after full acceptance, canonical path/size/content-SHA256 tree summaries were identical:

- v0.1 source (excluding generated `node_modules`, `.next`, and `__pycache__`): 191 files,
  `862fe2d4ed7368031cabeea3be9827d4904ee49c177b973b31c931472b11b8c8`.
- v0.1 runtime: 5994 files, `10773a57a52e683f4692224b4e22f7cb68c7146064dbf5d98dee5b454e473325`.
- `D:\ml_project\coscientist` (excluding `__pycache__`): 247 files,
  `c16f088155bea340930352e107814bb4abfebab726b214a5816932499fb5b953`.

Residual risks and operating limits are recorded in [security-hardening.md](security-hardening.md).

<!-- Purpose: Specifies the five-role, evidence-bound paper-writing and PDF-quality workflow. -->
# Top-conference paper writing

## Entry contract

Paper writing starts only after an immutable Research Review decision has been applied to the exact current
ResearchState and entered `report_planning`. The service freshly verifies the reviewed Analysis, Study,
Experiment Plan, Artifacts, EvidenceClaims, LiteratureSource records, citation locators, and, for B mode, the
approved VisualizationProfile. A stale or ineligible review cannot be used to write a paper.

## Roles and bounded orchestration

1. `Lead Author` owns title, abstract, contributions, outline, terminology, notation, introduction, and the
   initial bounded conclusion.
2. `Technical Content Editor` owns method, theory, experimental setup, results, analysis, assumptions, and exact
   Artifact-backed number bindings.
3. `Related Work & Citation Editor` owns related work, citation uses, and novelty positioning against verified
   literature evidence with precise locators.
4. `Presentation & LaTeX Editor` owns structured figures, tables, algorithms, appendix, limitations, broader
   impact, and the reproducibility statement. It emits data, not executable LaTeX.
5. `Top-Conference Reviewer` independently scores novelty, correctness, rigor, significance, clarity,
   reproducibility, limitations, and broader impact, and returns immutable structured defects.

The Lead runs first. Technical and Citation editors can run concurrently with `max_parallel_agents <= 2`.
Presentation runs after their merge. The Reviewer receives a fresh hash-addressed revision context without
author chat. A `revise` recommendation creates a child `PaperRevision`; at most two revision rounds are allowed.

## Evidence and quality gates

- Each primary scientific claim binds one or more exact `EvidenceClaim` IDs.
- Each reported primary numerical literal binds a hash-verified Analysis or Experiment Artifact and locator.
- Each citation binds an existing, verified `LiteratureSource`, a compatible literature evidence record, and a
  page, section, paragraph, figure, or table locator.
- Novelty claims bind supporting evidence and at least one contrasting verified source.
- Tables bind their source Artifact IDs and cannot introduce numbers absent from those Artifacts.
- The deterministic outcome boundary governs the abstract and conclusion. Negative and insufficient outcomes
  remain first-class and cannot be rewritten as proof or state of the art.
- B-mode generated figures bind the exact approved VisualizationProfile ID and hash. Legacy figures bind the
  immutable import manifest hash and carry an explicit legacy/unverified label.
- A final revision must receive a `ready` Reviewer recommendation and pass exact-revision LaTeX/PDF checks.

No agent can invent an experiment, number, citation, or Artifact. Missing support causes a failed gate or a
downgraded conclusion rather than synthetic content.

## Conference configurations and rendering

`ConferenceTemplateConfig` supports `neurips`, `icml`, `iclr`, and `generic_top_conference`. These are built-in
compatible structures and review criteria, not bundled official style packages. They do not predict or promise
acceptance.

The renderer deterministically escapes agent text, creates BibTeX from stored source metadata, and materializes
only inside the project paper directory. It runs fixed `pdflatex`/`bibtex` commands with `shell=False`,
`-no-shell-escape`, a bounded timeout, and a credential-stripped environment. The final pass rejects unresolved
citations/references and build errors. PDF QA then checks metadata, extracted text, page count, and one PNG render
per page. SVG source figures are preserved; the safe PDF build uses a labeled placeholder because converting SVG
through shell escape is prohibited.

## Immutable outputs and APIs

The runtime root is `D:\code\work\autoresearch\v_0_2_runtime_data`. Each successful paper revision is stored at:

```text
projects/{project_id}/papers/{paper_id}/revision-{revision}/
    paper.tex
    references.bib
    appendix.tex
    reproducibility_statement.md
    preview.md
    figures/
    tables/
    build.log
    paper.pdf
    pages/page-*.png
```

SQLite schema version 9 stores append-only revisions, review reports and defects, quality reports, build records,
agent runs, Artifact metadata, and the final paper record. The loopback API exposes:

- `POST /api/projects/{project_id}/papers`
- `GET /api/projects/{project_id}/papers`
- `GET /api/projects/{project_id}/papers/{paper_id}`
- `GET /api/projects/{project_id}/papers/{paper_id}/artifacts`
- `GET /api/projects/{project_id}/papers/{paper_id}/artifacts/{artifact_id}/content`
- `GET /api/projects/{project_id}/paper-agent-runs`

Artifact content resolution is confined to the owning Project Workspace. Credentials, raw secrets, and child
process environment secrets are never persisted in paper records or files.

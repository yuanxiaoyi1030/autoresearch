<!-- Purpose: Documents Goal 3 literature roles, evidence policy, official source contracts, and audit API. -->
# Literature Multi-Agent contract

The runtime has two LLM roles and one deterministic non-LLM Coordinator:

- Literature Lead: query plan, source-grounded synthesis, Related Work, evidence drafts, Research Gap,
  and complete replacement revisions.
- Evidence Reviewer: independent formal context; existence/DOI/version/locator/access/support/missing-work
  checks; structured defects only.
- Coordinator: provider fan-out with at most two workers, source fact normalization, evidence validation,
  persistence, reviewer routing, and a hard maximum of two Lead revision rounds.

Search clients follow the public contracts documented by
[arXiv API](https://github.com/arXiv/arxiv-docs/blob/develop/source/help/api/user-manual.md),
[OpenAlex API](https://help.openalex.org/api/), and
[Crossref REST API](https://support.crossref.org/hc/en-us/articles/214320426-REST-API).
They use fixed HTTPS endpoints and Python stdlib transports, so Goal 3 adds no SDK dependency.

Access labels describe content actually presented to the Lead, not what a landing page might make
available. Search-result abstracts are `abstract_only` even when a PDF URL exists. Imported PDFs are
recorded distinctly and keep their import-relative path/hash provenance; they are never executed.
`full_text` is reserved for a later reader that actually provides validated text. Abstract-only and
metadata-only sources cannot be bound as `core_support`; core support also requires a precise locator.

Durable records:

- `literature_search_attempts`: every query/provider success, failure, or network denial;
- `literature_sources`: normalized bibliographic/source facts and access level;
- `literature_matrices`, `literature_evidence`, `research_gaps`: immutable Lead revisions;
- `evidence_review_reports`: Reviewer defects and independent-context hash;
- `literature_agent_runs`: role, operation, revision, input hash, output artifact, model, and usage.

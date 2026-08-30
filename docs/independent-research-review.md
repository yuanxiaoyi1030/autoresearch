<!-- Purpose: Documents formal reviewer isolation, Meta disagreement handling, Policy Guard rules, and feedback loops. -->
# Independent research review

## Team contract

The Meta Reviewer has two operations: assign exactly one scope to each specialist, then synthesize their
immutable reports. It never generates the original hypothesis, Plan, implementation, analysis, or paper and
does not perform specialist review itself.

Each specialist receives a separate context hash and the common constraints `original_agent_chat_included=false`,
`peer_review_reports_included=false`, and `reviewer_can_modify_evidence=false`.

- Methodology Reviewer receives the approved hypothesis, Plan, Study design, implementation tasks, scientific
  review, and EvidenceClaims.
- Statistical Reviewer receives MetricSpec, RunSpec, AnalysisSpec, AnalysisRecord, deterministic verification,
  scientific review, and EvidenceClaims.
- Evidence & Reproducibility Reviewer receives EvidenceClaims, Run/Analysis Artifacts, implementation, runs,
  CodeLineage, ReproducibilitySpec, literature evidence/sources, and deterministic verification.

Meta synthesis hash-binds all three specialist report IDs and hashes. When specialist decisions differ, the
service verifies that a disagreement entry reproduces the actual role/decision map; otherwise it appends a
deterministic disagreement record so no minority position disappears.

## Policy precedence

Reviewer proposals are advisory. Policy rules are evaluated from current files and records:

1. Plan and approval binding failure forces `REVISE_PLAN`.
2. Approved B-mode lineage coverage/action/modification divergence forces `REVISE_PLAN`.
3. Code, Run, config, environment, Artifact, lineage-file, or statistic verification failure forces
   `RETURN_TO_EXPERIMENT` unless a higher-priority Plan rule already failed.
4. Missing approved metric/seed/replicate observations force `RETURN_TO_EXPERIMENT`.
5. An EvidenceClaim outside its Analysis outcome/comparisons/Artifact scope forces
   `INSUFFICIENT_EVIDENCE`.
6. Core literature claims require a verified full-text/imported source and precise locator; metadata or abstract
   support forces `INSUFFICIENT_EVIDENCE`.
7. A core experiment-result claim must bind the machine-readable Analysis Artifact, every current comparison,
   and the original metrics Artifacts.

If no hard rule fails, stricter specialist/Meta requests to return or revise are honored. Otherwise the final
decision is exactly the deterministic Analysis outcome. Policy stores every rule result and explains any Meta
override.

## Feedback loop

The decision is append-only. Before applying it, the system runs a new VerificationReport and Policy evaluation;
if the resulting decision changed, the old review is stale and cannot transition state. From `RESEARCH_REVIEW`,
supported, negative, and insufficient evidence enter `REPORT_PLANNING`; return goes to `EXPERIMENT`; revise goes
to `EXPERIMENT_PLANNING`. The transition is recorded once with before/after state revisions.

<!-- Purpose: Documents Goal 4 roles, immutable revisions, B-mode binding, approvals, and experiment gate. -->
# Hypothesis and Experiment Planning contract

## Role separation

- Research Design Lead generates candidate Hypotheses and complete Experiment Plans, or complete
  child revisions in response to recorded Reviewer/user feedback.
- Critical Reviewer receives a new formal context with `lead_chat_history_included=false`. It checks
  novelty, falsifiability, Topic alignment, baseline, ablation, controls, statistics, feasibility,
  resources, reproducibility, confounding, alternative explanations, and legacy reuse. Its output is
  defects plus a summary; it has no approval field.
- The deterministic Coordinator validates, hashes, persists, routes review, records user decisions,
  and evaluates the formal-experiment gate.

## Immutable revision chain

Initial revisions are numbered zero and have no parent. Every later revision must name the latest
parent and contain at least one feedback record. Feedback records bind either a Critical Reviewer
defect, a user rejection, or explicit user revision feedback. The content hash covers identity,
revision number, parent, full scientific content, feedback, and provenance; persistence and approval
recompute it to detect mutation.

Provenance binds ResearchContext and Literature Evidence Matrix hashes. Plans additionally bind the
approved Hypothesis revision, selected candidate and approval record. B-mode Plans also bind the exact
LegacyReuseAssessment and immutable import manifest.

## Two user approval gates

Hypothesis and Experiment Plan decisions are separate immutable records. Only the latest revision can
receive one decision. A rejected revision cannot later be approved; a child revision is required.
Major or blocking Critical Reviewer defects prevent approval. Critical Reviewer outputs cannot create
approval records because `PlanningApproval.actor_type` is fixed to `user` and reviewer output schemas
contain no decision.

Formal experiments require the latest Plan to pass all of these checks:

1. Plan content still matches its hash and has a matching user approval.
2. The bound Hypothesis is latest, hash-valid, user-approved, and selects the same candidate.
3. The Plan has a matching independent review with no unresolved major/blocking defect.
4. For B mode, assessment ID/hash, import ID, and manifest hash still match Project Understanding.

## Generic plan and budget

Study variables are named records with roles and open value-domain dictionaries. Conditions and runs
carry domain-specific assignments/parameters without a built-in optimizer or other fixed variable.
Every condition has a RunSpec, at least one baseline exists, a primary metric exists, and the analysis
declares estimands, comparisons, uncertainty, missing-data/outlier handling, assumptions, figures,
confounders, and alternative explanations.

Expected runs equal `seeds × replicates_per_seed` across RunSpecs. Validation rejects plans exceeding
approved totals for runs, compute minutes, GPU hours, or estimated cost before persistence or approval.

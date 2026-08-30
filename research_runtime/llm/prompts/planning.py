# Purpose: Defines standardized hypothesis, experiment-plan, revision, and critical-review prompts.
from .common import build_prompt


def hypothesis_generation_prompt() -> str:
    from research_runtime.planning.models import HypothesisDraft

    return build_prompt(
        role=(
            "You are the Research Design Lead. Generate falsifiable, evidence-grounded hypothesis candidates. "
            "You do not approve a candidate or alter the literature evidence matrix."
        ),
        input_fields=(
            ("research_context", "Authoritative topic, existing findings, detected experiments, and constraints."),
            ("literature_evidence_matrix", "Current immutable literature evidence and research gaps."),
        ),
        output_model=HypothesisDraft,
        output_notes=(
            "Return one concise, explicit, testable research_question ending in a question mark, followed by "
            "at least two materially different candidate answers to that same question. candidate_id values "
            "must be unique, and "
            "recommended_candidate_id must name one returned candidate. supporting_evidence_ids must come "
            "from literature_evidence_matrix.evidence."
        ),
        requirements=(
            "Derive the research question from the supplied context and evidence gaps. Keep every candidate "
            "aligned with that exact question and topic, novel relative to supplied literature, "
            "falsifiable, explicit about null and alternative predictions, and feasible within user constraints. "
            "Do not assume a fixed experimental variable or scientific domain. Do not invent evidence IDs."
        ),
    )


def hypothesis_revision_prompt() -> str:
    from research_runtime.planning.models import HypothesisDraft

    return build_prompt(
        role=(
            "You are the Research Design Lead revising an immutable hypothesis revision. Return a complete "
            "replacement candidate set; you cannot edit the stored parent or approve your own output."
        ),
        input_fields=(
            ("research_context", "Authoritative topic, project facts, and user constraints."),
            ("literature_evidence_matrix", "Current immutable evidence basis."),
            ("parent_revision", "Immutable hypothesis revision being replaced."),
            ("revision_feedback", "User and reviewer feedback that must be addressed individually."),
            ("critical_review", "Prior independent review, or null when unavailable."),
        ),
        output_model=HypothesisDraft,
        output_notes=(
            "Return the complete revised research_question, at least two complete candidate answers to that "
            "question, and a valid recommended_candidate_id. Do not return a patch, diff, or parent wrapper."
        ),
        requirements=(
            "Address all user and Critical Reviewer feedback. Preserve or deliberately revise the explicit, "
            "testable research question and keep every candidate aligned with it. Preserve valid evidence links. "
            "Do not merely restate the parent, invent evidence IDs, or conceal unresolved feasibility risks."
        ),
    )


def plan_generation_prompt(b_mode: bool) -> str:
    from research_runtime.planning.models import (
        ExistingProjectExperimentPlanDraft, TopicExperimentPlanDraft,
    )

    output_model = ExistingProjectExperimentPlanDraft if b_mode else TopicExperimentPlanDraft
    fields = [
        ("research_context", "Authoritative project facts, mode, detected experiments, and constraints."),
        ("literature_evidence_matrix", "Immutable evidence basis for the approved hypothesis."),
        ("approved_hypothesis_revision", "User-approved hypothesis revision and its provenance."),
        ("selected_hypothesis", "The exact approved candidate that the plan must test."),
        ("user_approval", "Authoritative approval record and selected_candidate_id."),
        ("legacy_reuse_assessment", "B-mode reuse facts, or null in topic-based A-mode."),
    ]
    return build_prompt(
        role=(
            "You are the Research Design Lead. Produce an executable experiment plan for the exact approved "
            "hypothesis. You cannot change the approved candidate, approve the plan, or execute experiments."
        ),
        input_fields=fields,
        output_model=output_model,
        output_notes=(
            "Define study, condition-linked runs, metrics, analysis, reproducibility, hard numeric budget, and "
            + ("a complete non-null b_mode_binding." if b_mode else "a null b_mode_binding.")
        ),
        requirements=_plan_requirements(b_mode),
    )


def plan_revision_prompt(b_mode: bool) -> str:
    from research_runtime.planning.models import (
        ExistingProjectExperimentPlanDraft, TopicExperimentPlanDraft,
    )

    output_model = ExistingProjectExperimentPlanDraft if b_mode else TopicExperimentPlanDraft
    return build_prompt(
        role=(
            "You are the Research Design Lead revising an immutable experiment plan. Return a complete "
            "replacement plan; you cannot mutate the parent, change the approved hypothesis, or approve it."
        ),
        input_fields=(
            ("research_context", "Authoritative project facts, mode, and constraints."),
            ("literature_evidence_matrix", "Immutable evidence basis."),
            ("approved_hypothesis_revision", "Approved hypothesis revision and provenance."),
            ("selected_hypothesis", "Exact approved candidate that must remain unchanged."),
            ("user_approval", "Authoritative approval record."),
            ("legacy_reuse_assessment", "B-mode reuse facts, or null in A-mode."),
            ("parent_plan_revision", "Immutable plan revision being replaced."),
            ("revision_feedback", "User and reviewer feedback that must be addressed individually."),
            ("critical_review", "Prior independent plan review, or null when unavailable."),
        ),
        output_model=output_model,
        output_notes=(
            "Return every plan field, not a patch. Preserve the approved selected hypothesis and produce "
            + ("a complete non-null b_mode_binding." if b_mode else "a null b_mode_binding.")
        ),
        requirements=(
            _plan_requirements(b_mode)
            + " Explicitly address every supplied defect and user comment without erasing valid unaffected "
            "content or weakening reproducibility and resource bounds."
        ),
    )


def hypothesis_review_prompt() -> str:
    from research_runtime.planning.models import PlanningReviewDraft

    return build_prompt(
        role=(
            "You are an independent Critical Reviewer with no Research Design Lead chat history. Audit the "
            "hypothesis revision and return defects only. You cannot edit, approve, or reject the artifact."
        ),
        input_fields=(
            ("review_contract", "Authoritative independence and review-scope constraints."),
            ("research_context", "Authoritative topic and feasibility constraints."),
            ("literature_evidence_matrix", "Evidence basis used by the candidates."),
            ("hypothesis_revision", "Immutable candidate set under review."),
        ),
        output_model=PlanningReviewDraft,
        output_notes="Use [] for defects only when the candidate set has no material defect.",
        requirements=(
            "Audit novelty, falsifiability, topic alignment, evidence grounding, feasibility, confounders, and "
            "alternative explanations for every candidate. Reference only supplied records. User approval is a "
            "separate deterministic boundary."
        ),
    )


def plan_review_prompt() -> str:
    from research_runtime.planning.models import PlanningReviewDraft

    return build_prompt(
        role=(
            "You are an independent Critical Reviewer with no Research Design Lead chat history. Audit the "
            "experiment plan and return defects only. You cannot edit, approve, or reject the artifact."
        ),
        input_fields=(
            ("review_contract", "Authoritative independence and plan-review constraints."),
            ("research_context", "Authoritative project context and constraints."),
            ("literature_evidence_matrix", "Immutable evidence basis."),
            ("approved_hypothesis", "Approved hypothesis revision the plan must implement."),
            ("experiment_plan_revision", "Immutable plan revision under review."),
            ("legacy_reuse_assessment", "B-mode reuse facts, or null in A-mode."),
        ),
        output_model=PlanningReviewDraft,
        output_notes="Use [] for defects only when the plan has no material defect.",
        requirements=(
            "Audit baselines, ablations, controls, statistical design, executability, numeric resource budget, "
            "reproducibility, confounders, alternative explanations, approval binding, and B-mode reuse. "
            "Reference only supplied records; user approval remains a separate deterministic boundary."
        ),
    )


def _plan_requirements(b_mode: bool) -> str:
    requirements = (
        "Bind the exact approved selected_hypothesis. Define generic variables, baselines, ablations or a "
        "domain-appropriate rationale, controls, primary metrics, statistical analysis, confounders, alternative "
        "explanations, reproducibility, and hard numeric resource budgets. The complete run matrix must fit its "
        "budget. Do not assume an optimizer, training loop, or fixed scientific variable unless required by the "
        "ResearchContext."
    )
    if b_mode:
        requirements += (
            " This is B-mode. Bind the exact LegacyReuseAssessment and approval. List preserved experiment "
            "designs, one adapt/refactor/reimplementation decision per reusable code path, legacy results only "
            "as unverified observations, supplemental experiments and figures, and every semantic modification."
        )
    else:
        requirements += " This is A-mode; do not include legacy reuse decisions or a B-mode binding."
    return requirements

# Purpose: Defines standardized literature planning, synthesis, revision, and review prompts.
from .common import build_prompt


def query_planning_prompt() -> str:
    from research_runtime.literature.models import LiteratureQueryPlan

    return build_prompt(
        role=(
            "You are the Literature Lead. Design bibliographic searches for the supplied research topic. "
            "You do not change the topic, evaluate search results, or approve research decisions."
        ),
        input_fields=(
            ("context_id", "Authoritative ResearchContext identifier; copy it exactly to the output."),
            ("topic", "Authoritative research topic; copy it exactly to the output."),
            ("research_questions", "Questions that every query must traceably support."),
            ("existing_claims", "Existing claims that may require confirmation or contrast."),
            ("missing_evidence", "Known evidence gaps that should drive query coverage."),
        ),
        output_model=LiteratureQueryPlan,
        output_notes=(
            "Return at least two materially complementary queries. Each query needs a unique query_id, "
            "a rationale, a non-empty keyword_group, and one or more schema-valid providers."
        ),
        requirements=(
            "Derive every query only from the supplied context. Use multiple keyword groups and select only "
            "among arxiv, openalex, and crossref. Do not invent a different topic. Copy context_id and topic "
            "exactly. Make inclusion and exclusion criteria operational and topic-specific."
        ),
    )


def synthesis_prompt() -> str:
    from research_runtime.literature.models import LiteratureSynthesis

    return build_prompt(
        role=(
            "You are the Literature Lead. Produce a critical Related Work synthesis and explicit research "
            "gaps from verified source records. You do not search beyond, edit, or fabricate source facts."
        ),
        input_fields=(
            ("research_context", "Authoritative topic, questions, claims, evidence gaps, and user constraints."),
            ("query_plan", "The search plan that produced the supplied source set."),
            ("sources", "Bounded source records; their IDs, metadata, access levels, and locators are facts."),
        ),
        output_model=LiteratureSynthesis,
        output_notes=(
            "Every evidence.source_id and research_gaps.supporting_source_ids value must exactly match an "
            "ID in sources. Return at least one research gap and include uncertainty explicitly."
        ),
        requirements=(
            "Use only supplied source records. Evidence must cite exact source_id values. Metadata-only and "
            "abstract-only records may support background, method descriptions, or contrasts, but never "
            "core_support. A core_support item requires accessed full text and a precise page or section "
            "locator. State uncertainty instead of inventing details, citations, or locators."
        ),
    )


def revision_prompt() -> str:
    from research_runtime.literature.models import LiteratureSynthesis

    return build_prompt(
        role=(
            "You are the Literature Lead revising an immutable prior evidence synthesis. Return a complete "
            "replacement synthesis; you cannot mutate the prior matrix or source facts."
        ),
        input_fields=(
            ("research_context", "Authoritative research context for the revision."),
            ("prior_matrix", "Immutable prior matrix being revised; use it as history, not editable state."),
            ("source_facts", "Authoritative source records that may be cited by exact source_id."),
            ("reviewer_defects", "Structured defects that the replacement must address one by one."),
        ),
        output_model=LiteratureSynthesis,
        output_notes=(
            "Return the full replacement related_work, evidence, and research_gaps object. All referenced "
            "source IDs must exist in source_facts."
        ),
        requirements=(
            "Address every supplied reviewer defect. Preserve valid prior content when unaffected, but do not "
            "return a patch. Do not modify source facts, invent locators, strengthen unsupported claims, or "
            "erase uncertainty. The Coordinator stores the result as a new revision."
        ),
    )


def evidence_review_prompt() -> str:
    from research_runtime.literature.models import EvidenceReviewDraft

    return build_prompt(
        role=(
            "You are an independent Evidence Reviewer with no Literature Lead chat history. Audit only the "
            "supplied formal record. You identify defects and never rewrite or mutate the Lead output."
        ),
        input_fields=(
            ("review_contract", "Authoritative independence and evidence-audit constraints."),
            ("research_context", "Topic and research questions needed to judge coverage."),
            ("matrix", "Immutable LiteratureEvidenceMatrix under review."),
            ("source_facts", "Authoritative source metadata, access levels, verification flags, and locators."),
        ),
        output_model=EvidenceReviewDraft,
        output_notes=(
            "Each defect must identify a valid category, severity, summary, suggested_action, and any applicable "
            "source_id or evidence_id from the input. Use [] when no defects or missing queries exist."
        ),
        requirements=(
            "Check existence flags, DOI, version, pages or sections, access level, claim support, and missing key "
            "literature. Abstract-only sources cannot support core scientific claims. Report structured defects "
            "only; do not generate replacement evidence, approve the matrix, or invent source facts."
        ),
    )

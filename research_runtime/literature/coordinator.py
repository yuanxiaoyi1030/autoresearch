# Purpose: Deterministically coordinates two literature agents, isolated search, validation, and immutable revisions.
from __future__ import annotations

import re
from typing import List

from research_runtime.understanding import ResearchContext

from .agents import EvidenceReviewer, LiteratureLead, canonical_hash
from .models import (
    AccessLevel, EvidenceReviewReport, LiteratureAgentRole, LiteratureAgentRun,
    LiteratureEvidence, LiteratureEvidenceMatrix, LiteratureRunResult, LiteratureSource,
    LiteratureSynthesis, ResearchGap, identifier,
)
from .search import LiteratureSearchCoordinator


class LiteratureCoordinator:
    AGENT_COUNT = 2

    def __init__(self, repository, search: LiteratureSearchCoordinator, lead: LiteratureLead,
                 reviewer: EvidenceReviewer, *, max_parallel_agents: int = 2,
                 max_revision_rounds: int = 2, max_synthesis_sources: int = 24) -> None:
        if not 1 <= max_parallel_agents <= 2:
            raise ValueError("literature max_parallel_agents must be between 1 and 2")
        if not 0 <= max_revision_rounds <= 2:
            raise ValueError("literature max_revision_rounds must be between 0 and 2")
        if max_synthesis_sources < 2:
            raise ValueError("literature max_synthesis_sources must be at least 2")
        self.repository = repository
        self.search = search
        self.lead = lead
        self.reviewer = reviewer
        self.max_parallel_agents = max_parallel_agents
        self.max_revision_rounds = max_revision_rounds
        self.max_synthesis_sources = max_synthesis_sources
        self.search.on_attempt = repository.save_attempt

    def run(self, project_id: str, context: ResearchContext,
            *, allow_network: bool = True) -> LiteratureRunResult:
        if context.project_id != project_id:
            raise ValueError("research context does not belong to project")

        plan_response = self.lead.plan_queries(context)
        plan = plan_response.value.model_copy(update={
            "topic": context.topic or context.summary,
            "context_id": context.context_id,
        })
        # Revalidate after fixing authoritative identity fields.
        plan = type(plan).model_validate(plan.model_dump(mode="json"))
        self._validate_queries_derived(context, plan)
        plan_run = self._agent_run(
            project_id, context.context_id, LiteratureAgentRole.LEAD, "query_plan", 0,
            plan_response, "query_plan:" + canonical_hash(plan),
        )
        self.repository.save_agent_run(plan_run)

        sources, attempts = self.search.run(
            project_id, context, plan, allow_network=allow_network,
        )
        self.repository.save_sources(project_id, context.context_id, sources)
        synthesis_sources = self._select_synthesis_sources(sources)

        synthesis_response = self.lead.synthesize(context, plan, synthesis_sources)
        matrix = self._matrix(
            project_id, context, plan, synthesis_sources, synthesis_response.value, 0, None,
        )
        self.repository.save_matrix(matrix)
        synthesis_run = self._agent_run(
            project_id, context.context_id, LiteratureAgentRole.LEAD, "synthesis", 0,
            synthesis_response, matrix.matrix_id,
        )
        self.repository.save_agent_run(synthesis_run)

        reviews: List[EvidenceReviewReport] = []
        agent_runs = [plan_run, synthesis_run]
        while True:
            review_context = self._independent_review_context(context, matrix, synthesis_sources)
            review_hash = canonical_hash(review_context)
            review_response = self.reviewer.review(review_context)
            report = EvidenceReviewReport(
                project_id=project_id,
                context_id=context.context_id,
                matrix_id=matrix.matrix_id,
                revision=matrix.revision,
                defects=review_response.value.defects,
                missing_key_literature_queries=review_response.value.missing_key_literature_queries,
                reviewer_summary=review_response.value.reviewer_summary,
                independent_context_hash=review_hash,
            )
            self.repository.save_review(report)
            review_run = self._agent_run(
                project_id, context.context_id, LiteratureAgentRole.EVIDENCE_REVIEWER,
                "independent_review", matrix.revision, review_response, report.report_id,
                input_context_hash=review_hash,
            )
            self.repository.save_agent_run(review_run)
            reviews.append(report)
            agent_runs.append(review_run)

            if not report.requires_revision or matrix.revision >= self.max_revision_rounds:
                break
            revision_response = self.lead.revise(
                context, matrix, synthesis_sources, report.defects,
            )
            prior = matrix
            matrix = self._matrix(
                project_id, context, plan, synthesis_sources, revision_response.value,
                prior.revision + 1, prior.matrix_id,
            )
            self.repository.save_matrix(matrix)
            revision_run = self._agent_run(
                project_id, context.context_id, LiteratureAgentRole.LEAD, "revision",
                matrix.revision, revision_response, matrix.matrix_id,
            )
            self.repository.save_agent_run(revision_run)
            agent_runs.append(revision_run)

        return LiteratureRunResult(
            final_matrix=matrix,
            sources=sources,
            search_attempts=attempts,
            review_reports=reviews,
            agent_runs=agent_runs,
        )

    def _select_synthesis_sources(
        self, sources: List[LiteratureSource],
    ) -> List[LiteratureSource]:
        """Bound LLM context while retaining every discovered source in the audit record."""
        if len(sources) <= self.max_synthesis_sources:
            return list(sources)
        full_text = [
            source for source in sources
            if source.access_level in {AccessLevel.FULL_TEXT, AccessLevel.IMPORTED_PDF}
        ]
        remaining = [source for source in sources if source not in full_text]
        return (full_text + remaining)[:self.max_synthesis_sources]

    @staticmethod
    def _matrix(project_id: str, context: ResearchContext, plan, sources: List[LiteratureSource],
                synthesis: LiteratureSynthesis, revision: int,
                parent_matrix_id: str = None) -> LiteratureEvidenceMatrix:
        source_map = {source.source_id: source for source in sources}
        matrix_id = identifier("matrix_")
        evidence = []
        for draft in synthesis.evidence:
            source = source_map.get(draft.source_id)
            if source is None:
                raise ValueError(f"evidence references unknown source_id={draft.source_id}")
            evidence.append(LiteratureEvidence(
                project_id=project_id, context_id=context.context_id, matrix_id=matrix_id,
                source_id=draft.source_id, claim=draft.claim, support_summary=draft.support_summary,
                role=draft.role, source_access_level=source.access_level, locator=draft.locator,
            ))
        gaps = []
        for draft in synthesis.research_gaps:
            unknown = set(draft.supporting_source_ids) - set(source_map)
            if unknown:
                raise ValueError("research gap references unknown source_ids: " + ", ".join(sorted(unknown)))
            gaps.append(ResearchGap(
                project_id=project_id, context_id=context.context_id, matrix_id=matrix_id,
                statement=draft.statement, rationale=draft.rationale,
                supporting_source_ids=draft.supporting_source_ids, uncertainty=draft.uncertainty,
            ))
        return LiteratureEvidenceMatrix(
            matrix_id=matrix_id, project_id=project_id, context_id=context.context_id,
            revision=revision, parent_matrix_id=parent_matrix_id, query_plan=plan,
            source_ids=[source.source_id for source in sources], evidence=evidence,
            related_work=synthesis.related_work, research_gaps=gaps,
        )

    @staticmethod
    def _independent_review_context(context: ResearchContext, matrix: LiteratureEvidenceMatrix,
                                    sources: List[LiteratureSource]) -> dict:
        return {
            "review_contract": {
                "independent_context": True,
                "lead_chat_history_included": False,
                "checks": [
                    "existence", "doi", "version", "page_or_section", "access_level",
                    "claim_support", "missing_key_literature",
                ],
                "abstract_only_core_support_forbidden": True,
            },
            "research_context": {
                "context_id": context.context_id,
                "topic": context.topic,
                "summary": context.summary,
                "research_questions": context.research_questions,
            },
            "matrix": matrix.model_dump(mode="json"),
            "source_facts": [source.model_dump(mode="json") for source in sources],
        }

    @staticmethod
    def _agent_run(project_id, context_id, role, operation, revision, response,
                   output_artifact_id, input_context_hash=None) -> LiteratureAgentRun:
        return LiteratureAgentRun(
            project_id=project_id, context_id=context_id, role=role, operation=operation,
            revision=revision,
            input_context_hash=input_context_hash or response.input_context_hash,
            output_artifact_id=output_artifact_id, provider_id=response.provider_id,
            model=response.model, input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    @staticmethod
    def _validate_queries_derived(context: ResearchContext, plan) -> None:
        context_text = " ".join(filter(None, [
            context.topic, context.summary, *context.research_questions,
        ])).casefold()
        context_words = set(re.findall(r"[^\W_]{2,}", context_text, flags=re.UNICODE))
        context_compact = re.sub(r"\W+", "", context_text, flags=re.UNICODE)
        context_pairs = {context_compact[index:index + 2] for index in range(len(context_compact) - 1)}
        for item in plan.queries:
            query_text = " ".join([item.query, *item.keyword_group]).casefold()
            query_words = set(re.findall(r"[^\W_]{2,}", query_text, flags=re.UNICODE))
            query_compact = re.sub(r"\W+", "", query_text, flags=re.UNICODE)
            query_pairs = {query_compact[index:index + 2] for index in range(len(query_compact) - 1)}
            if not (context_words & query_words or context_pairs & query_pairs):
                raise ValueError(
                    f"literature query is not traceably derived from current ResearchContext: {item.query}"
                )

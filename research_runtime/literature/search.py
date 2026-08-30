# Purpose: Runs failure-isolated multi-source searches, imported-PDF discovery, deduplication, and ranking.
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import math
import re
from typing import Callable, Dict, Iterable, List, Optional, Tuple
import unicodedata

from research_runtime.understanding import MaterialKind, ResearchContext

from .clients import LiteratureSearchClient, normalize_arxiv_id, normalize_doi
from .models import (
    AccessLevel, LiteratureProvider, LiteratureQueryPlan, LiteratureSource, SearchAttempt,
    SearchAttemptStatus,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _title_key(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    words = set(re.findall(r"[^\W_]{2,}", normalized, flags=re.UNICODE))
    compact = re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)
    if any(ord(character) > 127 for character in compact):
        words.update(compact[index:index + 2] for index in range(len(compact) - 1))
    return words


class LiteratureSearchCoordinator:
    def __init__(self, clients: Dict[LiteratureProvider, LiteratureSearchClient], *,
                 max_workers: int = 2, per_query_limit: int = 10,
                 on_attempt: Optional[Callable[[SearchAttempt], None]] = None) -> None:
        if not 1 <= max_workers <= 2:
            raise ValueError("literature search max_workers must be between 1 and 2")
        self.clients = clients
        self.max_workers = max_workers
        self.per_query_limit = per_query_limit
        self.on_attempt = on_attempt

    def run(self, project_id: str, context: ResearchContext, plan: LiteratureQueryPlan,
            *, allow_network: bool = True) -> Tuple[List[LiteratureSource], List[SearchAttempt]]:
        sources: List[LiteratureSource] = self._imported_pdf_sources(context)
        attempts: List[SearchAttempt] = []
        jobs = []
        for query in plan.queries:
            for provider in query.providers:
                if provider is LiteratureProvider.IMPORTED_PDF:
                    continue
                jobs.append((query.query_id, query.query, provider))

        if not allow_network:
            for query_id, query_text, provider in jobs:
                attempt = SearchAttempt(
                    project_id=project_id, context_id=context.context_id, query_id=query_id,
                    provider=provider, query=query_text, status=SearchAttemptStatus.FAILED,
                    error_code="network_not_allowed",
                    error_message="External literature search was disabled for this run",
                    request_parameters={"limit": self.per_query_limit},
                )
                attempts.append(attempt)
                self._record(attempt)
            return self.rank(self.deduplicate(sources), plan), attempts

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="literature-search") as pool:
            futures = {
                pool.submit(self._one, project_id, context.context_id, *job): job
                for job in jobs
            }
            for future in as_completed(futures):
                result, attempt = future.result()
                sources.extend(result)
                attempts.append(attempt)
                self._record(attempt)
        attempts.sort(key=lambda item: (item.query_id, item.provider.value, item.started_at))
        return self.rank(self.deduplicate(sources), plan), attempts

    def _one(self, project_id: str, context_id: str, query_id: str, query_text: str,
             provider: LiteratureProvider) -> Tuple[List[LiteratureSource], SearchAttempt]:
        started = _now()
        client = self.clients.get(provider)
        if client is None:
            return [], SearchAttempt(
                project_id=project_id, context_id=context_id, query_id=query_id,
                provider=provider, query=query_text, status=SearchAttemptStatus.FAILED,
                request_parameters={"limit": self.per_query_limit}, error_code="client_unavailable",
                error_message=f"No client is configured for {provider.value}",
                started_at=started, finished_at=_now(),
            )
        try:
            results = client.search(query_text, self.per_query_limit)
            return results, SearchAttempt(
                project_id=project_id, context_id=context_id, query_id=query_id,
                provider=provider, query=query_text, status=SearchAttemptStatus.SUCCESS,
                result_count=len(results), request_parameters={"limit": self.per_query_limit},
                started_at=started, finished_at=_now(),
            )
        except Exception as exc:
            return [], SearchAttempt(
                project_id=project_id, context_id=context_id, query_id=query_id,
                provider=provider, query=query_text, status=SearchAttemptStatus.FAILED,
                request_parameters={"limit": self.per_query_limit},
                error_code=type(exc).__name__, error_message=str(exc)[:1000],
                started_at=started, finished_at=_now(),
            )

    def _record(self, attempt: SearchAttempt) -> None:
        if self.on_attempt:
            self.on_attempt(attempt)

    @staticmethod
    def _imported_pdf_sources(context: ResearchContext) -> List[LiteratureSource]:
        results = []
        for material in context.materials:
            if MaterialKind.PAPER not in material.kinds or not material.relative_path.lower().endswith(".pdf"):
                continue
            results.append(LiteratureSource(
                title=material.relative_path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                imported_relative_path=material.relative_path,
                access_level=AccessLevel.IMPORTED_PDF,
                origins=[LiteratureProvider.IMPORTED_PDF],
                provider_record_ids={LiteratureProvider.IMPORTED_PDF.value: material.sha256},
                existence_verified=True,
                metadata_verified=False,
            ))
        return results

    @staticmethod
    def deduplicate(sources: Iterable[LiteratureSource]) -> List[LiteratureSource]:
        merged: Dict[str, LiteratureSource] = {}
        aliases: Dict[str, str] = {}
        for source in sources:
            keys = []
            if normalize_doi(source.doi):
                keys.append("doi:" + normalize_doi(source.doi))
            if normalize_arxiv_id(source.arxiv_id):
                keys.append("arxiv:" + normalize_arxiv_id(source.arxiv_id).lower())
            keys.append("title:" + _title_key(source.title))
            canonical = next((aliases[key] for key in keys if key in aliases), None)
            if canonical is None:
                canonical = keys[0]
                merged[canonical] = source.model_copy(deep=True)
            else:
                merged[canonical] = LiteratureSearchCoordinator._merge(merged[canonical], source)
            for key in keys:
                aliases[key] = canonical
        return list(merged.values())

    @staticmethod
    def _merge(left: LiteratureSource, right: LiteratureSource) -> LiteratureSource:
        access_order = {
            AccessLevel.METADATA_ONLY: 0, AccessLevel.ABSTRACT_ONLY: 1,
            AccessLevel.FULL_TEXT: 2, AccessLevel.IMPORTED_PDF: 3,
        }
        preferred = right if access_order[right.access_level] > access_order[left.access_level] else left
        update = {
            "authors": left.authors or right.authors,
            "publication_year": left.publication_year or right.publication_year,
            "doi": normalize_doi(left.doi or right.doi),
            "arxiv_id": normalize_arxiv_id(left.arxiv_id or right.arxiv_id),
            "openalex_id": left.openalex_id or right.openalex_id,
            "version": left.version or right.version,
            "pages": left.pages or right.pages,
            "sections": list(dict.fromkeys(left.sections + right.sections)),
            "abstract": left.abstract or right.abstract,
            "landing_url": left.landing_url or right.landing_url,
            "full_text_url": left.full_text_url or right.full_text_url,
            "imported_relative_path": left.imported_relative_path or right.imported_relative_path,
            "access_level": preferred.access_level,
            "origins": list(dict.fromkeys(left.origins + right.origins)),
            "provider_record_ids": {**left.provider_record_ids, **right.provider_record_ids},
            "cited_by_count": max(left.cited_by_count, right.cited_by_count),
            "existence_verified": left.existence_verified or right.existence_verified,
            "metadata_verified": left.metadata_verified or right.metadata_verified,
        }
        return left.model_copy(update=update)

    @staticmethod
    def rank(sources: List[LiteratureSource], plan: LiteratureQueryPlan) -> List[LiteratureSource]:
        query_terms = _tokens(" ".join(query.query for query in plan.queries))
        ranked = []
        for source in sources:
            source_terms = _tokens(source.title + " " + (source.abstract or ""))
            overlap = len(query_terms & source_terms) / max(1, len(query_terms))
            citation_signal = math.log1p(source.cited_by_count) / 20.0
            verification = 0.1 if source.metadata_verified else 0.0
            source.relevance_score = round(overlap + citation_signal + verification, 6)
            ranked.append(source)
        return sorted(ranked, key=lambda item: (-item.relevance_score, item.title.casefold()))

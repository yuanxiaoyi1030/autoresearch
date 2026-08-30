# Purpose: Implements replaceable stdlib clients for arXiv, OpenAlex, and Crossref metadata searches.
from __future__ import annotations

from abc import ABC, abstractmethod
import html
import json
import re
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .models import AccessLevel, LiteratureProvider, LiteratureSource


Fetch = Callable[[Request, float], bytes]


def _default_fetch(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # nosec: endpoints are fixed by clients
        return response.read()


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", html.unescape(value))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().lower()
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized)
    return normalized.rstrip(".,") or None


def normalize_arxiv_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", normalized, flags=re.IGNORECASE)


class LiteratureSearchClient(ABC):
    provider: LiteratureProvider

    @abstractmethod
    def search(self, query: str, limit: int = 10, timeout: float = 20.0) -> List[LiteratureSource]:
        raise NotImplementedError


class ArxivClient(LiteratureSearchClient):
    provider = LiteratureProvider.ARXIV
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, fetch: Fetch = _default_fetch, user_agent: str = "AutoResearch/0.2") -> None:
        self.fetch = fetch
        self.user_agent = user_agent

    def search(self, query: str, limit: int = 10, timeout: float = 20.0) -> List[LiteratureSource]:
        parameters = {
            "search_query": f"all:{query}", "start": 0, "max_results": limit,
            "sortBy": "relevance", "sortOrder": "descending",
        }
        request = Request(
            self.endpoint + "?" + urlencode(parameters),
            headers={"User-Agent": self.user_agent, "Accept": "application/atom+xml"},
        )
        root = ET.fromstring(self.fetch(request, timeout))
        atom = "{http://www.w3.org/2005/Atom}"
        arxiv = "{http://arxiv.org/schemas/atom}"
        results: List[LiteratureSource] = []
        for entry in root.findall(atom + "entry"):
            raw_id = (entry.findtext(atom + "id") or "").strip()
            version_match = re.search(r"(v\d+)$", raw_id)
            published = entry.findtext(atom + "published") or ""
            doi = normalize_doi(entry.findtext(arxiv + "doi"))
            pdf_url = None
            for link in entry.findall(atom + "link"):
                if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                    pdf_url = link.attrib.get("href")
            authors = [
                (author.findtext(atom + "name") or "").strip()
                for author in entry.findall(atom + "author")
                if (author.findtext(atom + "name") or "").strip()
            ]
            abstract = _clean_text(entry.findtext(atom + "summary"))
            arxiv_id = normalize_arxiv_id(raw_id)
            results.append(LiteratureSource(
                title=_clean_text(entry.findtext(atom + "title")) or raw_id,
                authors=authors,
                publication_year=int(published[:4]) if published[:4].isdigit() else None,
                doi=doi,
                arxiv_id=arxiv_id,
                version=version_match.group(1) if version_match else None,
                abstract=abstract,
                landing_url=raw_id or None,
                full_text_url=pdf_url,
                # Search reads metadata/abstract only; a PDF link is availability, not evidence of reading.
                access_level=AccessLevel.ABSTRACT_ONLY if abstract else AccessLevel.METADATA_ONLY,
                origins=[self.provider],
                provider_record_ids={self.provider.value: arxiv_id or raw_id},
                existence_verified=True,
                metadata_verified=True,
            ))
        return results


class OpenAlexClient(LiteratureSearchClient):
    provider = LiteratureProvider.OPENALEX
    endpoint = "https://api.openalex.org/works"

    def __init__(self, fetch: Fetch = _default_fetch, api_key: Optional[str] = None,
                 user_agent: str = "AutoResearch/0.2") -> None:
        self.fetch = fetch
        self.api_key = api_key
        self.user_agent = user_agent

    def search(self, query: str, limit: int = 10, timeout: float = 20.0) -> List[LiteratureSource]:
        parameters = {"search": query, "per-page": limit}
        request = Request(
            self.endpoint + "?" + urlencode(parameters),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                **({"Authorization": "Bearer " + self.api_key} if self.api_key else {}),
            },
        )
        payload = json.loads(self.fetch(request, timeout).decode("utf-8"))
        results: List[LiteratureSource] = []
        for item in payload.get("results", []):
            abstract = self._abstract(item.get("abstract_inverted_index"))
            identifiers = item.get("ids") or {}
            location = item.get("best_oa_location") or {}
            openalex_id = (item.get("id") or identifiers.get("openalex") or "").rsplit("/", 1)[-1]
            authors = [
                ((authorship.get("author") or {}).get("display_name") or "").strip()
                for authorship in item.get("authorships") or []
                if ((authorship.get("author") or {}).get("display_name") or "").strip()
            ]
            results.append(LiteratureSource(
                title=_clean_text(item.get("title")) or openalex_id,
                authors=authors,
                publication_year=item.get("publication_year"),
                doi=normalize_doi(item.get("doi") or identifiers.get("doi")),
                openalex_id=openalex_id or None,
                abstract=abstract,
                landing_url=location.get("landing_page_url") or item.get("doi"),
                full_text_url=location.get("pdf_url"),
                access_level=AccessLevel.ABSTRACT_ONLY if abstract else AccessLevel.METADATA_ONLY,
                origins=[self.provider],
                provider_record_ids={self.provider.value: openalex_id},
                cited_by_count=item.get("cited_by_count") or 0,
                existence_verified=True,
                metadata_verified=True,
            ))
        return results

    @staticmethod
    def _abstract(index: Optional[Dict[str, Iterable[int]]]) -> Optional[str]:
        if not index:
            return None
        positions = [(position, word) for word, values in index.items() for position in values]
        return " ".join(word for _, word in sorted(positions)) or None


class CrossrefClient(LiteratureSearchClient):
    provider = LiteratureProvider.CROSSREF
    endpoint = "https://api.crossref.org/works"

    def __init__(self, fetch: Fetch = _default_fetch, user_agent: str = "AutoResearch/0.2") -> None:
        self.fetch = fetch
        self.user_agent = user_agent

    def search(self, query: str, limit: int = 10, timeout: float = 20.0) -> List[LiteratureSource]:
        parameters = {"query.bibliographic": query, "rows": limit}
        request = Request(
            self.endpoint + "?" + urlencode(parameters),
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        payload = json.loads(self.fetch(request, timeout).decode("utf-8"))
        results: List[LiteratureSource] = []
        for item in (payload.get("message") or {}).get("items", []):
            doi = normalize_doi(item.get("DOI"))
            title_values = item.get("title") or []
            date_parts = ((item.get("published-print") or item.get("published-online") or {}).get("date-parts") or [])
            authors = []
            for author in item.get("author") or []:
                name = " ".join(part for part in [author.get("given"), author.get("family")] if part)
                if name:
                    authors.append(name)
            abstract = _clean_text(item.get("abstract"))
            results.append(LiteratureSource(
                title=_clean_text(title_values[0] if title_values else None) or doi or "Untitled work",
                authors=authors,
                publication_year=date_parts[0][0] if date_parts and date_parts[0] else None,
                doi=doi,
                pages=item.get("page"),
                abstract=abstract,
                landing_url=item.get("URL"),
                access_level=AccessLevel.ABSTRACT_ONLY if abstract else AccessLevel.METADATA_ONLY,
                origins=[self.provider],
                provider_record_ids={self.provider.value: doi or item.get("URL", "")},
                cited_by_count=item.get("is-referenced-by-count") or 0,
                existence_verified=True,
                metadata_verified=True,
            ))
        return results


def default_clients(openalex_api_key: Optional[str] = None) -> Dict[LiteratureProvider, LiteratureSearchClient]:
    return {
        LiteratureProvider.ARXIV: ArxivClient(),
        LiteratureProvider.OPENALEX: OpenAlexClient(api_key=openalex_api_key),
        LiteratureProvider.CROSSREF: CrossrefClient(),
    }

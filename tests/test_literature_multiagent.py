# Purpose: Verifies generic multi-source literature search, evidence boundaries, independent review, revisions, and persistence.
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import Settings
from research_runtime.literature import (
    AccessLevel, AgentResponse, CitationLocator, DefectSeverity, EvidenceDraft,
    EvidenceReviewDraft, EvidenceReviewer, EvidenceRole, LiteratureLead, LiteratureProvider,
    LiteratureQuery, LiteratureQueryPlan, LiteratureSearchClient, LiteratureSearchCoordinator,
    LiteratureSource, LiteratureSynthesis, ResearchGapDraft, ReviewDefect,
    ReviewDefectCategory,
)
from research_runtime.literature.models import LiteratureEvidence
from research_runtime.literature.clients import ArxivClient, CrossrefClient, OpenAlexClient
from research_runtime.understanding import (
    MaterialKind, ResearchContext, ResearchMaterial, UnderstandingMode,
)


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


class ScriptedSearchClient(LiteratureSearchClient):
    def __init__(self, provider, factory=None, error=None):
        self.provider = provider
        self.factory = factory
        self.error = error

    def search(self, query: str, limit: int = 10, timeout: float = 20.0):
        if self.error:
            raise self.error
        return self.factory(query)


class ScriptedLead(LiteratureLead):
    def __init__(self):
        self.context_topics = []
        self.revised_parent_ids = []

    def plan_queries(self, context):
        topic = context.topic or context.summary
        self.context_topics.append(topic)
        return AgentResponse(LiteratureQueryPlan(
            topic=topic,
            context_id=context.context_id,
            queries=[
                LiteratureQuery(
                    query=topic + " mechanisms", rationale="Find mechanisms",
                    keyword_group=[topic, "mechanisms"],
                ),
                LiteratureQuery(
                    query=topic + " empirical evaluation", rationale="Find evaluations",
                    keyword_group=[topic, "evaluation"],
                ),
            ],
            inclusion_criteria=["Directly relevant empirical or methodological work"],
        ), "1" * 64)

    def synthesize(self, context, plan, sources):
        return AgentResponse(self._synthesis(context, sources, "initial synthesis"), "2" * 64)

    def revise(self, context, matrix, sources, defects):
        self.revised_parent_ids.append(matrix.matrix_id)
        return AgentResponse(
            self._synthesis(context, sources, f"revised synthesis {matrix.revision + 1}"),
            str(matrix.revision + 3) * 64,
        )

    @staticmethod
    def _synthesis(context, sources, related_work):
        first = sources[0]
        return LiteratureSynthesis(
            related_work=related_work,
            evidence=[EvidenceDraft(
                source_id=first.source_id,
                claim="Prior literature discusses a relevant relationship.",
                support_summary="Only the indexed abstract is available, so this is background evidence.",
                role=EvidenceRole.BACKGROUND,
            )],
            research_gaps=[ResearchGapDraft(
                statement="The target setting remains insufficiently evaluated.",
                rationale="The retrieved records do not directly resolve the project question.",
                supporting_source_ids=[first.source_id],
                uncertainty="The gap may narrow after full-text reading and broader retrieval.",
            )],
        )


class ScriptedReviewer(EvidenceReviewer):
    def __init__(self):
        self.contexts = []

    def review(self, independent_context):
        self.contexts.append(independent_context)
        revision = independent_context["matrix"]["revision"]
        defects = [] if revision >= 2 else [ReviewDefect(
            category=ReviewDefectCategory.SYNTHESIS,
            severity=DefectSeverity.MAJOR,
            summary=f"Revision {revision} needs a clearer boundary.",
            suggested_action="State the evidence limitation explicitly.",
        )]
        return AgentResponse(EvidenceReviewDraft(
            defects=defects,
            reviewer_summary="Independent structured audit complete.",
        ), "f" * 64)


class LiteratureMultiAgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.settings = Settings(
            runtime_root=self.root / "runtime", allowed_import_roots=[self.allowed],
        )
        self.lead = ScriptedLead()
        self.reviewer = ScriptedReviewer()
        self.clients = {
            LiteratureProvider.ARXIV: ScriptedSearchClient(
                LiteratureProvider.ARXIV, self._arxiv_results,
            ),
            LiteratureProvider.OPENALEX: ScriptedSearchClient(
                LiteratureProvider.OPENALEX, self._openalex_results,
            ),
            LiteratureProvider.CROSSREF: ScriptedSearchClient(
                LiteratureProvider.CROSSREF, error=RuntimeError("temporary Crossref outage"),
            ),
        }
        self.app = create_app(
            self.settings, literature_clients=self.clients,
            literature_lead=self.lead, evidence_reviewer=self.reviewer,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_multi_query_multi_source_failure_isolation_review_and_persistence(self):
        topic = "Urban tree canopy effects on pedestrian heat exposure"
        project = self.client.post("/api/projects", json={
            "title": "Heat exposure study", "project_type": "topic_based", "topic": topic,
        })
        project_id = project.json()["project"]["project_id"]
        understood = self.client.post(
            f"/api/projects/{project_id}/understanding",
            json={"constraints": {"network_allowed": True}},
        )
        self.assertEqual(understood.status_code, 201, understood.text)

        response = self.client.post(
            f"/api/projects/{project_id}/literature", json={"allow_network": True},
        )
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        matrix = result["final_matrix"]
        self.assertEqual(matrix["revision"], 2)
        self.assertEqual(matrix["query_plan"]["topic"], topic)
        self.assertEqual(len(matrix["query_plan"]["queries"]), 2)
        self.assertTrue(all(topic in item["query"] for item in matrix["query_plan"]["queries"]))
        self.assertEqual(self.lead.context_topics, [topic])

        attempts = result["search_attempts"]
        self.assertEqual(len(attempts), 6)
        failures = [item for item in attempts if item["status"] == "failed"]
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(item["provider"] == "crossref" for item in failures))
        self.assertTrue(result["sources"], "one provider failure discarded successful sources")
        duplicate = next(item for item in result["sources"] if item["doi"] == "10.1000/tree.1")
        self.assertEqual(set(duplicate["origins"]), {"arxiv", "openalex"})
        self.assertEqual(duplicate["access_level"], "abstract_only")

        self.assertEqual(len(result["review_reports"]), 3)
        self.assertEqual(len(self.lead.revised_parent_ids), 2)
        self.assertTrue(all(
            context["review_contract"]["lead_chat_history_included"] is False
            for context in self.reviewer.contexts
        ))
        self.assertTrue(all(len(report["independent_context_hash"]) == 64
                            for report in result["review_reports"]))
        self.assertEqual({run["role"] for run in result["agent_runs"]},
                         {"literature_lead", "evidence_reviewer"})
        self.assertEqual(self.app.state.services.literature.AGENT_COUNT, 2)
        self.assertLessEqual(self.app.state.services.literature.max_parallel_agents, 2)

        history = self.client.get(f"/api/projects/{project_id}/literature/history").json()
        self.assertEqual([item["revision"] for item in history], [0, 1, 2])
        self.assertEqual(history[0]["related_work"], "initial synthesis")
        self.assertEqual(history[1]["parent_matrix_id"], history[0]["matrix_id"])
        self.assertEqual(history[2]["parent_matrix_id"], history[1]["matrix_id"])
        self.assertEqual(len(self.client.get(
            f"/api/projects/{project_id}/literature/search-attempts"
        ).json()), 6)
        self.assertEqual(len(self.client.get(
            f"/api/projects/{project_id}/literature/evidence"
        ).json()), 3)
        self.assertEqual(len(self.client.get(
            f"/api/projects/{project_id}/literature/gaps"
        ).json()), 3)

        with TestClient(create_app(self.settings)) as restarted:
            latest = restarted.get(f"/api/projects/{project_id}/literature")
            self.assertEqual(latest.status_code, 200, latest.text)
            self.assertEqual(latest.json()["matrix_id"], matrix["matrix_id"])
            self.assertEqual(len(restarted.get(
                f"/api/projects/{project_id}/literature/reviews"
            ).json()), 3)

    def test_access_level_core_claim_and_citation_locator_boundaries(self):
        with self.assertRaisesRegex(ValueError, "cannot support core"):
            LiteratureEvidence(
                project_id="project", context_id="context", source_id="source",
                claim="A core claim", support_summary="Abstract statement",
                role=EvidenceRole.CORE_SUPPORT,
                source_access_level=AccessLevel.ABSTRACT_ONLY,
                locator=CitationLocator(section="Results"),
            )
        with self.assertRaisesRegex(ValueError, "precise citation locator"):
            LiteratureEvidence(
                project_id="project", context_id="context", source_id="source",
                claim="A core claim", support_summary="Full text statement",
                role=EvidenceRole.CORE_SUPPORT,
                source_access_level=AccessLevel.FULL_TEXT,
                locator=CitationLocator(version="v2"),
            )
        accepted = LiteratureEvidence(
            project_id="project", context_id="context", source_id="source",
            claim="A core claim", support_summary="Located in full text",
            role=EvidenceRole.CORE_SUPPORT, source_access_level=AccessLevel.FULL_TEXT,
            locator=CitationLocator(version="v2", pages="4-5", section="3. Results"),
        )
        self.assertEqual(accepted.locator.version, "v2")
        self.assertEqual(accepted.locator.pages, "4-5")

    def test_deduplication_uses_doi_arxiv_then_normalized_title(self):
        sources = [
            LiteratureSource(
                title="A Study: Of Sensors", doi="https://doi.org/10.42/ABC",
                origins=[LiteratureProvider.CROSSREF],
            ),
            LiteratureSource(
                title="Different provider title", doi="10.42/abc",
                abstract="Abstract", origins=[LiteratureProvider.OPENALEX],
            ),
            LiteratureSource(
                title="Another preprint", arxiv_id="2401.00001v3",
                origins=[LiteratureProvider.ARXIV],
            ),
            LiteratureSource(
                title="Another preprint revised", arxiv_id="2401.00001v4",
                origins=[LiteratureProvider.OPENALEX],
            ),
            LiteratureSource(
                title="A  Study of Sensors", origins=[LiteratureProvider.ARXIV],
            ),
        ]
        deduped = LiteratureSearchCoordinator.deduplicate(sources)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].doi, "10.42/abc")
        self.assertEqual(deduped[0].access_level, AccessLevel.ABSTRACT_ONLY)
        self.assertEqual(deduped[1].arxiv_id, "2401.00001")
        unicode_sources = LiteratureSearchCoordinator.deduplicate([
            LiteratureSource(
                title="城市树冠：热暴露", origins=[LiteratureProvider.CROSSREF],
            ),
            LiteratureSource(
                title="城市树冠 热暴露", origins=[LiteratureProvider.OPENALEX],
            ),
            LiteratureSource(
                title="传感网络纠错", origins=[LiteratureProvider.ARXIV],
            ),
        ])
        self.assertEqual(len(unicode_sources), 2)

    def test_synthesis_source_selection_is_bounded_and_prefers_full_text(self):
        sources = [
            LiteratureSource(
                title=f"Ranked metadata source {index}",
                origins=[LiteratureProvider.CROSSREF],
                relevance_score=1.0 - index / 100,
            )
            for index in range(30)
        ]
        full_text = LiteratureSource(
            title="Lower-ranked full text source",
            origins=[LiteratureProvider.OPENALEX],
            access_level=AccessLevel.FULL_TEXT,
            relevance_score=0.01,
        )
        sources.append(full_text)
        coordinator = self.app.state.services.literature

        selected = coordinator._select_synthesis_sources(sources)

        self.assertEqual(len(selected), coordinator.max_synthesis_sources)
        self.assertIn(full_text, selected)
        self.assertEqual(len(sources), 31, "selection must not discard the audit source list")

    def test_provider_contract_parsers_label_only_content_actually_read(self):
        arxiv_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry><id>http://arxiv.org/abs/2401.12345v2</id><updated>2024-02-01T00:00:00Z</updated>
          <published>2024-01-01T00:00:00Z</published><title> Example preprint </title>
          <summary> An abstract. </summary><author><name>First Author</name></author>
          <arxiv:doi>https://doi.org/10.55/EXAMPLE</arxiv:doi>
          <link title="pdf" href="https://arxiv.org/pdf/2401.12345" type="application/pdf"/></entry>
        </feed>'''
        arxiv = ArxivClient(fetch=lambda request, timeout: arxiv_xml).search("example")
        self.assertEqual(arxiv[0].arxiv_id, "2401.12345")
        self.assertEqual(arxiv[0].version, "v2")
        self.assertEqual(arxiv[0].doi, "10.55/example")
        self.assertEqual(arxiv[0].access_level, AccessLevel.ABSTRACT_ONLY)
        self.assertTrue(arxiv[0].full_text_url)

        openalex_json = b'''{"results":[{"id":"https://openalex.org/W123","title":"Indexed work",
          "publication_year":2023,"doi":"https://doi.org/10.66/OA",
          "abstract_inverted_index":{"Indexed":[0],"abstract":[1]},
          "authorships":[{"author":{"display_name":"OA Author"}}],"cited_by_count":7,
          "best_oa_location":{"pdf_url":"https://example.org/work.pdf"}}]}'''
        openalex = OpenAlexClient(fetch=lambda request, timeout: openalex_json).search("indexed")
        self.assertEqual(openalex[0].abstract, "Indexed abstract")
        self.assertEqual(openalex[0].openalex_id, "W123")
        self.assertEqual(openalex[0].access_level, AccessLevel.ABSTRACT_ONLY)

        crossref_json = b'''{"message":{"items":[{"DOI":"10.77/CR","title":["Crossref work"],
          "published-online":{"date-parts":[[2022,4,3]]},"page":"12-19",
          "author":[{"given":"C","family":"Author"}],"URL":"https://doi.org/10.77/CR"}]}}'''
        crossref = CrossrefClient(fetch=lambda request, timeout: crossref_json).search("crossref")
        self.assertEqual(crossref[0].doi, "10.77/cr")
        self.assertEqual(crossref[0].pages, "12-19")
        self.assertEqual(crossref[0].access_level, AccessLevel.METADATA_ONLY)

    def test_imported_pdf_is_distinct_and_network_denials_are_auditable(self):
        context = ResearchContext(
            project_id="project", mode=UnderstandingMode.EXISTING_PROJECT,
            import_id="import", manifest_hash="a" * 64,
            summary="An existing marine ecology project",
            research_questions=["How do marine heatwaves affect recruitment?"],
            materials=[ResearchMaterial(
                relative_path="papers/reference.pdf", sha256="b" * 64, size_bytes=100,
                media_type="application/pdf", kinds=[MaterialKind.PAPER],
            )],
        )
        plan = LiteratureQueryPlan(
            topic=context.summary, context_id=context.context_id,
            queries=[
                LiteratureQuery(
                    query="marine heatwaves recruitment", rationale="primary",
                    keyword_group=["marine heatwaves"],
                    providers=[LiteratureProvider.IMPORTED_PDF],
                ),
                LiteratureQuery(
                    query="ocean warming juvenile survival", rationale="complementary",
                    keyword_group=["ocean warming"],
                    providers=[LiteratureProvider.ARXIV, LiteratureProvider.OPENALEX],
                ),
            ],
        )
        search = LiteratureSearchCoordinator({}, max_workers=2)
        sources, attempts = search.run("project", context, plan, allow_network=False)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].access_level, AccessLevel.IMPORTED_PDF)
        self.assertEqual(sources[0].imported_relative_path, "papers/reference.pdf")
        self.assertEqual(len(attempts), 2)
        self.assertTrue(all(item.error_code == "network_not_allowed" for item in attempts))
        self.assertEqual(
            {item.provider for item in attempts},
            {LiteratureProvider.ARXIV, LiteratureProvider.OPENALEX},
        )

    def test_unconfigured_llm_is_explicit_and_schema_is_upgraded(self):
        unconfigured_settings = Settings(
            runtime_root=self.root / "unconfigured_runtime",
            allowed_import_roots=[self.allowed],
        )
        with TestClient(create_app(unconfigured_settings)) as client:
            created = client.post("/api/projects", json={
                "title": "Archive preservation", "project_type": "topic_based",
                "topic": "Predictors of archival manuscript preservation",
            })
            project_id = created.json()["project"]["project_id"]
            self.assertEqual(client.post(
                f"/api/projects/{project_id}/understanding", json={}
            ).status_code, 201)
            response = client.post(
                f"/api/projects/{project_id}/literature", json={"allow_network": False},
            )
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn("No LLM route", response.text)
            with client.app.state.services.database.connect() as connection:
                version = connection.execute("SELECT version FROM schema_meta").fetchone()["version"]
                tables = {
                    row["name"] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertEqual(version, 9)
            self.assertTrue({
                "literature_search_attempts", "literature_sources", "literature_matrices",
                "literature_evidence", "research_gaps", "evidence_review_reports",
                "literature_agent_runs",
                "hypothesis_revisions", "experiment_plan_revisions",
                "planning_review_reports", "planning_approvals", "planning_agent_runs",
                "implementation_revisions", "studies", "experiment_runs",
                "experiment_artifacts", "experiment_agent_runs",
                "visualization_profile_approvals",
                "analysis_records", "analysis_artifacts", "verification_reports",
                "scientific_review_reports", "analysis_agent_runs",
                "evidence_claims", "research_specialist_reviews",
                "research_meta_reviews", "research_policy_decisions",
                "research_review_records", "research_review_agent_runs",
                "research_review_transitions",
                "paper_revisions", "paper_review_reports", "paper_quality_reports",
                "paper_builds", "paper_artifacts", "paper_agent_runs", "paper_records",
            } <= tables)

    @staticmethod
    def _arxiv_results(query):
        return [LiteratureSource(
            title="Trees and thermal exposure", authors=["A. Author"],
            publication_year=2024, doi="10.1000/tree.1", arxiv_id="2401.12345",
            version="v2", abstract="Tree canopy and thermal exposure are studied.",
            access_level=AccessLevel.ABSTRACT_ONLY,
            origins=[LiteratureProvider.ARXIV],
            provider_record_ids={"arxiv": "2401.12345"},
            existence_verified=True, metadata_verified=True,
        )]

    @staticmethod
    def _openalex_results(query):
        return [
            LiteratureSource(
                title="Trees & thermal exposure", authors=["A. Author"],
                publication_year=2024, doi="https://doi.org/10.1000/TREE.1",
                abstract="An indexed duplicate abstract.", access_level=AccessLevel.ABSTRACT_ONLY,
                origins=[LiteratureProvider.OPENALEX],
                provider_record_ids={"openalex": "W1"}, cited_by_count=12,
                existence_verified=True, metadata_verified=True,
            ),
            LiteratureSource(
                title="Pedestrian microclimate field methods", publication_year=2022,
                doi="10.1000/micro.2", access_level=AccessLevel.METADATA_ONLY,
                origins=[LiteratureProvider.OPENALEX],
                provider_record_ids={"openalex": "W2"}, existence_verified=True,
                metadata_verified=True,
            ),
        ]


if __name__ == "__main__":
    unittest.main()

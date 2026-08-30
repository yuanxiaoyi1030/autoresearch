# Purpose: Verifies five-role paper writing, bounded revision, evidence gates, conference templates, and real PDF build QA.
import uuid
import os
import json
from pathlib import Path
import shutil
import unittest

from fastapi.testclient import TestClient

from apps.backend.main import create_app
from research_runtime.config import Settings
from research_runtime.literature import (
    AccessLevel, CitationLocator, EvidenceRole, LiteratureEvidence, LiteratureProvider,
    LiteratureSource,
)
from research_runtime.planning import canonical_hash
from research_runtime.writing import (
    CitationEditorDraft, CitationUseDraft, ConferenceTarget, ConferenceTemplateConfig,
    ContributionDraft, LeadAuthor, LeadAuthorDraft, NoveltyClaimDraft, PaperAgentResponse,
    PaperDefectSeverity, PaperNumberBindingDraft, PaperReviewDefect,
    PaperReviewRecommendation, PaperRevision, PaperSectionDraft, PaperSectionName,
    PresentationDraft, PresentationLatexEditor, RelatedWorkCitationEditor, TableDraft,
    TechnicalContentDraft, TechnicalContentEditor, TopConferenceReviewer,
    TopConferenceReviewDraft, TopConferenceScores,
)
from tests import test_analysis_review as analysis_helpers
from tests import test_hypothesis_planning as planning_helpers
from tests import test_independent_research_review as review_helpers
from tests import test_study_runtime as study_helpers


class ScriptedLeadAuthor(LeadAuthor):
    def __init__(self):
        self.contexts = []

    def author(self, context):
        self.contexts.append(context)
        claim_id = context["evidence_claims"][0]["claim_id"]
        value = LeadAuthorDraft(
            title="Evidence-Bound Evaluation of a Generic Research Intervention",
            abstract="We present a fully traceable evaluation under the approved study design.",
            contributions=[ContributionDraft(
                statement="A deterministic and reproducible evaluation of the approved intervention.",
                claim_ids=[claim_id],
            )],
            outline=list(PaperSectionName),
            narrative="The paper connects the approved question, method, evidence, and bounded conclusion.",
            terminology={"intervention": "the approved non-baseline condition"},
            notation={"delta": "the pre-specified effect estimate"},
            sections=[
                PaperSectionDraft(
                    section=PaperSectionName.INTRODUCTION, title="Introduction",
                    paragraphs=["The approved question is evaluated with immutable provenance."],
                ),
                PaperSectionDraft(
                    section=PaperSectionName.CONCLUSION, title="Conclusion",
                    paragraphs=["The conclusion is restricted to the reviewed evidence package."],
                ),
            ],
        )
        return PaperAgentResponse(value, canonical_hash(context))


class ScriptedTechnicalEditor(TechnicalContentEditor):
    def __init__(self):
        self.contexts = []

    def edit(self, context):
        self.contexts.append(context)
        comparison = context["analysis"]["payload"]["comparisons"][0]
        literal = str(comparison["effect_estimate"])
        artifact = next(
            item for item in context["analysis_artifacts"] if item["kind"] == "machine_json"
        )
        binding = PaperNumberBindingDraft(
            binding_id="number_effect", literal=literal, artifact_id=artifact["artifact_id"],
            locator="payload.comparisons[0].effect_estimate", section=PaperSectionName.RESULTS,
        )
        sections = [
            PaperSectionDraft(section=PaperSectionName.METHOD, title="Method",
                              paragraphs=["The method follows the immutable approved intervention and baseline."]),
            PaperSectionDraft(section=PaperSectionName.THEORY, title="Theory",
                              paragraphs=["The analysis targets the pre-specified estimand under stated assumptions."]),
            PaperSectionDraft(section=PaperSectionName.EXPERIMENTAL_SETUP, title="Experimental Setup",
                              paragraphs=["Runs, configurations, environments, and seeds are retained as Artifacts."]),
            PaperSectionDraft(section=PaperSectionName.RESULTS, title="Results",
                              paragraphs=["The verified effect estimate is {{num:number_effect}}."]),
            PaperSectionDraft(section=PaperSectionName.ANALYSIS, title="Analysis",
                              paragraphs=["Interpretation retains uncertainty, missingness, and alternative explanations."]),
        ]
        return PaperAgentResponse(TechnicalContentDraft(
            sections=sections, number_bindings=[binding],
            method_assumptions=["The approved sampling and comparison structure applies."],
            analysis_boundaries=["No extrapolation beyond the approved conditions."],
        ), canonical_hash(context))


class ScriptedCitationEditor(RelatedWorkCitationEditor):
    def __init__(self):
        self.contexts = []

    def edit(self, context):
        self.contexts.append(context)
        source = context["eligible_sources"][0]
        evidence = next(
            item for item in context["eligible_literature_evidence"]
            if item["source_id"] == source["source_id"]
        )
        locator = CitationLocator.model_validate(evidence["locator"])
        value = CitationEditorDraft(
            introduction=PaperSectionDraft(
                section=PaperSectionName.INTRODUCTION, title="Introduction",
                paragraphs=["Prior verified work motivates the bounded research question."],
            ),
            related_work=PaperSectionDraft(
                section=PaperSectionName.RELATED_WORK, title="Related Work",
                paragraphs=["The closest verified study provides a concrete comparison point."],
            ),
            citation_uses=[CitationUseDraft(
                source_id=source["source_id"], evidence_id=evidence["evidence_id"],
                section=PaperSectionName.RELATED_WORK,
                purpose="Position the approved contribution against verified prior work.",
                locator=locator,
            )],
            novelty_claims=[NoveltyClaimDraft(
                statement="The contribution differs in its immutable evidence binding.",
                supporting_evidence_ids=[evidence["evidence_id"]],
                contrasting_source_ids=[source["source_id"]],
            )],
        )
        return PaperAgentResponse(value, canonical_hash(context))


class ScriptedPresentationEditor(PresentationLatexEditor):
    def __init__(self):
        self.contexts = []

    def edit(self, context):
        self.contexts.append(context)
        source_artifact = context["analysis_artifacts"][0]["artifact_id"] if "analysis_artifacts" in context else None
        # The service auto-selects the verified primary analysis figure when this list is empty.
        value = PresentationDraft(
            figures=[],
            tables=[TableDraft(
                label="tab:evidence", caption="Evidence provenance summary.",
                columns=["Component", "Status"], rows=[["Analysis", "Verified"]],
                source_artifact_ids=[source_artifact] if source_artifact else ["analysis-record"],
            )],
            algorithms=[],
            appendix_sections=[PaperSectionDraft(
                section=PaperSectionName.APPENDIX, title="Additional Reproducibility Details",
                paragraphs=["The appendix records the bounded execution and verification protocol."],
            )],
            reproducibility_statement=(
                "Code, configuration, environment, Artifact hashes, and seed assignments are retained "
                "with the immutable Study and Analysis records."
            ),
            limitations=PaperSectionDraft(
                section=PaperSectionName.LIMITATIONS, title="Limitations",
                paragraphs=["The result is limited to the approved conditions and available evidence."],
            ),
            broader_impact=PaperSectionDraft(
                section=PaperSectionName.BROADER_IMPACT, title="Broader Impact",
                paragraphs=["Use should preserve uncertainty and avoid unsupported deployment claims."],
            ),
        )
        return PaperAgentResponse(value, canonical_hash(context))


class ScriptedTopReviewer(TopConferenceReviewer):
    def __init__(self):
        self.contexts = []

    def review(self, context):
        self.contexts.append(context)
        if len(self.contexts) == 1:
            recommendation = PaperReviewRecommendation.REVISE
            defects = [PaperReviewDefect(
                category="clarity", severity=PaperDefectSeverity.MAJOR,
                summary="Clarify how the conclusion remains bounded.",
                section=PaperSectionName.CONCLUSION,
                required_change="Carry the deterministic outcome boundary into the conclusion.",
            )]
        else:
            recommendation = PaperReviewRecommendation.READY
            defects = []
        value = TopConferenceReviewDraft(
            scores=TopConferenceScores(
                novelty=7, correctness=8, rigor=8, significance=7,
                clarity=8, reproducibility=9, limitations=8, broader_impact=8,
            ),
            recommendation=recommendation,
            summary="The manuscript is assessed against evidence and venue criteria.",
            strengths=["Immutable evidence binding and explicit uncertainty."], defects=defects,
        )
        return PaperAgentResponse(value, canonical_hash(context))


class PaperWritingTests(unittest.TestCase):
    _approved_topic_plan = study_helpers.StudyRuntimeTests._approved_topic_plan
    _approved_b_plan = study_helpers.StudyRuntimeTests._approved_b_plan
    _approve_planning = study_helpers.StudyRuntimeTests._approve_planning
    _seed_literature = study_helpers.StudyRuntimeTests._seed_literature
    _wait = study_helpers.StudyRuntimeTests._wait
    _wait_for_status = study_helpers.StudyRuntimeTests._wait_for_status
    _completed_study = analysis_helpers.AnalysisReviewTests._completed_study
    _execute_plan = analysis_helpers.AnalysisReviewTests._execute_plan
    _analysis = review_helpers.IndependentResearchReviewTests._analysis
    _review = review_helpers.IndependentResearchReviewTests._review
    _advance_to_review = review_helpers.IndependentResearchReviewTests._advance_to_review
    _fingerprint = staticmethod(study_helpers.StudyRuntimeTests._fingerprint)

    def setUp(self):
        self.temporary = __import__("tempfile").TemporaryDirectory(dir=study_helpers.TEST_TEMP_ROOT)
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.settings = Settings(runtime_root=self.root / "runtime", allowed_import_roots=[self.allowed])
        self.lead = ScriptedLeadAuthor()
        self.technical = ScriptedTechnicalEditor()
        self.citation = ScriptedCitationEditor()
        self.presentation = ScriptedPresentationEditor()
        self.top_reviewer = ScriptedTopReviewer()
        self.app = create_app(
            self.settings,
            research_design_lead=planning_helpers.ScriptedDesignLead(),
            critical_reviewer=planning_helpers.ScriptedCriticalReviewer(),
            experimental_lead=study_helpers.ScriptedExperimentalLead(),
            research_engineer=analysis_helpers.AnalysisResearchEngineer(),
            scientific_reviewer=analysis_helpers.ProceedingScientificReviewer(),
            meta_reviewer=review_helpers.ScriptedMetaReviewer(),
            methodology_reviewer=review_helpers.ScriptedMethodologyReviewer(),
            statistical_reviewer=review_helpers.ScriptedStatisticalReviewer(),
            research_evidence_reviewer=review_helpers.ScriptedEvidenceReviewer(),
            lead_author=self.lead, technical_content_editor=self.technical,
            citation_editor=self.citation, presentation_editor=self.presentation,
            top_conference_reviewer=self.top_reviewer,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_five_role_revision_evidence_latex_pdf_and_visual_qa(self):
        project_id, analysis = self._analysis(
            "Conference paper", "Generic intervention evidence-bound conference paper",
        )
        services = self.app.state.services
        neutral_payload = {
            "project": services.projects.get(project_id).model_dump(mode="json"),
            "plan": services.planning_repository.latest_plan(project_id).model_dump(mode="json"),
        }
        self.assertNotIn("weight_decay", json.dumps(neutral_payload, sort_keys=True).lower())
        review = self._review(project_id, analysis)
        self._add_precise_literature(project_id, analysis["context_id"])
        self._advance_to_review(project_id, __import__("research_runtime.state", fromlist=["ResearchOutcome"]).ResearchOutcome.SUPPORTED)
        state = self.client.get(f"/api/projects/{project_id}/state").json()
        applied = self.client.post(
            f"/api/projects/{project_id}/research-reviews/{review['record']['review_run_id']}/apply",
            json={"expected_state_revision": state["revision"]},
        )
        self.assertEqual(applied.status_code, 201, applied.text)
        report_state = self.client.get(f"/api/projects/{project_id}/state").json()
        response = self.client.post(f"/api/projects/{project_id}/papers", json={
            "research_review_run_id": review["record"]["review_run_id"],
            "config": {
                "target": "neurips", "max_parallel_agents": 2,
                "max_review_revisions": 2,
            },
            "expected_state_revision": report_state["revision"],
        })
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(
            result["record"]["status"], "quality_passed", result["quality_report"],
        )
        self.assertEqual(len(result["revisions"]), 2)
        self.assertEqual(len(result["reviews"]), 2)
        self.assertEqual(result["reviews"][0]["recommendation"], "revise")
        self.assertTrue(result["reviews"][0]["defects"])
        self.assertEqual(result["reviews"][1]["recommendation"], "ready")
        self.assertEqual(len(result["agent_runs"]), 10)
        self.assertEqual({item["role"] for item in result["agent_runs"]}, {
            "lead_author", "technical_content_editor", "related_work_citation_editor",
            "presentation_latex_editor", "top_conference_reviewer",
        })
        self.assertTrue(all(item["status"] == "pass" for item in result["quality_report"]["gates"]))
        self.assertTrue(result["build"]["success"])
        self.assertTrue(result["build"]["visual_qa_passed"])
        self.assertGreater(result["build"]["page_count"], 0)
        kinds = {item["kind"] for item in result["artifacts"]}
        self.assertTrue({
            "paper_tex", "references_bib", "figure", "table", "appendix",
            "reproducibility_statement", "markdown_preview", "pdf", "build_log",
            "pdf_page_render",
        }.issubset(kinds))
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/state").json()["stage"], "completed")

        fetched = self.client.get(
            f"/api/projects/{project_id}/papers/{result['record']['paper_id']}"
        )
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["record"]["content_hash"], result["record"]["content_hash"])
        pdf = next(item for item in result["artifacts"] if item["kind"] == "pdf")
        content = self.client.get(
            f"/api/projects/{project_id}/papers/{result['record']['paper_id']}/artifacts/"
            f"{pdf['paper_artifact_id']}/content"
        )
        self.assertEqual(content.status_code, 200, content.text)
        self.assertTrue(content.content.startswith(b"%PDF"))
        qa_output = os.environ.get("AUTORESEARCH_PAPER_QA_OUTPUT")
        if qa_output:
            qa_path = Path(qa_output)
            qa_path.parent.mkdir(parents=True, exist_ok=True)
            source_pdf = self.settings.runtime_root / "projects" / project_id / pdf["relative_path"]
            shutil.copyfile(source_pdf, qa_path)

        tex = next(item for item in result["artifacts"] if item["kind"] == "paper_tex")
        tex_path = self.settings.runtime_root / "projects" / project_id / tex["relative_path"]
        tex_text = tex_path.read_text(encoding="utf-8")
        self.assertIn("NeurIPS-style", tex_text)
        self.assertIn("\\bibliography{references}", tex_text)
        bib = next(item for item in result["artifacts"] if item["kind"] == "references_bib")
        bib_text = (
            self.settings.runtime_root / "projects" / project_id / bib["relative_path"]
        ).read_text(encoding="utf-8")
        self.assertIn("Verified Full Text Prior Work", bib_text)

        model_result = self.app.state.services.paper_writing.get(result["record"]["paper_id"])
        for target in ConferenceTarget:
            configured = model_result.revisions[-1].model_copy(update={
                "config": ConferenceTemplateConfig(target=target)
            })
            rendered = self.app.state.services.paper_writing.renderer._paper_tex(configured)
            self.assertIn("manuscript", rendered)

        tampered_payload = model_result.revisions[-1].content.model_dump(mode="python")
        for section in tampered_payload["sections"]:
            if section["section"] == PaperSectionName.RESULTS:
                section["paragraphs"].append("An invented effect is 999.")
        tampered_content = model_result.revisions[-1].content.model_validate(tampered_payload)
        revision_data = model_result.revisions[-1].model_dump(mode="python", exclude={"content_hash"})
        revision_data["content"] = tampered_content
        tampered_revision = PaperRevision.model_validate(revision_data)
        review_model = services.research_review_repository.get_record(review["record"]["review_run_id"])
        analysis_model = services.analysis_repository.get_analysis(analysis["analysis_id"])
        study = services.experiment_repository.get_study(analysis_model.study_id)
        quality = services.paper_writing.quality.inspect(
            tampered_revision, review_model,
            services.research_review_repository.list_claims(analysis_model.analysis_id),
            services.literature_repository.list_sources(project_id),
            services.literature_repository.list_evidence(project_id),
            services.analysis_repository.list_artifacts(analysis_model.analysis_id),
            [services.experiment_repository.get_artifact(item)
             for item in analysis_model.payload.source_artifact_ids],
            services.projects.get(project_id), study, model_result.build, model_result.reviews[-1],
        )
        gates = {item.gate_code: item.status.value for item in quality.gates}
        self.assertEqual(gates["NUMBER_ARTIFACT_BINDING"], "fail")
        self.assertEqual(gates["LATEX_BUILD"], "fail")

    def test_conference_and_revision_limits_are_hard(self):
        self.assertEqual({item.value for item in ConferenceTarget}, {
            "neurips", "icml", "iclr", "generic_top_conference",
        })
        with self.assertRaises(ValueError):
            ConferenceTemplateConfig(target="iclr", max_parallel_agents=3)
        with self.assertRaises(ValueError):
            ConferenceTemplateConfig(target="icml", max_review_revisions=3)

    def test_b_mode_paper_inherits_approved_visualization_profile(self):
        source = self.allowed / "legacy_paper"
        (source / "src").mkdir(parents=True)
        (source / "configs").mkdir()
        (source / "results").mkdir()
        (source / "figures").mkdir()
        (source / "src" / "experiment.py").write_text(
            "def legacy_design(values):\n    return sum(values) / len(values)\n",
            encoding="utf-8",
        )
        (source / "src" / "plot.py").write_text(
            "import matplotlib.pyplot as plt\n"
            "def plot(values):\n"
            "    plt.plot(values, color='#336699')\n"
            "    plt.savefig('result.svg', dpi=180)\n",
            encoding="utf-8",
        )
        (source / "configs" / "experiment.yaml").write_text(
            "seed: 11\nmetric: legacy_score\n", encoding="utf-8",
        )
        (source / "results" / "legacy_metrics.json").write_text(
            '{"legacy_score": 0.61, "status": "unverified"}', encoding="utf-8",
        )
        (source / "figures" / "legacy_main.svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='200'>"
            "<path stroke='#336699' d='M0 180 L300 20'/></svg>", encoding="utf-8",
        )
        before = self._fingerprint(source)
        project_id, plan, context, profiles = self._approved_b_plan(source)
        binding = plan["plan"]["b_mode_binding"]
        self.assertTrue(binding["supplemental_experiments"])
        self.assertTrue(binding["supplemental_figures"])
        self.assertTrue(binding["code_reuse_decisions"])
        self.assertTrue(all(
            decision["action"] in {"adapt", "refactor", "reimplementation"}
            for decision in binding["code_reuse_decisions"]
        ))
        profile = profiles[0]
        approved = self.client.post(
            f"/api/projects/{project_id}/visualization-profiles/{profile['profile_id']}/decision",
            json={"approved": True, "feedback": "Use the inherited visual design for the paper."},
        )
        self.assertEqual(approved.status_code, 201, approved.text)
        created = self.client.post(f"/api/projects/{project_id}/studies", json={
            "plan_revision_id": plan["plan_revision_id"],
            "visualization_profile_id": profile["profile_id"],
        })
        self.assertEqual(created.status_code, 201, created.text)
        study = created.json()["study"]
        self._execute_plan(project_id, study, plan)
        analysis_response = self.client.post(
            f"/api/projects/{project_id}/studies/{study['study_id']}/analyses"
        )
        self.assertEqual(analysis_response.status_code, 201, analysis_response.text)
        analysis = analysis_response.json()["analysis"]
        review = self._review(project_id, analysis)
        self._add_precise_literature(project_id, context["context_id"])
        outcome = __import__("research_runtime.state", fromlist=["ResearchOutcome"]).ResearchOutcome.SUPPORTED
        self._advance_to_review(project_id, outcome)
        state = self.client.get(f"/api/projects/{project_id}/state").json()
        applied = self.client.post(
            f"/api/projects/{project_id}/research-reviews/{review['record']['review_run_id']}/apply",
            json={"expected_state_revision": state["revision"]},
        )
        self.assertEqual(applied.status_code, 201, applied.text)
        report_state = self.client.get(f"/api/projects/{project_id}/state").json()
        response = self.client.post(f"/api/projects/{project_id}/papers", json={
            "research_review_run_id": review["record"]["review_run_id"],
            "config": {"target": "iclr", "max_parallel_agents": 2, "max_review_revisions": 2},
            "expected_state_revision": report_state["revision"],
        })
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["record"]["status"], "quality_passed", result["quality_report"])
        final = result["revisions"][-1]["content"]
        generated = [item for item in final["figures"] if not item["legacy_unverified"]]
        self.assertTrue(generated)
        self.assertTrue(all(
            item["visualization_profile_id"] == profile["profile_id"]
            and item["visualization_profile_hash"] == study["visualization_profile_hash"]
            for item in generated
        ))
        gates = {item["gate_code"]: item["status"] for item in result["quality_report"]["gates"]}
        self.assertEqual(gates["B_MODE_VISUALIZATION_PROFILE"], "pass")
        self.assertEqual(before, self._fingerprint(source))

    def _add_precise_literature(self, project_id, context_id):
        source = LiteratureSource(
            title="Verified Full Text Prior Work", authors=["Ada Researcher"], publication_year=2025,
            venue="Verified Proceedings", landing_url="https://example.org/verified-work",
            access_level=AccessLevel.FULL_TEXT, origins=[LiteratureProvider.CROSSREF],
            provider_record_ids={"crossref": "10.0000/verified"},
            existence_verified=True, metadata_verified=True,
        )
        repository = self.app.state.services.literature_repository
        repository.save_sources(project_id, context_id, [source])
        matrix = repository.latest_matrix(project_id)
        matrix_id = "matrix_paper_" + uuid.uuid4().hex
        evidence = LiteratureEvidence(
            project_id=project_id, context_id=context_id, matrix_id=matrix_id,
            source_id=source.source_id,
            claim="Verified prior work supplies a concrete methodological comparison.",
            support_summary="The full text describes the comparison protocol.",
            role=EvidenceRole.CORE_SUPPORT, source_access_level=AccessLevel.FULL_TEXT,
            locator=CitationLocator(section="Methods", paragraph="2"),
        )
        updated = matrix.model_copy(update={
            "matrix_id": matrix_id, "revision": matrix.revision + 1,
            "parent_matrix_id": matrix.matrix_id,
            "source_ids": [source.source_id],
            "evidence": [evidence],
            "research_gaps": [item.model_copy(update={
                "gap_id": "gap_paper_" + uuid.uuid4().hex,
                "matrix_id": matrix_id,
            }) for item in matrix.research_gaps],
        })
        repository.save_matrix(updated)


if __name__ == "__main__":
    unittest.main()

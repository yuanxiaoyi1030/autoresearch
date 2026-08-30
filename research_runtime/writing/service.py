# Purpose: Orchestrates evidence-bound paper authors, bounded revision, deterministic build/QA, persistence, and workflow.
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from research_runtime.analysis import AnalysisArtifactKind, AnalysisStatus
from research_runtime.experiments import ArtifactKind
from research_runtime.literature import LiteratureEvidence, LiteratureSource
from research_runtime.planning import canonical_hash
from research_runtime.review import ResearchReviewDecision
from research_runtime.state import ResearchOutcome, ResearchStage
from research_runtime.understanding import UnderstandingMode
from research_runtime.workflow import WorkflowAction

from .agents import (
    LeadAuthor, PaperAgentResponse, PresentationLatexEditor, RelatedWorkCitationEditor,
    TechnicalContentEditor, TopConferenceReviewer,
)
from .models import (
    ConferenceTemplateConfig, FigurePlacementDraft, PaperAgentRole, PaperAgentRun,
    PaperCitationBinding, PaperClaimBinding, PaperContent, PaperFigureBinding,
    PaperNumberBinding, PaperRecord, PaperReviewRecommendation, PaperRevision,
    PaperRevisionStatus, PaperSectionDraft, PaperSectionName, PaperWritingResult,
    TopConferenceReviewReport, identifier,
)
from .quality import PaperQualityGuard
from .renderer import LatexPaperRenderer


class PaperWritingService:
    def __init__(self, projects, understanding, literature, planning, experiments, analyses,
                 reviews, papers, workspace, analysis_runtime, workflow,
                 lead_author: LeadAuthor, technical_editor: TechnicalContentEditor,
                 citation_editor: RelatedWorkCitationEditor,
                 presentation_editor: PresentationLatexEditor,
                 top_reviewer: TopConferenceReviewer, events=None) -> None:
        self.projects = projects
        self.understanding = understanding
        self.literature = literature
        self.planning = planning
        self.experiments = experiments
        self.analyses = analyses
        self.reviews = reviews
        self.papers = papers
        self.workspace = workspace
        self.analysis_runtime = analysis_runtime
        self.workflow = workflow
        self.lead_author = lead_author
        self.technical_editor = technical_editor
        self.citation_editor = citation_editor
        self.presentation_editor = presentation_editor
        self.top_reviewer = top_reviewer
        self.events = events
        self.renderer = LatexPaperRenderer(workspace)
        self.quality = PaperQualityGuard(workspace)

    def write(self, project_id: str, research_review_run_id: str,
              config: ConferenceTemplateConfig,
              expected_state_revision: int) -> PaperWritingResult:
        inputs = self._inputs(project_id, research_review_run_id, expected_state_revision)
        paper_id = identifier("paper_")
        revisions: List[PaperRevision] = []
        review_reports: List[TopConferenceReviewReport] = []
        all_agent_runs: List[PaperAgentRun] = []
        previous = None
        previous_review = None

        self._transition(project_id, WorkflowAction.REPORT_PLAN_READY)
        for revision_number in range(config.max_review_revisions + 1):
            base_context = self._base_context(inputs, config, previous, previous_review)
            lead_context = {**base_context, "assignment": {
                "role": PaperAgentRole.LEAD_AUTHOR.value,
                "owns": ["core contributions", "outline", "narrative", "terminology", "notation", "conclusion"],
            }}
            lead = self.lead_author.author(lead_context)
            self._require_context(lead_context, lead, "Lead Author")

            technical_context = {**base_context, "assignment": {
                "role": PaperAgentRole.TECHNICAL_CONTENT_EDITOR.value,
                "owns": ["method", "theory", "experimental_setup", "results", "analysis"],
            }, "lead_outline": lead.value.outline, "lead_terminology": lead.value.terminology,
                "analysis": inputs["analysis"].model_dump(mode="json"),
                "analysis_artifacts": [item.model_dump(mode="json") for item in inputs["analysis_artifacts"]],
                "experiment_artifacts": [item.model_dump(mode="json") for item in inputs["experiment_artifacts"]],
            }
            citation_context = {**base_context, "assignment": {
                "role": PaperAgentRole.RELATED_WORK_CITATION_EDITOR.value,
                "owns": ["introduction", "related_work", "references", "novelty_claims"],
            }, "lead_contributions": [item.model_dump(mode="json") for item in lead.value.contributions],
                "eligible_sources": [item.model_dump(mode="json") for item in inputs["eligible_sources"]],
                "eligible_literature_evidence": [
                    item.model_dump(mode="json") for item in inputs["eligible_evidence"]
                ],
            }
            with ThreadPoolExecutor(max_workers=config.max_parallel_agents) as pool:
                technical_future = pool.submit(self.technical_editor.edit, technical_context)
                citation_future = pool.submit(self.citation_editor.edit, citation_context)
                technical = technical_future.result()
                citation = citation_future.result()
            self._require_context(technical_context, technical, "Technical Content Editor")
            self._require_context(citation_context, citation, "Citation Editor")

            presentation_context = {**base_context, "assignment": {
                "role": PaperAgentRole.PRESENTATION_LATEX_EDITOR.value,
                "owns": ["figures", "tables", "algorithms", "appendix", "reproducibility", "limitations", "broader_impact"],
            }, "target_template": config.model_dump(mode="json"),
                "approved_visualization_profile": inputs["visualization_profile"],
                "available_figures": [
                    item.model_dump(mode="json") for item in inputs["analysis_artifacts"]
                    if item.kind is AnalysisArtifactKind.FIGURE_SVG
                ] + [
                    item.model_dump(mode="json") for item in inputs["experiment_artifacts"]
                    if item.kind is ArtifactKind.FIGURE
                ],
                "analysis_artifacts": [
                    item.model_dump(mode="json") for item in inputs["analysis_artifacts"]
                ],
                "experiment_artifacts": [
                    item.model_dump(mode="json") for item in inputs["experiment_artifacts"]
                ],
                "legacy_figure_paths": inputs["legacy_figure_paths"],
            }
            presentation = self.presentation_editor.edit(presentation_context)
            self._require_context(presentation_context, presentation, "Presentation Editor")

            content, figure_sources = self._merge_content(
                inputs, lead.value, technical.value, citation.value, presentation.value,
            )
            revision = PaperRevision(
                paper_id=paper_id, project_id=project_id,
                context_id=inputs["context"].context_id,
                research_review_run_id=inputs["review"].review_run_id,
                research_review_content_hash=inputs["review"].content_hash,
                revision=revision_number,
                parent_revision_id=previous.revision_id if previous else None,
                config=config, research_outcome=inputs["outcome"], content=content,
                source_review_report_id=previous_review.review_report_id if previous_review else None,
            )
            author_runs = [
                self._agent_run(paper_id, project_id, revision_number, PaperAgentRole.LEAD_AUTHOR,
                                "author_or_revise", lead, revision.revision_id),
                self._agent_run(paper_id, project_id, revision_number,
                                PaperAgentRole.TECHNICAL_CONTENT_EDITOR, "technical_edit",
                                technical, revision.revision_id),
                self._agent_run(paper_id, project_id, revision_number,
                                PaperAgentRole.RELATED_WORK_CITATION_EDITOR, "citation_edit",
                                citation, revision.revision_id),
                self._agent_run(paper_id, project_id, revision_number,
                                PaperAgentRole.PRESENTATION_LATEX_EDITOR, "presentation_edit",
                                presentation, revision.revision_id),
            ]
            self.papers.save_revision(revision, author_runs)
            revisions.append(revision)
            all_agent_runs.extend(author_runs)

            self._transition(project_id, WorkflowAction.REPORT_DRAFT_READY)
            reviewer_context = {
                "review_contract": {
                    "independent": True, "author_agent_chats_included": False,
                    "may_rewrite_paper": False, "may_predict_acceptance": False,
                    "criteria": [
                        "novelty", "correctness", "rigor", "significance", "clarity",
                        "reproducibility", "limitations", "broader_impact",
                    ],
                },
                "target": config.target.value,
                "paper_revision": revision.model_dump(mode="json"),
                "research_review_decision": inputs["review"].final_decision.value,
                "verification": inputs["verification"].model_dump(mode="json"),
                "evidence_inventory": {
                    "claim_ids": [item.claim_id for item in inputs["claims"]],
                    "source_ids": [item.source_id for item in inputs["eligible_sources"]],
                    "analysis_artifact_ids": [item.artifact_id for item in inputs["analysis_artifacts"]],
                    "experiment_artifact_ids": [item.artifact_id for item in inputs["experiment_artifacts"]],
                },
            }
            reviewer = self.top_reviewer.review(reviewer_context)
            self._require_context(reviewer_context, reviewer, "Top-Conference Reviewer")
            report = TopConferenceReviewReport(
                **reviewer.value.model_dump(), paper_id=paper_id, project_id=project_id,
                revision_id=revision.revision_id, revision_content_hash=revision.content_hash,
                target=config.target, independent_context_hash=reviewer.input_context_hash,
                provider_id=reviewer.provider_id, model=reviewer.model,
            )
            reviewer_run = self._agent_run(
                paper_id, project_id, revision_number, PaperAgentRole.TOP_CONFERENCE_REVIEWER,
                "independent_top_conference_review", reviewer, report.review_report_id,
            )
            self.papers.save_review(report, reviewer_run)
            review_reports.append(report)
            all_agent_runs.append(reviewer_run)
            previous, previous_review = revision, report
            if report.recommendation is PaperReviewRecommendation.READY:
                break
            if report.recommendation is PaperReviewRecommendation.RETURN_TO_RESEARCH_REVIEW:
                break
            if revision_number < config.max_review_revisions:
                self._transition(project_id, WorkflowAction.REPORT_REVISION_REQUIRED)

        final_revision = revisions[-1]
        final_review = review_reports[-1]
        source_map = self._figure_sources(inputs, final_revision.content.figures)
        build, artifacts = self.renderer.render(
            final_revision,
            {item.source_id: item for item in inputs["eligible_sources"]},
            source_map,
        )
        quality = self.quality.inspect(
            final_revision, inputs["review"], inputs["claims"], inputs["eligible_sources"],
            inputs["eligible_evidence"], inputs["analysis_artifacts"],
            inputs["experiment_artifacts"], inputs["project"], inputs["study"], build,
            final_review,
        )
        if quality.passed:
            final_status = PaperRevisionStatus.QUALITY_PASSED
        elif final_review.recommendation is PaperReviewRecommendation.RETURN_TO_RESEARCH_REVIEW:
            final_status = PaperRevisionStatus.EVIDENCE_BLOCKED
        else:
            final_status = PaperRevisionStatus.NEEDS_REVISION
        record = PaperRecord(
            paper_id=paper_id, project_id=project_id, context_id=inputs["context"].context_id,
            research_review_run_id=inputs["review"].review_run_id, target=config.target,
            revision_ids=[item.revision_id for item in revisions],
            review_report_ids=[item.review_report_id for item in review_reports],
            final_revision_id=final_revision.revision_id,
            quality_report_id=quality.quality_report_id, build_id=build.build_id,
            status=final_status,
        )
        self.papers.save_final(record, quality, build, artifacts)
        if quality.passed:
            self._transition(project_id, WorkflowAction.REPORT_COMPLETED)
        elif final_review.recommendation is PaperReviewRecommendation.RETURN_TO_RESEARCH_REVIEW:
            self._transition(project_id, WorkflowAction.REPORT_EVIDENCE_REVIEW)
        self._emit(project_id, "paper.writing.completed", "Paper writing bundle finalized", {
            "paper_id": paper_id, "target": config.target.value,
            "revisions": len(revisions), "status": final_status.value,
            "quality_passed": quality.passed, "pdf_pages": build.page_count,
        })
        return PaperWritingResult(
            record=record, revisions=revisions, reviews=review_reports,
            quality_report=quality, build=build, artifacts=artifacts,
            agent_runs=all_agent_runs,
        )

    def get(self, paper_id: str) -> PaperWritingResult:
        record = self.papers.get_record(paper_id)
        if record is None:
            raise KeyError(paper_id)
        quality = self.papers.get_quality(record.quality_report_id)
        build = self.papers.get_build(record.build_id)
        if quality is None or build is None:
            raise ValueError("paper record is incomplete")
        return PaperWritingResult(
            record=record, revisions=self.papers.list_revisions(paper_id),
            reviews=self.papers.list_reviews(paper_id), quality_report=quality,
            build=build, artifacts=self.papers.list_artifacts(paper_id),
            agent_runs=[
                item for item in self.papers.list_agent_runs(record.project_id)
                if item.paper_id == paper_id
            ],
        )

    def _inputs(self, project_id, review_run_id, expected_state_revision):
        project = self.projects.get(project_id)
        state = self.projects.get_state(project_id)
        review = self.reviews.get_record(review_run_id)
        transition = self.reviews.get_transition(review_run_id)
        if project is None or state is None:
            raise ValueError("project does not exist")
        if expected_state_revision != state.revision:
            raise ValueError(f"stale revision: expected {expected_state_revision}, current {state.revision}")
        if state.stage is not ResearchStage.REPORT_PLANNING:
            raise ValueError("project must be at REPORT_PLANNING to start paper writing")
        if review is None or review.project_id != project_id:
            raise ValueError("ResearchReviewRecord does not belong to project")
        if transition is None or transition.to_stage is not ResearchStage.REPORT_PLANNING:
            raise ValueError("research review decision must be applied before paper writing")
        outcome = {
            ResearchReviewDecision.SUPPORTED: ResearchOutcome.SUPPORTED,
            ResearchReviewDecision.NEGATIVE_RESULT: ResearchOutcome.NEGATIVE_RESULT,
            ResearchReviewDecision.INSUFFICIENT_EVIDENCE: ResearchOutcome.INSUFFICIENT_EVIDENCE,
        }.get(review.final_decision)
        if outcome is None or state.outcome is not outcome:
            raise ValueError("only an applied bounded research outcome can enter paper writing")
        analysis = self.analyses.get_analysis(review.analysis_id)
        if analysis is None or analysis.status is not AnalysisStatus.COMPLETED or analysis.payload is None:
            raise ValueError("paper writing requires a completed AnalysisRecord")
        verification = self.analysis_runtime.verify(analysis.analysis_id)
        if not verification.passed:
            raise ValueError("fresh verification failed before paper writing")
        context = self.understanding.get_context(review.context_id)
        study = self.experiments.get_study(analysis.study_id)
        plan = self.planning.get_plan(analysis.plan_revision_id)
        if context is None or study is None or plan is None:
            raise ValueError("paper evidence package is incomplete")
        claims = self.reviews.list_claims(analysis.analysis_id)
        claims = [item for item in claims if item.claim_id in review.claim_ids]
        if len(claims) != len(review.claim_ids):
            raise ValueError("ResearchReviewRecord claim set is incomplete")
        analysis_artifacts = self.analyses.list_artifacts(analysis.analysis_id)
        experiment_artifacts = [
            self.experiments.get_artifact(item)
            for item in analysis.payload.source_artifact_ids
        ]
        if any(item is None for item in experiment_artifacts):
            raise ValueError("source experiment Artifact is missing")
        sources = self.literature.list_sources(project_id)
        evidence = self.literature.list_evidence(project_id)
        eligible_evidence = [item for item in evidence if item.locator.is_precise]
        eligible_source_ids = {item.source_id for item in eligible_evidence}
        eligible_sources = [
            item for item in sources
            if item.source_id in eligible_source_ids and item.existence_verified and item.metadata_verified
        ]
        if not eligible_sources or not eligible_evidence:
            raise ValueError("paper writing requires verified literature with precise citation locators")
        visualization_profile = None
        if study.visualization_profile_id:
            profile = self.understanding.get_profile(study.visualization_profile_id)
            approval = self.experiments.profile_approval(study.visualization_profile_id)
            if (
                profile is None or approval is None or not approval.approved
                or approval.profile_hash != study.visualization_profile_hash
                or canonical_hash(profile) != study.visualization_profile_hash
            ):
                raise ValueError("bound VisualizationProfile approval is stale")
            visualization_profile = profile.model_dump(mode="json")
            visualization_profile["approved_profile_hash"] = approval.profile_hash
        legacy_figure_paths = [
            item.relative_path for item in context.materials
            if "figure" in {kind.value for kind in item.kinds}
        ]
        return {
            "project": project, "state": state, "review": review, "outcome": outcome,
            "analysis": analysis, "verification": verification, "context": context,
            "study": study, "plan": plan, "claims": claims,
            "analysis_artifacts": analysis_artifacts,
            "experiment_artifacts": experiment_artifacts,
            "eligible_sources": eligible_sources, "eligible_evidence": eligible_evidence,
            "visualization_profile": visualization_profile,
            "legacy_figure_paths": legacy_figure_paths,
        }

    def _base_context(self, inputs, config, previous, previous_review):
        return {
            "writing_contract": {
                "plain_text_only": True, "no_invented_experiments": True,
                "no_invented_numbers": True, "no_invented_citations": True,
                "major_numbers_require_artifact": True,
                "primary_claims_require_evidence_claim": True,
                "evidence_shortfall_requires_downgrade": True,
                "max_parallel_agents": config.max_parallel_agents,
                "max_review_revisions": config.max_review_revisions,
            },
            "conference": config.model_dump(mode="json"),
            "project": inputs["project"].model_dump(mode="json"),
            "research_context": inputs["context"].model_dump(mode="json"),
            "research_outcome": inputs["outcome"].value,
            "research_review": inputs["review"].model_dump(mode="json"),
            "evidence_claims": [item.model_dump(mode="json") for item in inputs["claims"]],
            "experiment_plan": inputs["plan"].model_dump(mode="json"),
            "previous_revision": previous.model_dump(mode="json") if previous else None,
            "reviewer_defects": [
                item.model_dump(mode="json") for item in previous_review.defects
            ] if previous_review else [],
        }

    def _merge_content(self, inputs, lead, technical, citation, presentation):
        sections = {}
        for item in lead.sections:
            sections[item.section] = item
        sections[PaperSectionName.INTRODUCTION] = citation.introduction
        sections[PaperSectionName.RELATED_WORK] = citation.related_work
        for item in technical.sections:
            sections[item.section] = item
        sections[PaperSectionName.LIMITATIONS] = presentation.limitations
        sections[PaperSectionName.BROADER_IMPACT] = presentation.broader_impact
        if PaperSectionName.CONCLUSION not in sections:
            raise ValueError("Lead Author must provide a conclusion section")
        boundary = self._outcome_boundary(inputs["outcome"])
        abstract = lead.abstract.strip()
        if boundary not in abstract:
            abstract += " " + boundary
        conclusion = sections[PaperSectionName.CONCLUSION]
        paragraphs = list(conclusion.paragraphs)
        if boundary not in " ".join(paragraphs):
            paragraphs.append(boundary)
        sections[PaperSectionName.CONCLUSION] = conclusion.model_copy(update={"paragraphs": paragraphs})

        claims_by_id = {item.claim_id: item for item in inputs["claims"]}
        contribution_claim_ids = {
            claim_id for item in lead.contributions for claim_id in item.claim_ids
        }
        if not contribution_claim_ids.issubset(claims_by_id):
            raise ValueError("Lead Author referenced an unknown EvidenceClaim")
        claim_sections = {
            PaperSectionName.INTRODUCTION, PaperSectionName.RESULTS,
            PaperSectionName.ANALYSIS, PaperSectionName.CONCLUSION,
        }
        claim_bindings = [
            PaperClaimBinding(
                claim_id=item.claim_id, claim_content_hash=item.content_hash,
                statement=item.statement, primary=True, sections=sorted(claim_sections, key=lambda x: x.value),
            )
            for item in inputs["claims"] if item.claim_id in contribution_claim_ids
        ]

        artifact_map = {
            item.artifact_id: item for item in [
                *inputs["analysis_artifacts"], *inputs["experiment_artifacts"],
            ]
        }
        number_bindings = []
        for item in technical.number_bindings:
            artifact = artifact_map.get(item.artifact_id)
            if artifact is None:
                raise ValueError("Technical Editor referenced an unknown Artifact")
            number_bindings.append(PaperNumberBinding(
                **item.model_dump(), artifact_sha256=artifact.sha256,
            ))

        source_map = {item.source_id: item for item in inputs["eligible_sources"]}
        evidence_map = {item.evidence_id: item for item in inputs["eligible_evidence"]}
        citation_bindings = []
        used_keys = set()
        for item in citation.citation_uses:
            source = source_map.get(item.source_id)
            evidence = evidence_map.get(item.evidence_id)
            if source is None or evidence is None or evidence.source_id != source.source_id:
                raise ValueError("Citation Editor referenced an ineligible source/evidence pair")
            key = self._citation_key(source, used_keys)
            used_keys.add(key)
            citation_bindings.append(PaperCitationBinding(
                citation_key=key, source_id=source.source_id, evidence_id=evidence.evidence_id,
                source_access_level=source.access_level, locator=item.locator,
                section=item.section, purpose=item.purpose,
            ))

        figure_drafts = list(presentation.figures)
        if not figure_drafts:
            figures = [
                item for item in inputs["analysis_artifacts"]
                if item.kind is AnalysisArtifactKind.FIGURE_SVG
            ]
            if figures:
                figure_drafts.append(FigurePlacementDraft(
                    label="fig:primary-result", caption="Verified primary analysis result.",
                    source_artifact_id=figures[0].artifact_id,
                ))
        figure_bindings = []
        for draft in figure_drafts:
            if draft.source_artifact_id:
                artifact = artifact_map.get(draft.source_artifact_id)
                if artifact is None:
                    raise ValueError("Presentation Editor referenced an unknown figure Artifact")
                suffix = Path(artifact.relative_path).suffix.lower() or ".bin"
                figure_bindings.append(PaperFigureBinding(
                    **draft.model_dump(),
                    bundled_relative_path="figures/" + draft.label.replace(":", "-") + suffix,
                    source_sha256=artifact.sha256,
                    visualization_profile_id=artifact.visualization_profile_id,
                    visualization_profile_hash=artifact.visualization_profile_hash,
                ))
            else:
                caption = draft.caption
                if "legacy/unverified" not in caption.lower():
                    caption = "Legacy/unverified: " + caption
                suffix = Path(draft.legacy_relative_path).suffix.lower() or ".bin"
                material = next(
                    (item for item in inputs["context"].materials
                     if item.relative_path == draft.legacy_relative_path), None,
                )
                if material is None:
                    raise ValueError("legacy figure is not present in the immutable import manifest")
                figure_bindings.append(PaperFigureBinding(
                    **draft.model_dump(exclude={"caption"}), caption=caption,
                    bundled_relative_path="figures/" + draft.label.replace(":", "-") + suffix,
                    source_sha256=material.sha256,
                ))

        for table in presentation.tables:
            if any(item not in artifact_map for item in table.source_artifact_ids):
                raise ValueError("Presentation Editor table referenced an unknown Artifact")

        ordered = [
            PaperSectionName.INTRODUCTION, PaperSectionName.RELATED_WORK,
            PaperSectionName.METHOD, PaperSectionName.THEORY,
            PaperSectionName.EXPERIMENTAL_SETUP, PaperSectionName.RESULTS,
            PaperSectionName.ANALYSIS, PaperSectionName.LIMITATIONS,
            PaperSectionName.BROADER_IMPACT, PaperSectionName.CONCLUSION,
        ]
        missing = [item.value for item in ordered if item not in sections]
        if missing:
            raise ValueError("paper sections missing after role merge: " + ", ".join(missing))
        return PaperContent(
            title=lead.title, abstract=abstract, contributions=lead.contributions,
            narrative=lead.narrative, terminology=lead.terminology, notation=lead.notation,
            sections=[sections[item] for item in ordered], claim_bindings=claim_bindings,
            number_bindings=number_bindings, citation_bindings=citation_bindings,
            novelty_claims=citation.novelty_claims, figures=figure_bindings,
            tables=presentation.tables, algorithms=presentation.algorithms,
            appendix_sections=presentation.appendix_sections,
            reproducibility_statement=presentation.reproducibility_statement,
            outcome_boundary=boundary,
        ), figure_bindings

    def _figure_sources(self, inputs, figures):
        artifacts = {
            item.artifact_id: item for item in [
                *inputs["analysis_artifacts"], *inputs["experiment_artifacts"],
            ]
        }
        sources = {}
        project_root = self.workspace.project_root(inputs["project"].project_id).resolve(strict=True)
        for figure in figures:
            if figure.source_artifact_id:
                artifact = artifacts.get(figure.source_artifact_id)
                if artifact is None:
                    raise ValueError("paper figure Artifact disappeared")
                path = (project_root / artifact.relative_path).resolve(strict=True)
                path.relative_to(project_root)
                if self._sha256(path) != artifact.sha256:
                    raise ValueError("paper figure Artifact hash changed")
                sources[figure.label] = path
            else:
                context = inputs["context"]
                if context.mode is not UnderstandingMode.EXISTING_PROJECT or not context.import_id:
                    raise ValueError("legacy paper figure requires B-mode immutable import")
                sources[figure.label] = self.workspace.resolve_import_file(
                    inputs["project"].project_id, context.import_id,
                    figure.legacy_relative_path,
                )
        return sources

    def _transition(self, project_id, action):
        state = self.projects.get_state(project_id)
        return self.workflow.transition(project_id, action, expected_revision=state.revision)

    @staticmethod
    def _agent_run(paper_id, project_id, revision, role, operation,
                   response: PaperAgentResponse, output_record_id):
        return PaperAgentRun(
            paper_id=paper_id, project_id=project_id, revision=revision,
            role=role, operation=operation, input_context_hash=response.input_context_hash,
            output_record_id=output_record_id, provider_id=response.provider_id,
            model=response.model, input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    @staticmethod
    def _require_context(context, response, role):
        expected = canonical_hash(context)
        if response.input_context_hash != expected:
            raise ValueError(f"{role} response context hash mismatch")

    @staticmethod
    def _outcome_boundary(outcome):
        return {
            ResearchOutcome.SUPPORTED: (
                "The verified evidence supports the bounded claims stated in this paper; "
                "it does not establish claims beyond the approved study."
            ),
            ResearchOutcome.NEGATIVE_RESULT: (
                "The verified study yielded a negative result; the paper reports this outcome "
                "without converting it into support for the tested hypothesis."
            ),
            ResearchOutcome.INSUFFICIENT_EVIDENCE: (
                "The available evidence is insufficient to support the tested claim; "
                "all interpretations remain explicitly provisional."
            ),
        }[outcome]

    @staticmethod
    def _citation_key(source: LiteratureSource, used):
        author = source.authors[0] if source.authors else "source"
        stem = re.sub(r"[^A-Za-z0-9]", "", author.split()[-1]) or "source"
        year = re.sub(r"[^0-9]", "", str(source.publication_year or "")) or "nd"
        suffix = re.sub(r"[^A-Za-z0-9]", "", source.source_id)[-6:] or "record"
        base = (stem + year + suffix)[:48]
        key = base
        counter = 2
        while key in used:
            key = (base[:44] + str(counter))
            counter += 1
        return key

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _emit(self, project_id, event_type, summary, payload):
        if self.events is not None:
            self.events.append(project_id, event_type, summary, payload=payload)

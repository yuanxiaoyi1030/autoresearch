# Purpose: Applies deterministic claim, number, citation, outcome, visualization, build, and PDF gates.
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional

from research_runtime.literature import LiteratureEvidence, LiteratureSource
from research_runtime.planning import canonical_hash
from research_runtime.review import EvidenceClaim, ResearchReviewDecision, ResearchReviewRecord
from research_runtime.state import ProjectType, ResearchOutcome

from .models import (
    PaperBuildRecord, PaperGateResult, PaperGateStatus, PaperQualityReport, PaperRevision,
    PaperReviewRecommendation, TopConferenceReviewReport,
)


class PaperQualityGuard:
    REQUIRED_SECTIONS = {
        "introduction", "related_work", "method", "theory", "experimental_setup",
        "results", "analysis", "limitations", "broader_impact", "conclusion",
    }

    def __init__(self, workspace) -> None:
        self.workspace = workspace

    def inspect(self, revision: PaperRevision, review: ResearchReviewRecord,
                claims: Iterable[EvidenceClaim], sources: Iterable[LiteratureSource],
                evidence: Iterable[LiteratureEvidence], analysis_artifacts,
                experiment_artifacts, project, study, build: PaperBuildRecord,
                top_review: TopConferenceReviewReport) -> PaperQualityReport:
        claims_by_id = {item.claim_id: item for item in claims}
        sources_by_id = {item.source_id: item for item in sources}
        evidence_by_id = {item.evidence_id: item for item in evidence}
        artifacts = {
            item.artifact_id: item for item in [*analysis_artifacts, *experiment_artifacts]
        }
        gates = [
            self._structure(revision),
            self._review_binding(revision, review),
            self._claim_binding(revision, review, claims_by_id),
            self._number_binding(revision, artifacts),
            self._citation_binding(revision, sources_by_id, evidence_by_id),
            self._novelty_binding(revision, evidence_by_id, sources_by_id),
            self._outcome_boundary(revision, review),
            self._visualization(revision, project, study),
            self._legacy_labels(revision),
            self._reproducibility(revision),
            self._top_conference_review(top_review, revision),
            self._latex_build(build, revision),
            self._pdf_visual(build),
        ]
        return PaperQualityReport(
            paper_id=revision.paper_id, project_id=revision.project_id,
            revision_id=revision.revision_id, revision_content_hash=revision.content_hash,
            gates=gates, passed=all(item.status is PaperGateStatus.PASS for item in gates),
        )

    def _structure(self, revision):
        sections = {item.section.value for item in revision.content.sections}
        missing = sorted(self.REQUIRED_SECTIONS - sections)
        return self._gate(
            "TOP_CONFERENCE_STRUCTURE", not missing,
            "Required top-conference sections are present" if not missing
            else "Missing required sections: " + ", ".join(missing),
            [revision.revision_id],
        )

    def _review_binding(self, revision, review):
        valid = (
            revision.research_review_run_id == review.review_run_id
            and revision.research_review_content_hash == review.content_hash
            and review.final_decision in {
                ResearchReviewDecision.SUPPORTED, ResearchReviewDecision.NEGATIVE_RESULT,
                ResearchReviewDecision.INSUFFICIENT_EVIDENCE,
            }
        )
        return self._gate(
            "RESEARCH_REVIEW_BINDING", valid,
            "Paper binds an approved immutable research review" if valid
            else "Paper does not bind an eligible immutable research review",
            [review.review_run_id],
        )

    def _claim_binding(self, revision, review, claims: Dict[str, EvidenceClaim]):
        bound = {item.claim_id: item for item in revision.content.claim_bindings}
        contribution_ids = {
            claim_id for item in revision.content.contributions for claim_id in item.claim_ids
        }
        valid = bool(bound) and contribution_ids.issubset(bound) and set(bound).issubset(review.claim_ids)
        for claim_id, binding in bound.items():
            claim = claims.get(claim_id)
            valid = valid and claim is not None and claim.content_hash == binding.claim_content_hash
            valid = valid and claim.statement == binding.statement
        return self._gate(
            "CLAIM_EVIDENCE_BINDING", bool(valid),
            "Every primary contribution binds an immutable EvidenceClaim" if valid
            else "A primary contribution is missing or mismatches its EvidenceClaim",
            list(bound),
        )

    def _number_binding(self, revision, artifacts):
        valid = True
        records = []
        literals = {item.literal for item in revision.content.number_bindings}
        for binding in revision.content.number_bindings:
            records.append(binding.artifact_id)
            artifact = artifacts.get(binding.artifact_id)
            if artifact is None or artifact.sha256 != binding.artifact_sha256:
                valid = False
                continue
            path = self.workspace.project_root(revision.project_id) / artifact.relative_path
            if not path.is_file() or self._sha256(path) != artifact.sha256:
                valid = False
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if binding.literal not in text:
                valid = False
        scientific_text = [revision.content.abstract]
        scientific_text.extend(
            paragraph for section in revision.content.sections
            if section.section.value in {
                "method", "theory", "experimental_setup", "results", "analysis", "conclusion",
            }
            for paragraph in section.paragraphs
        )
        scientific_text.extend(
            paragraph for section in revision.content.appendix_sections
            for paragraph in section.paragraphs
        )
        scientific_text.extend(step for item in revision.content.algorithms for step in item.steps)
        marker_pattern = re.compile(r"\{\{num:([^}]+)\}\}")
        binding_ids = {item.binding_id for item in revision.content.number_bindings}
        for text in scientific_text:
            if not set(marker_pattern.findall(text)).issubset(binding_ids):
                valid = False
            stripped = marker_pattern.sub("", text)
            for token in re.findall(r"(?<![A-Za-z0-9_])[+-]?(?:\d+\.\d+|\d+)(?:[eE][+-]?\d+)?%?", stripped):
                if token not in literals:
                    valid = False
        for table in revision.content.tables:
            table_artifacts = [artifacts.get(item) for item in table.source_artifact_ids]
            if any(item is None for item in table_artifacts):
                valid = False
                continue
            source_texts = []
            for artifact in table_artifacts:
                path = self.workspace.project_root(revision.project_id) / artifact.relative_path
                if not path.is_file() or self._sha256(path) != artifact.sha256:
                    valid = False
                    continue
                source_texts.append(path.read_text(encoding="utf-8", errors="replace"))
            table_text = " ".join([table.caption, *table.columns, *[cell for row in table.rows for cell in row]])
            for token in re.findall(r"(?<![A-Za-z0-9_])[+-]?(?:\d+\.\d+|\d+)(?:[eE][+-]?\d+)?%?", table_text):
                if not any(token in source for source in source_texts):
                    valid = False
        return self._gate(
            "NUMBER_ARTIFACT_BINDING", valid,
            "Every scientific numeric literal is present in a hash-verified Artifact" if valid
            else "An unbound, absent, or hash-mismatched scientific number was detected",
            records,
        )

    def _citation_binding(self, revision, sources, evidence):
        valid = bool(revision.content.citation_bindings)
        records = []
        for binding in revision.content.citation_bindings:
            records.extend([binding.source_id, binding.evidence_id])
            source = sources.get(binding.source_id)
            item = evidence.get(binding.evidence_id)
            valid = valid and source is not None and item is not None
            if source is None or item is None:
                continue
            valid = valid and item.source_id == source.source_id
            valid = valid and source.existence_verified and source.metadata_verified
            valid = valid and binding.source_access_level == source.access_level == item.source_access_level
            valid = valid and binding.locator == item.locator and binding.locator.is_precise
        return self._gate(
            "CITATION_SOURCE_LOCATOR_BINDING", bool(valid),
            "Every citation binds a verified LiteratureSource and precise locator" if valid
            else "A citation is invented, unverifiable, access-mismatched, or lacks a precise locator",
            records,
        )

    def _novelty_binding(self, revision, evidence, sources):
        valid = True
        records = []
        for novelty in revision.content.novelty_claims:
            records.extend(novelty.supporting_evidence_ids + novelty.contrasting_source_ids)
            if not novelty.supporting_evidence_ids or not novelty.contrasting_source_ids:
                valid = False
            valid = valid and all(item in evidence for item in novelty.supporting_evidence_ids)
            valid = valid and all(item in sources for item in novelty.contrasting_source_ids)
        return self._gate(
            "NOVELTY_EVIDENCE_BINDING", bool(valid),
            "Novelty statements are evidence- and source-bound" if valid
            else "A novelty statement lacks verified comparison evidence",
            records,
        )

    def _outcome_boundary(self, revision, review):
        expected = {
            ResearchReviewDecision.SUPPORTED: ResearchOutcome.SUPPORTED,
            ResearchReviewDecision.NEGATIVE_RESULT: ResearchOutcome.NEGATIVE_RESULT,
            ResearchReviewDecision.INSUFFICIENT_EVIDENCE: ResearchOutcome.INSUFFICIENT_EVIDENCE,
        }.get(review.final_decision)
        conclusion = next(
            (item for item in revision.content.sections if item.section.value == "conclusion"), None
        )
        conclusion_text = " ".join(conclusion.paragraphs) if conclusion else ""
        boundary = revision.content.outcome_boundary
        valid = revision.research_outcome is expected and boundary in revision.content.abstract
        valid = valid and boundary in conclusion_text
        if expected in {ResearchOutcome.NEGATIVE_RESULT, ResearchOutcome.INSUFFICIENT_EVIDENCE}:
            prohibited = re.compile(r"\b(proves?|definitively|state[- ]of[- ]the[- ]art|conclusively)\b", re.I)
            valid = valid and not prohibited.search(revision.content.abstract + " " + conclusion_text)
        return self._gate(
            "OUTCOME_CONCLUSION_BOUNDARY", bool(valid),
            "Abstract and conclusion preserve the deterministic research outcome" if valid
            else "Paper overstates or omits the deterministic research outcome boundary",
            [review.review_run_id],
        )

    def _visualization(self, revision, project, study):
        valid = True
        if project.project_type is ProjectType.EXISTING_PROJECT and study.visualization_profile_id:
            new_figures = [item for item in revision.content.figures if not item.legacy_unverified]
            valid = bool(new_figures) and all(
                item.visualization_profile_id == study.visualization_profile_id
                and item.visualization_profile_hash == study.visualization_profile_hash
                for item in new_figures
            )
        return self._gate(
            "B_MODE_VISUALIZATION_PROFILE", valid,
            "B-mode figures inherit the approved VisualizationProfile" if valid
            else "B-mode generated figures do not inherit the approved VisualizationProfile",
            [study.visualization_profile_id] if study.visualization_profile_id else [],
        )

    def _legacy_labels(self, revision):
        legacy = [item for item in revision.content.figures if item.legacy_relative_path]
        valid = all(
            item.legacy_unverified and "legacy/unverified" in item.caption.lower()
            for item in legacy
        )
        return self._gate(
            "LEGACY_FIGURE_LABEL", valid,
            "Every legacy figure is explicitly labeled legacy/unverified" if valid
            else "A legacy figure is presented without an explicit legacy/unverified label",
            [item.legacy_relative_path for item in legacy],
        )

    def _reproducibility(self, revision):
        value = revision.content.reproducibility_statement.lower()
        required = ("code", "configuration", "environment", "artifact", "seed")
        valid = all(item in value for item in required)
        return self._gate(
            "REPRODUCIBILITY_STATEMENT", valid,
            "Reproducibility statement covers code, configuration, environment, Artifacts, and seeds"
            if valid else "Reproducibility statement omits required execution provenance",
            [revision.revision_id],
        )

    def _latex_build(self, build, revision):
        valid = (
            build.success and build.revision_id == revision.revision_id
            and build.revision_content_hash == revision.content_hash
        )
        return self._gate(
            "LATEX_BUILD", valid,
            "Controlled LaTeX/BibTeX build completed for the exact revision" if valid
            else "Controlled LaTeX/BibTeX build failed or was produced for another revision",
            [build.build_id],
        )

    def _top_conference_review(self, review, revision):
        valid = (
            review.revision_id == revision.revision_id
            and review.revision_content_hash == revision.content_hash
            and review.recommendation is PaperReviewRecommendation.READY
        )
        return self._gate(
            "TOP_CONFERENCE_REVIEW", valid,
            "Independent top-conference review has no major unresolved defects" if valid
            else "Independent top-conference review requires revision or evidence review",
            [review.review_report_id],
        )

    def _pdf_visual(self, build):
        valid = build.visual_qa_passed and build.page_count > 0 and not build.visual_qa_notes
        return self._gate(
            "PDF_VISUAL_QA", valid,
            "PDF rendered one non-defective PNG per page" if valid
            else "PDF render QA failed: " + "; ".join(build.visual_qa_notes),
            [build.pdf_artifact_id] if build.pdf_artifact_id else [],
        )

    @staticmethod
    def _gate(code, passed, summary, records):
        return PaperGateResult(
            gate_code=code, status=PaperGateStatus.PASS if passed else PaperGateStatus.FAIL,
            summary=summary, record_ids=[item for item in records if item],
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

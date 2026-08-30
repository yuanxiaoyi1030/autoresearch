# Purpose: Enforces deterministic research-review rules before any LLM recommendation can pass.
from __future__ import annotations

from research_runtime.literature import AccessLevel
from research_runtime.analysis import AnalysisArtifactKind
from research_runtime.state import ResearchOutcome

from .models import (
    ClaimType, PolicyRuleResult, PolicyRuleStatus, ResearchPolicyDecision,
    ResearchReviewDecision,
)


OUTCOME_DECISION = {
    ResearchOutcome.SUPPORTED: ResearchReviewDecision.SUPPORTED,
    ResearchOutcome.NEGATIVE_RESULT: ResearchReviewDecision.NEGATIVE_RESULT,
    ResearchOutcome.INSUFFICIENT_EVIDENCE: ResearchReviewDecision.INSUFFICIENT_EVIDENCE,
}


class ResearchPolicyGuard:
    def __init__(self, planning, experiments, analyses, literature, analysis_runtime,
                 study_runtime) -> None:
        self.planning = planning
        self.experiments = experiments
        self.analyses = analyses
        self.literature = literature
        self.analysis_runtime = analysis_runtime
        self.study_runtime = study_runtime

    def inspect(self, project_id, analysis, scientific_review, verification, claims):
        rules = []

        def result(code, passed, summary, ids=(), forced=None):
            rules.append(PolicyRuleResult(
                rule_code=code,
                status=PolicyRuleStatus.PASS if passed else PolicyRuleStatus.FAIL,
                summary=summary, record_ids=list(ids),
                forced_decision=None if passed else forced,
            ))

        plan_passed = verification.plan_verified
        result(
            "PLAN_BINDING", plan_passed,
            "Analysis, Study, Runs, and approval gate bind the current approved Plan hash.",
            [analysis.analysis_id, verification.verification_id],
            ResearchReviewDecision.REVISE_PLAN,
        )
        lineage_design_codes = {
            "LINEAGE_COVERAGE", "LINEAGE_MODIFICATIONS", "LINEAGE_DESIGN_FIDELITY",
        }
        lineage_design_passed = not any(
            item.code in lineage_design_codes for item in verification.findings
        )
        result(
            "LINEAGE_DESIGN_BINDING", lineage_design_passed,
            "B-mode source-to-derived design mappings match the approved Plan.",
            [verification.verification_id], ResearchReviewDecision.REVISE_PLAN,
        )
        evidence_integrity = (
            verification.implementation_verified and verification.runs_verified
            and verification.artifacts_verified and verification.environment_verified
            and verification.statistics_verified and verification.lineage_verified
        )
        result(
            "VERIFIED_EVIDENCE_PACK", evidence_integrity,
            "Code, config, environment, Artifact hashes, lineage, and statistics pass fresh verification.",
            [verification.verification_id], ResearchReviewDecision.RETURN_TO_EXPERIMENT,
        )
        missing = bool(analysis.payload and analysis.payload.missing_runs)
        result(
            "COMPLETE_APPROVED_EXPERIMENTS", not missing,
            "All approved metric/seed/replicate observations are present.",
            [analysis.analysis_id], ResearchReviewDecision.RETURN_TO_EXPERIMENT,
        )
        scientific_gate = scientific_review.may_enter_research_review
        scientific_forced = (
            ResearchReviewDecision.REVISE_PLAN
            if scientific_review.policy_recommendation.value == "revise_plan"
            else ResearchReviewDecision.RETURN_TO_EXPERIMENT
        )
        result(
            "SCIENTIFIC_REVIEW_ENTRY", scientific_gate,
            "Scientific experiment review permits entry to formal independent review.",
            [scientific_review.review_id], scientific_forced,
        )

        claim_passed, citation_passed, artifact_ids = self._claims(
            project_id, analysis, claims,
        )
        result(
            "CLAIM_EVIDENCE_BOUNDARY", claim_passed,
            "EvidenceClaims preserve the deterministic outcome and bind valid comparisons/Artifacts.",
            [item.claim_id for item in claims], ResearchReviewDecision.INSUFFICIENT_EVIDENCE,
        )
        result(
            "CITATION_ACCESS_LEVEL", citation_passed,
            "Core literature claims use verified full-text/imported sources with precise locators.",
            [item.claim_id for item in claims], ResearchReviewDecision.INSUFFICIENT_EVIDENCE,
        )
        result(
            "CLAIM_ARTIFACT_HASH", self._artifacts(project_id, artifact_ids),
            "Every Artifact cited by an EvidenceClaim currently matches its immutable hash.",
            artifact_ids, ResearchReviewDecision.RETURN_TO_EXPERIMENT,
        )
        return rules

    def decide(self, review_run_id, project_id, context_id, analysis, verification,
               meta_review, specialists, rules):
        forced = [item.forced_decision for item in rules if item.status is PolicyRuleStatus.FAIL]
        proposals = [meta_review.proposed_decision] + [
            item.proposed_decision for item in specialists
        ]
        if (ResearchReviewDecision.REVISE_PLAN in forced
                or ResearchReviewDecision.REVISE_PLAN in proposals):
            final = ResearchReviewDecision.REVISE_PLAN
        elif (ResearchReviewDecision.RETURN_TO_EXPERIMENT in forced
                or ResearchReviewDecision.RETURN_TO_EXPERIMENT in proposals):
            final = ResearchReviewDecision.RETURN_TO_EXPERIMENT
        elif (ResearchReviewDecision.INSUFFICIENT_EVIDENCE in forced
                or ResearchReviewDecision.INSUFFICIENT_EVIDENCE in proposals):
            final = ResearchReviewDecision.INSUFFICIENT_EVIDENCE
        else:
            final = OUTCOME_DECISION[analysis.outcome]
        overridden = final is not meta_review.proposed_decision
        failed = [item for item in rules if item.status is PolicyRuleStatus.FAIL]
        explanation = None
        if overridden:
            explanation = (
                "Deterministic Policy Guard overrode Meta Reviewer using: "
                + ", ".join(item.rule_code for item in failed)
                if failed else
                "Policy preserved the deterministic research outcome or a stricter specialist decision."
            )
        feedback = [item.summary for item in failed] + list(meta_review.feedback)
        return ResearchPolicyDecision(
            review_run_id=review_run_id, project_id=project_id, context_id=context_id,
            analysis_id=analysis.analysis_id, analysis_content_hash=analysis.content_hash,
            verification_id=verification.verification_id,
            verification_report_hash=verification.content_hash,
            meta_review_id=meta_review.meta_review_id,
            meta_review_hash=meta_review.content_hash,
            rule_results=rules, final_decision=final,
            reviewer_decision_overridden=overridden,
            override_explanation=explanation, feedback=feedback,
        )

    def _claims(self, project_id, analysis, claims):
        plan = self.planning.repository.get_plan(analysis.plan_revision_id)
        comparison_ids = {
            item.comparison_id for item in (analysis.payload.comparisons if analysis.payload else [])
        }
        analysis_artifacts = {
            item.artifact_id: item for item in self.analyses.list_artifacts(analysis.analysis_id)
        }
        experiment_artifacts = {}
        for run_id in (analysis.payload.source_run_ids if analysis.payload else []):
            experiment_artifacts.update({
                item.artifact_id: item for item in self.experiments.list_artifacts(run_id)
            })
        evidence_by_id = {item.evidence_id: item for item in self.literature.list_evidence(project_id)}
        sources_by_id = {item.source_id: item for item in self.literature.list_sources(project_id)}
        claim_passed = bool(claims)
        citation_passed = True
        artifact_ids = []
        for claim in claims:
            if claim.analysis_id != analysis.analysis_id or claim.analysis_content_hash != analysis.content_hash:
                claim_passed = False
            if claim.claim_type is ClaimType.EXPERIMENT_RESULT:
                if claim.outcome is not analysis.outcome:
                    claim_passed = False
                if (not set(claim.comparison_ids) <= comparison_ids
                        or (claim.core_claim and set(claim.comparison_ids) != comparison_ids)):
                    claim_passed = False
                bound_analysis = [
                    analysis_artifacts[item]
                    for item in claim.analysis_artifact_ids if item in analysis_artifacts
                ]
                if (not claim.analysis_artifact_ids or not claim.experiment_artifact_ids
                        or not any(
                            item.kind is AnalysisArtifactKind.MACHINE_JSON
                            for item in bound_analysis
                        )):
                    claim_passed = False
            if not set(claim.analysis_artifact_ids) <= set(analysis_artifacts):
                claim_passed = False
            if not set(claim.experiment_artifact_ids) <= set(experiment_artifacts):
                claim_passed = False
            artifact_ids.extend(claim.analysis_artifact_ids + claim.experiment_artifact_ids)
            for evidence_id in claim.literature_evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                source = sources_by_id.get(evidence.source_id) if evidence else None
                if (plan is None or evidence is None or source is None
                        or evidence.matrix_id != plan.literature_matrix_id
                        or evidence.context_id != analysis.context_id
                        or not source.existence_verified or not source.metadata_verified):
                    citation_passed = False
                    continue
                if claim.core_claim and (
                    evidence.source_access_level not in {AccessLevel.FULL_TEXT, AccessLevel.IMPORTED_PDF}
                    or not evidence.locator.is_precise
                    or source.access_level not in {AccessLevel.FULL_TEXT, AccessLevel.IMPORTED_PDF}
                ):
                    citation_passed = False
            if claim.claim_type is ClaimType.LITERATURE_CONTEXT and claim.core_claim \
                    and not claim.literature_evidence_ids:
                citation_passed = False
        return claim_passed, citation_passed, sorted(set(artifact_ids))

    def _artifacts(self, project_id, artifact_ids):
        for artifact_id in artifact_ids:
            analysis_artifact = self.analyses.get_artifact(artifact_id)
            if analysis_artifact is not None:
                verification = self.analysis_runtime.verify_artifact(artifact_id)
            else:
                experiment_artifact = self.experiments.get_artifact(artifact_id)
                if experiment_artifact is None:
                    return False
                verification = self.study_runtime.verify_artifact(artifact_id)
            if verification.artifact.project_id != project_id or not verification.hash_matches:
                return False
        return True

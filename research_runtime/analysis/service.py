# Purpose: Runs deterministic analysis, independent audit, immutable Artifact generation, and scientific review policy.
from __future__ import annotations

import csv
import io
import json
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from research_runtime.experiments import ArtifactKind, ExperimentRunStatus
from research_runtime.experiments.executor import hash_file, is_reparse, tree_hash
from research_runtime.planning import canonical_hash
from research_runtime.state import ProjectType, ResearchOutcome
from research_runtime.understanding import ApprovalStatus, LineageVerification

from .agents import ScientificReviewer
from .models import (
    AnalysisAgentRole, AnalysisAgentRun, AnalysisArtifact, AnalysisArtifactKind,
    AnalysisArtifactVerification, AnalysisRecord, AnalysisStatus, AnalysisWorkflowResult,
    ScientificRecommendation, ScientificReviewReport, VerificationFinding,
    VerificationReport, VerificationSeverity,
)
from .statistics import DeterministicStatistics


_REVIEW_OBSERVATION_LIMIT = 200


def compact_analysis_context(analysis):
    """Keep large deterministic series out of bounded LLM review inputs."""
    context = analysis.model_dump(mode="json")
    payload = context.get("payload")
    observations = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(observations, list) or len(observations) <= _REVIEW_OBSERVATION_LIMIT:
        return context
    payload["observations"] = []
    payload["observation_digest"] = {
        "total_count": len(observations),
        "seed_level_count": sum(item.get("seed") is not None for item in observations
                                 if isinstance(item, dict)),
        "series_point_count": sum(item.get("seed") is None for item in observations
                                   if isinstance(item, dict)),
        "values_omitted": True,
        "reason": (
            "Detailed observations remain bound to the verified AnalysisRecord and source Artifacts; "
            "review group_summaries, comparisons, missing_runs, and outliers instead."
        ),
    }
    return context


class StatisticalAnalyst:
    """Loads verified metrics and invokes the deterministic AnalysisSpec implementation."""

    def __init__(self, statistics: Optional[DeterministicStatistics] = None) -> None:
        self.statistics = statistics or DeterministicStatistics()

    def analyze(self, plan, study, runs, metric_inputs):
        return self.statistics.analyze(plan, study, runs, metric_inputs)


class VerificationAuditor:
    """Fresh-context auditor that never writes to source Run or Analysis Artifacts."""

    def __init__(self, service: "AnalysisReviewService") -> None:
        self.service = service

    def verify(self, analysis_id: str) -> VerificationReport:
        return self.service._verify(analysis_id)


class AnalysisReviewService:
    def __init__(self, projects, understanding, planning, experiments, analyses,
                 workspace, reviewer: ScientificReviewer,
                 analyst: Optional[StatisticalAnalyst] = None, events=None) -> None:
        self.projects = projects
        self.understanding = understanding
        self.planning = planning
        self.experiments = experiments
        self.analyses = analyses
        self.workspace = workspace
        self.reviewer = reviewer
        self.analyst = analyst or StatisticalAnalyst()
        self.auditor = VerificationAuditor(self)
        self.events = events

    def run(self, project_id: str, study_id: str) -> AnalysisWorkflowResult:
        project, context, plan, study, implementation, runs = self._inputs(project_id, study_id)
        self.planning.require_formal_experiment(project_id, study.plan_revision_id)
        analysis_id = "analysis_run_" + os.urandom(16).hex()
        analyst_context = {
            "contract": {
                "approved_analysis_spec_only": True,
                "deterministic_numeric_recalculation": True,
                "source_artifacts_read_only": True,
            },
            "plan_revision_id": plan.plan_revision_id,
            "plan_content_hash": plan.content_hash,
            "analysis_spec_hash": canonical_hash(plan.plan.analysis),
            "study_id": study.study_id,
            "run_records": [self._run_digest(item) for item in runs],
        }
        analyst_input_hash = canonical_hash(analyst_context)
        try:
            metric_inputs = self._metric_inputs(plan, runs, require_verified=True)
            payload = self.analyst.analyze(plan, study, runs, metric_inputs)
            artifact_specs = self._materialize_analysis(
                project_id, study, analysis_id, payload,
            )
            record = AnalysisRecord(
                analysis_id=analysis_id, project_id=project_id,
                context_id=context.context_id, study_id=study_id,
                plan_revision_id=plan.plan_revision_id, plan_content_hash=plan.content_hash,
                implementation_revision_id=implementation.implementation_revision_id,
                implementation_content_hash=implementation.content_hash,
                status=AnalysisStatus.COMPLETED, payload=payload, outcome=payload.outcome,
                artifact_ids=[item.artifact_id for item in artifact_specs],
            )
            self.analyses.save_analysis_bundle(record, artifact_specs)
        except Exception as exc:
            record = AnalysisRecord(
                analysis_id=analysis_id, project_id=project_id,
                context_id=context.context_id, study_id=study_id,
                plan_revision_id=plan.plan_revision_id, plan_content_hash=plan.content_hash,
                implementation_revision_id=implementation.implementation_revision_id,
                implementation_content_hash=implementation.content_hash,
                status=AnalysisStatus.FAILED,
                outcome=ResearchOutcome.INSUFFICIENT_EVIDENCE,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.analyses.save_analysis(record)
            analyst_run = AnalysisAgentRun(
                project_id=project_id, context_id=context.context_id,
                analysis_id=analysis_id, role=AnalysisAgentRole.STATISTICAL_ANALYST,
                operation="deterministic_analysis_failed", input_context_hash=analyst_input_hash,
                output_record_id=analysis_id, provider_id="deterministic_stdlib",
                model="analysis-v1",
            )
            self.analyses.save_agent_run(analyst_run)
            raise ValueError(f"Analysis {analysis_id} failed and was preserved: {record.error}") from exc

        analyst_run = AnalysisAgentRun(
            project_id=project_id, context_id=context.context_id,
            analysis_id=analysis_id, role=AnalysisAgentRole.STATISTICAL_ANALYST,
            operation="approved_analysis_spec", input_context_hash=analyst_input_hash,
            output_record_id=analysis_id, provider_id="deterministic_stdlib",
            model="analysis-v1",
        )
        self.analyses.save_agent_run(analyst_run)
        verification = self.auditor.verify(analysis_id)
        review, reviewer_run = self.review(analysis_id, verification.verification_id)
        artifacts = self.analyses.list_artifacts(analysis_id)
        persisted_runs = [
            item for item in self.analyses.list_agent_runs(project_id)
            if item.analysis_id == analysis_id
        ]
        return AnalysisWorkflowResult(
            analysis=record, verification=verification, review=review,
            artifacts=artifacts, agent_runs=persisted_runs,
        )

    def verify(self, analysis_id: str) -> VerificationReport:
        return self.auditor.verify(analysis_id)

    def review(self, analysis_id: str, verification_id: str):
        analysis = self._require_analysis(analysis_id)
        verification = self.analyses.get_verification(verification_id)
        if verification is None or verification.analysis_id != analysis_id:
            raise ValueError("VerificationReport does not belong to AnalysisRecord")
        project, context, plan, study, implementation, runs = self._inputs(
            analysis.project_id, analysis.study_id,
        )
        analysis_context = self._review_analysis_context(analysis)
        review_context = {
            "review_contract": {
                "fresh_context": True, "analyst_chat_history_included": False,
                "reviewer_can_modify_artifacts": False,
                "deterministic_statistics_authoritative": True,
                "valid_outcomes": [item.value for item in ResearchOutcome],
            },
            "research_context": context.model_dump(mode="json"),
            "approved_plan": plan.model_dump(mode="json"),
            "implementation": implementation.model_dump(mode="json"),
            "analysis": analysis_context,
            "verification": verification.model_dump(mode="json"),
            "failed_or_incomplete_runs": [
                self._run_digest(item) for item in runs
                if item.status is not ExperimentRunStatus.COMPLETED
            ],
        }
        response = self.reviewer.review(review_context)
        expected_review_hash = canonical_hash(review_context)
        if response.input_context_hash != expected_review_hash:
            raise ValueError("Scientific Reviewer input context hash mismatch")
        draft = response.value
        required_actions = list(draft.required_actions)
        outcome_mismatch = draft.assessed_outcome is not analysis.outcome
        if outcome_mismatch:
            required_actions.append(
                "Reviewer outcome was bounded to the deterministic AnalysisRecord outcome."
            )
        if not verification.passed:
            policy = (
                ScientificRecommendation.REVISE_PLAN
                if not verification.plan_verified
                else ScientificRecommendation.SUPPLEMENT_EXPERIMENT
            )
            may_enter = False
        else:
            policy = (
                ScientificRecommendation.SUPPLEMENT_EXPERIMENT
                if outcome_mismatch else draft.recommendation
            )
            may_enter = (
                not outcome_mismatch and draft.may_enter_research_review
                and policy is ScientificRecommendation.PROCEED_TO_RESEARCH_REVIEW
            )
        report = ScientificReviewReport(
            project_id=analysis.project_id, context_id=analysis.context_id,
            study_id=analysis.study_id, analysis_id=analysis.analysis_id,
            analysis_content_hash=analysis.content_hash,
            verification_id=verification.verification_id,
            verification_context_hash=verification.independent_context_hash,
            verification_report_hash=verification.content_hash,
            assessed_outcome=analysis.outcome,
            reviewer_recommendation=draft.recommendation,
            policy_recommendation=policy, summary=draft.summary,
            claim_strength=draft.claim_strength,
            alternative_explanations=draft.alternative_explanations,
            confounders=draft.confounders, required_actions=required_actions,
            may_enter_research_review=may_enter,
            provider_id=response.provider_id, model=response.model,
            input_context_hash=response.input_context_hash,
        )
        self.analyses.save_review(report)
        run = AnalysisAgentRun(
            project_id=analysis.project_id, context_id=analysis.context_id,
            analysis_id=analysis.analysis_id, role=AnalysisAgentRole.SCIENTIFIC_REVIEWER,
            operation="scientific_review", input_context_hash=response.input_context_hash,
            output_record_id=report.review_id, provider_id=response.provider_id,
            model=response.model, input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        self.analyses.save_agent_run(run)
        return report, run

    @staticmethod
    def _review_analysis_context(analysis):
        return compact_analysis_context(analysis)

    def verify_artifact(self, artifact_id: str) -> AnalysisArtifactVerification:
        artifact = self.analyses.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        project_root = self.workspace.project_root(artifact.project_id).resolve(strict=True)
        path = (project_root / artifact.relative_path).resolve(strict=False)
        try:
            path.relative_to(project_root)
        except ValueError:
            raise ValueError("Analysis Artifact path escapes project") from None
        if not path.is_file() or is_reparse(path):
            return AnalysisArtifactVerification(
                artifact=artifact, exists=False, hash_matches=False,
            )
        digest, size = hash_file(path)
        return AnalysisArtifactVerification(
            artifact=artifact, exists=True,
            hash_matches=digest == artifact.sha256 and size == artifact.size_bytes,
            actual_sha256=digest, actual_size_bytes=size,
        )

    def _verify(self, analysis_id: str) -> VerificationReport:
        analysis = self._require_analysis(analysis_id)
        project, context, plan, study, implementation, runs = self._inputs(
            analysis.project_id, analysis.study_id,
        )
        if analysis.status is not AnalysisStatus.COMPLETED or analysis.payload is None:
            raise ValueError("only completed AnalysisRecords can be verified")
        findings: List[VerificationFinding] = []

        def finding(code, summary, record_type, record_id, expected=None, actual=None,
                    severity=VerificationSeverity.ERROR):
            findings.append(VerificationFinding(
                code=code, severity=severity, summary=summary,
                record_type=record_type, record_id=record_id,
                expected=str(expected) if expected is not None else None,
                actual=str(actual) if actual is not None else None,
            ))

        plan_verified = True
        if plan.content_hash != plan.calculated_hash():
            plan_verified = False
            finding("PLAN_RECORD_HASH", "Stored Experiment Plan hash is invalid.",
                    "ExperimentPlanRevision", plan.plan_revision_id,
                    plan.calculated_hash(), plan.content_hash)
        gate = self.planning.formal_experiment_gate(project.project_id, plan.plan_revision_id)
        if not gate.allowed or gate.plan_content_hash != plan.content_hash:
            plan_verified = False
            finding("PLAN_APPROVAL_GATE", "Experiment Plan no longer passes the formal approval gate.",
                    "ExperimentPlanRevision", plan.plan_revision_id,
                    "allowed with matching hash", gate.reasons)
        for record_type, record_id, value in (
            ("Study", study.study_id, study.plan_content_hash),
            ("AnalysisRecord", analysis.analysis_id, analysis.plan_content_hash),
            ("AnalysisPayload", analysis.analysis_id, analysis.payload.plan_content_hash),
        ):
            if value != plan.content_hash:
                plan_verified = False
                finding("PLAN_HASH_MISMATCH", f"{record_type} is not bound to the approved Plan hash.",
                        record_type, record_id, plan.content_hash, value)

        implementation_verified = True
        if (implementation.content_hash != implementation.calculated_hash()
                or study.implementation_content_hash != implementation.content_hash
                or analysis.implementation_content_hash != implementation.content_hash
                or analysis.payload.implementation_content_hash != implementation.content_hash):
            implementation_verified = False
            finding("IMPLEMENTATION_HASH_MISMATCH", "Implementation binding/hash is inconsistent.",
                    "ImplementationRevision", implementation.implementation_revision_id)
        implementation_root = self.workspace.workspace_root(project.project_id) / study.workspace_relative_root
        try:
            if tree_hash(implementation_root) != study.code_tree_sha256:
                raise ValueError("code tree hash mismatch")
        except (OSError, ValueError) as exc:
            implementation_verified = False
            finding("IMPLEMENTATION_TREE", "Approved implementation tree failed verification.",
                    "Study", study.study_id, study.code_tree_sha256, str(exc))

        lineage_verified = self._verify_lineage(project, context, plan, implementation, finding)
        (runs_verified, seeds_verified, environment_verified,
         run_plan_verified, run_artifacts_verified) = self._verify_runs(
            plan, study, runs, finding,
        )
        plan_verified = plan_verified and run_plan_verified
        specs = {item.run_spec_id: item for item in plan.plan.runs}
        observed_counts = {}
        for observation in analysis.payload.observations:
            # A metric artifact may also expose a deterministic series (for
            # example, one value per epoch).  Those values intentionally have
            # no seed/replicate identity; only seed-level observations can
            # participate in the RunSpec identity checks below.
            if observation.seed is None:
                continue
            spec = specs.get(observation.run_spec_id)
            key = (observation.run_spec_id, observation.metric_id,
                   observation.seed, observation.replicate)
            observed_counts[key] = observed_counts.get(key, 0) + 1
            if (spec is None or observation.seed not in spec.seeds
                    or observation.replicate is None
                    or observation.replicate >= spec.replicates_per_seed):
                seeds_verified = False
                finding("OBSERVATION_SEED", "Metric observation seed/replicate is outside the approved RunSpec.",
                        "Observation", observation.observation_id,
                        f"seeds={spec.seeds if spec else []}",
                        f"seed={observation.seed},replicate={observation.replicate}")
        if any(count > 1 for count in observed_counts.values()):
            seeds_verified = False
            finding("OBSERVATION_DUPLICATE", "Duplicate metric observation seed/replicate detected.",
                    "AnalysisPayload", analysis.analysis_id)
        pair_counts = {}
        for observation in analysis.payload.observations:
            if observation.pair_id:
                key = (observation.metric_id, observation.condition_id, observation.pair_id)
                pair_counts[key] = pair_counts.get(key, 0) + 1
        if any(count > 1 for count in pair_counts.values()):
            seeds_verified = False
            finding("OBSERVATION_PAIR_DUPLICATE", "Duplicate pair IDs detected within a metric/condition.",
                    "AnalysisPayload", analysis.analysis_id)
        source_artifacts_verified, artifacts_verified = self._verify_source_and_analysis_artifacts(
            analysis, study, runs, finding,
        )
        artifacts_verified = artifacts_verified and run_artifacts_verified

        recomputed_hash = None
        statistics_verified = source_artifacts_verified
        if statistics_verified:
            try:
                metric_inputs = self._metric_inputs(plan, runs, require_verified=True)
                recomputed = DeterministicStatistics().analyze(
                    plan, study, runs, metric_inputs,
                )
                recomputed_hash = recomputed.content_hash
                if recomputed.content_hash != analysis.payload.content_hash:
                    statistics_verified = False
                    finding("STATISTIC_MISMATCH", "Stored statistics differ from independent recomputation.",
                            "AnalysisPayload", analysis.analysis_id,
                            recomputed.content_hash, analysis.payload.content_hash)
            except Exception as exc:
                statistics_verified = False
                finding("STATISTIC_RECOMPUTE_FAILED", "Independent statistic recomputation failed.",
                        "AnalysisPayload", analysis.analysis_id, actual=f"{type(exc).__name__}: {exc}")
        else:
            statistics_verified = False
            finding("STATISTIC_SOURCE_UNVERIFIED", "Statistics cannot pass while source bindings fail.",
                    "AnalysisPayload", analysis.analysis_id)

        audit_context = {
            "contract": {
                "independent_context": True, "analyst_chat_history_included": False,
                "read_only_artifacts": True, "deterministic_recalculation": True,
            },
            "analysis_id": analysis.analysis_id,
            "analysis_content_hash": analysis.content_hash,
            "plan_revision_id": plan.plan_revision_id,
            "run_ids": [item.run_id for item in runs],
            "artifact_ids": analysis.payload.source_artifact_ids + analysis.artifact_ids,
        }
        report = VerificationReport(
            project_id=analysis.project_id, context_id=analysis.context_id,
            study_id=analysis.study_id, analysis_id=analysis.analysis_id,
            analysis_content_hash=analysis.content_hash,
            independent_context_hash=canonical_hash(audit_context),
            plan_verified=plan_verified,
            implementation_verified=implementation_verified,
            lineage_verified=lineage_verified, runs_verified=runs_verified,
            artifacts_verified=artifacts_verified, seeds_verified=seeds_verified,
            environment_verified=environment_verified,
            statistics_verified=statistics_verified, findings=findings,
            recomputed_payload_hash=recomputed_hash,
        )
        self.analyses.save_verification(report)
        self.analyses.save_agent_run(self._auditor_run(report))
        return report

    def _verify_lineage(self, project, context, plan, implementation, finding):
        if project.project_type is ProjectType.TOPIC_BASED:
            return True
        binding = plan.plan.b_mode_binding
        records = self.understanding.list_lineage(project.project_id)
        relevant = [
            item for item in records
            if item.context_id == context.context_id
            and item.derived_workspace_path.startswith(implementation.workspace_relative_root + "/")
        ]
        expected = {item.source_relative_path: item for item in binding.code_reuse_decisions}
        actual = {item.source_relative_path: item for item in relevant}
        mappings = {
            item.source_relative_path: item
            for item in implementation.code_package.legacy_mappings
        }
        passed = set(expected) == set(actual) == set(mappings)
        if not passed:
            finding("LINEAGE_COVERAGE", "B-mode CodeLineage does not cover every approved reuse decision.",
                    "ImplementationRevision", implementation.implementation_revision_id,
                    sorted(expected), sorted(actual))
        material_by_path = {item.relative_path: item for item in context.materials}
        for path, decision in expected.items():
            record = actual.get(path)
            mapping = mappings.get(path)
            if record is None:
                continue
            expected_derived = (
                f"{implementation.workspace_relative_root}/{mapping.derived_relative_path}"
                if mapping is not None else None
            )
            if (mapping is None or mapping.action != decision.action.value
                    or record.derived_workspace_path != expected_derived
                    or record.strategy is not binding.recommended_strategy
                    or not record.legacy_baseline
                    or record.base_plan_revision != plan.revision
                    or record.target_plan_revision != plan.revision):
                passed = False
                finding("LINEAGE_DESIGN_FIDELITY", "Derived mapping/action does not faithfully bind the approved legacy design.",
                        "CodeLineageRecord", record.lineage_id)
            material = material_by_path.get(path)
            if (material is None or record.source_sha256 != material.sha256
                    or record.plan_approval_status is not ApprovalStatus.APPROVED
                    or record.verification is not LineageVerification.VERIFIED
                    or not record.execution_eligible):
                passed = False
                finding("LINEAGE_RECORD", "B-mode lineage approval/source binding is invalid.",
                        "CodeLineageRecord", record.lineage_id)
            expected_mods = [item.model_dump(mode="json") for item in decision.modifications]
            actual_mods = [item.model_dump(mode="json") for item in record.modifications]
            if expected_mods != actual_mods:
                passed = False
                finding("LINEAGE_MODIFICATIONS", "Derived implementation changes diverge from approved reuse design.",
                        "CodeLineageRecord", record.lineage_id)
            try:
                source = self.workspace.resolve_import_file(
                    project.project_id, context.import_id, record.source_relative_path,
                )
                derived = self.workspace.resolve_workspace_file(
                    project.project_id, record.derived_workspace_path, must_exist=True,
                )
                if hash_file(source)[0] != record.source_sha256 or hash_file(derived)[0] != record.derived_sha256:
                    raise ValueError("source or derived hash mismatch")
            except (OSError, ValueError) as exc:
                passed = False
                finding("LINEAGE_FILE_HASH", "Source-to-derived file hash verification failed.",
                        "CodeLineageRecord", record.lineage_id, actual=str(exc))
        return passed

    def _verify_runs(self, plan, study, runs, finding):
        runs_verified = True
        seeds_verified = True
        environment_verified = True
        run_plan_verified = True
        artifacts_verified = True
        specs = {item.run_spec_id: item for item in plan.plan.runs}
        for run in runs:
            if run.smoke:
                continue
            spec = specs.get(run.run_spec_id)
            if spec is None:
                runs_verified = False
                finding("UNKNOWN_RUN_SPEC", "Run references an unapproved RunSpec.",
                        "ExperimentRun", run.run_id, actual=run.run_spec_id)
                continue
            if (run.plan_revision_id != plan.plan_revision_id
                    or run.plan_content_hash != plan.content_hash
                    or run.code_tree_sha256 != study.code_tree_sha256):
                runs_verified = False
                if (run.plan_revision_id != plan.plan_revision_id
                        or run.plan_content_hash != plan.content_hash):
                    run_plan_verified = False
                finding("RUN_BINDING", "Run Plan/code binding is inconsistent.",
                        "ExperimentRun", run.run_id)
            expected_config = {
                "study_id": study.study_id,
                "plan_revision_id": plan.plan_revision_id,
                "run_spec": spec.model_dump(mode="json"),
                "smoke": False,
            }
            if run.config != expected_config or run.config_sha256 != canonical_hash(run.config):
                runs_verified = False
                if run.config.get("run_spec", {}).get("seeds") != spec.seeds:
                    seeds_verified = False
                    finding("RUN_SEED_MISMATCH", "Run config seeds differ from approved RunSpec.",
                            "ExperimentRun", run.run_id, spec.seeds,
                            run.config.get("run_spec", {}).get("seeds"))
                finding("RUN_CONFIG", "Run config/hash differs from approved deterministic config.",
                        "ExperimentRun", run.run_id, canonical_hash(expected_config), run.config_sha256)
            try:
                if tree_hash(Path(run.cwd)) != study.code_tree_sha256:
                    raise ValueError("run code snapshot hash mismatch")
            except (OSError, ValueError) as exc:
                runs_verified = False
                finding("RUN_CODE_SNAPSHOT", "Run code snapshot failed hash verification.",
                        "ExperimentRun", run.run_id, study.code_tree_sha256, str(exc))

            artifacts = self.experiments.list_artifacts(run.run_id)
            for artifact in artifacts:
                if not self._experiment_artifact_matches(artifact):
                    artifacts_verified = False
                    finding("RUN_ARTIFACT_HASH", "Run Artifact hash/size verification failed.",
                            "Artifact", artifact.artifact_id, artifact.sha256)
            config_artifact = next((item for item in artifacts if item.kind is ArtifactKind.CONFIG), None)
            env_artifact = next((item for item in artifacts if item.kind is ArtifactKind.ENVIRONMENT), None)
            if config_artifact is None:
                runs_verified = False
                finding("CONFIG_MISSING", "Run has no Config Artifact.",
                        "ExperimentRun", run.run_id)
            else:
                try:
                    payload = self._read_experiment_artifact(config_artifact)
                    if payload != run.config:
                        raise ValueError("config Artifact content mismatch")
                except Exception as exc:
                    runs_verified = False
                    finding("CONFIG_ARTIFACT", "Config Artifact failed verification.",
                            "Artifact", config_artifact.artifact_id, actual=str(exc))
            if env_artifact is None:
                environment_verified = False
                finding("ENVIRONMENT_MISSING", "Run has no Environment Artifact.",
                        "ExperimentRun", run.run_id)
            else:
                try:
                    payload = self._read_experiment_artifact(env_artifact)
                    if payload != run.environment.model_dump(mode="json"):
                        raise ValueError("environment Artifact content mismatch")
                except Exception as exc:
                    environment_verified = False
                    finding("ENVIRONMENT_ARTIFACT", "Environment Artifact failed verification.",
                            "Artifact", env_artifact.artifact_id, actual=str(exc))

        return (runs_verified, seeds_verified, environment_verified,
                run_plan_verified, artifacts_verified)

    def _verify_source_and_analysis_artifacts(self, analysis, study, runs, finding):
        passed = True
        source_passed = True
        if study.visualization_profile_id:
            approval = self.experiments.profile_approval(study.visualization_profile_id)
            if (approval is None or not approval.approved
                    or approval.profile_hash != study.visualization_profile_hash):
                passed = False
                finding("VISUALIZATION_PROFILE_APPROVAL",
                        "Analysis figure is not bound to the approved VisualizationProfile decision.",
                        "Study", study.study_id,
                        study.visualization_profile_hash,
                        approval.profile_hash if approval else None)
        source_ids = set(analysis.payload.source_artifact_ids)
        known = {
            item.artifact_id: item for run in runs
            for item in self.experiments.list_artifacts(run.run_id)
        }
        for artifact_id in source_ids:
            artifact = known.get(artifact_id)
            if artifact is None or artifact.kind is not ArtifactKind.METRICS:
                passed = False
                source_passed = False
                finding("SOURCE_ARTIFACT", "Analysis source does not resolve to a metrics Artifact.",
                        "Artifact", artifact_id)
                continue
            if analysis.payload.source_artifact_hashes.get(artifact_id) != artifact.sha256:
                passed = False
                source_passed = False
                finding("SOURCE_HASH_BINDING", "Analysis payload source hash differs from Artifact record.",
                        "Artifact", artifact_id, artifact.sha256,
                        analysis.payload.source_artifact_hashes.get(artifact_id))
            try:
                self._read_experiment_artifact(artifact)
            except Exception as exc:
                passed = False
                source_passed = False
                finding("ARTIFACT_HASH", "Source Artifact hash/content verification failed.",
                        "Artifact", artifact_id, artifact.sha256, str(exc))

        expected_contents = self._analysis_contents(study, analysis.payload)
        artifacts = self.analyses.list_artifacts(analysis.analysis_id)
        by_name = {Path(item.relative_path).name: item for item in artifacts}
        if set(by_name) != set(expected_contents):
            passed = False
            finding("ANALYSIS_ARTIFACT_COVERAGE", "Analysis Artifact set is incomplete or unexpected.",
                    "AnalysisRecord", analysis.analysis_id,
                    sorted(expected_contents), sorted(by_name))
        for name, content in expected_contents.items():
            artifact = by_name.get(name)
            if artifact is None:
                continue
            verification = self.verify_artifact(artifact.artifact_id)
            actual_expected_hash = self._bytes_hash(content)
            if (not verification.hash_matches or artifact.sha256 != actual_expected_hash
                    or set(artifact.generated_from_artifact_ids) != source_ids):
                passed = False
                finding("ANALYSIS_ARTIFACT_CONTENT", "Analysis table/figure/JSON is not deterministically derived from verified inputs.",
                        "AnalysisArtifact", artifact.artifact_id,
                        actual_expected_hash, artifact.sha256)
        return source_passed, passed

    def _metric_inputs(self, plan, runs, *, require_verified):
        selected = DeterministicStatistics._selected_formal_runs(plan, runs)
        inputs = []
        for spec in plan.plan.runs:
            run = selected.get(spec.run_spec_id)
            if run is None:
                continue
            artifacts = self.experiments.list_artifacts(run.run_id)
            metrics = [item for item in artifacts if item.kind is ArtifactKind.METRICS]
            if len(metrics) != 1:
                if not metrics:
                    continue
                raise ValueError(f"Run {run.run_id} must have exactly one metrics Artifact")
            payload = self._read_experiment_artifact(metrics[0], require_verified=require_verified)
            if not isinstance(payload, dict):
                raise ValueError("metrics Artifact must contain a JSON object")
            inputs.append((run, metrics[0], payload))
        return inputs

    def _read_experiment_artifact(self, artifact, require_verified=True):
        project_root = self.workspace.project_root(artifact.project_id).resolve(strict=True)
        path = (project_root / artifact.relative_path).resolve(strict=True)
        path.relative_to(project_root)
        if is_reparse(path) or path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Artifact is reparse-backed or exceeds analysis limit")
        digest, size = hash_file(path)
        if require_verified and (digest != artifact.sha256 or size != artifact.size_bytes):
            raise ValueError("Artifact hash/size mismatch")
        return json.loads(path.read_text(encoding="utf-8"))

    def _experiment_artifact_matches(self, artifact):
        try:
            project_root = self.workspace.project_root(artifact.project_id).resolve(strict=True)
            path = (project_root / artifact.relative_path).resolve(strict=True)
            path.relative_to(project_root)
            if is_reparse(path):
                return False
            digest, size = hash_file(path)
            return digest == artifact.sha256 and size == artifact.size_bytes
        except (OSError, ValueError):
            return False

    def _materialize_analysis(self, project_id, study, analysis_id, payload):
        project_root = self.workspace.project_root(project_id)
        root = project_root / "analysis" / analysis_id
        root.mkdir(parents=True, exist_ok=False)
        contents = self._analysis_contents(study, payload)
        artifacts = []
        kind_map = {
            "analysis.json": (AnalysisArtifactKind.MACHINE_JSON, "application/json"),
            "results.csv": (AnalysisArtifactKind.TABLE_CSV, "text/csv"),
            "results.svg": (AnalysisArtifactKind.FIGURE_SVG, "image/svg+xml"),
        }
        for name, content in contents.items():
            path = root / name
            data = content.encode("utf-8")
            with path.open("xb") as stream:
                stream.write(data)
            digest, size = hash_file(path)
            kind, media_type = kind_map[name]
            artifacts.append(AnalysisArtifact(
                project_id=project_id, study_id=study.study_id,
                analysis_id=analysis_id, kind=kind,
                relative_path=path.relative_to(project_root).as_posix(),
                sha256=digest, size_bytes=size, media_type=media_type,
                generated_from_artifact_ids=payload.source_artifact_ids,
                visualization_profile_id=(
                    study.visualization_profile_id if kind is AnalysisArtifactKind.FIGURE_SVG else None
                ),
                visualization_profile_hash=(
                    study.visualization_profile_hash if kind is AnalysisArtifactKind.FIGURE_SVG else None
                ),
            ))
        return artifacts

    def _analysis_contents(self, study, payload):
        json_text = json.dumps(
            payload.model_dump(mode="json"), ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        )
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([
            "metric_id", "baseline_condition_id", "target_condition_id", "method",
            "n_baseline", "n_target", "n_pairs", "baseline_mean", "target_mean",
            "effect_estimate", "effect_size", "standard_error", "statistic", "df",
            "p_value", "adjusted_p_value", "multiplicity_method",
            "ci_low", "ci_high", "significant",
        ])
        for item in payload.comparisons:
            interval = item.confidence_interval or [None, None]
            writer.writerow([
                item.metric_id, item.baseline_condition_id, item.target_condition_id,
                item.method.value, item.n_baseline, item.n_target, item.n_pairs,
                self._number(item.baseline_mean), self._number(item.target_mean),
                self._number(item.effect_estimate), self._number(item.effect_size),
                self._number(item.standard_error), self._number(item.statistic),
                self._number(item.degrees_of_freedom), self._number(item.p_value),
                self._number(item.adjusted_p_value), item.multiplicity_method,
                self._number(interval[0]), self._number(interval[1]), item.significant,
            ])
        table = output.getvalue()
        figure = self._svg(study, payload)
        return {"analysis.json": json_text, "results.csv": table, "results.svg": figure}

    def _svg(self, study, payload):
        profile = None
        if study.visualization_profile_id:
            profile = self.understanding.get_profile(study.visualization_profile_id)
            if profile is None or canonical_hash(profile) != study.visualization_profile_hash:
                raise ValueError("approved VisualizationProfile changed before analysis figure generation")
        colors = list(profile.colors) if profile and profile.colors else ["#336699", "#9c755f"]
        summaries = payload.group_summaries
        values = [item.mean for item in summaries if item.mean is not None]
        maximum = max([abs(item) for item in values] + [1.0])
        bars = []
        for index, item in enumerate(summaries):
            value = item.mean or 0.0
            width = abs(value) / maximum * 360.0
            x = 420.0 if value >= 0 else 420.0 - width
            y = 45 + index * 42
            color = colors[index % len(colors)]
            bars.append(
                f'<rect x="{x:.3f}" y="{y}" width="{width:.3f}" height="24" fill="{escape(color)}"/>'
                f'<text x="10" y="{y + 17}" font-size="12">{escape(item.condition_id)} n={item.n}</text>'
                f'<text x="790" y="{y + 17}" text-anchor="end" font-size="12">{self._number(value)}</text>'
            )
        title = escape(payload.comparisons[0].metric_name if payload.comparisons else "Approved analysis")
        height = max(140, 90 + len(summaries) * 42)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="{height}">'
            '<rect width="100%" height="100%" fill="white"/>'
            f'<text x="400" y="24" text-anchor="middle" font-size="16">{title}</text>'
            f'<line x1="420" y1="35" x2="420" y2="{height - 20}" stroke="#333333"/>'
            + "".join(bars)
            + f'<text x="790" y="{height - 8}" text-anchor="end" font-size="10">outcome={payload.outcome.value}</text>'
            + "</svg>"
        )

    @staticmethod
    def _bytes_hash(content):
        import hashlib
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _number(value):
        if value is None:
            return ""
        return format(float(value), ".12g")

    def _inputs(self, project_id, study_id):
        project = self.projects.get(project_id)
        study = self.experiments.get_study(study_id)
        if project is None or study is None or study.project_id != project_id:
            raise ValueError("Study does not belong to project")
        context = self.understanding.get_context(study.context_id)
        plan = self.planning.repository.get_plan(study.plan_revision_id)
        implementation = self.experiments.get_implementation(study.implementation_revision_id)
        if context is None or plan is None or implementation is None:
            raise ValueError("analysis provenance is unavailable")
        return project, context, plan, study, implementation, self.experiments.list_runs(study_id)

    def _require_analysis(self, analysis_id):
        analysis = self.analyses.get_analysis(analysis_id)
        if analysis is None:
            raise KeyError(analysis_id)
        return analysis

    def _auditor_run(self, report):
        return AnalysisAgentRun(
            project_id=report.project_id, context_id=report.context_id,
            analysis_id=report.analysis_id, role=AnalysisAgentRole.VERIFICATION_AUDITOR,
            operation="independent_deterministic_verification",
            input_context_hash=report.independent_context_hash,
            output_record_id=report.verification_id,
            provider_id="deterministic_auditor", model="verification-v1",
        )

    @staticmethod
    def _run_digest(run):
        return {
            "run_id": run.run_id, "run_spec_id": run.run_spec_id,
            "status": run.status.value, "smoke": run.smoke, "attempt": run.attempt,
            "plan_content_hash": run.plan_content_hash,
            "implementation_content_hash": run.implementation_content_hash,
            "code_tree_sha256": run.code_tree_sha256, "config_sha256": run.config_sha256,
            "environment_sha256": run.environment.environment_sha256,
            "artifact_ids": run.artifact_ids,
        }

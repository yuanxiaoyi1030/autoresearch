# Purpose: Recomputes approved descriptive, independent-group, and paired statistics using only deterministic stdlib code.
from __future__ import annotations

from collections import defaultdict
import math
import re
from statistics import mean, median, variance
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from research_runtime.experiments import Artifact, ExperimentRun, ExperimentRunStatus
from research_runtime.planning import ExperimentPlanRevision, MetricDirection, canonical_hash
from research_runtime.state import ResearchOutcome

from .models import (
    AnalysisMethod, AnalysisPayload, GroupSummary, MissingRunFinding, Observation,
    OutlierFinding, StatisticalComparison,
)


def stable_id(prefix: str, payload) -> str:
    return prefix + canonical_hash(payload)[:32]


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 3e-14:
        d = 3e-14
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 3e-14:
            d = 3e-14
        c = 1.0 + aa / c
        if abs(c) < 3e-14:
            c = 3e-14
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 3e-14:
            d = 3e-14
        c = 1.0 + aa / c
        if abs(c) < 3e-14:
            c = 3e-14
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def student_t_cdf(value: float, degrees_of_freedom: float) -> float:
    if degrees_of_freedom <= 0:
        raise ValueError("degrees_of_freedom must be positive")
    if math.isinf(value):
        return 1.0 if value > 0 else 0.0
    x = degrees_of_freedom / (degrees_of_freedom + value * value)
    tail = 0.5 * regularized_beta(x, degrees_of_freedom / 2.0, 0.5)
    return 1.0 - tail if value >= 0 else tail


def student_t_quantile(probability: float, degrees_of_freedom: float) -> float:
    if not 0.5 < probability < 1:
        raise ValueError("only upper Student-t quantiles are supported")
    low, high = 0.0, 1.0
    while student_t_cdf(high, degrees_of_freedom) < probability and high < 1e6:
        high *= 2.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if student_t_cdf(middle, degrees_of_freedom) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


class DeterministicStatistics:
    """Pure computation shared by the Analyst and the independently invoked Auditor."""

    def analyze(self, plan: ExperimentPlanRevision, study, runs: List[ExperimentRun],
                metric_inputs: List[Tuple[ExperimentRun, Artifact, dict]]) -> AnalysisPayload:
        metrics = plan.plan.metrics
        primary = next(item for item in metrics if item.primary)
        selected_runs = self._selected_formal_runs(plan, runs)
        input_by_run = {run.run_id: (artifact, payload) for run, artifact, payload in metric_inputs}
        observations: List[Observation] = []
        source_artifacts = []
        source_hashes = {}
        for run_spec in plan.plan.runs:
            run = selected_runs.get(run_spec.run_spec_id)
            if run is None or run.run_id not in input_by_run:
                continue
            artifact, payload = input_by_run[run.run_id]
            source_artifacts.append(artifact.artifact_id)
            source_hashes[artifact.artifact_id] = artifact.sha256
            observations.extend(self._extract_observations(run, run_spec, artifact, payload, metrics))

        missing = self._missing_findings(plan, runs, selected_runs, observations)
        summaries = self._summaries(plan, observations)
        outliers = self._outliers(observations)
        method, selection_note = self._method(plan)
        comparisons = self._comparisons(plan, observations, primary, method)
        outcome, rationale = self._outcome(primary.direction, comparisons, missing)
        return AnalysisPayload(
            analysis_spec_hash=canonical_hash(plan.plan.analysis),
            plan_content_hash=plan.content_hash,
            implementation_content_hash=study.implementation_content_hash,
            source_run_ids=[selected_runs[key].run_id for key in sorted(selected_runs)],
            source_artifact_ids=sorted(source_artifacts),
            source_artifact_hashes=source_hashes,
            observations=observations, group_summaries=summaries, comparisons=comparisons,
            missing_runs=missing, outliers=outliers,
            method_selection=[selection_note],
            assumption_checks=list(plan.plan.analysis.assumption_checks),
            outcome=outcome, outcome_rationale=rationale,
        )

    @staticmethod
    def _selected_formal_runs(plan, runs):
        selected = {}
        valid_spec_ids = {item.run_spec_id for item in plan.plan.runs}
        for run in runs:
            if run.smoke or run.run_spec_id not in valid_spec_ids:
                continue
            if run.status is ExperimentRunStatus.COMPLETED and run.evidence_eligible:
                current = selected.get(run.run_spec_id)
                if current is None or run.attempt > current.attempt:
                    selected[run.run_spec_id] = run
        return selected

    def _extract_observations(self, run, run_spec, artifact, payload, metrics):
        rows = payload.get("observations") if isinstance(payload, dict) else None
        extracted = []
        if isinstance(rows, list):
            for index, row in enumerate(rows):
                if (not isinstance(row, dict)
                        or not isinstance(row.get("value"), (int, float))
                        or isinstance(row.get("value"), bool)):
                    continue
                metric = self._metric_for_row(row, metrics)
                if metric is None:
                    continue
                seed = (
                    row.get("seed")
                    if isinstance(row.get("seed"), int) and not isinstance(row.get("seed"), bool)
                    else None
                )
                replicate = row.get("replicate", row.get("replicate_id"))
                replicate = (
                    replicate
                    if isinstance(replicate, int) and not isinstance(replicate, bool) and replicate >= 0
                    else None
                )
                pair_id = row.get("pair_id")
                if pair_id is None and seed is not None:
                    pair_id = f"seed:{seed}:replicate:{replicate or 0}"
                base = {
                    "run_id": run.run_id, "run_spec_id": run_spec.run_spec_id,
                    "artifact_id": artifact.artifact_id, "metric_id": metric.metric_id,
                    "condition_id": run_spec.condition_id, "seed": seed,
                    "replicate": replicate, "pair_id": str(pair_id) if pair_id is not None else None,
                    "index": index, "value": float(row["value"]),
                }
                extracted.append(Observation(
                    observation_id=stable_id("obs_", base), metric_name=metric.name,
                    **{key: value for key, value in base.items() if key != "index"},
                ))
            return extracted

        metric_map = payload.get("metrics", {}) if isinstance(payload, dict) else {}
        for metric in metrics:
            raw = None
            if isinstance(metric_map, dict):
                raw = metric_map.get(metric.metric_id, metric_map.get(metric.name))
            if raw is None and isinstance(payload, dict):
                raw = payload.get(metric.metric_id, payload.get(metric.name))
            if raw is None and metric.primary and isinstance(payload, dict):
                raw = payload.get("value")
            if isinstance(raw, dict):
                condition_key = getattr(run_spec, "parameters", {}).get("output_condition_key")
                if condition_key in raw:
                    raw = raw[condition_key]
                elif run_spec.condition_id in raw:
                    raw = raw[run_spec.condition_id]
            values = raw if isinstance(raw, list) else [raw]
            for index, value in enumerate(values):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                seed = run_spec.seeds[index // run_spec.replicates_per_seed] if index < run_spec.expected_runs else None
                replicate = index % run_spec.replicates_per_seed
                base = {
                    "run_id": run.run_id, "run_spec_id": run_spec.run_spec_id,
                    "artifact_id": artifact.artifact_id, "metric_id": metric.metric_id,
                    "condition_id": run_spec.condition_id, "seed": seed,
                    "replicate": replicate,
                    "pair_id": f"seed:{seed}:replicate:{replicate}" if seed is not None else None,
                    "index": index, "value": float(value),
                }
                extracted.append(Observation(
                    observation_id=stable_id("obs_", base), metric_name=metric.name,
                    **{key: child for key, child in base.items() if key != "index"},
                ))
        return extracted

    @staticmethod
    def _metric_for_row(row, metrics):
        identity = str(row.get("metric_id", row.get("metric", row.get("name", "")))).casefold()
        if not identity and len(metrics) == 1:
            return metrics[0]
        return next(
            (item for item in metrics if identity in {item.metric_id.casefold(), item.name.casefold()}),
            None,
        )

    @staticmethod
    def _missing_findings(plan, runs, selected, observations):
        findings = []
        for spec in plan.plan.runs:
            for metric in plan.plan.metrics:
                observed = [
                    item for item in observations
                    if item.run_spec_id == spec.run_spec_id and item.metric_id == metric.metric_id
                ]
                counts = defaultdict(int)
                for item in observed:
                    if item.seed is not None:
                        counts[item.seed] += 1
                missing_seeds = [
                    seed for seed in spec.seeds if counts[seed] < spec.replicates_per_seed
                ]
                failed = [
                    item.run_id for item in runs
                    if not item.smoke and item.run_spec_id == spec.run_spec_id
                    and item.status is not ExperimentRunStatus.COMPLETED
                ]
                if len(observed) < spec.expected_runs or missing_seeds or spec.run_spec_id not in selected:
                    findings.append(MissingRunFinding(
                        run_spec_id=spec.run_spec_id, metric_id=metric.metric_id,
                        expected_observations=spec.expected_runs,
                        observed_observations=len(observed), missing_seeds=missing_seeds,
                        failed_run_ids=failed,
                        reason="Approved metric observations are incomplete; failed attempts are retained.",
                    ))
        return findings

    def _summaries(self, plan, observations):
        grouped = defaultdict(list)
        for item in observations:
            grouped[(item.metric_id, item.condition_id)].append(item.value)
        results = []
        alpha = self._alpha(plan)
        confidence = 1.0 - alpha if alpha is not None else None
        for (metric_id, condition_id), values in sorted(grouped.items()):
            n = len(values)
            avg = mean(values)
            sample_variance = variance(values) if n >= 2 else None
            sd = math.sqrt(sample_variance) if sample_variance is not None else None
            se = sd / math.sqrt(n) if sd is not None else None
            interval = None
            if se is not None and confidence is not None:
                critical = student_t_quantile((1.0 + confidence) / 2.0, n - 1)
                interval = [avg - critical * se, avg + critical * se]
            results.append(GroupSummary(
                metric_id=metric_id, condition_id=condition_id, n=n, mean=avg,
                variance=sample_variance, standard_deviation=sd, standard_error=se,
                minimum=min(values), maximum=max(values), confidence_level=confidence,
                confidence_interval=interval,
            ))
        return results

    @staticmethod
    def _alpha(plan):
        if plan.plan.analysis.significance_level is not None:
            return plan.plan.analysis.significance_level
        text = " ".join(plan.plan.analysis.uncertainty_methods)
        match = re.search(r"(?<!\d)(\d{1,2}(?:\.\d+)?)\s*%", text)
        if match:
            confidence = float(match.group(1)) / 100.0
            if 0.0 < confidence < 1.0:
                return 1.0 - confidence
        return None

    def _apply_multiplicity(self, comparisons, plan):
        alpha = self._alpha(plan)
        text = plan.plan.analysis.multiplicity_correction.casefold()
        populated = [(index, item) for index, item in enumerate(comparisons) if item.p_value is not None]
        adjusted: Dict[int, float] = {}
        if any(token in text for token in ("not applicable", "none", "unadjusted", "single")):
            method = "none"
            adjusted = {index: item.p_value for index, item in populated}
        elif "bonferroni" in text:
            method = "bonferroni"
            count = max(1, len(populated))
            adjusted = {index: min(1.0, item.p_value * count) for index, item in populated}
        elif "holm" in text:
            method = "holm"
            ordered = sorted(populated, key=lambda pair: pair[1].p_value)
            running = 0.0
            count = len(ordered)
            for rank, (index, item) in enumerate(ordered):
                running = max(running, min(1.0, item.p_value * (count - rank)))
                adjusted[index] = running
        else:
            method = "unsupported_prespecified_correction"
        return [
            item.model_copy(update={
                "adjusted_p_value": adjusted.get(index),
                "multiplicity_method": method,
                "significant": (
                    adjusted[index] < alpha
                    if alpha is not None and index in adjusted else None
                ),
            })
            for index, item in enumerate(comparisons)
        ]

    @staticmethod
    def _outliers(observations):
        grouped = defaultdict(list)
        for item in observations:
            grouped[(item.metric_id, item.condition_id)].append(item)
        results = []
        for (metric_id, condition_id), items in grouped.items():
            if len(items) < 4:
                continue
            values = [item.value for item in items]
            q1, q3 = _quantile(values, 0.25), _quantile(values, 0.75)
            spread = q3 - q1
            lower, upper = q1 - 1.5 * spread, q3 + 1.5 * spread
            for item in items:
                if item.value < lower or item.value > upper:
                    results.append(OutlierFinding(
                        observation_id=item.observation_id, metric_id=metric_id,
                        condition_id=condition_id, value=item.value,
                        lower_fence=lower, upper_fence=upper,
                    ))
        return results

    @staticmethod
    def _method(plan):
        design = plan.plan.study.design_type.casefold()
        methods = " ".join(
            plan.plan.analysis.statistical_methods + plan.plan.analysis.comparisons
        ).casefold()
        if (any(token in design for token in ("paired", "matched", "repeated", "crossover"))
                or any(token in methods for token in ("paired", "repeated measures", "crossover"))):
            return AnalysisMethod.PAIRED_T, "Paired t analysis selected from approved matched/paired design text."
        return AnalysisMethod.INDEPENDENT_WELCH, "Welch analysis selected as the conservative two-group fallback."

    def _comparisons(self, plan, observations, metric, method):
        baseline_ids = plan.plan.study.baseline_condition_ids
        target_ids = [
            item.condition_id for item in plan.plan.study.conditions
            if item.condition_id not in baseline_ids
        ]
        results = []
        for baseline_id in baseline_ids:
            for target_id in target_ids:
                baseline = [
                    item for item in observations
                    if item.metric_id == metric.metric_id and item.condition_id == baseline_id
                ]
                target = [
                    item for item in observations
                    if item.metric_id == metric.metric_id and item.condition_id == target_id
                ]
                if method is AnalysisMethod.PAIRED_T:
                    result = self._paired(metric, baseline_id, target_id, baseline, target, plan)
                else:
                    result = self._welch(metric, baseline_id, target_id, baseline, target, plan)
                results.append(result)
        return self._apply_multiplicity(results, plan)

    @staticmethod
    def _base_comparison(metric, baseline_id, target_id, method, baseline, target):
        deterministic_input = {
            "metric_id": metric.metric_id, "baseline_condition_id": baseline_id,
            "target_condition_id": target_id, "method": method.value,
            "baseline": [(item.pair_id, item.seed, item.replicate, item.value) for item in baseline],
            "target": [(item.pair_id, item.seed, item.replicate, item.value) for item in target],
        }
        return deterministic_input, {
            "comparison_id": stable_id("comparison_", deterministic_input),
            "metric_id": metric.metric_id, "metric_name": metric.name,
            "baseline_condition_id": baseline_id, "target_condition_id": target_id,
            "method": method, "n_baseline": len(baseline), "n_target": len(target),
            "deterministic_input_hash": canonical_hash(deterministic_input),
        }

    def _welch(self, metric, baseline_id, target_id, baseline, target, plan):
        inputs, base = self._base_comparison(
            metric, baseline_id, target_id, AnalysisMethod.INDEPENDENT_WELCH, baseline, target,
        )
        alpha = self._alpha(plan)
        confidence = 1.0 - alpha if alpha is not None else None
        if len(baseline) < 2 or len(target) < 2:
            return StatisticalComparison(
                **base, confidence_level=confidence,
                uncertainty_note="At least two observations per condition are required.",
            )
        x, y = [item.value for item in baseline], [item.value for item in target]
        mx, my, vx, vy = mean(x), mean(y), variance(x), variance(y)
        effect = my - mx
        var_effect = vx / len(x) + vy / len(y)
        se = math.sqrt(var_effect)
        denominator = ((vx / len(x)) ** 2 / (len(x) - 1)
                       + (vy / len(y)) ** 2 / (len(y) - 1))
        df = var_effect ** 2 / denominator if denominator > 0 else float(len(x) + len(y) - 2)
        statistic = effect / se if se > 0 else (0.0 if effect == 0 else math.copysign(math.inf, effect))
        p_value = 2.0 * (1.0 - student_t_cdf(abs(statistic), df))
        interval = None
        if alpha is not None:
            critical = student_t_quantile(1.0 - alpha / 2.0, df)
            interval = [effect - critical * se, effect + critical * se]
        pooled_denominator = len(x) + len(y) - 2
        pooled = math.sqrt(((len(x) - 1) * vx + (len(y) - 1) * vy) / pooled_denominator)
        effect_size = None
        if pooled > 0:
            correction = 1.0 - 3.0 / (4.0 * (len(x) + len(y)) - 9.0)
            effect_size = effect / pooled * correction
        return StatisticalComparison(
            **base, baseline_mean=mx, target_mean=my, effect_estimate=effect,
            effect_size=effect_size, variance=var_effect, standard_error=se,
            statistic=statistic if math.isfinite(statistic) else None,
            degrees_of_freedom=df, p_value=max(0.0, min(1.0, p_value)),
            confidence_level=confidence, confidence_interval=interval,
            significant=None,
            uncertainty_note="Two-sided Welch t interval/test; Hedges g uses pooled sample variance.",
        )

    def _paired(self, metric, baseline_id, target_id, baseline, target, plan):
        inputs, base = self._base_comparison(
            metric, baseline_id, target_id, AnalysisMethod.PAIRED_T, baseline, target,
        )
        alpha = self._alpha(plan)
        confidence = 1.0 - alpha if alpha is not None else None
        baseline_by_pair = {item.pair_id: item for item in baseline if item.pair_id}
        target_by_pair = {item.pair_id: item for item in target if item.pair_id}
        pair_ids = sorted(set(baseline_by_pair) & set(target_by_pair))
        differences = [target_by_pair[key].value - baseline_by_pair[key].value for key in pair_ids]
        duplicate_pairs = (
            len(baseline_by_pair) != len([item for item in baseline if item.pair_id])
            or len(target_by_pair) != len([item for item in target if item.pair_id])
        )
        if duplicate_pairs:
            return StatisticalComparison(
                **base, n_pairs=len(differences), confidence_level=confidence,
                uncertainty_note="Duplicate pair IDs make the approved paired analysis non-identifiable.",
            )
        if len(differences) < 2:
            return StatisticalComparison(
                **base, n_pairs=len(differences), confidence_level=confidence,
                uncertainty_note="At least two complete approved pairs are required.",
            )
        effect = mean(differences)
        diff_variance = variance(differences)
        se = math.sqrt(diff_variance / len(differences))
        df = float(len(differences) - 1)
        statistic = effect / se if se > 0 else (0.0 if effect == 0 else math.copysign(math.inf, effect))
        p_value = 2.0 * (1.0 - student_t_cdf(abs(statistic), df))
        interval = None
        if alpha is not None:
            critical = student_t_quantile(1.0 - alpha / 2.0, df)
            interval = [effect - critical * se, effect + critical * se]
        effect_size = effect / math.sqrt(diff_variance) if diff_variance > 0 else None
        return StatisticalComparison(
            **base, n_pairs=len(differences),
            baseline_mean=mean([baseline_by_pair[key].value for key in pair_ids]),
            target_mean=mean([target_by_pair[key].value for key in pair_ids]),
            effect_estimate=effect, effect_size=effect_size, effect_size_name="cohens_dz",
            variance=diff_variance, standard_error=se,
            statistic=statistic if math.isfinite(statistic) else None,
            degrees_of_freedom=df, p_value=max(0.0, min(1.0, p_value)),
            confidence_level=confidence, confidence_interval=interval,
            significant=None,
            uncertainty_note="Two-sided paired t interval/test over complete approved pair IDs.",
        )

    @staticmethod
    def _outcome(direction: MetricDirection, comparisons, missing):
        if missing or not comparisons or any(item.p_value is None for item in comparisons):
            return (
                ResearchOutcome.INSUFFICIENT_EVIDENCE,
                "Approved observations or uncertainty estimates are incomplete; no stronger claim is allowed.",
            )
        primary = comparisons[0]
        if direction is MetricDirection.DESCRIPTIVE or primary.significant is None:
            return (
                ResearchOutcome.INSUFFICIENT_EVIDENCE,
                "The approved AnalysisSpec does not provide an executable inferential threshold/correction.",
            )
        direction_supported = True
        if direction is MetricDirection.MAXIMIZE:
            direction_supported = (primary.effect_estimate or 0.0) > 0
        elif direction is MetricDirection.MINIMIZE:
            direction_supported = (primary.effect_estimate or 0.0) < 0
        if primary.significant and direction_supported:
            return ResearchOutcome.SUPPORTED, "The primary approved comparison passes its prespecified threshold."
        return (
            ResearchOutcome.NEGATIVE_RESULT,
            "The complete primary comparison does not support the prespecified directional/threshold claim.",
        )

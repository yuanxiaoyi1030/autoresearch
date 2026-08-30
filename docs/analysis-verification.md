<!-- Purpose: Documents the deterministic AnalysisSpec execution and independent experiment audit contract. -->
# Analysis and experiment verification contract

## Metrics input

A formal Run may expose one `metrics.json` Artifact. The preferred generic shape is:

```json
{
  "observations": [
    {
      "metric_id": "optional when the Plan has one metric",
      "value": 1.25,
      "seed": 11,
      "replicate": 0,
      "pair_id": "optional matched-unit identifier"
    }
  ]
}
```

For compatibility, `metrics` mappings, metric-name/id fields, and a scalar/list `value` are accepted.
Every accepted observation is rebound to the approved MetricSpec, RunSpec, condition, Artifact, seed,
and replicate. Missing approved metrics, seeds, replicates, conditions, or completed Runs are recorded;
they are never silently imputed.

## Deterministic methods

- matched, paired, repeated-measures, and crossover Study designs use complete-pair t analysis;
- other two-group designs use Welch t analysis;
- summaries include n, mean, sample variance, standard deviation/error, extrema, and approved intervals;
- comparisons include effect estimate, Hedges g or Cohen dz, degrees of freedom, test statistic, raw and
  adjusted p-values, confidence interval, and significance decision;
- `none`, Bonferroni, and Holm correction declarations are executable; unknown declarations do not receive
  a guessed replacement;
- IQR findings are reported but never removed from the analysis data.

`SUPPORTED` requires a complete primary comparison, an executable approved threshold/correction, statistical
support, and the approved metric direction. Complete non-support is `NEGATIVE_RESULT`. Missing observations,
unresolved methods, or unavailable uncertainty are `INSUFFICIENT_EVIDENCE`.

## Independent verification

The Auditor recomputes from files rather than trusting the AnalysisRecord. It checks Plan approval/hash,
implementation and run snapshots, config/seed/environment identity, all Artifact hashes, machine/table/figure
content, and B-mode lineage coverage, source/derived hashes, action, modification list, Plan revision, and
approved reuse strategy. A report includes a fresh context hash, source Analysis hash, independent recomputation
hash, typed findings, and its own immutable content hash.

Scientific review is downstream of verification. Verification failure can only yield a supplement/revise
recommendation. Verification success does not force a positive finding: negative and insufficient outcomes
remain eligible for formal review when their conclusion boundary is scientifically honest.

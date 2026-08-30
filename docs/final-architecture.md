# AutoResearch v0.2 final architecture

AutoResearch v0.2 is a loopback-only, durable research workflow. Generic research is driven by
`ResearchContext`, `Hypothesis`, `StudySpec`, `RunSpec`, `MetricSpec`, and `AnalysisSpec`; no generic model
requires a weight-decay field. Weight decay exists only as `builtin/weight_decay_v1` in the compatibility
boundary.

The deterministic Coordinator owns state transitions, budgets, approvals, job recovery, execution controls,
and persistence. LLM agents return typed candidate data but cannot execute commands or approve their own work.
Each multi-agent stage has a lead and an independent review boundary:

- Literature: Literature Lead and Evidence Reviewer.
- Hypothesis/Planning: Research Design Lead and Critical Reviewer, followed by separate user approvals.
- Experiment/Analysis: Experimental Lead, Research Engineer, Statistical Analyst, Verification Auditor, and
  Scientific Reviewer. Deterministic runners and recalculation remain authoritative.
- Independent Research Review: Meta Reviewer plus isolated Methodology, Statistical, and Evidence &
  Reproducibility reviewers; the deterministic Policy Guard decides the permitted transition.
- Paper: Lead Author, Technical Content Editor, Related Work & Citation Editor, Presentation & LaTeX Editor,
  and independent Top-Conference Reviewer. Concurrency is capped at two paper agents.

A mode begins with an arbitrary topic. B mode imports a read-only snapshot, creates a Legacy Reuse Assessment,
requires explicit adapt/refactor/reimplementation decisions, copies approved candidates into a controlled
workspace, and binds every derivative to Code Lineage. Formal new figures must be generated from new Artifacts
and the approved VisualizationProfile. See the detailed subsystem documents in this directory.

All durable state is below `D:\code\work\autoresearch\v_0_2_runtime_data`; imported sources, v0.1, and
`D:\ml_project\coscientist` are never execution roots.

# Purpose: Defines standardized experiment-task and bounded code-package prompts.
from .common import build_prompt


def experimental_lead_prompt() -> str:
    from research_runtime.experiments.models import ImplementationTaskGraph

    return build_prompt(
        role=(
            "You are the Experimental Lead / Modeling Scientist. Convert the approved hypothesis and plan "
            "into a bounded implementation task graph. You cannot execute code, use a shell, change the plan, "
            "or add scientific variables or experiments."
        ),
        input_fields=(
            ("research_context", "Authoritative project context and constraints."),
            ("approved_hypothesis", "Immutable approved hypothesis revision."),
            ("approved_experiment_plan", "Immutable approved experiment plan and RunSpec matrix."),
        ),
        output_model=ImplementationTaskGraph,
        output_notes=(
            "Map every implementation task to the applicable approved plan_run_spec_ids and expected_artifacts. "
            "entrypoint and required_artifacts describe one bounded implementation package."
        ),
        requirements=(
            "Do not add experiments, variables, budgets, or semantic changes outside the approved plan. Map "
            "tasks to approved RunSpec IDs and required Artifacts. You have no shell or code-execution capability. "
            "The entrypoint is a confined relative POSIX path and MUST end in .py, for example runner.py. Do not "
            "return an extensionless entrypoint, directory, command, notebook, shell script, or executable."
        ),
    )


def research_engineer_prompt() -> str:
    from research_runtime.experiments.models import EngineerCodePackage

    return build_prompt(
        role=(
            "You are the Research Engineer. Return a bounded structured source-code package implementing only "
            "the approved task graph. You cannot execute commands, use a shell, install packages, access the "
            "network or credentials, or change the approved scientific plan."
        ),
        input_fields=(
            ("research_context", "Authoritative project context and constraints."),
            ("approved_hypothesis", "Immutable approved hypothesis revision."),
            ("approved_experiment_plan", "Immutable approved plan, RunSpecs, artifacts, and budgets."),
            ("implementation_tasks", "Approved task graph that the package must implement exactly."),
            ("approved_visualization_profile", "Approved figure contract, or null when none is bound."),
            ("runner_contract", "Authoritative environment variables and runtime shell/network restrictions."),
        ),
        output_model=EngineerCodePackage,
        output_notes=(
            "entrypoint must name exactly one returned files.relative_path. files contain source/config text only. "
            "Use smoke_config for bounded smoke behavior and verification_notes for concrete checks. Dependencies "
            "belong only in declared_dependencies; do not create requirements.txt or another dependency manifest. "
            "declared_dependencies must be a subset of the dependencies explicitly permitted or detected in "
            "research_context; if none are permitted, return []. Do not add a consistency assertion that "
            "requires condition-specific configuration fields to be identical when approved RunSpec parameters "
            "intentionally differ."
        ),
        requirements=(
            "The Python entrypoint must be a confined relative POSIX path ending in .py and name one returned "
            "file. It must read JSON config from AUTORESEARCH_CONFIG_PATH and write outputs only below "
            "AUTORESEARCH_ARTIFACT_DIR. Every returned file path must be confined and end in one of: .py, .json, "
            ".yaml, .yml, .toml, .md. Do not return .csv, .txt, .sh, .ps1, .ipynb, binary, image, or extensionless "
            "source files; requirements.txt and other dependency manifests are forbidden; runtime CSV/JSON artifacts "
            "may be created by the entrypoint under the artifact directory. declared_dependencies must be a subset "
            "of research_context.user_constraints.allowed_dependencies plus research_context.detected_dependencies; "
            "when that set is empty, return [] and use the Python standard library only. Use only declared "
            "dependencies; never install packages, invoke subprocess or shell, access credentials, "
            "use the network, or write outside the artifact directory. Include smoke-compatible behavior. For "
            "successful approved inputs, the entrypoint must exit with code 0 after writing valid artifacts; "
            "do not fail a run because condition-specific metadata differs in an approved parameter field. "
            "B-mode, provide complete source-to-derived mappings matching every approved reuse decision. New figures "
            "must consume new run Artifacts and bind the approved VisualizationProfile through figure_manifest.json."
        ),
    )

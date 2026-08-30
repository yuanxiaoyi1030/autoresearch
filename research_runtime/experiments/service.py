# Purpose: Materializes verified implementations, registers Studies, runs approved specs, and preserves every attempt/artifact.
from __future__ import annotations

import ast
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import threading
from typing import Dict, List, Optional

from research_runtime.planning import (
    ApprovalDecision, ExperimentPlanRevision, PlanningArtifactKind, canonical_hash,
)
from research_runtime.state import ProjectType, utc_now
from research_runtime.understanding import (
    ApprovalStatus, CodeModification, LineageVerification, ModificationClass,
    UnderstandingMode,
)

from .agents import ExperimentalLead, ResearchEngineer
from .executor import LocalStudyExecutor, hash_file, is_reparse, tree_hash
from .models import (
    Artifact, ArtifactKind, ArtifactVerification, ExperimentAgentRole, ExperimentAgentRun,
    ExperimentRun, ExperimentRunDetail, ExperimentRunStatus, ImplementationRevision,
    ImplementationStatus, RunControlRequest, StudyCreationResult, StudyRecord,
    VisualizationProfileApproval,
)


FORBIDDEN_IMPORTS = {
    "subprocess", "socket", "requests", "urllib", "http", "ftplib", "ctypes",
    "multiprocessing", "importlib", "runpy", "pip", "ensurepip",
}
# Python 3.9 (the supported d2l runtime) predates ``sys.stdlib_module_names``.
# Keep this allowlist explicit so implementation validation remains deterministic
# and does not discover or import arbitrary installed modules.
STDLIB_MODULES = frozenset(set(sys.builtin_module_names) | {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii",
    "bisect", "calendar", "cmath", "collections", "concurrent", "contextlib",
    "contextvars", "copy", "csv", "dataclasses", "datetime", "decimal",
    "difflib", "enum", "fractions", "functools", "gc", "getopt", "glob",
    "gzip", "hashlib", "heapq", "hmac", "html", "inspect", "io", "itertools",
    "json", "logging", "lzma", "math", "mimetypes", "numbers", "operator",
    "os", "pathlib", "pickle", "platform", "pprint", "queue", "random", "re",
    "secrets", "shlex", "shutil", "signal", "statistics", "string", "struct",
    "sys", "tempfile", "textwrap", "threading", "time", "timeit", "traceback",
    "types", "typing", "unicodedata", "uuid", "warnings", "weakref", "xml",
    "zipfile", "zlib",
})
FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "__import__", "os.system", "os.popen", "os.open",
    "os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.rename", "os.renames",
    "os.replace", "shutil.rmtree", "shutil.move", "pathlib.Path.unlink",
    "pathlib.Path.rename", "pathlib.Path.replace", "pathlib.Path.rmdir",
}
SENSITIVE_NAME = re.compile(
    r"(?i)(api_?key|access_?token|refresh_?token|authorization|cookie|password|secret|credential|bearer)"
)


class ImplementationValidator:
    def validate(self, package, context) -> None:
        local_modules = {
            Path(item.relative_path).stem for item in package.files
            if item.relative_path.endswith(".py")
        }
        allowed_declared = {item.casefold().replace("-", "_") for item in package.declared_dependencies}
        user_allowed = {item.casefold().replace("-", "_") for item in context.user_constraints.allowed_dependencies}
        detected = {item.casefold().replace("-", "_") for item in context.detected_dependencies}
        if user_allowed and not allowed_declared <= user_allowed | detected:
            raise ValueError("implementation declares a dependency outside user constraints")
        forbidden_user = {
            item.casefold().replace("-", "_")
            for item in context.user_constraints.forbidden_dependencies
        }
        if allowed_declared & forbidden_user:
            raise ValueError("implementation declares a user-forbidden dependency")
        for item in package.files:
            if not item.relative_path.endswith(".py"):
                continue
            try:
                tree = ast.parse(item.content, filename=item.relative_path)
            except SyntaxError as exc:
                raise ValueError(f"implementation Python syntax error: {item.relative_path}:{exc.lineno}") from None
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    for name in names:
                        top = name.split(".", 1)[0]
                        if top in FORBIDDEN_IMPORTS:
                            raise ValueError(f"forbidden runtime capability import: {top}")
                        if (top not in STDLIB_MODULES and top not in local_modules
                                and top.casefold() not in allowed_declared):
                            raise ValueError(f"undeclared implementation dependency: {top}")
                if isinstance(node, ast.Call):
                    called = self._call_name(node.func)
                    if called in FORBIDDEN_CALLS:
                        raise ValueError(f"forbidden runtime call: {called}")
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if SENSITIVE_NAME.search(node.value) and "AUTORESEARCH_" not in node.value:
                        raise ValueError("implementation contains a credential-sensitive literal")

    @staticmethod
    def _call_name(node) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))


class StudyImplementationService:
    def __init__(self, projects, understanding, planning, experiments, workspace,
                 code_lineage, lead: ExperimentalLead, engineer: ResearchEngineer,
                 executor: LocalStudyExecutor, events=None) -> None:
        self.projects = projects
        self.understanding = understanding
        self.planning = planning
        self.experiments = experiments
        self.workspace = workspace
        self.code_lineage = code_lineage
        self.lead = lead
        self.engineer = engineer
        self.executor = executor
        self.events = events
        self.validator = ImplementationValidator()
        self._threads: Dict[str, threading.Thread] = {}
        self._thread_lock = threading.RLock()
        self.recovered_runs = self.experiments.recover_running()

    def decide_visualization_profile(self, project_id: str, profile_id: str,
                                     approved: bool, feedback: str) -> VisualizationProfileApproval:
        profile = self.understanding.get_profile(profile_id)
        if profile is None or profile.project_id != project_id:
            raise ValueError("VisualizationProfile does not belong to project")
        if not feedback.strip():
            raise ValueError("VisualizationProfile decision requires feedback")
        decision = VisualizationProfileApproval(
            project_id=project_id, profile_id=profile_id,
            profile_hash=canonical_hash(profile), approved=approved, feedback=feedback,
        )
        self.experiments.save_profile_approval(decision)
        return decision

    def create_study(self, project_id: str, plan_revision_id: str,
                     visualization_profile_id: Optional[str] = None,
                     parent_implementation_id: Optional[str] = None) -> StudyCreationResult:
        plan = self.planning.require_formal_experiment(project_id, plan_revision_id)
        project = self.projects.get(project_id)
        context = self.understanding.get_context(plan.context_id)
        hypothesis = self.planning.repository.get_hypothesis(plan.hypothesis_revision_id)
        if project is None or context is None or hypothesis is None:
            raise ValueError("approved planning provenance is unavailable")
        profile, profile_hash = self._approved_profile(
            project_id, context, visualization_profile_id,
        )
        latest = self.experiments.latest_implementation(project_id)
        if latest is not None:
            if not parent_implementation_id or latest.implementation_revision_id != parent_implementation_id:
                raise ValueError("new Implementation Revision must descend from the latest implementation")
            revision_number = latest.revision + 1
        else:
            if parent_implementation_id:
                raise ValueError("initial implementation cannot specify a parent")
            revision_number = 0

        lead_response = self.lead.create_tasks(context, hypothesis, plan)
        self._validate_tasks(plan, lead_response.value)
        engineer_response = self.engineer.implement(
            context, hypothesis, plan, lead_response.value, profile,
        )
        package = engineer_response.value
        if package.entrypoint != lead_response.value.entrypoint:
            raise ValueError("Research Engineer entrypoint diverges from Experimental Lead tasks")
        self.validator.validate(package, context)
        self._validate_b_mode(project.project_type, context, plan, package)

        semantic = any(
            item.classification is ModificationClass.SEMANTIC
            for item in package.implementation_modifications
        )
        if semantic:
            implementation = ImplementationRevision(
                project_id=project_id, context_id=context.context_id,
                plan_revision_id=plan.plan_revision_id, plan_content_hash=plan.content_hash,
                revision=revision_number, parent_revision_id=parent_implementation_id,
                task_graph=lead_response.value, code_package=package,
                status=ImplementationStatus.REQUIRES_PLAN_REVISION,
                rejection_reasons=[
                    "Research Engineer proposed semantic changes outside the approved Plan; "
                    "create and approve a new Experiment Plan revision."
                ],
            )
            self.experiments.save_implementation(implementation)
            agent_runs = self._save_agent_runs(
                project_id, context.context_id, implementation, lead_response, engineer_response,
            )
            return StudyCreationResult(
                implementation=implementation, study=None, agent_runs=agent_runs,
            )

        implementation_id = "implrev_" + os.urandom(16).hex()
        relative_root = f"implementations/{implementation_id}"
        absolute_root = self.workspace.workspace_root(project_id) / relative_root
        self._materialize(absolute_root, package)
        code_hash = tree_hash(absolute_root)
        implementation = ImplementationRevision(
            implementation_revision_id=implementation_id,
            project_id=project_id, context_id=context.context_id,
            plan_revision_id=plan.plan_revision_id, plan_content_hash=plan.content_hash,
            revision=revision_number, parent_revision_id=parent_implementation_id,
            task_graph=lead_response.value, code_package=package,
            status=ImplementationStatus.VERIFIED,
            workspace_relative_root=relative_root, code_tree_sha256=code_hash,
        )
        self.experiments.save_implementation(implementation)
        agent_runs = self._save_agent_runs(
            project_id, context.context_id, implementation, lead_response, engineer_response,
        )
        lineage_ids = self._record_lineage(
            project, context, plan, implementation, package,
        )
        study = StudyRecord(
            project_id=project_id, context_id=context.context_id,
            plan_revision_id=plan.plan_revision_id, plan_content_hash=plan.content_hash,
            implementation_revision_id=implementation.implementation_revision_id,
            implementation_content_hash=implementation.content_hash,
            name=plan.plan.study.name, objective=plan.plan.study.objective,
            entrypoint=package.entrypoint, workspace_relative_root=relative_root,
            code_tree_sha256=code_hash,
            run_spec_ids=[item.run_spec_id for item in plan.plan.runs],
            visualization_profile_id=profile.profile_id if profile else None,
            visualization_profile_hash=profile_hash,
        )
        self.experiments.save_study(study)
        return StudyCreationResult(
            implementation=implementation, study=study,
            lineage_ids=lineage_ids, agent_runs=agent_runs,
        )

    def start_run(self, project_id: str, study_id: str, run_spec_id: str,
                  *, smoke: bool = False, parent_run_id: Optional[str] = None) -> ExperimentRun:
        study, plan, implementation, run_spec = self._run_inputs(
            project_id, study_id, run_spec_id,
        )
        if not smoke and not any(
            item.smoke and item.status is ExperimentRunStatus.COMPLETED
            for item in self.experiments.list_runs(study_id)
        ):
            raise ValueError("a completed smoke Run is required before a formal Run")
        if not smoke and parent_run_id is None and any(
            not item.smoke and item.run_spec_id == run_spec_id
            for item in self.experiments.list_runs(study_id)
        ):
            raise ValueError("this RunSpec already has an immutable formal attempt; use resume")
        if smoke and parent_run_id is None and any(
            item.smoke and item.run_spec_id == run_spec_id
            for item in self.experiments.list_runs(study_id)
        ):
            raise ValueError("this RunSpec already has an immutable smoke attempt; use resume")
        config = {
            "study_id": study.study_id,
            "plan_revision_id": plan.plan_revision_id,
            "run_spec": run_spec.model_dump(mode="json"),
            "smoke": smoke,
        }
        if smoke:
            config["run_spec"]["seeds"] = run_spec.seeds[:1]
            config["run_spec"]["replicates_per_seed"] = 1
            config["smoke_overrides"] = implementation.code_package.smoke_config.model_dump(
                mode="json", exclude_none=True,
            )
        return self._create_and_start(
            project_id, study, plan, implementation, run_spec,
            config, smoke, parent_run_id,
        )

    def _create_and_start(self, project_id, study, plan, implementation, run_spec,
                          config, smoke, parent_run_id):
        run_id = "run_" + os.urandom(16).hex()
        prepared = self.executor.prepare(
            project_root=self.workspace.project_root(project_id),
            workspace_root=self.workspace.workspace_root(project_id),
            source_root=self.workspace.workspace_root(project_id) / study.workspace_relative_root,
            run_id=run_id, entrypoint=study.entrypoint,
            approved_code_hash=study.code_tree_sha256, config=config,
            dependencies=implementation.code_package.declared_dependencies,
            visualization_profile=self._profile_payload(study),
        )
        parent = self.experiments.get_run(parent_run_id) if parent_run_id else None
        run = ExperimentRun(
            run_id=run_id, project_id=project_id, study_id=study.study_id,
            run_spec_id=run_spec.run_spec_id, parent_run_id=parent_run_id,
            attempt=(parent.attempt + 1 if parent else 1), smoke=smoke,
            evidence_eligible=not smoke, plan_revision_id=plan.plan_revision_id,
            plan_content_hash=plan.content_hash,
            implementation_revision_id=implementation.implementation_revision_id,
            implementation_content_hash=implementation.content_hash,
            code_tree_sha256=prepared.code_hash, config_sha256=prepared.config_hash,
            config=config, environment=prepared.environment,
            command_arguments=prepared.command, cwd=str(prepared.code_root),
            timeout_seconds=(30 if smoke else min(
                900, run_spec.resource_request.estimated_minutes_per_replicate * 60 + 30,
            )), output_limit_bytes=1_048_576,
        )
        self.experiments.create_run(run)
        thread = threading.Thread(
            target=self._execute_run,
            args=(run, prepared, study.entrypoint),
            name=f"study-run-{run.run_id}", daemon=True,
        )
        with self._thread_lock:
            self._threads[run.run_id] = thread
        thread.start()
        return run

    def pause_run(self, run_id: str) -> ExperimentRun:
        run = self._require_run(run_id)
        if run.status not in {ExperimentRunStatus.QUEUED, ExperimentRunStatus.RUNNING}:
            raise ValueError("only queued/running Runs can be paused")
        return self.experiments.request_control(run_id, RunControlRequest.PAUSE)

    def cancel_run(self, run_id: str) -> ExperimentRun:
        run = self._require_run(run_id)
        if run.status not in {ExperimentRunStatus.QUEUED, ExperimentRunStatus.RUNNING}:
            raise ValueError("only queued/running Runs can be cancelled")
        return self.experiments.request_control(run_id, RunControlRequest.CANCEL)

    def resume_run(self, run_id: str) -> ExperimentRun:
        parent = self._require_run(run_id)
        if parent.status not in {
            ExperimentRunStatus.PAUSED, ExperimentRunStatus.FAILED,
            ExperimentRunStatus.STALE, ExperimentRunStatus.TIMED_OUT,
            ExperimentRunStatus.OUTPUT_LIMIT_EXCEEDED,
        }:
            raise ValueError("only paused/failed/interrupted Runs can be resumed")
        study, plan, implementation, run_spec = self._run_inputs(
            parent.project_id, parent.study_id, parent.run_spec_id,
        )
        return self._create_and_start(
            parent.project_id, study, plan, implementation, run_spec,
            parent.config, parent.smoke, parent.run_id,
        )

    def detail(self, run_id: str) -> ExperimentRunDetail:
        run = self._require_run(run_id)
        return ExperimentRunDetail(run=run, artifacts=self.experiments.list_artifacts(run_id))

    def verify_artifact(self, artifact_id: str) -> ArtifactVerification:
        artifact = self.experiments.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        project_root = self.workspace.project_root(artifact.project_id).resolve(strict=True)
        path = (project_root / artifact.relative_path).resolve(strict=False)
        try:
            path.relative_to(project_root)
        except ValueError:
            raise ValueError("Artifact path escapes project") from None
        if not path.is_file() or is_reparse(path):
            return ArtifactVerification(artifact=artifact, exists=False, hash_matches=False)
        digest, size = hash_file(path)
        return ArtifactVerification(
            artifact=artifact, exists=True,
            hash_matches=digest == artifact.sha256 and size == artifact.size_bytes,
            actual_sha256=digest, actual_size_bytes=size,
        )

    def _execute_run(self, run, prepared, entrypoint):
        running = run.model_copy(update={
            "status": ExperimentRunStatus.RUNNING, "started_at": utc_now(),
        })
        self.experiments.update_run(running)
        outcome = self.executor.execute(
            prepared, entrypoint=entrypoint,
            timeout_seconds=running.timeout_seconds,
            output_limit_bytes=running.output_limit_bytes,
            control=lambda: self._control(running.run_id),
        )
        finished = running.model_copy(update={
            "status": outcome.status, "control_request": RunControlRequest.NONE,
            "exit_code": outcome.exit_code, "termination_reason": outcome.reason,
            "resource_usage": outcome.usage, "error": outcome.error,
            "finished_at": utc_now(),
        })
        records = []
        artifact_error = None
        try:
            records = self._register_artifacts(finished, prepared)
        except Exception as exc:
            artifact_error = f"artifact registration failed: {type(exc).__name__}: {exc}"
        if artifact_error:
            finished = finished.model_copy(update={
                "status": ExperimentRunStatus.FAILED,
                "termination_reason": "artifact_registration_error",
                "error": artifact_error,
            })
        finished = finished.model_copy(update={
            "artifact_ids": [item.artifact_id for item in records],
        })
        self.experiments.update_run(finished)
        with self._thread_lock:
            self._threads.pop(run.run_id, None)

    def _register_artifacts(self, run, prepared):
        candidates = [
            (prepared.config_path, ArtifactKind.CONFIG),
            (prepared.environment_path, ArtifactKind.ENVIRONMENT),
            (prepared.stdout_path, ArtifactKind.STDOUT),
            (prepared.stderr_path, ArtifactKind.STDERR),
        ]
        for path in sorted(item for item in prepared.artifact_root.rglob("*") if item.is_file()):
            name = path.name.casefold()
            if name == "metrics.json":
                kind = ArtifactKind.METRICS
            elif name == "figure_manifest.json":
                kind = ArtifactKind.FIGURE_MANIFEST
            elif path.suffix.casefold() in {".png", ".svg", ".jpg", ".jpeg"}:
                kind = ArtifactKind.FIGURE
            elif "analysis" in name:
                kind = ArtifactKind.ANALYSIS
            elif path.suffix.casefold() in {".pt", ".pth", ".ckpt"}:
                kind = ArtifactKind.CHECKPOINT
            else:
                kind = ArtifactKind.OUTPUT
            candidates.append((path, kind))
        manifest = self._figure_manifest(run, prepared, candidates)
        project_root = self.workspace.project_root(run.project_id).resolve(strict=True)
        records = []
        by_artifact_relative = {}
        for path, kind in candidates:
            resolved = path.resolve(strict=True)
            resolved.relative_to(prepared.run_root)
            if is_reparse(path):
                raise ValueError("Artifact cannot be a symlink or junction")
            digest, size = hash_file(path)
            artifact_relative = (
                path.relative_to(prepared.artifact_root).as_posix()
                if prepared.artifact_root in path.parents else None
            )
            record = Artifact(
                project_id=run.project_id, study_id=run.study_id, run_id=run.run_id,
                kind=kind, relative_path=resolved.relative_to(project_root).as_posix(),
                sha256=digest, size_bytes=size,
                media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                evidence_eligible=run.evidence_eligible and run.status is ExperimentRunStatus.COMPLETED,
            )
            records.append(record)
            if artifact_relative:
                by_artifact_relative[artifact_relative] = record
        if manifest:
            for figure_path, details in manifest.get("figures", {}).items():
                figure = by_artifact_relative.get(figure_path)
                if figure is None or figure.kind is not ArtifactKind.FIGURE:
                    raise ValueError("figure_manifest references an unknown figure")
                input_ids = []
                for input_path in details.get("inputs", []):
                    source = by_artifact_relative.get(input_path)
                    if source is None:
                        raise ValueError("figure_manifest references an unknown input Artifact")
                    input_ids.append(source.artifact_id)
                updated = figure.model_copy(update={
                    "visualization_profile_id": manifest["profile_id"],
                    "visualization_profile_hash": manifest["profile_hash"],
                    "generated_from_artifact_ids": input_ids,
                })
                records[records.index(figure)] = updated
                by_artifact_relative[figure_path] = updated
        # Artifact rows are append-only: all metadata is finalized before the
        # first insert, including figure-to-input and profile bindings.
        return [self.experiments.add_artifact(record) for record in records]

    def _figure_manifest(self, run, prepared, candidates):
        figures = [path for path, kind in candidates if kind is ArtifactKind.FIGURE]
        if not figures:
            return None
        study = self.experiments.get_study(run.study_id)
        if not study.visualization_profile_id:
            return None
        path = prepared.artifact_root / "figure_manifest.json"
        if not path.is_file() or path.stat().st_size > 1_048_576:
            raise ValueError("approved VisualizationProfile requires bounded figure_manifest.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (payload.get("profile_id") != study.visualization_profile_id
                or payload.get("profile_hash") != study.visualization_profile_hash):
            raise ValueError("figure_manifest does not bind the approved VisualizationProfile")
        if set(payload.get("figures", {})) != {
            item.relative_to(prepared.artifact_root).as_posix() for item in figures
        }:
            raise ValueError("every new figure must appear exactly once in figure_manifest")
        profile = self.understanding.get_profile(study.visualization_profile_id)
        if profile.colors:
            for figure in figures:
                if figure.suffix.casefold() == ".svg":
                    text = figure.read_text(encoding="utf-8", errors="replace").casefold()
                    if not any(color.casefold() in text for color in profile.colors):
                        raise ValueError("SVG does not use an approved VisualizationProfile color")
        return payload

    def _run_inputs(self, project_id, study_id, run_spec_id):
        study = self.experiments.get_study(study_id)
        if study is None or study.project_id != project_id:
            raise ValueError("Study does not belong to project")
        plan = self.planning.require_formal_experiment(project_id, study.plan_revision_id)
        implementation = self.experiments.get_implementation(study.implementation_revision_id)
        if implementation is None or implementation.status is not ImplementationStatus.VERIFIED:
            raise ValueError("Study implementation is not verified")
        if implementation.content_hash != study.implementation_content_hash:
            raise ValueError("Study implementation hash mismatch")
        if tree_hash(self.workspace.workspace_root(project_id) / study.workspace_relative_root) != study.code_tree_sha256:
            raise ValueError("Study code changed after verification")
        run_spec = next((item for item in plan.plan.runs if item.run_spec_id == run_spec_id), None)
        if run_spec is None or run_spec_id not in study.run_spec_ids:
            raise ValueError("RunSpec is not registered by Study")
        return study, plan, implementation, run_spec

    def _approved_profile(self, project_id, context, profile_id):
        profiles = self.understanding.list_profiles(project_id)
        current = [item for item in profiles if item.context_id == context.context_id]
        if context.mode is UnderstandingMode.EXISTING_PROJECT and current and not profile_id:
            raise ValueError("B-mode Study with a detected VisualizationProfile requires explicit approval/binding")
        if not profile_id:
            return None, None
        profile = self.understanding.get_profile(profile_id)
        approval = self.experiments.profile_approval(profile_id)
        if profile is None or profile.project_id != project_id or profile.context_id != context.context_id:
            raise ValueError("VisualizationProfile does not belong to current project/context")
        if approval is None or not approval.approved or approval.profile_hash != canonical_hash(profile):
            raise ValueError("VisualizationProfile requires a matching user approval")
        return profile, approval.profile_hash

    def _profile_payload(self, study):
        if not study.visualization_profile_id:
            return {}
        profile = self.understanding.get_profile(study.visualization_profile_id)
        if profile is None or canonical_hash(profile) != study.visualization_profile_hash:
            raise ValueError("Study VisualizationProfile hash verification failed")
        payload = profile.model_dump(mode="json")
        payload["approved_profile_hash"] = study.visualization_profile_hash
        return payload

    @staticmethod
    def _validate_tasks(plan, tasks):
        run_ids = {item.run_spec_id for item in plan.plan.runs}
        referenced = {run_id for item in tasks.tasks for run_id in item.plan_run_spec_ids}
        if referenced - run_ids:
            raise ValueError("Experimental Lead task references an unknown RunSpec")
        if referenced != run_ids:
            raise ValueError("Experimental Lead tasks must cover every approved RunSpec")
        if tasks.entrypoint.startswith("/") or ".." in Path(tasks.entrypoint).parts:
            raise ValueError("Experimental Lead entrypoint escapes implementation")

    @staticmethod
    def _validate_b_mode(project_type, context, plan, package):
        if project_type is ProjectType.TOPIC_BASED:
            if package.legacy_mappings:
                raise ValueError("A-mode implementation cannot claim legacy code mappings")
            return
        binding = plan.plan.b_mode_binding
        if binding is None:
            raise ValueError("B-mode approved Plan is missing reuse binding")
        approved = {item.source_relative_path: item for item in binding.code_reuse_decisions}
        mappings = {item.source_relative_path: item for item in package.legacy_mappings}
        if set(mappings) != set(approved):
            raise ValueError("Research Engineer must map every approved B-mode code decision")
        derived = {item.relative_path for item in package.files}
        for source, mapping in mappings.items():
            if mapping.derived_relative_path not in derived:
                raise ValueError("legacy mapping derived file is absent from Engineer package")
            if mapping.action != approved[source].action.value:
                raise ValueError("legacy mapping action diverges from approved Plan")
            approved_mods = [item.model_dump(mode="json") for item in approved[source].modifications]
            actual_mods = [item.model_dump(mode="json") for item in mapping.modifications]
            if actual_mods != approved_mods:
                raise ValueError("legacy mapping modifications diverge from approved Plan")

    @staticmethod
    def _materialize(root: Path, package):
        root.mkdir(parents=True, exist_ok=False)
        try:
            for item in package.files:
                destination = root / item.relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(item.content)
            manifest = {
                "entrypoint": package.entrypoint,
                "files": [{"relative_path": item.relative_path,
                           "content_hash": canonical_hash(item.content)} for item in package.files],
                "declared_dependencies": package.declared_dependencies,
            }
            with (root / "implementation_manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            # Only the newly-created implementation root is recoverable scratch at this point.
            import shutil
            shutil.rmtree(root, ignore_errors=True)
            raise

    def _record_lineage(self, project, context, plan, implementation, package):
        if project.project_type is ProjectType.TOPIC_BASED:
            return []
        records = []
        for mapping in package.legacy_mappings:
            modifications = [CodeModification.model_validate(item.model_dump(mode="json"))
                             for item in mapping.modifications]
            record = self.code_lineage.record_candidate(
                project_id=project.project_id, context_id=context.context_id,
                source_relative_path=mapping.source_relative_path,
                derived_workspace_path=(
                    f"{implementation.workspace_relative_root}/{mapping.derived_relative_path}"
                ),
                strategy=plan.plan.b_mode_binding.recommended_strategy,
                modifications=modifications, copy_from_snapshot=False,
                base_plan_revision=plan.revision, target_plan_revision=plan.revision,
                legacy_baseline=True, plan_approval_status=ApprovalStatus.APPROVED,
                verification=LineageVerification.VERIFIED,
                auditor_notes=[
                    f"Bound to approved Plan {plan.plan_revision_id}/{plan.content_hash}",
                    f"Implementation Revision {implementation.implementation_revision_id}/{implementation.content_hash}",
                    f"Reuse action: {mapping.action}",
                ],
            )
            if not record.execution_eligible:
                raise ValueError("B-mode CodeLineageRecord did not become execution eligible")
            records.append(record.lineage_id)
        return records

    def _save_agent_runs(self, project_id, context_id, implementation, lead_response, engineer_response):
        runs = [
            ExperimentAgentRun(
                project_id=project_id, context_id=context_id,
                role=ExperimentAgentRole.EXPERIMENTAL_LEAD, operation="implementation_tasks",
                input_context_hash=lead_response.input_context_hash,
                output_artifact_id=implementation.implementation_revision_id,
                provider_id=lead_response.provider_id, model=lead_response.model,
                input_tokens=lead_response.input_tokens, output_tokens=lead_response.output_tokens,
            ),
            ExperimentAgentRun(
                project_id=project_id, context_id=context_id,
                role=ExperimentAgentRole.RESEARCH_ENGINEER, operation="code_package",
                input_context_hash=engineer_response.input_context_hash,
                output_artifact_id=implementation.implementation_revision_id,
                provider_id=engineer_response.provider_id, model=engineer_response.model,
                input_tokens=engineer_response.input_tokens, output_tokens=engineer_response.output_tokens,
            ),
        ]
        for run in runs:
            self.experiments.save_agent_run(run)
        return runs

    def _control(self, run_id):
        run = self.experiments.get_run(run_id)
        return run.control_request if run else RunControlRequest.CANCEL

    def _require_run(self, run_id):
        run = self.experiments.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

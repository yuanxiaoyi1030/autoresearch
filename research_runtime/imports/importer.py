# Purpose: Creates a hash-verified read-only legacy snapshot without importing or executing source code.
import json
import shutil
from pathlib import Path
from typing import Callable, Optional

from research_runtime.state import ImportSession, ImportStatus, ProjectType, utc_now
from research_runtime.workspace import WorkspaceManager

from .manifest import ManifestBuilder, sha256_file


CopyFunction = Callable[[Path, Path], object]


class ExistingProjectImporter:
    def __init__(self, projects, imports, workspace: WorkspaceManager,
                 allowed_import_roots: tuple, copy_function: CopyFunction = shutil.copy2) -> None:
        self.projects = projects
        self.imports = imports
        self.workspace = workspace
        self.allowed_import_roots = allowed_import_roots
        self.copy_function = copy_function
        self.manifests = ManifestBuilder()

    def recover_interrupted(self) -> int:
        recovered = 0
        for session in self.imports.list_with_status(ImportStatus.RUNNING):
            self.imports.update(session.model_copy(update={
                "status": ImportStatus.STALE,
                "error": "interrupted before completion",
                "updated_at": utc_now(),
            }))
            recovered += 1
        return recovered

    def import_project(self, project_id: str, source_root: Path,
                       progress: Optional[Callable[[str, str, dict], None]] = None) -> ImportSession:
        progress = progress or (lambda event_type, summary, payload: None)
        project = self.projects.get(project_id)
        if project is None:
            raise KeyError(project_id)
        if project.project_type is not ProjectType.EXISTING_PROJECT:
            raise ValueError("only existing_project projects can import legacy sources")
        source = self.workspace.require_allowed_source(Path(source_root), self.allowed_import_roots)
        declared_source = Path(project.source_root).resolve(strict=True)
        if source != declared_source:
            raise ValueError("import source must match the project source_root")
        progress("import.scan_started", "Scanning source as data without executing files", {"source_root": str(source)})
        manifest = self.manifests.scan(source)
        existing = self.imports.find_completed(project_id, str(source), manifest.manifest_hash)
        if existing is not None:
            progress("import.reused", "Reused content-identical import", {"import_id": existing.import_id})
            return existing

        session = ImportSession(
            project_id=project_id,
            source_root=str(source),
            status=ImportStatus.RUNNING,
            manifest_hash=manifest.manifest_hash,
        )
        self.imports.create(session)
        final_root = self.workspace.import_root(project_id, session.import_id)
        temporary_root = final_root.parent / ("." + session.import_id + ".tmp")
        try:
            temporary_root.mkdir(parents=True, exist_ok=False)
            snapshot_root = temporary_root / "snapshot"
            for item in manifest.files:
                source_file = source / Path(item.relative_path)
                target_file = snapshot_root / Path(item.relative_path)
                target_file.parent.mkdir(parents=True, exist_ok=True)
                self.copy_function(source_file, target_file)
                if sha256_file(target_file) != item.sha256:
                    raise OSError(f"snapshot hash mismatch: {item.relative_path}")
            (temporary_root / "manifest.json").write_text(
                json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            temporary_root.replace(final_root)
            completed = session.model_copy(update={
                "status": ImportStatus.COMPLETED,
                "snapshot_path": str(final_root / "snapshot"),
                "updated_at": utc_now(),
            })
            self.imports.save_completed(completed, manifest)
            state = self.projects.get_state(project_id)
            if state is not None:
                self.projects.update_state(state.model_copy(update={"latest_import_id": completed.import_id}))
            progress("import.completed", "Read-only source snapshot completed", {
                "import_id": completed.import_id,
                "files": manifest.total_files,
                "manifest_hash": manifest.manifest_hash,
            })
            return completed
        except Exception as exc:
            failed = session.model_copy(update={
                "status": ImportStatus.FAILED,
                "error": f"{type(exc).__name__}: {exc}",
                "updated_at": utc_now(),
            })
            self.imports.update(failed)
            raise

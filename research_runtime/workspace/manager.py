# Purpose: Resolves project-confined v0.2 runtime paths and rejects traversal, symlinks, and junctions.
import os
import stat
from pathlib import Path
from typing import Iterable


RUNTIME_DIRECTORIES = ("projects", "compatibility", "cache", "exports", "tmp")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class WorkspaceManager:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root).resolve(strict=False)

    def ensure_runtime(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        for name in RUNTIME_DIRECTORIES:
            (self.runtime_root / name).mkdir(exist_ok=True)

    def project_root(self, project_id: str) -> Path:
        self._validate_identifier(project_id)
        return self.runtime_root / "projects" / project_id

    def import_root(self, project_id: str, import_id: str) -> Path:
        self._validate_identifier(import_id)
        return self.project_root(project_id) / "imports" / import_id

    def resolve_import_file(self, project_id: str, import_id: str, relative_path: str) -> Path:
        """Resolve a regular file inside an immutable import snapshot without following reparses."""
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise WorkspaceBoundaryError("import path must be a non-empty relative path")
        supplied = Path(relative_path)
        if supplied.is_absolute() or supplied.anchor or ".." in supplied.parts:
            raise WorkspaceBoundaryError("absolute paths and parent traversal are not allowed")
        root = (self.import_root(project_id, import_id) / "snapshot").resolve(strict=True)
        self._reject_reparse(root)
        candidate = root.joinpath(*[part for part in supplied.parts if part not in {"", "."}])
        current = root
        for part in candidate.relative_to(root).parts:
            current = current / part
            if current.exists() or current.is_symlink():
                self._reject_reparse(current)
        resolved = candidate.resolve(strict=True)
        if not is_relative_to(resolved, root):
            raise WorkspaceBoundaryError("import path escapes the immutable snapshot")
        if not resolved.is_file():
            raise FileNotFoundError(relative_path)
        return resolved

    def workspace_root(self, project_id: str, create: bool = True) -> Path:
        root = self.project_root(project_id) / "workspace"
        if create:
            root.mkdir(parents=True, exist_ok=True)
        return root.resolve(strict=False)

    def resolve_workspace_file(self, project_id: str, relative_path: str, *,
                               must_exist: bool = False, create_parent: bool = False) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise WorkspaceBoundaryError("workspace path must be a non-empty relative path")
        supplied = Path(relative_path)
        if supplied.is_absolute() or supplied.anchor or ".." in supplied.parts:
            raise WorkspaceBoundaryError("absolute paths and parent traversal are not allowed")
        root = self.workspace_root(project_id)
        self._reject_reparse(root)
        candidate = root.joinpath(*[part for part in supplied.parts if part not in {"", "."}])
        if candidate == root:
            raise WorkspaceBoundaryError("workspace path must identify a file")
        current = root
        for part in candidate.relative_to(root).parts:
            current = current / part
            if current.exists() or current.is_symlink():
                self._reject_reparse(current)
        resolved = candidate.resolve(strict=False)
        if not is_relative_to(resolved, root):
            raise WorkspaceBoundaryError("workspace path escapes the active project")
        if create_parent:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            current = root
            for part in candidate.parent.relative_to(root).parts:
                current = current / part
                self._reject_reparse(current)
            if not is_relative_to(candidate.resolve(strict=False), root):
                raise WorkspaceBoundaryError("workspace parent escapes the active project")
        if must_exist:
            if not candidate.exists() or not candidate.is_file():
                raise FileNotFoundError(relative_path)
            self._reject_reparse(candidate)
        elif candidate.exists() and not candidate.is_file():
            raise WorkspaceBoundaryError("workspace path is not a regular file")
        return candidate

    @staticmethod
    def require_allowed_source(source: Path, allowed_roots: Iterable[Path]) -> Path:
        resolved = Path(source).resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("import source must be a directory")
        if not any(is_relative_to(resolved, Path(root).resolve(strict=False)) for root in allowed_roots):
            raise ValueError("import source is outside allowed roots")
        WorkspaceManager._reject_reparse(resolved)
        return resolved

    @staticmethod
    def _reject_reparse(path: Path) -> None:
        try:
            value = os.lstat(str(path))
        except FileNotFoundError:
            return
        attributes = getattr(value, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if stat.S_ISLNK(value.st_mode) or (attributes & reparse_flag):
            raise WorkspaceBoundaryError(f"symlink or junction is not allowed: {path.name}")

    @staticmethod
    def _validate_identifier(value: str) -> None:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        if not value or any(char not in allowed for char in value):
            raise ValueError("invalid workspace identifier")


class WorkspaceBoundaryError(ValueError):
    pass

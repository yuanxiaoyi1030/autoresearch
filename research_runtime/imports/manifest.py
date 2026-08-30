# Purpose: Builds stable manifests without executing or modifying imported research files.
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import List

from research_runtime.state import ExcludedMaterial, ImportManifest, SourceMaterial


EXCLUDED_DIRECTORIES = {
    ".git", ".next", ".matplotlib_cache", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "__pycache__", "build", "dist", "node_modules", "v_0_1_runtime_data", "v_0_2_runtime_data",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def is_reparse(path: Path) -> bool:
    value = os.lstat(str(path))
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python_source"
    if suffix in {".r", ".jl", ".m", ".sh", ".ps1", ".js", ".ts"}:
        return "code_source"
    if suffix == ".ipynb":
        return "notebook"
    if suffix in {".md", ".txt", ".rst"}:
        return "text"
    if suffix == ".pdf":
        return "paper_pdf"
    if suffix in {".tex", ".bib"}:
        return "paper_source"
    if suffix in {".ppt", ".pptx"}:
        return "presentation"
    if suffix in {".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock"}:
        return "configuration"
    if suffix in {
        ".json", ".csv", ".tsv", ".parquet", ".feather", ".arrow",
        ".npy", ".npz", ".h5", ".hdf5", ".mat",
    }:
        return "structured_data"
    if suffix in {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".eps"}:
        return "figure"
    return "binary_or_other"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ManifestBuilder:
    def scan(self, source_root: Path) -> ImportManifest:
        source_root = Path(source_root).resolve(strict=True)
        files: List[SourceMaterial] = []
        excluded: List[ExcludedMaterial] = []
        for directory, dirnames, filenames in os.walk(str(source_root), followlinks=False):
            kept_directories = []
            for name in sorted(dirnames):
                candidate = Path(directory) / name
                if name.lower() in EXCLUDED_DIRECTORIES:
                    excluded.append(ExcludedMaterial(
                        relative_path=candidate.relative_to(source_root).as_posix(),
                        reason=f"excluded_directory:{name}",
                    ))
                elif is_reparse(candidate):
                    excluded.append(ExcludedMaterial(
                        relative_path=candidate.relative_to(source_root).as_posix(),
                        reason="symlink_or_reparse_directory",
                    ))
                else:
                    kept_directories.append(name)
            dirnames[:] = kept_directories
            for filename in sorted(filenames):
                path = Path(directory) / filename
                relative_path = path.relative_to(source_root).as_posix()
                if is_reparse(path):
                    excluded.append(ExcludedMaterial(
                        relative_path=relative_path, reason="symlink_or_reparse_file",
                    ))
                    continue
                if path.suffix.lower() in EXCLUDED_SUFFIXES:
                    excluded.append(ExcludedMaterial(relative_path=relative_path, reason="excluded_cache_suffix"))
                    continue
                stat_result = path.stat()
                files.append(SourceMaterial(
                    relative_path=relative_path,
                    size_bytes=stat_result.st_size,
                    mtime_ns=stat_result.st_mtime_ns,
                    sha256=sha256_file(path),
                    media_type=classify(path),
                ))
        files.sort(key=lambda item: item.relative_path)
        excluded.sort(key=lambda item: item.relative_path)
        canonical = [
            {
                "relative_path": item.relative_path,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
                "media_type": item.media_type,
            }
            for item in files
        ]
        manifest_hash = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        warnings = ["Imported observations, code, and figures remain unverified until reproduced."]
        if excluded:
            warnings.append(f"Excluded {len(excluded)} build, cache, runtime, or symlink entries.")
        return ImportManifest(
            manifest_hash=manifest_hash,
            source_root=str(source_root),
            files=files,
            total_files=len(files),
            total_bytes=sum(item.size_bytes for item in files),
            excluded=excluded,
            warnings=warnings,
        )

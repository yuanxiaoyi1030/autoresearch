# Purpose: Imports v0.1 weight-decay evidence through a read-only SQLite and hash-verified copy boundary.
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
from typing import Any, Dict, Iterable, List, Sequence, Tuple
import uuid

from research_runtime.imports.manifest import sha256_file

from .models import (
    BuiltinStudyDescriptor, CompatibilityArtifactCheck, CompatibilityVerification,
    V01ArtifactReference, V01CompatibilityImport, V01RunReference,
)


BUILTIN_WEIGHT_DECAY_V1 = BuiltinStudyDescriptor(
    builtin_id="builtin/weight_decay_v1",
    display_name="v0.1 Weight Decay Condensation Regression",
    legacy_study_id="weight_decay_condensation_v1",
    expected_conditions=[
        {"condition": condition, "seed": seed, "weight_decay": weight_decay}
        for condition, weight_decay in (("baseline", 0.0), ("treatment", 0.001))
        for seed in (0, 1, 2)
    ],
)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_reparse(path: Path) -> bool:
    result = os.lstat(str(path))
    attributes = getattr(result, "st_file_attributes", 0)
    return stat.S_ISLNK(result.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


class V01CompatibilityImporter:
    REQUIRED_TABLE_COLUMNS = {
        "experiment_runs": {
            "run_id", "project_id", "job_id", "plan_hash", "fixture_id", "status",
            "evidence_eligible", "config_sha256", "payload_json", "finished_at",
        },
        "artifacts": {
            "artifact_id", "project_id", "run_id", "kind", "relative_path", "sha256",
            "size_bytes", "evidence_eligible", "payload_json",
        },
    }

    def __init__(self, repository, v0_2_runtime_root: Path,
                 v0_1_runtime_root: Path) -> None:
        self.repository = repository
        self.v0_2_runtime_root = Path(v0_2_runtime_root).resolve(strict=False)
        self.v0_1_runtime_root = Path(v0_1_runtime_root).resolve(strict=False)
        if self.v0_2_runtime_root == self.v0_1_runtime_root:
            raise ValueError("v0.1 and v0.2 runtime roots must be distinct")
        if (_is_relative_to(self.v0_2_runtime_root, self.v0_1_runtime_root)
                or _is_relative_to(self.v0_1_runtime_root, self.v0_2_runtime_root)):
            raise ValueError("v0.1 and v0.2 runtime roots must not overlap")

    @staticmethod
    def builtins() -> List[BuiltinStudyDescriptor]:
        return [BUILTIN_WEIGHT_DECAY_V1]

    def import_weight_decay_v1(self) -> V01CompatibilityImport:
        if not self.v0_1_runtime_root.is_dir() or _is_reparse(self.v0_1_runtime_root):
            raise ValueError("configured v0.1 runtime root is unavailable or is a reparse point")
        database = self._source_database()
        database_hash_before = sha256_file(database)
        runs, raw_runs, artifact_rows = self._read_verified_cohort(database)
        verified_artifacts = self._verify_source_artifacts(raw_runs, artifact_rows)
        source_manifest_hash = _canonical_hash({
            "builtin": BUILTIN_WEIGHT_DECAY_V1.model_dump(mode="json"),
            "source_database_sha256": database_hash_before,
            "runs": [item.model_dump(mode="json") for item in runs],
            "artifacts": [
                {
                    "artifact_id": item["artifact_id"],
                    "run_id": item["run_id"],
                    "kind": item["kind"],
                    "relative_path": item["relative_path"],
                    "sha256": item["sha256"],
                    "size_bytes": item["size_bytes"],
                }
                for item, _ in verified_artifacts
            ],
        })
        existing = self.repository.find(
            "v0.1", BUILTIN_WEIGHT_DECAY_V1.builtin_id, source_manifest_hash,
        )
        if existing is not None:
            verification = self.verify(existing.compatibility_import_id)
            if not verification.passed:
                raise ValueError("existing v0.1 compatibility snapshot failed verification")
            if sha256_file(database) != database_hash_before:
                raise ValueError("v0.1 database changed while reusing compatibility import")
            return existing

        import_id = "compat_" + source_manifest_hash[:32]
        relative_root = Path("compatibility") / "v0_1" / source_manifest_hash[:32]
        final_root = self.v0_2_runtime_root / relative_root
        temporary_root = final_root.parent / (".tmp_" + uuid.uuid4().hex[:12])
        if final_root.exists():
            recovered = self._recover_orphaned_snapshot(final_root, source_manifest_hash)
            return self.repository.save(recovered)
        temporary_root.mkdir(parents=True, exist_ok=False)
        try:
            imported: List[V01ArtifactReference] = []
            for row, source in verified_artifacts:
                suffix = PurePosixPath(row["relative_path"]).name
                artifact_relative = Path("artifacts") / (
                    row["artifact_id"] + PurePosixPath(suffix).suffix
                )
                target = temporary_root / artifact_relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(source), str(target))
                copied_hash = sha256_file(target)
                copied_size = target.stat().st_size
                if copied_hash != row["sha256"] or copied_size != row["size_bytes"]:
                    raise OSError(f"compatibility copy hash mismatch: {row['artifact_id']}")
                payload = json.loads(row["payload_json"])
                imported.append(V01ArtifactReference(
                    legacy_artifact_id=row["artifact_id"],
                    legacy_run_id=row["run_id"], kind=row["kind"],
                    media_type=payload.get("media_type") or (
                        mimetypes.guess_type(suffix)[0] or "application/octet-stream"
                    ),
                    source_relative_path=(
                        Path("projects") / row["project_id"] / Path(row["relative_path"])
                    ).as_posix(),
                    source_sha256=row["sha256"], source_size_bytes=row["size_bytes"],
                    imported_relative_path=(relative_root / artifact_relative).as_posix(),
                    imported_sha256=copied_hash, imported_size_bytes=copied_size,
                    evidence_eligible=bool(row["evidence_eligible"]),
                ))

            database_hash_after = sha256_file(database)
            for row, source in verified_artifacts:
                if sha256_file(source) != row["sha256"] or source.stat().st_size != row["size_bytes"]:
                    raise ValueError("v0.1 Artifact changed during compatibility import")
            if database_hash_after != database_hash_before:
                raise ValueError("v0.1 database changed during compatibility import")
            record = V01CompatibilityImport(
                compatibility_import_id=import_id,
                source_runtime_root=str(self.v0_1_runtime_root),
                source_database_relative_path=database.name,
                source_database_sha256_before=database_hash_before,
                source_database_sha256_after=database_hash_after,
                source_manifest_hash=source_manifest_hash,
                imported_manifest_relative_path=(relative_root / "manifest.json").as_posix(),
                source_integrity_unchanged=True,
                runs=runs, artifacts=imported,
                warnings=[
                    "v0.1 code and Notebook cells were not imported or executed.",
                    "Legacy evidence is hash-verified but remains scientifically unverified until reproduced in v0.2.",
                ],
            )
            (temporary_root / "manifest.json").write_text(
                json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            temporary_root.replace(final_root)
            return self.repository.save(record)
        except Exception:
            if temporary_root.exists():
                shutil.rmtree(temporary_root)
            raise

    def verify(self, compatibility_import_id: str) -> CompatibilityVerification:
        record = self.repository.get(compatibility_import_id)
        if record is None:
            raise KeyError(compatibility_import_id)
        manifest = self._v0_2_path(record.imported_manifest_relative_path)
        manifest_exists = manifest.is_file() and not _is_reparse(manifest)
        manifest_matches = False
        findings: List[str] = []
        if manifest_exists:
            try:
                persisted = V01CompatibilityImport.model_validate_json(
                    manifest.read_text(encoding="utf-8")
                )
                manifest_matches = (
                    persisted.model_dump(mode="json") == record.model_dump(mode="json")
                    and persisted.source_manifest_hash == record.source_manifest_hash
                )
            except Exception:
                manifest_matches = False
        if not manifest_exists:
            findings.append("compatibility manifest is missing")
        elif not manifest_matches:
            findings.append("compatibility manifest differs from the immutable database record")
        checks = []
        for artifact in record.artifacts:
            path = self._v0_2_path(artifact.imported_relative_path)
            exists = path.is_file() and not _is_reparse(path)
            actual = sha256_file(path) if exists else None
            matched = exists and actual == artifact.imported_sha256
            checks.append(CompatibilityArtifactCheck(
                legacy_artifact_id=artifact.legacy_artifact_id,
                exists=exists, hash_matches=matched,
                expected_sha256=artifact.imported_sha256, actual_sha256=actual,
            ))
            if not matched:
                findings.append(f"imported Artifact failed hash verification: {artifact.legacy_artifact_id}")
        return CompatibilityVerification(
            compatibility_import_id=compatibility_import_id,
            passed=manifest_exists and manifest_matches and all(item.hash_matches for item in checks),
            manifest_exists=manifest_exists, manifest_hash_matches=manifest_matches,
            artifact_checks=checks, findings=findings,
        )

    def artifact_path(self, compatibility_import_id: str, legacy_artifact_id: str) -> Path:
        record = self.repository.get(compatibility_import_id)
        if record is None:
            raise KeyError(compatibility_import_id)
        artifact = next(
            (item for item in record.artifacts if item.legacy_artifact_id == legacy_artifact_id),
            None,
        )
        if artifact is None:
            raise KeyError(legacy_artifact_id)
        path = self._v0_2_path(artifact.imported_relative_path)
        if not path.is_file() or _is_reparse(path) or sha256_file(path) != artifact.imported_sha256:
            raise ValueError("compatibility Artifact failed immutable verification")
        return path

    def _source_database(self) -> Path:
        database = self.v0_1_runtime_root / "autoresearch.sqlite3"
        if not database.is_file() or _is_reparse(database):
            raise ValueError("v0.1 autoresearch.sqlite3 is unavailable or unsafe")
        return database

    def _connect_read_only(self, database: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(
            database.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        self._validate_schema(connection)
        return connection

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table, required in self.REQUIRED_TABLE_COLUMNS.items():
            if table not in tables:
                raise ValueError(f"v0.1 database is missing table {table}")
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            missing = required - columns
            if missing:
                raise ValueError(f"v0.1 table {table} is missing columns: {sorted(missing)}")

    def _read_verified_cohort(self, database: Path):
        connection = self._connect_read_only(database)
        try:
            rows = connection.execute(
                """SELECT payload_json FROM experiment_runs
                   WHERE fixture_id=? AND status='completed' AND evidence_eligible=1""",
                (BUILTIN_WEIGHT_DECAY_V1.legacy_study_id,),
            ).fetchall()
            payloads = [json.loads(row["payload_json"]) for row in rows]
            cohorts: Dict[Tuple[str, str, str], List[dict]] = {}
            for payload in payloads:
                key = (
                    str(payload.get("project_id", "")), str(payload.get("job_id", "")),
                    str(payload.get("plan_hash", "")),
                )
                cohorts.setdefault(key, []).append(payload)
            valid = []
            for key, values in cohorts.items():
                try:
                    references = self._validate_cohort(key, values)
                except ValueError:
                    continue
                valid.append((max(str(item.get("finished_at") or "") for item in values), references, values))
            if not valid:
                raise ValueError("v0.1 database has no complete exact weight-decay regression cohort")
            _, references, selected = max(valid, key=lambda item: item[0])
            run_ids = [item.legacy_run_id for item in references]
            placeholders = ",".join("?" for _ in run_ids)
            artifact_rows = [dict(row) for row in connection.execute(
                f"""SELECT artifact_id,project_id,run_id,kind,relative_path,sha256,
                    size_bytes,evidence_eligible,payload_json FROM artifacts
                    WHERE run_id IN ({placeholders}) ORDER BY run_id,relative_path,artifact_id""",
                run_ids,
            ).fetchall()]
        finally:
            connection.close()
        selected_by_id = {item["run_id"]: item for item in selected}
        ordered_payloads = [selected_by_id[item.legacy_run_id] for item in references]
        return references, ordered_payloads, artifact_rows

    def _validate_cohort(self, key: Tuple[str, str, str], values: Sequence[dict]) -> List[V01RunReference]:
        expected = {
            (item["condition"], item["seed"]): float(item["weight_decay"])
            for item in BUILTIN_WEIGHT_DECAY_V1.expected_conditions
        }
        found: Dict[Tuple[str, int], dict] = {}
        for payload in values:
            config = payload.get("config") or {}
            condition = str(config.get("condition", ""))
            seed = config.get("seed")
            matrix_key = (condition, seed)
            if matrix_key not in expected:
                continue
            if matrix_key in found:
                raise ValueError("duplicate condition in v0.1 cohort")
            if payload.get("fixture_id") != BUILTIN_WEIGHT_DECAY_V1.legacy_study_id:
                raise ValueError("legacy fixture ID mismatch")
            if payload.get("status") != "completed" or not payload.get("evidence_eligible"):
                raise ValueError("legacy cohort contains ineligible Run")
            if config.get("study_id") != BUILTIN_WEIGHT_DECAY_V1.legacy_study_id:
                raise ValueError("legacy config Study ID mismatch")
            if float(config.get("weight_decay", -1)) != expected[matrix_key]:
                raise ValueError("legacy weight-decay matrix mismatch")
            if config.get("paired_initialization_key") != f"weight_decay_v1_seed_{seed}":
                raise ValueError("legacy pairing key mismatch")
            if config.get("device") != "cpu":
                raise ValueError("legacy regression cohort was not CPU-bound")
            if _canonical_hash(config) != payload.get("config_sha256"):
                raise ValueError("legacy Run config hash mismatch")
            found[matrix_key] = payload
        if set(found) != set(expected) or len(values) != 6:
            raise ValueError("legacy cohort is not the exact six-run registered matrix")
        references = []
        for condition in ("baseline", "treatment"):
            for seed in (0, 1, 2):
                payload = found[(condition, seed)]
                config = payload["config"]
                references.append(V01RunReference(
                    legacy_run_id=payload["run_id"], legacy_project_id=key[0],
                    legacy_job_id=key[1], legacy_plan_hash=key[2],
                    condition=condition, seed=seed,
                    weight_decay=float(config["weight_decay"]),
                    paired_initialization_key=config["paired_initialization_key"],
                    config_sha256=payload["config_sha256"], status="completed",
                    finished_at=payload.get("finished_at"),
                ))
        return references

    def _verify_source_artifacts(self, raw_runs: Sequence[dict], artifact_rows: Sequence[dict]):
        run_by_id = {item["run_id"]: item for item in raw_runs}
        rows_by_run: Dict[str, List[dict]] = {run_id: [] for run_id in run_by_id}
        verified = []
        for row in artifact_rows:
            if row["run_id"] not in run_by_id or row["project_id"] != run_by_id[row["run_id"]]["project_id"]:
                raise ValueError("v0.1 Artifact ownership mismatch")
            path = self._source_artifact_path(row["project_id"], row["relative_path"])
            if path.stat().st_size != row["size_bytes"] or sha256_file(path) != row["sha256"]:
                raise ValueError(f"v0.1 Artifact hash mismatch: {row['artifact_id']}")
            rows_by_run[row["run_id"]].append(row)
            verified.append((row, path))
        for run_id, payload in run_by_id.items():
            rows = rows_by_run[run_id]
            if not any(item["kind"] == "metrics" for item in rows):
                raise ValueError(f"v0.1 Run has no metrics Artifact: {run_id}")
            expected_ids = set(payload.get("artifact_ids") or [])
            actual_ids = {item["artifact_id"] for item in rows}
            if expected_ids != actual_ids:
                raise ValueError(f"v0.1 Run Artifact set differs from its immutable record: {run_id}")
        return verified

    def _source_artifact_path(self, project_id: str, relative_path: str) -> Path:
        relative = PurePosixPath(relative_path.replace("\\", "/"))
        if not relative_path.strip() or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("v0.1 Artifact path is not confined")
        project_root = self.v0_1_runtime_root / "projects" / project_id
        if not project_root.is_dir() or _is_reparse(project_root):
            raise ValueError("v0.1 Artifact project root is unavailable or unsafe")
        lexical = project_root
        for part in relative.parts:
            lexical = lexical / part
            if lexical.exists() and _is_reparse(lexical):
                raise ValueError("v0.1 Artifact path crosses a symlink or reparse point")
        resolved = lexical.resolve(strict=True)
        project_resolved = project_root.resolve(strict=True)
        if not _is_relative_to(resolved, project_resolved):
            raise ValueError("v0.1 Artifact path escapes its project root")
        if not resolved.is_file():
            raise ValueError("v0.1 Artifact is not a regular file")
        return resolved

    def _v0_2_path(self, relative_path: str) -> Path:
        relative = PurePosixPath(relative_path.replace("\\", "/"))
        if not relative_path.strip() or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("compatibility path is not confined")
        lexical = self.v0_2_runtime_root.joinpath(*relative.parts)
        resolved = lexical.resolve(strict=False)
        if not _is_relative_to(resolved, self.v0_2_runtime_root):
            raise ValueError("compatibility path escapes v0.2 runtime")
        return resolved

    def _recover_orphaned_snapshot(self, final_root: Path,
                                   source_manifest_hash: str) -> V01CompatibilityImport:
        manifest = final_root / "manifest.json"
        if not manifest.is_file() or _is_reparse(manifest):
            raise ValueError("orphaned compatibility directory has no valid manifest")
        record = V01CompatibilityImport.model_validate_json(manifest.read_text(encoding="utf-8"))
        if record.source_manifest_hash != source_manifest_hash:
            raise ValueError("orphaned compatibility manifest belongs to different source content")
        for artifact in record.artifacts:
            target = self._v0_2_path(artifact.imported_relative_path)
            if not target.is_file() or _is_reparse(target) or sha256_file(target) != artifact.imported_sha256:
                raise ValueError("orphaned compatibility snapshot contains a mismatched Artifact")
        return record

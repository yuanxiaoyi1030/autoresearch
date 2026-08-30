# Purpose: Persists immutable v0.1 compatibility imports with content-based idempotency.
from __future__ import annotations

import sqlite3
from typing import List, Optional

from research_runtime.compatibility.models import V01CompatibilityImport
from research_runtime.security import assert_secret_free

from storage.database import Database


class CompatibilityRepository:
    def __init__(self, database: Database, known_secrets=lambda: ()) -> None:
        self.database = database
        self.known_secrets = known_secrets

    def save(self, record: V01CompatibilityImport) -> V01CompatibilityImport:
        assert_secret_free(
            record.model_dump(mode="json"), self.known_secrets(),
            context="V01CompatibilityImport",
        )
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """INSERT INTO compatibility_imports(
                       compatibility_import_id,source_version,builtin_id,legacy_study_id,
                       source_manifest_hash,status,import_json,created_at
                       ) VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        record.compatibility_import_id, record.source_version,
                        record.builtin_id, record.legacy_study_id,
                        record.source_manifest_hash, record.status.value,
                        record.model_dump_json(), record.created_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.find(
                record.source_version, record.builtin_id, record.source_manifest_hash,
            )
            if existing is None:
                raise ValueError("compatibility import identity conflict") from None
            return existing
        return record

    def get(self, compatibility_import_id: str) -> Optional[V01CompatibilityImport]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT import_json FROM compatibility_imports WHERE compatibility_import_id=?",
                (compatibility_import_id,),
            ).fetchone()
        return V01CompatibilityImport.model_validate_json(row["import_json"]) if row else None

    def find(self, source_version: str, builtin_id: str,
             source_manifest_hash: str) -> Optional[V01CompatibilityImport]:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT import_json FROM compatibility_imports
                   WHERE source_version=? AND builtin_id=? AND source_manifest_hash=?""",
                (source_version, builtin_id, source_manifest_hash),
            ).fetchone()
        return V01CompatibilityImport.model_validate_json(row["import_json"]) if row else None

    def list(self) -> List[V01CompatibilityImport]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT import_json FROM compatibility_imports
                   ORDER BY created_at,compatibility_import_id"""
            ).fetchall()
        return [V01CompatibilityImport.model_validate_json(row["import_json"]) for row in rows]

# Purpose: Persists v0.2 import sessions and immutable manifest details.
from datetime import datetime
from typing import List, Optional

from research_runtime.state import ImportManifest, ImportSession, ImportStatus


class ImportRepository:
    def __init__(self, database) -> None:
        self.database = database

    def create(self, session: ImportSession) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO import_sessions VALUES (?,?,?,?,?,?,?,?,?)",
                self._values(session),
            )

    def update(self, session: ImportSession) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE import_sessions SET status=?, manifest_hash=?, snapshot_path=?, error=?, updated_at=?
                   WHERE import_id=?""",
                (
                    session.status.value, session.manifest_hash, session.snapshot_path, session.error,
                    session.updated_at.isoformat(), session.import_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(session.import_id)

    def save_completed(self, session: ImportSession, manifest: ImportManifest) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE import_sessions SET status=?, manifest_hash=?, snapshot_path=?, error=?, updated_at=?
                   WHERE import_id=?""",
                (
                    session.status.value, session.manifest_hash, session.snapshot_path, session.error,
                    session.updated_at.isoformat(), session.import_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(session.import_id)
            connection.execute(
                "INSERT INTO import_manifests VALUES (?,?,?)",
                (session.import_id, manifest.manifest_hash, manifest.model_dump_json()),
            )

    def get(self, import_id: str) -> Optional[ImportSession]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM import_sessions WHERE import_id=?", (import_id,)).fetchone()
        return self._session(row) if row else None

    def get_manifest(self, import_id: str) -> Optional[ImportManifest]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT manifest_json FROM import_manifests WHERE import_id=?", (import_id,)
            ).fetchone()
        return ImportManifest.model_validate_json(row["manifest_json"]) if row else None

    def list_project(self, project_id: str) -> List[ImportSession]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM import_sessions WHERE project_id=? ORDER BY created_at", (project_id,)
            ).fetchall()
        return [self._session(row) for row in rows]

    def list_with_status(self, status: ImportStatus) -> List[ImportSession]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM import_sessions WHERE status=? ORDER BY created_at", (status.value,)
            ).fetchall()
        return [self._session(row) for row in rows]

    def find_completed(self, project_id: str, source_root: str,
                       manifest_hash: str) -> Optional[ImportSession]:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT * FROM import_sessions WHERE project_id=? AND source_root=? AND manifest_hash=?
                   AND status=? ORDER BY created_at LIMIT 1""",
                (project_id, source_root, manifest_hash, ImportStatus.COMPLETED.value),
            ).fetchone()
        return self._session(row) if row else None

    @staticmethod
    def _values(session: ImportSession):
        return (
            session.import_id, session.project_id, session.source_root, session.status.value,
            session.manifest_hash, session.snapshot_path, session.error,
            session.created_at.isoformat(), session.updated_at.isoformat(),
        )

    @staticmethod
    def _session(row) -> ImportSession:
        return ImportSession(
            import_id=row["import_id"], project_id=row["project_id"], source_root=row["source_root"],
            status=ImportStatus(row["status"]), manifest_hash=row["manifest_hash"],
            snapshot_path=row["snapshot_path"], error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


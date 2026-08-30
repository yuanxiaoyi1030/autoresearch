# Purpose: Verifies allowed-root, cache exclusion, hash snapshot, source immutability, and workspace confinement.
import tempfile
import unittest
from pathlib import Path

from research_runtime.imports import ExistingProjectImporter, ManifestBuilder, sha256_file
from research_runtime.state import ProjectType, ResearchProject, ResearchState
from research_runtime.workspace import WorkspaceBoundaryError, WorkspaceManager
from storage import Database
from storage.repositories import ImportRepository, ProjectRepository


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


class ImportWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        root = Path(self.temporary.name)
        self.source = root / "allowed" / "project"
        self.source.mkdir(parents=True)
        (self.source / "model.py").write_text("VALUE = 7\n", encoding="utf-8")
        (self.source / "figure.svg").write_text("<svg/>\n", encoding="utf-8")
        cache = self.source / "node_modules"
        cache.mkdir()
        (cache / "ignored.js").write_text("ignored", encoding="utf-8")
        self.before = {path.name: sha256_file(path) for path in self.source.iterdir() if path.is_file()}
        self.workspace = WorkspaceManager(root / "runtime")
        self.workspace.ensure_runtime()
        database = Database(root / "runtime" / "test.sqlite3")
        database.initialize()
        self.projects = ProjectRepository(database)
        self.imports = ImportRepository(database)
        self.project = ResearchProject(title="Existing", project_type=ProjectType.EXISTING_PROJECT,
                                       source_root=str(self.source))
        self.projects.create(self.project, ResearchState(project_id=self.project.project_id))
        self.importer = ExistingProjectImporter(
            self.projects, self.imports, self.workspace, (root / "allowed",),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_import_is_hash_verified_and_does_not_modify_source(self):
        session = self.importer.import_project(self.project.project_id, self.source)
        manifest = self.imports.get_manifest(session.import_id)
        self.assertEqual({item.relative_path for item in manifest.files}, {"figure.svg", "model.py"})
        self.assertTrue(any("node_modules" in item.relative_path for item in manifest.excluded))
        snapshot = Path(session.snapshot_path)
        self.assertEqual(sha256_file(snapshot / "model.py"), self.before["model.py"])
        after = {path.name: sha256_file(path) for path in self.source.iterdir() if path.is_file()}
        self.assertEqual(self.before, after)
        reused = self.importer.import_project(self.project.project_id, self.source)
        self.assertEqual(reused.import_id, session.import_id)

    def test_boundaries_reject_escape_and_outside_source(self):
        with self.assertRaises(WorkspaceBoundaryError):
            self.workspace.resolve_workspace_file(self.project.project_id, "../escape.py")
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        with self.assertRaises(ValueError):
            self.importer.import_project(self.project.project_id, outside)


if __name__ == "__main__":
    unittest.main()

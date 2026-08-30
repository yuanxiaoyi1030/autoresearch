# Purpose: Verifies v0.2 isolation, loopback settings, neutral entrypoints, and stage graph models.
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from research_runtime.config import DEFAULT_RUNTIME_ROOT, Settings
from research_runtime.state import ProjectType, ResearchProject, ResearchStage
from research_runtime.workspace.manager import RUNTIME_DIRECTORIES, WorkspaceManager


TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


class ConfigStateTests(unittest.TestCase):
    def test_default_runtime_root_and_all_runtime_directories_are_v0_2_scoped(self):
        self.assertEqual(
            DEFAULT_RUNTIME_ROOT,
            Path(r"D:\code\work\autoresearch\v_0_2_runtime_data"),
        )
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            runtime_root = Path(directory) / "v_0_2_runtime_data"
            WorkspaceManager(runtime_root).ensure_runtime()
            self.assertEqual(
                {path.name for path in runtime_root.iterdir()},
                set(RUNTIME_DIRECTORIES),
            )
            self.assertTrue(all((runtime_root / name).is_dir() for name in RUNTIME_DIRECTORIES))

    def test_settings_are_loopback_and_v0_2_isolated(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            settings = Settings(runtime_root=Path(directory) / "runtime", allowed_import_roots=[Path(directory)])
            self.assertEqual(settings.host, "127.0.0.1")
            self.assertNotIn("v_0_1_runtime_data", str(settings.runtime_root))
        with self.assertRaises(ValueError):
            Settings(host="0.0.0.0")
        with self.assertRaises(ValueError):
            Settings(runtime_root=Path(r"D:\code\work\autoresearch\v_0_1_runtime_data"))

    def test_project_entrypoints_are_generic_and_mutually_exclusive(self):
        topic = ResearchProject(title="Arbitrary topic", project_type=ProjectType.TOPIC_BASED,
                                topic="Can a new measurement improve a generic outcome?")
        self.assertNotIn("weight", topic.topic.lower())
        existing = ResearchProject(title="Existing", project_type=ProjectType.EXISTING_PROJECT,
                                   source_root=r"D:\ml_project\example")
        self.assertIsNone(existing.topic)
        with self.assertRaises(ValidationError):
            ResearchProject(title="Bad", project_type=ProjectType.TOPIC_BASED)

    def test_v0_2_stage_graph_has_implementation_and_report_review(self):
        self.assertIn(ResearchStage.EXPERIMENT_IMPLEMENTATION, set(ResearchStage))
        self.assertIn(ResearchStage.REPORT_REVIEW, set(ResearchStage))


if __name__ == "__main__":
    unittest.main()

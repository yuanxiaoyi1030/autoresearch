# Purpose: Prevents LLM implementation prompts from omitting path constraints enforced by models.
import unittest

from research_runtime.experiments.agents import (
    EXPERIMENTAL_LEAD_INSTRUCTION,
    RESEARCH_ENGINEER_INSTRUCTION,
)


class ExperimentAgentContractTests(unittest.TestCase):
    def test_lead_prompt_requires_python_entrypoint(self):
        self.assertIn("MUST end in .py", EXPERIMENTAL_LEAD_INSTRUCTION)
        self.assertIn("confined relative POSIX path", EXPERIMENTAL_LEAD_INSTRUCTION)
        self.assertIn("extensionless entrypoint", EXPERIMENTAL_LEAD_INSTRUCTION)

    def test_engineer_prompt_matches_implementation_file_allowlist(self):
        self.assertIn("ending in .py", RESEARCH_ENGINEER_INSTRUCTION)
        self.assertIn(".py, .json, .yaml, .yml, .toml, .md", RESEARCH_ENGINEER_INSTRUCTION)
        self.assertIn("Do not return .csv", RESEARCH_ENGINEER_INSTRUCTION)
        self.assertIn("requirements.txt", RESEARCH_ENGINEER_INSTRUCTION)
        self.assertIn("dependency manifest", RESEARCH_ENGINEER_INSTRUCTION)
        self.assertIn("research_context.user_constraints.allowed_dependencies", RESEARCH_ENGINEER_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()

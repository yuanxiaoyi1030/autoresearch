# Purpose: Verifies every model-facing prompt has a complete standardized JSON contract.
import json
import unittest

from pydantic import BaseModel

from research_runtime.analysis.models import ScientificReviewDraft
from research_runtime.experiments.models import EngineerCodePackage, ImplementationTaskGraph
from research_runtime.literature.models import (
    EvidenceReviewDraft, LiteratureQueryPlan, LiteratureSynthesis,
)
from research_runtime.llm import (
    FakeProvider, LLMClient, LLMMessage, LLMModelConfig, LLMRole, LLMUsage,
    ProviderResponse, ProviderType, StageBudget,
)
from research_runtime.llm.prompts.analysis import scientific_review_prompt
from research_runtime.llm.prompts.common import build_prompt
from research_runtime.llm.prompts.experiments import experimental_lead_prompt, research_engineer_prompt
from research_runtime.llm.prompts.literature import (
    evidence_review_prompt, query_planning_prompt, revision_prompt, synthesis_prompt,
)
from research_runtime.llm.prompts.planning import (
    hypothesis_generation_prompt, hypothesis_review_prompt, hypothesis_revision_prompt,
    plan_generation_prompt, plan_review_prompt, plan_revision_prompt,
)
from research_runtime.llm.prompts.review import (
    evidence_reproducibility_review_prompt, meta_assignment_prompt, meta_synthesis_prompt,
    methodology_review_prompt, statistical_review_prompt,
)
from research_runtime.llm.prompts.runtime import connection_test_prompt, structured_output_retry_prompt
from research_runtime.llm.prompts.writing import (
    citation_editor_prompt, lead_author_prompt, presentation_editor_prompt,
    technical_editor_prompt, top_conference_review_prompt,
)
from research_runtime.planning.models import (
    ExistingProjectExperimentPlanDraft, HypothesisDraft, PlanningReviewDraft,
    TopicExperimentPlanDraft,
)
from research_runtime.review.models import MetaAssignmentPlan, MetaReviewDraft, SpecialistReviewDraft
from research_runtime.writing.models import (
    CitationEditorDraft, LeadAuthorDraft, PresentationDraft, TechnicalContentDraft,
    TopConferenceReviewDraft,
)


class _Probe(BaseModel):
    ok: bool


class _Answer(BaseModel):
    answer: str


def prompt_cases():
    return [
        (query_planning_prompt(), LiteratureQueryPlan),
        (synthesis_prompt(), LiteratureSynthesis),
        (revision_prompt(), LiteratureSynthesis),
        (evidence_review_prompt(), EvidenceReviewDraft),
        (hypothesis_generation_prompt(), HypothesisDraft),
        (hypothesis_revision_prompt(), HypothesisDraft),
        (plan_generation_prompt(False), TopicExperimentPlanDraft),
        (plan_generation_prompt(True), ExistingProjectExperimentPlanDraft),
        (plan_revision_prompt(False), TopicExperimentPlanDraft),
        (plan_revision_prompt(True), ExistingProjectExperimentPlanDraft),
        (hypothesis_review_prompt(), PlanningReviewDraft),
        (plan_review_prompt(), PlanningReviewDraft),
        (experimental_lead_prompt(), ImplementationTaskGraph),
        (research_engineer_prompt(), EngineerCodePackage),
        (scientific_review_prompt(), ScientificReviewDraft),
        (meta_assignment_prompt(), MetaAssignmentPlan),
        (methodology_review_prompt(), SpecialistReviewDraft),
        (statistical_review_prompt(), SpecialistReviewDraft),
        (evidence_reproducibility_review_prompt(), SpecialistReviewDraft),
        (meta_synthesis_prompt(), MetaReviewDraft),
        (lead_author_prompt(), LeadAuthorDraft),
        (technical_editor_prompt(), TechnicalContentDraft),
        (citation_editor_prompt(), CitationEditorDraft),
        (presentation_editor_prompt(), PresentationDraft),
        (top_conference_review_prompt(), TopConferenceReviewDraft),
        (connection_test_prompt(_Probe), _Probe),
        (structured_output_retry_prompt(_Answer), _Answer),
    ]


class PromptContractTests(unittest.TestCase):
    def test_every_prompt_has_ordered_contract_sections_and_complete_shape(self):
        headers = ["ROLE:", "FORMAT:", "INPUT:", "OUTPUT:", "REQUIREMENTS:"]
        for prompt, output_model in prompt_cases():
            with self.subTest(output_model=output_model.__name__):
                positions = [prompt.index(header) for header in headers]
                self.assertEqual(positions, sorted(positions))
                self.assertIn(f"Model: {output_model.__name__}", prompt)
                self.assertIn("BEGIN_FIELD_CONTRACT", prompt)
                self.assertIn("required", prompt)
                self.assertIn("nullable", prompt)
                example = self._example(prompt)
                schema = output_model.model_json_schema()
                self._assert_complete(schema, example, schema, set())

    def test_stage_prompts_preserve_critical_constraints(self):
        literature = synthesis_prompt()
        self.assertIn("source_id", literature)
        self.assertIn("abstract-only", literature)
        self.assertIn("core_support", literature)

        planning = plan_generation_prompt(True)
        self.assertIn("approved selected_hypothesis", planning)
        self.assertIn("LegacyReuseAssessment", planning)
        self.assertIn("B-mode", planning)

        hypotheses = hypothesis_generation_prompt() + hypothesis_revision_prompt()
        self.assertIn("explicit, testable research_question", hypotheses)
        self.assertIn("candidate answers to that same question", hypotheses)

        experiments = experimental_lead_prompt() + research_engineer_prompt()
        self.assertIn("confined relative POSIX path", experiments)
        self.assertIn("MUST end in .py", experiments)
        self.assertIn("shell", experiments)

        analysis = scientific_review_prompt()
        self.assertIn("Deterministic", analysis)
        self.assertIn("authoritative", analysis)

        review = methodology_review_prompt() + meta_synthesis_prompt()
        self.assertIn("peer reports", review)
        self.assertIn("Policy Guard", review)

        writing = lead_author_prompt() + technical_editor_prompt() + citation_editor_prompt()
        self.assertIn("evidence", writing)
        self.assertIn("numeric literal", writing)
        self.assertIn("citations", writing)
        self.assertIn("raw LaTeX", writing)

    def test_fake_provider_receives_system_contract_user_json_and_schema(self):
        provider = FakeProvider(responses=[ProviderResponse(
            structured_output={"answer": "ok"}, usage=LLMUsage(input_tokens=2, output_tokens=1),
        )])
        config = LLMModelConfig(
            provider_id="offline", provider_type=ProviderType.FAKE, model="fake-model",
            base_url="http://offline.invalid/v1", credential_required=False,
        )
        prompt = build_prompt(
            role="You are a test responder.",
            input_fields=(("question", "A test question."),),
            output_model=_Answer,
            output_notes="Return the answer field.",
            requirements="Use only the supplied question.",
        )
        answer, _ = LLMClient(provider, config).generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=prompt),
                LLMMessage(role=LLMRole.USER, content='{"question":"q"}'),
            ],
            _Answer,
            StageBudget(max_calls=1, max_input_tokens=100, max_output_tokens=100, max_total_tokens=200),
        )

        request = provider.requests[0]
        self.assertEqual(answer.answer, "ok")
        self.assertEqual(request.messages[0].content, prompt)
        self.assertEqual(json.loads(request.messages[1].content), {"question": "q"})
        self.assertEqual(request.response_schema["properties"]["answer"]["type"], "string")

    @staticmethod
    def _example(prompt):
        value = prompt.split("BEGIN_JSON_SHAPE\n", 1)[1].split("\nEND_JSON_SHAPE", 1)[0]
        return json.loads(value)

    def _assert_complete(self, node, example, root, seen):
        reference = node.get("$ref") if isinstance(node, dict) else None
        if reference:
            if reference in seen:
                return
            target = root
            for part in reference[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            self._assert_complete(target, example, root, seen | {reference})
            return

        branches = node.get("anyOf") or node.get("oneOf") if isinstance(node, dict) else None
        if branches:
            branch = next((item for item in branches if item.get("type") != "null"), branches[0])
            self._assert_complete(branch, example, root, seen)
            return
        if isinstance(node, dict) and node.get("allOf"):
            for branch in node["allOf"]:
                self._assert_complete(branch, example, root, seen)
            return

        properties = node.get("properties") if isinstance(node, dict) else None
        if properties:
            self.assertIsInstance(example, dict)
            self.assertEqual(set(properties), set(example))
            for name, child in properties.items():
                self._assert_complete(child, example[name], root, seen)
        elif isinstance(node, dict) and node.get("type") == "array":
            self.assertIsInstance(example, list)
            self.assertEqual(len(example), 1)
            self._assert_complete(node.get("items", {}), example[0], root, seen)


if __name__ == "__main__":
    unittest.main()

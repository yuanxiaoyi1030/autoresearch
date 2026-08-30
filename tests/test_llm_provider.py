# Purpose: Verifies provider contracts, OpenAI-compatible protocols, streaming, retries, timeouts, and budgets.
import json
import time
import unittest
from typing import Optional

from pydantic import BaseModel, Field

from research_runtime.llm import (
    BudgetExceeded, FakeProvider, HTTPResult, LLMClient, LLMError, LLMMessage, LLMModelConfig,
    LLMRole, LLMUsage, OpenAICompatibleProvider, OpenAIProtocol, ProviderError,
    ProviderResponse, ProviderType, StageBudget, ToolCall, ToolDefinition, build_default_registry,
)
from research_runtime.llm.client import parse_structured_json, strict_response_schema
from research_runtime.planning.models import (
    ExistingProjectExperimentPlanDraft, ExperimentPlanDraft, TopicExperimentPlanDraft,
)


class Answer(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)


class SupportingDetail(BaseModel):
    label: str
    note: Optional[str] = None


class StrictAnswer(BaseModel):
    answer: str
    detail: Optional[SupportingDetail] = None
    tags: list[str] = Field(default_factory=list)


class ScriptedTransport:
    def __init__(self, responses=None, failures=None, stream_lines=None):
        self.responses = list(responses or [])
        self.failures = list(failures or [])
        self.stream_lines = list(stream_lines or [])
        self.requests = []

    def post_json(self, url, headers, payload, timeout_seconds):
        self.requests.append((url, headers, payload, timeout_seconds))
        if self.failures:
            raise self.failures.pop(0)
        return self.responses.pop(0)

    def post_sse(self, url, headers, payload, timeout_seconds):
        self.requests.append((url, headers, payload, timeout_seconds))
        yield from self.stream_lines


def model_config(protocol=OpenAIProtocol.CHAT_COMPLETIONS, **updates):
    values = dict(
        provider_id="primary", provider_type=ProviderType.OPENAI_COMPATIBLE,
        model="research-model", base_url="https://llm.example.test/v1", protocol=protocol,
        temperature=0.15, max_output_tokens=100, timeout_seconds=0.5, retry_count=2,
        input_cost_per_million_tokens=1.0, output_cost_per_million_tokens=2.0,
    )
    values.update(updates)
    return LLMModelConfig(**values)


class LLMProviderTests(unittest.TestCase):
    def test_structured_json_parser_repairs_fences_and_trailing_commas_only(self):
        payload = parse_structured_json(
            '```json\n{"answer":"comma, } stays", "nested":{"value":1,},}\n```'
        )
        self.assertEqual(payload, {"answer": "comma, } stays", "nested": {"value": 1}})

        with self.assertRaises(json.JSONDecodeError):
            parse_structured_json('{"answer":"truncated"')

    def test_malformed_structured_output_gets_one_budgeted_regeneration(self):
        config = model_config(
            provider_type=ProviderType.FAKE, base_url="http://offline.invalid/v1",
            retry_count=0,
        )
        provider = FakeProvider(responses=[
            ProviderResponse(
                content='{"answer":"truncated"',
                usage=LLMUsage(input_tokens=3, output_tokens=2),
            ),
            ProviderResponse(
                structured_output={"answer": "complete", "confidence": 0.9},
                usage=LLMUsage(input_tokens=4, output_tokens=1),
            ),
        ])
        answer, result = LLMClient(provider, config).generate_structured(
            [LLMMessage(role=LLMRole.USER, content="q")], Answer,
            StageBudget(max_calls=2, max_input_tokens=20, max_output_tokens=20, max_total_tokens=40),
        )

        self.assertEqual(answer.answer, "complete")
        self.assertEqual(result.ledger.calls, 2)
        self.assertEqual(result.ledger.provider_attempts, 2)
        self.assertEqual(result.ledger.usage.total_tokens, 10)
        self.assertIn("Regenerate the complete response", provider.requests[1].messages[-1].content)

    def test_strict_response_schema_requires_all_explicit_object_properties(self):
        source = StrictAnswer.model_json_schema()
        normalized = strict_response_schema(source)

        self.assertEqual(normalized["required"], ["answer", "detail", "tags"])
        self.assertFalse(normalized["additionalProperties"])
        detail = normalized["$defs"]["SupportingDetail"]
        self.assertEqual(detail["required"], ["label", "note"])
        self.assertFalse(detail["additionalProperties"])
        self.assertNotIn("default", detail["properties"]["note"])
        self.assertNotIn("tags", source["required"])
        self.assertNotIn("additionalProperties", source)

    def test_strict_response_schema_collapses_nullable_any_of_with_explicit_type(self):
        source = StrictAnswer.model_json_schema()
        normalized = strict_response_schema(source)

        nullable_object = normalized["properties"]["detail"]
        self.assertIn("anyOf", nullable_object)
        self.assertEqual(nullable_object["type"], "object")

        nullable_string = normalized["$defs"]["SupportingDetail"]["properties"]["note"]
        self.assertNotIn("anyOf", nullable_string)
        self.assertEqual(nullable_string["type"], ["string", "null"])

        self.assertIn("anyOf", source["properties"]["detail"])

    def test_mode_specific_experiment_plan_schemas_avoid_complex_nullable_unions(self):
        topic = strict_response_schema(TopicExperimentPlanDraft.model_json_schema())
        existing = strict_response_schema(ExistingProjectExperimentPlanDraft.model_json_schema())

        self.assertNotIn('"anyOf"', json.dumps(topic))
        self.assertNotIn('"anyOf"', json.dumps(existing))
        self.assertEqual(topic["properties"]["b_mode_binding"]["type"], "null")
        self.assertIn("$ref", existing["properties"]["b_mode_binding"])

    def test_engineer_package_schema_has_no_propertyless_object(self):
        from research_runtime.experiments import EngineerCodePackage

        schema = strict_response_schema(EngineerCodePackage.model_json_schema())

        def visit(node):
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                self.assertTrue(node.get("properties"), node)
            for value in node.values():
                visit(value)

        visit(schema)

    def test_chat_structured_output_tools_usage_and_payload(self):
        transport = ScriptedTransport(responses=[HTTPResult(
            status_code=200, headers={"x-request-id": "req_1"}, data={
                "id": "chat_1",
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": json.dumps({"answer": "supported", "confidence": 0.8}),
                        "tool_calls": [{
                            "id": "call_1", "type": "function",
                            "function": {"name": "search", "arguments": '{"query":"topic"}'},
                        }],
                    },
                }],
                "usage": {
                    "prompt_tokens": 30, "completion_tokens": 10,
                    "prompt_tokens_details": {"cached_tokens": 4},
                    "completion_tokens_details": {"reasoning_tokens": 3},
                },
            },
        )])
        config = model_config(retry_count=0)
        provider = OpenAICompatibleProvider(config, "sk-contract-secret", transport)
        client = LLMClient(provider, config, ["sk-contract-secret"])
        answer, result = client.generate_structured(
            [LLMMessage(role=LLMRole.USER, content="Assess evidence")],
            Answer,
            StageBudget(max_calls=2, max_input_tokens=100, max_output_tokens=50, max_total_tokens=150),
            tools=[ToolDefinition(name="search", input_schema={
                "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
            })],
        )
        self.assertEqual(answer.answer, "supported")
        self.assertEqual(result.tool_calls[0].arguments, {"query": "topic"})
        self.assertEqual(result.usage.total_tokens, 40)
        self.assertEqual(result.usage.cached_input_tokens, 4)
        self.assertEqual(result.usage.reasoning_tokens, 3)
        self.assertAlmostEqual(result.usage.cost_usd, 0.00005)
        url, headers, payload, timeout = transport.requests[0]
        self.assertEqual(url, "https://llm.example.test/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer sk-contract-secret")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["tools"][0]["function"]["name"], "search")
        self.assertEqual(payload["max_completion_tokens"], 50)

    def test_responses_protocol_and_streaming_contract(self):
        transport = ScriptedTransport(
            responses=[HTTPResult(status_code=200, headers={}, data={
                "id": "resp_1", "status": "completed",
                "output": [
                    {"type": "message", "content": [{
                        "type": "output_text", "text": '{"answer":"yes","confidence":0.6}',
                    }]},
                    {"type": "function_call", "call_id": "call_2", "name": "lookup",
                     "arguments": '{"id":"paper"}'},
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7},
            })],
            stream_lines=[
                'data: {"type":"response.output_text.delta","delta":"hel"}',
                'data: {"type":"response.output_text.delta","delta":"lo"}',
                'data: [DONE]',
            ],
        )
        config = model_config(OpenAIProtocol.RESPONSES, retry_count=0)
        provider = OpenAICompatibleProvider(config, "sk-responses", transport)
        request_messages = [LLMMessage(role=LLMRole.USER, content="question")]
        answer, result = LLMClient(provider, config).generate_structured(
            request_messages, Answer,
            StageBudget(max_calls=1, max_input_tokens=100, max_output_tokens=100, max_total_tokens=200),
            tools=[ToolDefinition(name="lookup")],
        )
        self.assertEqual(answer.answer, "yes")
        self.assertEqual(result.tool_calls[0].name, "lookup")
        payload = transport.requests[0][2]
        self.assertFalse(payload["store"])
        self.assertEqual(payload["reasoning"]["effort"], "none")
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        from research_runtime.llm import ProviderRequest
        events = list(provider.stream(ProviderRequest(
            model=config.model, messages=request_messages, max_output_tokens=10,
        ), 0.5))
        self.assertEqual("".join(event.delta for event in events), "hello")

    def test_retry_timeout_and_stage_budgets_are_hard_limits(self):
        config = model_config(provider_type=ProviderType.FAKE, base_url="http://offline.invalid/v1")
        provider = FakeProvider(
            responses=[ProviderResponse(
                structured_output={"answer": "ok", "confidence": 0.5},
                usage=LLMUsage(input_tokens=8, output_tokens=4),
            )],
            failures=[ProviderError("temporary", retryable=True), ProviderError("busy", retryable=True)],
        )
        _, result = LLMClient(provider, config).generate_structured(
            [LLMMessage(role=LLMRole.USER, content="q")], Answer,
            StageBudget(max_calls=1, max_input_tokens=20, max_output_tokens=20, max_total_tokens=40),
        )
        self.assertEqual(result.ledger.provider_attempts, 3)
        self.assertEqual(result.ledger.calls, 1)

        def slow(_request):
            time.sleep(0.2)
            return ProviderResponse(structured_output={"answer": "late", "confidence": 0.1})

        timeout_config = model_config(
            provider_type=ProviderType.FAKE, base_url="http://offline.invalid/v1",
            timeout_seconds=0.03, retry_count=0,
        )
        started = time.monotonic()
        with self.assertRaisesRegex(LLMError, "retries exhausted"):
            LLMClient(FakeProvider(factory=slow), timeout_config).generate_structured(
                [LLMMessage(role=LLMRole.USER, content="q")], Answer, StageBudget(),
            )
        self.assertLess(time.monotonic() - started, 0.15)

        expensive = FakeProvider(responses=[ProviderResponse(
            structured_output={"answer": "costly", "confidence": 0.1},
            usage=LLMUsage(input_tokens=1, output_tokens=1, cost_usd=1.1),
        )])
        with self.assertRaisesRegex(BudgetExceeded, "cost"):
            LLMClient(expensive, timeout_config).generate_structured(
                [LLMMessage(role=LLMRole.USER, content="q")], Answer,
                StageBudget(max_cost_usd=1.0),
            )

    def test_registry_declares_extensions_and_fake_is_never_default(self):
        registry = build_default_registry()
        descriptors = {item.provider_type: item for item in registry.descriptors()}
        self.assertTrue(descriptors[ProviderType.OPENAI_COMPATIBLE].available)
        self.assertTrue(descriptors[ProviderType.OPENAI].available)
        self.assertFalse(descriptors[ProviderType.ANTHROPIC].available)
        self.assertFalse(descriptors[ProviderType.GEMINI].available)
        self.assertTrue(descriptors[ProviderType.FAKE].explicit_offline_only)
        fake_config = model_config(
            provider_type=ProviderType.FAKE, base_url="http://offline.invalid/v1",
            credential_required=False,
        )
        with self.assertRaisesRegex(LLMError, "offline_mode"):
            registry.create(fake_config, None)
        self.assertFalse(registry.create(fake_config, None, allow_offline=True).is_live)

    def test_prompt_metadata_and_echoed_secrets_are_redacted_before_return(self):
        secret = "sk-prompt-metadata-never-leak"
        config = model_config(
            provider_type=ProviderType.FAKE, base_url="http://offline.invalid/v1", retry_count=0,
        )
        provider = FakeProvider(responses=[ProviderResponse(
            structured_output={"answer": secret, "confidence": 0.5},
        )])
        answer, result = LLMClient(provider, config, [secret]).generate_structured(
            [LLMMessage(role=LLMRole.USER, content="q")], Answer, StageBudget(),
            metadata={"api_key": secret, "nested": f"Authorization: Bearer {secret}"},
        )
        self.assertNotIn(secret, str(answer))
        self.assertNotIn(secret, result.model_dump_json())
        self.assertNotIn(secret, provider.requests[0].model_dump_json())
        self.assertEqual(provider.requests[0].metadata["api_key"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()

# Purpose: Executes schema-validated LLM calls with hard stage budgets, deadlines, retries, and redacted failures.
from __future__ import annotations

import json
from copy import deepcopy
from queue import Empty, Queue
import threading
import time
from typing import Any, Dict, Iterable, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .errors import BudgetExceeded, LLMError, ProviderError, ProviderTimeoutError, StructuredOutputError
from .models import (
    BudgetLedger, LLMMessage, LLMModelConfig, ProviderRequest, ProviderResponse,
    StageBudget, StructuredLLMResult, ToolDefinition,
)
from .prompts.runtime import structured_output_retry_prompt
from .providers import LLMProvider
from .redaction import redact_secrets


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def parse_structured_json(content: str) -> Dict[str, Any]:
    """Parse provider JSON, tolerating only harmless presentation defects.

    Some OpenAI-compatible providers occasionally wrap otherwise valid JSON in
    a Markdown fence or emit a trailing comma.  Repairing those two cases is
    deterministic; incomplete JSON and other semantic damage still fail hard.
    """
    candidate = content.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        repaired: list[str] = []
        in_string = False
        escaped = False
        index = 0
        while index < len(candidate):
            char = candidate[index]
            if in_string:
                repaired.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
                repaired.append(char)
                index += 1
                continue
            if char == ",":
                lookahead = index + 1
                while lookahead < len(candidate) and candidate[lookahead].isspace():
                    lookahead += 1
                if lookahead < len(candidate) and candidate[lookahead] in "}]":
                    index += 1
                    continue
            repaired.append(char)
            index += 1
        payload = json.loads("".join(repaired))

    if not isinstance(payload, dict):
        raise ValueError("structured output must be a JSON object")
    return payload


def strict_response_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return an OpenAI-compatible strict JSON Schema without mutating the source."""
    normalized = deepcopy(schema)

    def resolve_local_ref(reference: str) -> Optional[Dict[str, Any]]:
        if not reference.startswith("#/"):
            return None
        target: Any = normalized
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return None
            target = target[part]
        return deepcopy(target) if isinstance(target, dict) else None

    def collapse_nullable_any_of(node: Dict[str, Any]) -> None:
        """Express Optional[T] with an explicit nullable type.

        Some OpenAI-compatible providers reject a property schema whose only
        discriminator is ``anyOf`` and report that the field is missing
        ``type``.  Pydantic emits exactly that shape for Optional fields.  A
        nullable union with one concrete branch can be represented without
        loss by inlining that branch and adding ``null`` to its type.
        """
        branches = node.get("anyOf")
        if not isinstance(branches, list) or len(branches) != 2:
            return
        null_branches = [branch for branch in branches if isinstance(branch, dict) and branch.get("type") == "null"]
        concrete_branches = [branch for branch in branches if branch not in null_branches]
        if len(null_branches) != 1 or len(concrete_branches) != 1:
            return

        concrete = deepcopy(concrete_branches[0])
        if set(concrete) == {"$ref"}:
            resolved = resolve_local_ref(str(concrete["$ref"]))
            if resolved is None:
                return
            concrete = resolved
        concrete_type = concrete.get("type")
        if isinstance(concrete_type, str) and concrete_type not in {"object", "array"}:
            concrete["type"] = [concrete_type, "null"]
        elif isinstance(concrete_type, list):
            concrete["type"] = list(dict.fromkeys([*concrete_type, "null"]))
        elif isinstance(concrete_type, str):
            # DeepSeek accepts object/array schemas but rejects those values
            # inside a nullable ``type`` array.  Keep the union for compatible
            # providers while satisfying validators that require an explicit
            # type beside ``anyOf``.  Call sites with mode-dependent complex
            # optionals should prefer a concrete response model instead.
            node["type"] = concrete_type
            return
        else:
            return

        preserved = {key: value for key, value in node.items() if key != "anyOf"}
        node.clear()
        node.update(concrete)
        node.update(preserved)

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return

        node.pop("default", None)
        collapse_nullable_any_of(node)
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties)
            node["additionalProperties"] = False

        for value in node.values():
            visit(value)

    visit(normalized)
    return normalized


class LLMClient:
    def __init__(self, provider: LLMProvider, config: LLMModelConfig,
                 known_secrets: Iterable[str] = (), ledger_lock=None) -> None:
        self.provider = provider
        self.config = config
        self.known_secrets = tuple(secret for secret in known_secrets if secret)
        self._ledger_lock = ledger_lock or threading.RLock()

    def generate_structured(
        self,
        messages: list[LLMMessage],
        output_model: Type[StructuredModel],
        budget: StageBudget,
        *,
        ledger: Optional[BudgetLedger] = None,
        tools: Optional[list[ToolDefinition]] = None,
        tool_choice: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[StructuredModel, StructuredLLMResult]:
        ledger = ledger or BudgetLedger()
        response_schema = strict_response_schema(output_model.model_json_schema())
        response: ProviderResponse
        validated: StructuredModel
        next_ledger: BudgetLedger
        last_structured_error: Optional[StructuredOutputError] = None

        # One bounded regeneration is allowed for malformed/truncated provider JSON.
        # It is a real stage call, consumes tokens, and can never exceed the stage budget.
        for structured_attempt in range(2):
            with self._ledger_lock:
                if structured_attempt and ledger.calls >= budget.max_calls:
                    assert last_structured_error is not None
                    raise last_structured_error
                self._preflight(ledger, budget)
                remaining_output = min(
                    self.config.max_output_tokens,
                    budget.max_output_tokens - ledger.usage.output_tokens,
                    budget.max_total_tokens - ledger.usage.total_tokens,
                )
                if remaining_output <= 0:
                    if last_structured_error is not None:
                        raise last_structured_error
                    raise BudgetExceeded("output token budget exhausted")
                # Every regeneration is visible in the hard stage-call ledger.
                ledger.calls += 1
            retry_instruction = []
            if structured_attempt:
                retry_instruction = [LLMMessage(
                    role="system",
                    content=structured_output_retry_prompt(output_model),
                )]
            request = ProviderRequest(
                model=self.config.model,
                messages=messages + retry_instruction,
                tools=tools or [],
                tool_choice=tool_choice,
                response_schema=response_schema,
                response_schema_name=output_model.__name__.lower(),
                max_output_tokens=remaining_output,
                temperature=self.config.temperature,
                metadata=redact_secrets(metadata or {}, self.known_secrets),
            )
            response = self._complete_with_retry(request, ledger)
            with self._ledger_lock:
                next_usage = ledger.usage + response.usage
                ledger.usage = next_usage
                self._check_usage(next_usage, budget)
                next_ledger = ledger.model_copy(deep=True)
            try:
                payload = response.structured_output
                if payload is None:
                    payload = parse_structured_json(response.content)
                payload = redact_secrets(payload, self.known_secrets)
                validated = output_model.model_validate(payload)
                break
            except (json.JSONDecodeError, ValueError) as exc:
                last_structured_error = StructuredOutputError(
                    f"provider returned invalid structured output: {exc}"
                )
            except ValidationError as exc:
                safe = redact_secrets(str(exc), self.known_secrets)
                last_structured_error = StructuredOutputError(
                    f"structured output failed schema validation: {safe}"
                )
        else:
            assert last_structured_error is not None
            raise last_structured_error
        result = StructuredLLMResult(
            provider_id=self.provider.provider_id,
            provider_type=self.provider.provider_type,
            model=self.config.model,
            is_live=self.provider.is_live,
            output=redact_secrets(validated.model_dump(mode="json"), self.known_secrets),
            content=redact_secrets(response.content, self.known_secrets),
            tool_calls=[
                call.model_copy(update={"arguments": redact_secrets(call.arguments, self.known_secrets)})
                for call in response.tool_calls
            ],
            usage=response.usage,
            ledger=next_ledger,
            finish_reason=response.finish_reason,
            provider_request_id=response.provider_request_id,
        )
        return validated, result

    def _complete_with_retry(self, request: ProviderRequest, ledger: BudgetLedger) -> ProviderResponse:
        last_error: Optional[BaseException] = None
        for attempt in range(self.config.retry_count + 1):
            ledger.provider_attempts += 1
            try:
                return self._call_with_timeout(request, self.config.timeout_seconds)
            except (ProviderTimeoutError, TimeoutError) as exc:
                last_error = exc
            except ProviderError as exc:
                if not exc.retryable:
                    safe = redact_secrets(str(exc), self.known_secrets)
                    raise LLMError(f"provider request failed: {safe}") from None
                last_error = exc
            except Exception as exc:
                safe = redact_secrets(f"{type(exc).__name__}: {exc}", self.known_secrets)
                raise LLMError(f"provider request failed: {safe}") from None
            if attempt < self.config.retry_count:
                time.sleep(min(0.05 * (2 ** attempt), 0.5))
        safe = redact_secrets(last_error or "unknown provider failure", self.known_secrets)
        raise LLMError(f"provider retries exhausted: {safe}") from None

    def _call_with_timeout(self, request: ProviderRequest, timeout_seconds: float) -> ProviderResponse:
        result: Queue = Queue(maxsize=1)

        def invoke() -> None:
            try:
                result.put((True, self.provider.complete(request, timeout_seconds)))
            except BaseException as exc:
                result.put((False, exc))

        threading.Thread(
            target=invoke, name="autoresearch-llm-call", daemon=True,
        ).start()
        try:
            succeeded, value = result.get(timeout=timeout_seconds)
        except Empty:
            raise ProviderTimeoutError() from None
        if not succeeded:
            raise value
        return value

    @staticmethod
    def _preflight(ledger: BudgetLedger, budget: StageBudget) -> None:
        if ledger.calls >= budget.max_calls:
            raise BudgetExceeded("stage call budget exhausted")
        LLMClient._check_usage(ledger.usage, budget)

    @staticmethod
    def _check_usage(usage, budget: StageBudget) -> None:
        if usage.input_tokens > budget.max_input_tokens:
            raise BudgetExceeded("stage input token budget exceeded")
        if usage.output_tokens > budget.max_output_tokens:
            raise BudgetExceeded("stage output token budget exceeded")
        if usage.total_tokens > budget.max_total_tokens:
            raise BudgetExceeded("stage total token budget exceeded")
        if budget.max_cost_usd is not None and usage.cost_usd > budget.max_cost_usd:
            raise BudgetExceeded("stage cost budget exceeded")

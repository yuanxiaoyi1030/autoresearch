# Purpose: Implements the dependency-free OpenAI-compatible provider and explicit test/offline fake provider.
from __future__ import annotations

from collections import deque
import json
from typing import Callable, Deque, Dict, Iterable, Iterator, Optional, Protocol

from .errors import LLMError, ProviderError, ProviderTimeoutError
from .models import (
    LLMModelConfig, LLMUsage, OpenAIProtocol, ProviderCapabilities, ProviderRequest,
    ProviderResponse, ProviderStreamEvent, ProviderType, ToolCall,
)
from .redaction import redact_secrets
from .transport import (
    JSONTransport, TransportConnectionError, TransportHTTPError, UrllibJSONTransport,
)


OPENAI_COMPATIBLE_CAPABILITIES = ProviderCapabilities(
    structured_output=True,
    tool_calls=True,
    streaming=True,
    usage_accounting=True,
    supports_temperature=True,
)
FAKE_CAPABILITIES = ProviderCapabilities(
    structured_output=True,
    tool_calls=True,
    streaming=False,
    usage_accounting=True,
    supports_temperature=True,
)


class LLMProvider(Protocol):
    provider_id: str
    provider_type: ProviderType
    capabilities: ProviderCapabilities
    is_live: bool

    def complete(self, request: ProviderRequest, timeout_seconds: float) -> ProviderResponse:
        ...

    def stream(self, request: ProviderRequest, timeout_seconds: float) -> Iterator[ProviderStreamEvent]:
        ...


class OpenAICompatibleProvider:
    is_live = True
    capabilities = OPENAI_COMPATIBLE_CAPABILITIES

    def __init__(self, config: LLMModelConfig, api_key: str,
                 transport: Optional[JSONTransport] = None) -> None:
        if config.provider_type not in {
            ProviderType.OPENAI_COMPATIBLE,
            ProviderType.OPENAI,
            ProviderType.LOCAL_OPENAI_COMPATIBLE,
        }:
            raise ValueError("OpenAICompatibleProvider received an incompatible provider type")
        if config.credential_required and not api_key:
            raise ValueError("API key is required")
        self.provider_id = config.provider_id
        self.provider_type = config.provider_type
        self.config = config
        self._api_key = api_key
        self._transport = transport or UrllibJSONTransport()

    @property
    def _endpoint(self) -> str:
        suffix = "/chat/completions" if self.config.protocol is OpenAIProtocol.CHAT_COMPLETIONS else "/responses"
        return self.config.base_url + suffix

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AutoResearch-v0.2",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def complete(self, request: ProviderRequest, timeout_seconds: float) -> ProviderResponse:
        payload = self._payload(request, stream=False)
        try:
            result = self._transport.post_json(self._endpoint, self._headers(), payload, timeout_seconds)
        except TimeoutError:
            raise ProviderTimeoutError() from None
        except TransportHTTPError as exc:
            raise self._http_error(exc) from None
        except TransportConnectionError as exc:
            message = redact_secrets(str(exc), [self._api_key])
            raise ProviderError(str(message), code="provider_connection_error", retryable=True) from None
        try:
            response = (
                self._parse_chat_completion(result.data, result.headers)
                if self.config.protocol is OpenAIProtocol.CHAT_COMPLETIONS
                else self._parse_response(result.data, result.headers)
            )
            return self._redacted_response(response)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            safe = redact_secrets(f"invalid provider response: {exc}", [self._api_key])
            raise ProviderError(str(safe), code="invalid_provider_response", retryable=False) from None

    def stream(self, request: ProviderRequest, timeout_seconds: float) -> Iterator[ProviderStreamEvent]:
        payload = self._payload(request, stream=True)
        try:
            for line in self._transport.post_sse(self._endpoint, self._headers(), payload, timeout_seconds):
                if not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if not data_text or data_text == "[DONE]":
                    continue
                event = self._parse_stream_data(json.loads(data_text))
                if event is not None:
                    yield event
        except TimeoutError:
            raise ProviderTimeoutError("provider stream timed out") from None
        except TransportHTTPError as exc:
            raise self._http_error(exc) from None
        except (TransportConnectionError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            safe = redact_secrets(f"provider stream failed: {exc}", [self._api_key])
            raise ProviderError(str(safe), code="provider_stream_error", retryable=True) from None

    def _payload(self, request: ProviderRequest, *, stream: bool) -> Dict:
        if self.config.protocol is OpenAIProtocol.CHAT_COMPLETIONS:
            payload: Dict = {
                "model": request.model,
                "messages": [message.model_dump(mode="json", exclude_none=True) for message in request.messages],
                "max_completion_tokens": request.max_output_tokens,
                "stream": stream,
            }
            if stream:
                payload["stream_options"] = {"include_usage": True}
            if request.temperature is not None:
                payload["temperature"] = request.temperature
            if request.tools:
                payload["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.input_schema,
                            "strict": tool.strict,
                        },
                    }
                    for tool in request.tools
                ]
                payload["tool_choice"] = request.tool_choice or "auto"
            if request.response_schema is not None:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.response_schema_name,
                        "strict": True,
                        "schema": request.response_schema,
                    },
                }
            return payload

        payload = {
            "model": request.model,
            "input": [message.model_dump(mode="json", exclude_none=True) for message in request.messages],
            "max_output_tokens": request.max_output_tokens,
            # DeepSeek V4 counts reasoning tokens inside max_output_tokens. Keep
            # structured calls focused on the machine-readable response so a
            # long hidden reasoning pass cannot consume the whole output budget.
            "reasoning": {"effort": "none"},
            "store": False,
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                    "strict": tool.strict,
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = request.tool_choice or "auto"
        if request.response_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.response_schema_name,
                    "strict": True,
                    "schema": request.response_schema,
                }
            }
        return payload

    def _parse_chat_completion(self, data: Dict, headers: Dict[str, str]) -> ProviderResponse:
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        calls = [self._chat_tool_call(item) for item in message.get("tool_calls", [])]
        usage = self._usage(data.get("usage") or {}, protocol=OpenAIProtocol.CHAT_COMPLETIONS)
        return ProviderResponse(
            content=content,
            structured_output=self._json_object_or_none(content),
            tool_calls=calls,
            usage=usage,
            finish_reason=choice.get("finish_reason") or "stop",
            provider_request_id=headers.get("x-request-id") or data.get("id"),
        )

    def _parse_response(self, data: Dict, headers: Dict[str, str]) -> ProviderResponse:
        text_parts = []
        calls = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"}:
                        text_parts.append(content.get("text", ""))
            elif item.get("type") == "function_call":
                calls.append(ToolCall(
                    call_id=item.get("call_id") or item.get("id") or "call_unknown",
                    name=item["name"],
                    arguments=self._arguments(item.get("arguments", "{}")),
                ))
        content = "".join(text_parts)
        usage = self._usage(data.get("usage") or {}, protocol=OpenAIProtocol.RESPONSES)
        return ProviderResponse(
            content=content,
            structured_output=self._json_object_or_none(content),
            tool_calls=calls,
            usage=usage,
            finish_reason=data.get("status") or "completed",
            provider_request_id=headers.get("x-request-id") or data.get("id"),
        )

    def _parse_stream_data(self, data: Dict) -> Optional[ProviderStreamEvent]:
        if self.config.protocol is OpenAIProtocol.CHAT_COMPLETIONS:
            usage_data = data.get("usage")
            if usage_data:
                return ProviderStreamEvent(
                    event_type="usage", usage=self._usage(usage_data, OpenAIProtocol.CHAT_COMPLETIONS),
                )
            choices = data.get("choices") or []
            if not choices:
                return None
            delta = choices[0].get("delta") or {}
            text = delta.get("content") or ""
            return ProviderStreamEvent(event_type="text_delta", delta=str(redact_secrets(text, [self._api_key])))
        event_type = data.get("type", "unknown")
        if event_type.endswith("output_text.delta"):
            return ProviderStreamEvent(
                event_type="text_delta",
                delta=str(redact_secrets(data.get("delta", ""), [self._api_key])),
                raw_type=event_type,
            )
        if event_type.endswith("completed") and data.get("response", {}).get("usage"):
            return ProviderStreamEvent(
                event_type="usage",
                usage=self._usage(data["response"]["usage"], OpenAIProtocol.RESPONSES),
                raw_type=event_type,
            )
        return ProviderStreamEvent(event_type="provider_event", raw_type=event_type)

    def _usage(self, data: Dict, protocol: OpenAIProtocol) -> LLMUsage:
        if protocol is OpenAIProtocol.CHAT_COMPLETIONS:
            input_tokens = int(data.get("prompt_tokens") or 0)
            output_tokens = int(data.get("completion_tokens") or 0)
            cached = int((data.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
            reasoning = int((data.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        else:
            input_tokens = int(data.get("input_tokens") or 0)
            output_tokens = int(data.get("output_tokens") or 0)
            cached = int((data.get("input_tokens_details") or {}).get("cached_tokens") or 0)
            reasoning = int((data.get("output_tokens_details") or {}).get("reasoning_tokens") or 0)
        cost = 0.0
        if self.config.input_cost_per_million_tokens is not None:
            cost += input_tokens * self.config.input_cost_per_million_tokens / 1_000_000
        if self.config.output_cost_per_million_tokens is not None:
            cost += output_tokens * self.config.output_cost_per_million_tokens / 1_000_000
        return LLMUsage(
            input_tokens=input_tokens, output_tokens=output_tokens,
            cached_input_tokens=cached, reasoning_tokens=reasoning, cost_usd=cost,
        )

    @staticmethod
    def _arguments(value) -> Dict:
        if isinstance(value, dict):
            return value
        decoded = json.loads(value or "{}")
        if not isinstance(decoded, dict):
            raise ValueError("tool arguments must be a JSON object")
        return decoded

    def _chat_tool_call(self, item: Dict) -> ToolCall:
        function = item["function"]
        return ToolCall(
            call_id=item.get("id") or "call_unknown",
            name=function["name"],
            arguments=self._arguments(function.get("arguments", "{}")),
        )

    @staticmethod
    def _json_object_or_none(content: str) -> Optional[Dict]:
        if not content:
            return None
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None

    def _redacted_response(self, response: ProviderResponse) -> ProviderResponse:
        calls = [
            call.model_copy(update={"arguments": redact_secrets(call.arguments, [self._api_key])})
            for call in response.tool_calls
        ]
        structured = (
            redact_secrets(response.structured_output, [self._api_key])
            if response.structured_output is not None else None
        )
        return response.model_copy(update={
            "content": redact_secrets(response.content, [self._api_key]),
            "structured_output": structured,
            "tool_calls": calls,
        })

    def _http_error(self, exc: TransportHTTPError) -> ProviderError:
        retryable = exc.status_code in {408, 409, 425, 429} or exc.status_code >= 500
        request_id = exc.headers.get("x-request-id")
        safe_body = redact_secrets(exc.body, [self._api_key])
        return ProviderError(
            f"provider returned HTTP {exc.status_code}: {safe_body}",
            code="provider_http_error", retryable=retryable,
            status_code=exc.status_code, request_id=request_id,
        )


class FakeProvider:
    """Deterministic provider available only when runtime offline_mode is explicitly enabled."""
    provider_type = ProviderType.FAKE
    capabilities = FAKE_CAPABILITIES
    is_live = False

    def __init__(self, provider_id: str = "offline", responses: Optional[Iterable[ProviderResponse]] = None,
                 factory: Optional[Callable[[ProviderRequest], ProviderResponse]] = None,
                 failures: Optional[Iterable[BaseException]] = None) -> None:
        self.provider_id = provider_id
        self.responses: Deque[ProviderResponse] = deque(responses or [])
        self.factory = factory
        self.failures: Deque[BaseException] = deque(failures or [])
        self.requests: list[ProviderRequest] = []

    def complete(self, request: ProviderRequest, timeout_seconds: float) -> ProviderResponse:
        self.requests.append(request)
        if self.failures:
            raise self.failures.popleft()
        if self.responses:
            return self.responses.popleft()
        if self.factory is not None:
            return self.factory(request)
        raise LLMError("fake provider has no scripted response")

    def stream(self, request: ProviderRequest, timeout_seconds: float) -> Iterator[ProviderStreamEvent]:
        raise LLMError("fake provider streaming is not configured")

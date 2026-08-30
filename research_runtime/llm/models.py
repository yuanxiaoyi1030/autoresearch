# Purpose: Defines provider-neutral LLM configuration, capability, request, response, usage, and budget records.
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator


class LLMRole(str, Enum):
    DEVELOPER = "developer"
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LLMStage(str, Enum):
    PROJECT_UNDERSTANDING = "project_understanding"
    LITERATURE = "literature"
    HYPOTHESIS_PLANNING = "hypothesis_planning"
    EXPERIMENT_CODE = "experiment_code"
    ANALYSIS = "analysis"
    RESEARCH_REVIEW = "research_review"
    WRITER = "writer"


class ProviderType(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    LOCAL_OPENAI_COMPATIBLE = "local_openai_compatible"
    FAKE = "fake"


class OpenAIProtocol(str, Enum):
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


class ProviderCapabilities(BaseModel):
    structured_output: bool = False
    tool_calls: bool = False
    streaming: bool = False
    usage_accounting: bool = False
    supports_temperature: bool = True


class ProviderDescriptor(BaseModel):
    provider_type: ProviderType
    display_name: str
    available: bool
    explicit_offline_only: bool = False
    capabilities: ProviderCapabilities
    note: Optional[str] = None


class LLMMessage(BaseModel):
    role: LLMRole
    content: str = ""
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


class ToolDefinition(BaseModel):
    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    strict: bool = True


class ToolCall(BaseModel):
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: Dict[str, Any] = Field(default_factory=dict)


class LLMUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


class StageBudget(BaseModel):
    max_calls: int = Field(default=8, ge=1, le=10_000)
    max_input_tokens: int = Field(default=100_000, ge=1)
    max_output_tokens: int = Field(default=32_000, ge=1)
    max_total_tokens: int = Field(default=132_000, ge=1)
    max_cost_usd: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def total_covers_each_side(self) -> "StageBudget":
        if self.max_total_tokens < max(self.max_input_tokens, self.max_output_tokens):
            raise ValueError("max_total_tokens must cover each individual token limit")
        return self


class BudgetLedger(BaseModel):
    calls: int = Field(default=0, ge=0)
    provider_attempts: int = Field(default=0, ge=0)
    usage: LLMUsage = Field(default_factory=LLMUsage)


class LLMModelConfig(BaseModel):
    provider_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    provider_type: ProviderType
    model: str = Field(min_length=1, max_length=256)
    base_url: str = Field(min_length=1, max_length=2048)
    protocol: OpenAIProtocol = OpenAIProtocol.CHAT_COMPLETIONS
    temperature: Optional[float] = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(default=4_000, ge=1)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    retry_count: int = Field(default=2, ge=0, le=8)
    credential_required: bool = True
    input_cost_per_million_tokens: Optional[float] = Field(default=None, ge=0)
    output_cost_per_million_tokens: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_endpoint(self) -> "LLMModelConfig":
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain query or fragment data")
        self.base_url = self.base_url.rstrip("/")
        return self


class StageRouteConfig(BaseModel):
    model: LLMModelConfig
    budget: StageBudget = Field(default_factory=StageBudget)

    @model_validator(mode="after")
    def priced_budget_requires_pricing(self) -> "StageRouteConfig":
        if self.budget.max_cost_usd is not None and (
            self.model.input_cost_per_million_tokens is None
            or self.model.output_cost_per_million_tokens is None
        ):
            raise ValueError("stage cost budget requires input and output token pricing")
        return self


class LLMRuntimeConfig(BaseModel):
    default_route: Optional[StageRouteConfig] = None
    stages: Dict[LLMStage, StageRouteConfig] = Field(default_factory=dict)
    offline_mode: bool = False

    @model_validator(mode="after")
    def fake_requires_explicit_offline_mode(self) -> "LLMRuntimeConfig":
        routes = list(self.stages.values())
        if self.default_route is not None:
            routes.append(self.default_route)
        if any(route.model.provider_type is ProviderType.FAKE for route in routes) and not self.offline_mode:
            raise ValueError("fake provider requires explicit offline_mode=true")
        return self

    def route_for(self, stage: LLMStage) -> Optional[StageRouteConfig]:
        return self.stages.get(stage) or self.default_route


class ProviderRequest(BaseModel):
    model: str = Field(min_length=1)
    messages: List[LLMMessage] = Field(min_length=1)
    tools: List[ToolDefinition] = Field(default_factory=list)
    tool_choice: Optional[Literal["none", "auto", "required"]] = None
    response_schema: Optional[Dict[str, Any]] = None
    response_schema_name: str = Field(default="autoresearch_output", pattern=r"^[A-Za-z0-9_-]+$")
    max_output_tokens: int = Field(ge=1)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProviderResponse(BaseModel):
    content: str = ""
    structured_output: Optional[Dict[str, Any]] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    finish_reason: str = "stop"
    provider_request_id: Optional[str] = None


class ProviderStreamEvent(BaseModel):
    event_type: str
    delta: str = ""
    tool_call: Optional[ToolCall] = None
    usage: Optional[LLMUsage] = None
    raw_type: Optional[str] = None


class StructuredLLMResult(BaseModel):
    provider_id: str
    provider_type: ProviderType
    model: str
    is_live: bool
    output: Dict[str, Any]
    content: str = ""
    tool_calls: List[ToolCall] = Field(default_factory=list)
    usage: LLMUsage
    ledger: BudgetLedger
    finish_reason: str
    provider_request_id: Optional[str] = None


class CredentialStatus(BaseModel):
    provider_id: str
    configured: bool
    source: Optional[Literal["environment", "process_memory"]] = None
    fingerprint: Optional[str] = None


class LLMConfigurationStatus(BaseModel):
    status: Literal["ready", "unconfigured", "credential_missing", "provider_unavailable"]
    ready: bool
    detail: str
    configured_stages: List[LLMStage] = Field(default_factory=list)
    credentials: List[CredentialStatus] = Field(default_factory=list)


class ConnectionTestResult(BaseModel):
    ok: bool
    provider_id: str
    provider_type: ProviderType
    model: str
    latency_ms: int = Field(ge=0)
    status: str
    error: Optional[str] = None
    usage: LLMUsage = Field(default_factory=LLMUsage)

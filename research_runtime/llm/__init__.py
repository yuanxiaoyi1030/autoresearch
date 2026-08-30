# Purpose: Exposes the v0.2 provider registry, secure runtime, client, models, and redaction boundary.
from .client import LLMClient
from .errors import (
    BudgetExceeded, CredentialMissingError, LLMError, LLMNotConfiguredError,
    ProviderError, ProviderTimeoutError, ProviderUnavailableError, StructuredOutputError,
)
from .models import (
    BudgetLedger, ConnectionTestResult, CredentialStatus, LLMConfigurationStatus,
    LLMMessage, LLMModelConfig, LLMRole, LLMRuntimeConfig, LLMStage, LLMUsage,
    OpenAIProtocol, ProviderCapabilities, ProviderDescriptor, ProviderRequest,
    ProviderResponse, ProviderStreamEvent, ProviderType, StageBudget, StageRouteConfig,
    StructuredLLMResult, ToolCall, ToolDefinition,
)
from .providers import FakeProvider, LLMProvider, OpenAICompatibleProvider
from .redaction import redact_secrets
from .registry import ProviderRegistry, build_default_registry
from .runtime import LLMRuntime
from .secrets import InMemoryCredentialStore, sanitized_subprocess_environment
from .transport import HTTPResult, JSONTransport, TransportConnectionError, TransportHTTPError

__all__ = [
    "BudgetExceeded", "BudgetLedger", "ConnectionTestResult", "CredentialMissingError",
    "CredentialStatus", "FakeProvider", "HTTPResult", "InMemoryCredentialStore", "JSONTransport",
    "LLMClient", "LLMConfigurationStatus", "LLMError", "LLMMessage", "LLMModelConfig",
    "LLMNotConfiguredError", "LLMProvider", "LLMRole", "LLMRuntime", "LLMRuntimeConfig",
    "LLMStage", "LLMUsage", "OpenAICompatibleProvider", "OpenAIProtocol", "ProviderCapabilities",
    "ProviderDescriptor", "ProviderError", "ProviderRegistry", "ProviderRequest", "ProviderResponse",
    "ProviderStreamEvent", "ProviderTimeoutError", "ProviderType", "ProviderUnavailableError",
    "StageBudget", "StageRouteConfig", "StructuredLLMResult", "StructuredOutputError", "ToolCall",
    "ToolDefinition", "TransportConnectionError", "TransportHTTPError", "build_default_registry",
    "redact_secrets", "sanitized_subprocess_environment",
]

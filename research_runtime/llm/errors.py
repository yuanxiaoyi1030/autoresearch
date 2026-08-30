# Purpose: Normalizes provider, configuration, budget, timeout, and structured-output failures.
from typing import Optional


class LLMError(RuntimeError):
    code = "llm_error"


class LLMNotConfiguredError(LLMError):
    code = "llm_not_configured"


class CredentialMissingError(LLMNotConfiguredError):
    code = "credential_missing"


class ProviderUnavailableError(LLMNotConfiguredError):
    code = "provider_unavailable"


class BudgetExceeded(LLMError):
    code = "budget_exceeded"


class StructuredOutputError(LLMError):
    code = "structured_output_error"


class ProviderError(LLMError):
    def __init__(self, message: str, *, code: str = "provider_error", retryable: bool = False,
                 status_code: Optional[int] = None, request_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.request_id = request_id


class ProviderTimeoutError(ProviderError):
    def __init__(self, message: str = "provider request timed out") -> None:
        super().__init__(message, code="provider_timeout", retryable=True)

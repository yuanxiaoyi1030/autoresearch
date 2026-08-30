# Purpose: Owns non-secret LLM routing config, process-memory credentials, stage ledgers, and redacted connection tests.
from __future__ import annotations

import os
from threading import RLock
import time
from typing import Dict, Optional

from pydantic import BaseModel

from research_runtime.config import ENV_PREFIX

from .client import LLMClient
from .errors import CredentialMissingError, LLMError, LLMNotConfiguredError, ProviderUnavailableError
from .models import (
    BudgetLedger, ConnectionTestResult, LLMConfigurationStatus, LLMMessage, LLMModelConfig,
    LLMRole, LLMRuntimeConfig, LLMStage, OpenAIProtocol, ProviderType, StageBudget,
    StageRouteConfig,
)
from .prompts.runtime import connection_test_prompt
from .redaction import redact_secrets
from .registry import ProviderRegistry, build_default_registry
from .secrets import InMemoryCredentialStore


class _ConnectionProbe(BaseModel):
    ok: bool


class LLMRuntime:
    def __init__(self, registry: Optional[ProviderRegistry] = None,
                 credentials: Optional[InMemoryCredentialStore] = None) -> None:
        self.registry = registry or build_default_registry()
        self.credentials = credentials or InMemoryCredentialStore()
        self._config = LLMRuntimeConfig()
        self._ledgers: Dict[LLMStage, BudgetLedger] = {}
        self._ledger_locks: Dict[LLMStage, RLock] = {}
        self._configuration_error: Optional[str] = None
        self._lock = RLock()

    @classmethod
    def from_environment(cls, registry: Optional[ProviderRegistry] = None) -> "LLMRuntime":
        runtime = cls(registry=registry)
        names = {
            "provider_id": ENV_PREFIX + "LLM_PROVIDER_ID",
            "provider_type": ENV_PREFIX + "LLM_PROVIDER",
            "model": ENV_PREFIX + "LLM_MODEL",
            "base_url": ENV_PREFIX + "LLM_BASE_URL",
            "protocol": ENV_PREFIX + "LLM_PROTOCOL",
            "api_key": ENV_PREFIX + "LLM_API_KEY",
        }
        supplied = {key: os.environ.get(name) for key, name in names.items()}
        if not any(supplied.values()):
            return runtime
        provider_id = supplied["provider_id"] or "default"
        try:
            missing = [key for key in ("provider_type", "model", "base_url") if not supplied[key]]
            if missing:
                raise ValueError("incomplete environment LLM config; missing: " + ", ".join(missing))
            model = LLMModelConfig(
                provider_id=provider_id,
                provider_type=ProviderType(supplied["provider_type"]),
                model=supplied["model"],
                base_url=supplied["base_url"],
                protocol=OpenAIProtocol(supplied["protocol"] or OpenAIProtocol.CHAT_COMPLETIONS.value),
                temperature=float(os.environ.get(ENV_PREFIX + "LLM_TEMPERATURE", "0.2")),
                max_output_tokens=int(os.environ.get(ENV_PREFIX + "LLM_MAX_OUTPUT_TOKENS", "4000")),
                timeout_seconds=float(os.environ.get(ENV_PREFIX + "LLM_TIMEOUT_SECONDS", "60")),
                retry_count=int(os.environ.get(ENV_PREFIX + "LLM_RETRY_COUNT", "2")),
                input_cost_per_million_tokens=(
                    float(os.environ[ENV_PREFIX + "LLM_INPUT_COST_PER_MILLION_TOKENS"])
                    if os.environ.get(ENV_PREFIX + "LLM_INPUT_COST_PER_MILLION_TOKENS") else None
                ),
                output_cost_per_million_tokens=(
                    float(os.environ[ENV_PREFIX + "LLM_OUTPUT_COST_PER_MILLION_TOKENS"])
                    if os.environ.get(ENV_PREFIX + "LLM_OUTPUT_COST_PER_MILLION_TOKENS") else None
                ),
            )
            budget = StageBudget(
                max_calls=int(os.environ.get(ENV_PREFIX + "LLM_STAGE_CALL_BUDGET", "8")),
                max_input_tokens=int(os.environ.get(ENV_PREFIX + "LLM_STAGE_INPUT_TOKEN_BUDGET", "100000")),
                max_output_tokens=int(os.environ.get(ENV_PREFIX + "LLM_STAGE_OUTPUT_TOKEN_BUDGET", "32000")),
                max_total_tokens=int(os.environ.get(ENV_PREFIX + "LLM_STAGE_TOTAL_TOKEN_BUDGET", "132000")),
                max_cost_usd=(
                    float(os.environ[ENV_PREFIX + "LLM_STAGE_COST_BUDGET_USD"])
                    if os.environ.get(ENV_PREFIX + "LLM_STAGE_COST_BUDGET_USD") else None
                ),
            )
            runtime.configure(LLMRuntimeConfig(default_route=StageRouteConfig(model=model, budget=budget)))
            runtime.credentials.load_environment(provider_id, names["api_key"])
        except (TypeError, ValueError) as exc:
            runtime._configuration_error = str(redact_secrets(exc, runtime.credentials.known_secrets()))
        return runtime

    def configure(self, config: LLMRuntimeConfig) -> LLMConfigurationStatus:
        with self._lock:
            previous_ids = {route.model.provider_id for route in self._all_routes(self._config)}
            next_ids = {route.model.provider_id for route in self._all_routes(config)}
            self._config = config.model_copy(deep=True)
            self._ledgers = {}
            self._ledger_locks = {}
            self._configuration_error = None
        for removed_id in previous_ids - next_ids:
            self.credentials.clear(removed_id)
        return self.status()

    def config(self) -> LLMRuntimeConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def set_credential(self, provider_id: str, api_key: str):
        status = self.credentials.set(provider_id, api_key, source="process_memory")
        return status

    def clear_credential(self, provider_id: str):
        return self.credentials.clear(provider_id)

    def configured_provider_ids(self) -> set[str]:
        return {route.model.provider_id for route in self._all_routes(self.config())}

    def usage(self) -> Dict[LLMStage, BudgetLedger]:
        with self._lock:
            return {stage: ledger.model_copy(deep=True) for stage, ledger in self._ledgers.items()}

    def status(self) -> LLMConfigurationStatus:
        config = self.config()
        routes = self._all_routes(config)
        provider_ids = [route.model.provider_id for route in routes]
        credentials = self.credentials.statuses(provider_ids)
        configured_stages = [stage for stage in LLMStage if config.route_for(stage) is not None]
        if self._configuration_error:
            return LLMConfigurationStatus(
                status="unconfigured", ready=False,
                detail=self._configuration_error,
                configured_stages=configured_stages, credentials=credentials,
            )
        if not routes:
            return LLMConfigurationStatus(
                status="unconfigured", ready=False,
                detail="No LLM route is configured; real research calls are disabled",
                configured_stages=[], credentials=[],
            )
        for route in routes:
            descriptor = self.registry.descriptor(route.model.provider_type)
            if not descriptor.available:
                return LLMConfigurationStatus(
                    status="provider_unavailable", ready=False,
                    detail=descriptor.note or "Configured provider is unavailable",
                    configured_stages=configured_stages, credentials=credentials,
                )
            if route.model.provider_type is ProviderType.FAKE and not config.offline_mode:
                return LLMConfigurationStatus(
                    status="provider_unavailable", ready=False,
                    detail="Fake provider requires explicit offline mode",
                    configured_stages=configured_stages, credentials=credentials,
                )
            if route.model.credential_required and not self.credentials.get(route.model.provider_id):
                return LLMConfigurationStatus(
                    status="credential_missing", ready=False,
                    detail=f"Credential is not configured for provider_id={route.model.provider_id}",
                    configured_stages=configured_stages, credentials=credentials,
                )
        return LLMConfigurationStatus(
            status="ready", ready=True, detail="LLM routes and credentials are configured",
            configured_stages=configured_stages, credentials=credentials,
        )

    def client_for(self, stage: LLMStage) -> tuple[LLMClient, StageRouteConfig, BudgetLedger]:
        config = self.config()
        route = config.route_for(stage)
        if route is None:
            raise LLMNotConfiguredError(f"No LLM route is configured for stage={stage.value}")
        credential = self.credentials.get(route.model.provider_id)
        if route.model.credential_required and not credential:
            raise CredentialMissingError(
                f"Credential is not configured for provider_id={route.model.provider_id}"
            )
        try:
            provider = self.registry.create(route.model, credential, allow_offline=config.offline_mode)
        except ValueError as exc:
            raise CredentialMissingError(str(exc)) from None
        with self._lock:
            ledger = self._ledgers.setdefault(stage, BudgetLedger())
            ledger_lock = self._ledger_locks.setdefault(stage, RLock())
        return LLMClient(
            provider, route.model, self.credentials.known_secrets(), ledger_lock=ledger_lock,
        ), route, ledger

    def test_connection(self, stage: LLMStage) -> ConnectionTestResult:
        started = time.monotonic()
        config = self.config()
        route = config.route_for(stage)
        if route is None:
            return ConnectionTestResult(
                ok=False, provider_id="unconfigured", provider_type=ProviderType.OPENAI_COMPATIBLE,
                model="unconfigured", latency_ms=0, status="unconfigured",
                error=f"No LLM route is configured for stage={stage.value}",
            )
        try:
            client, _, _ = self.client_for(stage)
            probe_budget = StageBudget(
                max_calls=1, max_input_tokens=2048, max_output_tokens=64, max_total_tokens=2112,
            )
            _, result = client.generate_structured(
                [
                    LLMMessage(role=LLMRole.SYSTEM, content=connection_test_prompt(_ConnectionProbe)),
                    LLMMessage(role=LLMRole.USER, content='{"probe":"connection"}'),
                ],
                _ConnectionProbe,
                probe_budget,
            )
            return ConnectionTestResult(
                ok=True, provider_id=route.model.provider_id,
                provider_type=route.model.provider_type, model=route.model.model,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="connected", usage=result.usage,
            )
        except (LLMError, ProviderUnavailableError, ValueError) as exc:
            safe = str(redact_secrets(exc, self.credentials.known_secrets()))
            return ConnectionTestResult(
                ok=False, provider_id=route.model.provider_id,
                provider_type=route.model.provider_type, model=route.model.model,
                latency_ms=int((time.monotonic() - started) * 1000),
                status=getattr(exc, "code", "connection_failed"), error=safe,
            )

    @staticmethod
    def _all_routes(config: LLMRuntimeConfig) -> list[StageRouteConfig]:
        unique: Dict[str, StageRouteConfig] = {}
        candidates = list(config.stages.values())
        if config.default_route is not None:
            candidates.append(config.default_route)
        for route in candidates:
            key = route.model.model_dump_json()
            unique[key] = route
        return list(unique.values())

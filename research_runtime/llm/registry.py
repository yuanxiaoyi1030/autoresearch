# Purpose: Registers provider factories and exposes honest availability/capability declarations.
from __future__ import annotations

from threading import RLock
from typing import Callable, Dict, Iterable, Optional

from .errors import ProviderUnavailableError
from .models import LLMModelConfig, ProviderCapabilities, ProviderDescriptor, ProviderType
from .providers import (
    FAKE_CAPABILITIES, OPENAI_COMPATIBLE_CAPABILITIES, FakeProvider, LLMProvider,
    OpenAICompatibleProvider,
)
from .transport import JSONTransport


ProviderFactory = Callable[[LLMModelConfig, Optional[str]], LLMProvider]


class ProviderRegistry:
    def __init__(self) -> None:
        self._descriptors: Dict[ProviderType, ProviderDescriptor] = {}
        self._factories: Dict[ProviderType, ProviderFactory] = {}
        self._lock = RLock()

    def register(self, descriptor: ProviderDescriptor,
                 factory: Optional[ProviderFactory] = None, *, replace: bool = False) -> None:
        with self._lock:
            if descriptor.provider_type in self._descriptors and not replace:
                raise ValueError(f"provider type already registered: {descriptor.provider_type.value}")
            if descriptor.available != (factory is not None):
                raise ValueError("descriptor availability must match factory availability")
            self._descriptors[descriptor.provider_type] = descriptor
            if factory is None:
                self._factories.pop(descriptor.provider_type, None)
            else:
                self._factories[descriptor.provider_type] = factory

    def descriptors(self) -> list[ProviderDescriptor]:
        with self._lock:
            return [self._descriptors[key] for key in sorted(self._descriptors, key=lambda item: item.value)]

    def descriptor(self, provider_type: ProviderType) -> ProviderDescriptor:
        with self._lock:
            descriptor = self._descriptors.get(provider_type)
        if descriptor is None:
            raise ProviderUnavailableError(f"provider type is not registered: {provider_type.value}")
        return descriptor

    def create(self, config: LLMModelConfig, credential: Optional[str], *,
               allow_offline: bool = False) -> LLMProvider:
        descriptor = self.descriptor(config.provider_type)
        if not descriptor.available:
            raise ProviderUnavailableError(
                descriptor.note or f"provider is not implemented: {config.provider_type.value}"
            )
        if descriptor.explicit_offline_only and not allow_offline:
            raise ProviderUnavailableError("fake provider requires explicit offline_mode=true")
        with self._lock:
            factory = self._factories[config.provider_type]
        return factory(config, credential)


def build_default_registry(transport: Optional[JSONTransport] = None) -> ProviderRegistry:
    registry = ProviderRegistry()

    def compatible(config: LLMModelConfig, credential: Optional[str]) -> LLMProvider:
        if config.credential_required and not credential:
            raise ValueError("credential is required")
        return OpenAICompatibleProvider(config, credential or "", transport=transport)

    for provider_type, display_name in (
        (ProviderType.OPENAI_COMPATIBLE, "OpenAI-compatible API"),
        (ProviderType.OPENAI, "OpenAI"),
        (ProviderType.LOCAL_OPENAI_COMPATIBLE, "Local OpenAI-compatible service"),
    ):
        registry.register(ProviderDescriptor(
            provider_type=provider_type,
            display_name=display_name,
            available=True,
            capabilities=OPENAI_COMPATIBLE_CAPABILITIES,
        ), compatible)

    registry.register(ProviderDescriptor(
        provider_type=ProviderType.ANTHROPIC,
        display_name="Anthropic",
        available=False,
        capabilities=ProviderCapabilities(),
        note="Anthropic adapter interface is reserved but not implemented in Milestone 1",
    ))
    registry.register(ProviderDescriptor(
        provider_type=ProviderType.GEMINI,
        display_name="Gemini",
        available=False,
        capabilities=ProviderCapabilities(),
        note="Gemini adapter interface is reserved but not implemented in Milestone 1",
    ))
    registry.register(ProviderDescriptor(
        provider_type=ProviderType.FAKE,
        display_name="Explicit offline/test fake",
        available=True,
        explicit_offline_only=True,
        capabilities=FAKE_CAPABILITIES,
    ), lambda config, credential: FakeProvider(provider_id=config.provider_id))
    return registry

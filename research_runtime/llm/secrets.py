# Purpose: Keeps API credentials in process memory and removes all credential-like variables from child environments.
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
import re
from threading import RLock
from typing import Dict, Iterable, Mapping, Optional

from .models import CredentialStatus


SENSITIVE_ENV_NAME = re.compile(
    r"(?i)(api_?key|access_?token|refresh_?token|authorization|cookie|password|secret|credential|bearer)"
)


@dataclass(frozen=True)
class _SecretRecord:
    value: str
    source: str


class InMemoryCredentialStore:
    """The only runtime owner of raw provider credentials; no persistence methods exist."""

    def __init__(self) -> None:
        self._records: Dict[str, _SecretRecord] = {}
        self._lock = RLock()

    def set(self, provider_id: str, value: str, source: str = "process_memory") -> CredentialStatus:
        raw = value.strip()
        if not raw:
            raise ValueError("API key must not be empty")
        if source not in {"environment", "process_memory"}:
            raise ValueError("unsupported credential source")
        with self._lock:
            self._records[provider_id] = _SecretRecord(value=raw, source=source)
        return self.status(provider_id)

    def load_environment(self, provider_id: str, variable_name: str) -> CredentialStatus:
        value = os.environ.get(variable_name)
        if value:
            return self.set(provider_id, value, source="environment")
        return self.status(provider_id)

    def get(self, provider_id: str) -> Optional[str]:
        with self._lock:
            record = self._records.get(provider_id)
            return record.value if record else None

    def clear(self, provider_id: str) -> CredentialStatus:
        with self._lock:
            self._records.pop(provider_id, None)
        return self.status(provider_id)

    def status(self, provider_id: str) -> CredentialStatus:
        with self._lock:
            record = self._records.get(provider_id)
        if record is None:
            return CredentialStatus(provider_id=provider_id, configured=False)
        fingerprint = "sha256:" + sha256(record.value.encode("utf-8")).hexdigest()[:10]
        return CredentialStatus(
            provider_id=provider_id, configured=True, source=record.source, fingerprint=fingerprint,
        )

    def statuses(self, provider_ids: Iterable[str]) -> list[CredentialStatus]:
        return [self.status(provider_id) for provider_id in sorted(set(provider_ids))]

    def known_secrets(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(record.value for record in self._records.values())


def sanitized_subprocess_environment(
    environment: Optional[Mapping[str, str]] = None,
    *,
    additional_sensitive_names: Iterable[str] = (),
) -> Dict[str, str]:
    """Build an experiment/worker environment that cannot inherit credentials."""
    source = dict(os.environ if environment is None else environment)
    blocked = {name.casefold() for name in additional_sensitive_names}
    return {
        name: value
        for name, value in source.items()
        if name.casefold() not in blocked and not SENSITIVE_ENV_NAME.search(name)
    }

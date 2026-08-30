# Purpose: Rejects credentials before durable state, events, jobs, artifacts, or metadata can persist them.
from __future__ import annotations

import re
from typing import Any, Iterable


SENSITIVE_FIELD = re.compile(
    r"(?i)(api[-_]?key|access[-_]?token|refresh[-_]?token|authorization|cookie|password|secret|credential)"
)
INLINE_CREDENTIAL = re.compile(
    r"(?i)bearer\s+[a-z0-9._~+/=-]+|"
    r"(?:api[-_]?key|access[-_]?token|refresh[-_]?token|secret|password|authorization)\s*[:=]\s*[^\s,;&]+"
)


class SecretPersistenceError(ValueError):
    pass


def assert_secret_free(value: Any, known_secrets: Iterable[str] = (), *,
                       context: str = "durable data") -> None:
    """Fail closed when a value looks like, names, or contains a configured credential."""
    secrets = tuple(secret for secret in known_secrets if secret)

    def inspect(item: Any) -> bool:
        if isinstance(item, dict):
            return any(SENSITIVE_FIELD.search(str(key)) or inspect(child) for key, child in item.items())
        if isinstance(item, (list, tuple, set)):
            return any(inspect(child) for child in item)
        if isinstance(item, BaseException):
            return inspect(str(item))
        if isinstance(item, str):
            return INLINE_CREDENTIAL.search(item) is not None or any(secret in item for secret in secrets)
        return False

    if inspect(value):
        raise SecretPersistenceError(f"credential-like content is forbidden in {context}")

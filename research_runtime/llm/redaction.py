# Purpose: Produces secret-free diagnostic values for API responses, events, errors, and logs.
from __future__ import annotations

import re
from typing import Any, Iterable


SENSITIVE_KEY = re.compile(
    r"(api[-_]?key|access[-_]?token|refresh[-_]?token|authorization|cookie|password|secret|credential)",
    re.IGNORECASE,
)
INLINE_SECRET = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._~+/=-]+|"
    r"((?:api[-_]?key|access[-_]?token|refresh[-_]?token|secret|password|authorization)\s*[:=]\s*)"
    r"[^\s,;&]+"
)
URL_SECRET = re.compile(
    r"(?i)([?&](?:api[-_]?key|key|token|access_token|secret|password)=)[^&#\s]+"
)


def redact_secrets(value: Any, known_secrets: Iterable[str] = ()) -> Any:
    """Return a structure-preserving diagnostic copy with credentials removed."""
    secrets = tuple(secret for secret in known_secrets if secret)
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact_secrets(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item, secrets) for item in value)
    if isinstance(value, set):
        return {redact_secrets(item, secrets) for item in value}
    if isinstance(value, BaseException):
        return redact_secrets(f"{type(value).__name__}: {value}", secrets)
    if isinstance(value, str):
        safe = value
        for secret in sorted(secrets, key=len, reverse=True):
            safe = safe.replace(secret, "[REDACTED]")
        safe = URL_SECRET.sub(lambda match: match.group(1) + "[REDACTED]", safe)
        return INLINE_SECRET.sub(
            lambda match: (match.group(1) or match.group(2) or "") + "[REDACTED]", safe,
        )
    return value

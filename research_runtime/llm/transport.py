# Purpose: Provides dependency-free JSON and SSE HTTP transport with bounded response bodies.
from __future__ import annotations

from dataclasses import dataclass
import json
import socket
from typing import Dict, Iterator, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_ERROR_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class HTTPResult:
    status_code: int
    headers: Dict[str, str]
    data: Dict


class TransportHTTPError(RuntimeError):
    def __init__(self, status_code: int, body: str, headers: Mapping[str, str]) -> None:
        super().__init__(f"HTTP {status_code}: {body}")
        self.status_code = status_code
        self.body = body
        self.headers = {str(key).lower(): str(value) for key, value in headers.items()}


class TransportConnectionError(RuntimeError):
    pass


class JSONTransport(Protocol):
    def post_json(self, url: str, headers: Mapping[str, str], payload: Dict,
                  timeout_seconds: float) -> HTTPResult:
        ...

    def post_sse(self, url: str, headers: Mapping[str, str], payload: Dict,
                 timeout_seconds: float) -> Iterator[str]:
        ...


class UrllibJSONTransport:
    """Standard-library transport; request bodies and headers are never logged."""

    @staticmethod
    def _request(url: str, headers: Mapping[str, str], payload: Dict) -> Request:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return Request(url, data=encoded, headers=dict(headers), method="POST")

    def post_json(self, url: str, headers: Mapping[str, str], payload: Dict,
                  timeout_seconds: float) -> HTTPResult:
        request = self._request(url, headers, payload)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
                parsed = json.loads(raw.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise TransportConnectionError("provider returned a non-object JSON response")
                return HTTPResult(
                    status_code=int(response.status),
                    headers={str(key).lower(): str(value) for key, value in response.headers.items()},
                    data=parsed,
                )
        except HTTPError as exc:
            body = exc.read(MAX_ERROR_BODY_BYTES).decode("utf-8", errors="replace")
            raise TransportHTTPError(exc.code, body, dict(exc.headers.items())) from None
        except (TimeoutError, socket.timeout) as exc:
            raise TimeoutError("HTTP request timed out") from None
        except (URLError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TransportConnectionError(f"HTTP transport failed: {exc}") from None

    def post_sse(self, url: str, headers: Mapping[str, str], payload: Dict,
                 timeout_seconds: float) -> Iterator[str]:
        request = self._request(url, headers, payload)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                for raw_line in response:
                    yield raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        except HTTPError as exc:
            body = exc.read(MAX_ERROR_BODY_BYTES).decode("utf-8", errors="replace")
            raise TransportHTTPError(exc.code, body, dict(exc.headers.items())) from None
        except (TimeoutError, socket.timeout):
            raise TimeoutError("HTTP stream timed out") from None
        except (URLError, OSError, UnicodeError) as exc:
            raise TransportConnectionError(f"HTTP stream failed: {exc}") from None

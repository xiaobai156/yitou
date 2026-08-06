from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit


RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
TLS_CERTIFICATE_FAILURE_MARKERS = (
    "certificate_verify_failed",
    "certificate verify failed",
    "hostname mismatch",
    "unable to get local issuer certificate",
)


class RequestFailure(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


def tls_failure_is_retryable(exc: BaseException) -> bool:
    detail = str(exc).lower()
    return not any(marker in detail for marker in TLS_CERTIFICATE_FAILURE_MARKERS)


@dataclass(frozen=True)
class ResponsePayload:
    url: str
    status_code: int
    text: str
    json_value: Any = None


@dataclass(frozen=True)
class RenderedPayload:
    html: str
    payloads: tuple[Any, ...] = ()


@dataclass(frozen=True)
class RenderedJsonPayload:
    url: str
    value: Any


@dataclass
class _Flight:
    ready: threading.Event = field(default_factory=threading.Event)
    payload: Any = None
    error: BaseException | None = None


def normalize_request_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise RequestFailure(f"URL无效：{value}")
    host = parsed.hostname.lower()
    port = parsed.port
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    netloc = host if port is None or port == default_port else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def response_text(response: Any) -> str:
    content = getattr(response, "content", b"")
    text = getattr(response, "text", "")
    if not isinstance(content, (bytes, bytearray)) or not content:
        return str(text or "")
    candidates = [str(text or "")]
    for encoding in (getattr(response, "encoding", None), "utf-8", "gb18030", "gbk"):
        if not encoding:
            continue
        try:
            candidates.append(bytes(content).decode(encoding, "replace"))
        except Exception:
            continue
    return max(candidates, key=lambda item: sum("\u4e00" <= char <= "\u9fff" for char in item) - item.count("�") * 20)

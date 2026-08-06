from __future__ import annotations

import httpx

from .settings import HEAD_VALUE_RE, MAX_WORKERS, PERIOD_RE
from .parsers.common import html_to_text
from .transport import FetchContext, response_text


def tls_verification_enabled() -> bool:
    return True


def build_client() -> FetchContext:
    return FetchContext(max_workers=MAX_WORKERS)


def text_quality_score(text: str) -> int:
    cjk_count = sum("\u4e00" <= char <= "\u9fff" for char in text)
    return cjk_count - text.count("�") * 20


def get_text(client: FetchContext | httpx.Client, url: str) -> str:
    if isinstance(client, FetchContext):
        return client.get_text(url)
    response = client.get(url)
    ensure_success_response(response, url)
    return response_text(response)


def page_content_score(text: str) -> int:
    plain = html_to_text(text)
    return (
        text_quality_score(plain)
        + len(PERIOD_RE.findall(plain)) * 5
        + len(HEAD_VALUE_RE.findall(plain)) * 3
    )


def ensure_success_response(response, url: str) -> None:
    status_code = int(getattr(response, "status_code", 200) or 200)
    if status_code >= 400:
        raise RuntimeError(f"HTTP {status_code}: {url}")


def get_json(client: FetchContext | httpx.Client, url: str):
    if isinstance(client, FetchContext):
        return client.get_json(url)
    response = client.get(url)
    ensure_success_response(response, url)
    return response.json()

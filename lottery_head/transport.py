from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from .settings import MAX_WORKERS, USER_AGENT
from .transport_browser import BrowserService
from .transport_types import RETRYABLE_HTTP_STATUSES, TLS_CERTIFICATE_FAILURE_MARKERS, RenderedJsonPayload, RenderedPayload, RequestFailure, ResponsePayload, _Flight, normalize_request_url, response_text, tls_failure_is_retryable


def build_http_client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        verify=True,
        trust_env=False,
        timeout=httpx.Timeout(12.0, connect=8.0),
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
    )


class FetchContext:
    """Thread-safe, run-scoped HTTP cache with URL single-flight and domain limits."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        max_workers: int = 10,
        domain_limit: int = 2,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.25,
        site_timeout_seconds: float = 35.0,
        browser_renderer: Callable[[str, float], Any] | None = None,
    ) -> None:
        self.max_workers = max(1, int(max_workers))
        self.domain_limit = max(1, int(domain_limit))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.site_timeout_seconds = max(1.0, float(site_timeout_seconds))
        self._client = client or build_http_client()
        self._owns_client = client is None
        self._lock = threading.Lock()
        self._flights: dict[str, _Flight] = {}
        self._domains: dict[str, threading.BoundedSemaphore] = defaultdict(
            lambda: threading.BoundedSemaphore(self.domain_limit)
        )
        self._browser_service = BrowserService(browser_renderer, max_workers=min(2, self.max_workers))
        self._browser_flights: dict[str, _Flight] = {}

    def __enter__(self) -> "FetchContext":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._browser_service.close()
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()
            self._owns_client = False

    def get_text(self, url: str) -> str:
        return self.fetch(url).text

    def get_json(self, url: str) -> Any:
        payload = self.fetch(url)
        if payload.json_value is not None:
            return payload.json_value
        try:
            return json.loads(payload.text)
        except Exception as exc:
            raise RequestFailure(f"JSON响应格式无效：{payload.url}") from exc

    def render_dynamic(self, url: str) -> RenderedPayload:
        key = normalize_request_url(url)
        with self._lock:
            flight = self._browser_flights.get(key)
            owner = flight is None
            if owner:
                flight = _Flight()
                self._browser_flights[key] = flight
        assert flight is not None
        if not owner:
            if not flight.ready.wait(self.site_timeout_seconds):
                raise RequestFailure("单站总时限已用尽：等待同URL浏览器渲染超时", retryable=True)
            if flight.error is not None:
                raise flight.error
            assert isinstance(flight.payload, RenderedPayload)
            return flight.payload
        try:
            payload = self._browser_service.render(key, self.site_timeout_seconds)
            flight.payload = payload
            return payload
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            flight.ready.set()

    def render_dynamic_fresh(self, url: str) -> RenderedPayload:
        key = normalize_request_url(url)
        return self._browser_service.render(key, self.site_timeout_seconds)

    def fetch(self, url: str) -> ResponsePayload:
        key = normalize_request_url(url)
        with self._lock:
            flight = self._flights.get(key)
            owner = flight is None
            if owner:
                flight = _Flight()
                self._flights[key] = flight
        assert flight is not None
        if not owner:
            if not flight.ready.wait(self.site_timeout_seconds):
                raise RequestFailure("单站总时限已用尽：等待同URL请求超时", retryable=True)
            if flight.error is not None:
                raise flight.error
            assert flight.payload is not None
            return flight.payload
        try:
            payload = self._fetch_with_retry(key)
            flight.payload = payload
            return payload
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            flight.ready.set()

    def _fetch_with_retry(self, url: str) -> ResponsePayload:
        deadline = time.monotonic() + self.site_timeout_seconds
        attempt = 0
        while True:
            if time.monotonic() >= deadline:
                raise RequestFailure("单站总时限已用尽", retryable=True)
            try:
                return self._fetch_once(url)
            except RequestFailure as exc:
                if not exc.retryable or attempt + 1 >= self.max_attempts:
                    raise
                delay = min(self.retry_backoff_seconds * (2**attempt), max(0.0, deadline - time.monotonic()))
                if delay:
                    time.sleep(delay)
                attempt += 1

    def _fetch_once(self, url: str) -> ResponsePayload:
        host = urlsplit(url).netloc
        limiter = self._domains[host]
        if not limiter.acquire(timeout=self.site_timeout_seconds):
            raise RequestFailure("单站总时限已用尽：等待同域请求超时", retryable=True)
        try:
            try:
                response = self._client.get(url)
            except httpx.TimeoutException as exc:
                raise RequestFailure(f"网络超时：{url}", retryable=True) from exc
            except httpx.ConnectError as exc:
                if "ssl" in str(exc).lower():
                    raise RequestFailure(
                        f"SSL/TLS失败：{url}", retryable=tls_failure_is_retryable(exc)
                    ) from exc
                raise RequestFailure(f"网络连接失败：{url}", retryable=True) from exc
            except httpx.TransportError as exc:
                category = "SSL/TLS失败" if "ssl" in str(exc).lower() else "网络请求失败"
                retryable = category != "SSL/TLS失败" or tls_failure_is_retryable(exc)
                raise RequestFailure(f"{category}：{url}", retryable=retryable) from exc
            except Exception as exc:
                raise RequestFailure(f"网络请求失败：{url}：{exc}", retryable=False) from exc
            status = int(getattr(response, "status_code", 0) or 0)
            if status < 200 or status >= 300:
                raise RequestFailure(
                    f"HTTP {status}：{url}",
                    retryable=status in RETRYABLE_HTTP_STATUSES,
                    status_code=status,
                )
            text = response_text(response)
            try:
                json_value = response.json()
            except Exception:
                json_value = None
            return ResponsePayload(url=url, status_code=status, text=text, json_value=json_value)
        finally:
            limiter.release()

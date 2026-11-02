from __future__ import annotations

import gzip
import http.client
import json
import os
import socket
import ssl
import threading
import time
import zlib
from collections import defaultdict
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import httpx

from .settings import USER_AGENT
from .transport_browser import BrowserService
from .transport_types import RETRYABLE_HTTP_STATUSES, RenderedPayload, RequestFailure, ResponsePayload, _Flight, normalize_request_url, response_text, tls_failure_is_retryable


def build_http_client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        verify=True,
        trust_env=False,
        timeout=httpx.Timeout(12.0, connect=8.0),
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
    )


LOCAL_PROXY_CANDIDATES = ("127.0.0.1:7897", "127.0.0.1:7890", "127.0.0.1:10809", "127.0.0.1:1080")


def detect_local_proxy() -> str | None:
    """无 HTTPS_PROXY 时探测本机已监听的代理端口（仅 tls_compat 域名使用）。"""
    for candidate in LOCAL_PROXY_CANDIDATES:
        host, _, port = candidate.partition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=0.3):
                return f"http://{candidate}"
        except (OSError, ValueError):
            continue
    return None


def build_insecure_http_client() -> httpx.Client:
    """仅用于站点显式声明 tls_compat 的域名（默认路径仍严格校验证书）。

    这些域名在本机直连会被拒（TLS 握手 EOF），必须经本机代理：优先使用
    环境里的 HTTPS_PROXY，未设置时探测本机已监听的代理端口；都没有才直连。
    """
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or detect_local_proxy()
    options: dict[str, Any] = {}
    if proxy:
        options["proxy"] = proxy
    return httpx.Client(
        follow_redirects=True,
        verify=False,
        trust_env=False,
        timeout=httpx.Timeout(12.0, connect=8.0),
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
        **options,
    )


DOH_ENDPOINTS = ("https://223.5.5.5/resolve", "https://1.1.1.1/dns-query")
_REAL_IP_CACHE: dict[str, list[str]] = {}


def resolve_real_ips(host: str) -> list[str]:
    """经 DoH 取真实 A 记录。

    本机 DNS 被代理接管时部分域名只返回代理假地址（198.18.0.0/15），直连必然
    握手失败；这里改用 DoH 拿真实 IP，作为直连失败后的最后一次尝试。
    """
    if host in _REAL_IP_CACHE:
        return _REAL_IP_CACHE[host]
    for endpoint in DOH_ENDPOINTS:
        try:
            with httpx.Client(verify=False, trust_env=False, timeout=httpx.Timeout(8.0)) as client:
                response = client.get(
                    endpoint,
                    params={"name": host, "type": "A"},
                    headers={"accept": "application/dns-json", "User-Agent": USER_AGENT},
                )
                payload = response.json()
            ips = [str(item["data"]) for item in payload.get("Answer", []) if item.get("type") == 1]
            if ips:
                _REAL_IP_CACHE[host] = ips
                return ips
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            continue
    return []


class _SniConnection(http.client.HTTPSConnection):
    """连接真实 IP，但用原域名做 SNI 和 Host（证书仍按域名严格校验）。"""

    def __init__(self, host: str, ip: str, timeout: float) -> None:
        super().__init__(host, timeout=timeout)
        self._ip = ip

    def connect(self) -> None:
        raw = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)


def _decode_body(body: bytes, content_encoding: str) -> str:
    encoding = (content_encoding or "").lower()
    if encoding == "gzip":
        body = gzip.decompress(body)
    elif encoding == "deflate":
        body = zlib.decompress(body)
    for charset in ("utf-8", "gb18030"):
        try:
            return body.decode(charset)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", "ignore")


def fetch_via_real_ip(url: str, timeout: float = 20.0, depth: int = 0) -> ResponsePayload:
    """按真实 IP 完成一次 HTTPS GET，返回与 httpx 一致的响应载荷。"""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.scheme.lower() != "https" or not host or depth > 3:
        raise RequestFailure(f"真实IP回退不支持：{url}", retryable=False)
    ips = resolve_real_ips(host)
    if not ips:
        raise RequestFailure(f"真实IP回退无法解析域名：{host}", retryable=False)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    last_error: Exception | None = None
    for ip in ips[:2]:
        connection = _SniConnection(host, ip, timeout)
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Host": parsed.netloc,
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            status = int(response.status)
            body = response.read()
            content_encoding = response.getheader("content-encoding", "")
            location = response.getheader("location", "")
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
            continue
        finally:
            connection.close()
        if status in {301, 302, 303, 307, 308} and location:
            if location.startswith("/"):
                location = f"{parsed.scheme}://{parsed.netloc}{location}"
            return fetch_via_real_ip(location, timeout, depth + 1)
        if status < 200 or status >= 300:
            raise RequestFailure(
                f"HTTP {status}：{url}",
                retryable=status in RETRYABLE_HTTP_STATUSES,
                status_code=status,
            )
        return ResponsePayload(url=url, status_code=status, text=_decode_body(body, content_encoding))
    raise RequestFailure(f"真实IP回退连接失败：{url}：{last_error}", retryable=False)


def tls_compat_hosts(rules: Iterable[Any] | None = None) -> set[str]:
    """收集声明了 tls_compat 的站点域名（配置是唯一来源；缺配置时返回空集）。"""
    if rules is None:
        try:
            from .config import load_rules

            rules = load_rules()
        except Exception:
            return set()
    hosts = {urlsplit(str(getattr(rule, "url", "") or "")).hostname or "" for rule in rules if getattr(rule, "tls_compat", False)}
    return {host for host in hosts if host}


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
        insecure_hosts: Iterable[str] | None = None,
    ) -> None:
        self.max_workers = max(1, int(max_workers))
        self.domain_limit = max(1, int(domain_limit))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.site_timeout_seconds = max(1.0, float(site_timeout_seconds))
        self._client = client or build_http_client()
        self._owns_client = client is None
        self._insecure_hosts = (
            {str(host) for host in insecure_hosts if host} if insecure_hosts is not None else tls_compat_hosts()
        )
        self._insecure_client: Any | None = None
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
        if self._insecure_client is not None:
            close = getattr(self._insecure_client, "close", None)
            if callable(close):
                close()
            self._insecure_client = None
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()
            self._owns_client = False

    def _is_insecure(self, url: str) -> bool:
        return (urlsplit(url).hostname or "") in self._insecure_hosts

    def _client_for(self, url: str) -> Any:
        if not self._is_insecure(url):
            return self._client
        if self._insecure_client is None:
            self._insecure_client = build_insecure_http_client()
        return self._insecure_client

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
            payload = self._browser_service.render(key, self.site_timeout_seconds, insecure=self._is_insecure(key))
            flight.payload = payload
            return payload
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            flight.ready.set()

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

    def _real_ip_fallback(self, url: str) -> ResponsePayload | None:
        """直连失败后按 DoH 真实 IP 重试一次（本机 DNS 返回代理假地址时用）。"""
        try:
            return fetch_via_real_ip(url, timeout=float(self.site_timeout_seconds))
        except RequestFailure:
            return None

    def _fetch_once(self, url: str) -> ResponsePayload:
        host = urlsplit(url).netloc
        limiter = self._domains[host]
        if not limiter.acquire(timeout=self.site_timeout_seconds):
            raise RequestFailure("单站总时限已用尽：等待同域请求超时", retryable=True)
        try:
            try:
                response = self._client_for(url).get(url)
            except httpx.TimeoutException as exc:
                raise RequestFailure(f"网络超时：{url}", retryable=True) from exc
            except httpx.ConnectError as exc:
                fallback = self._real_ip_fallback(url)
                if fallback is not None:
                    return fallback
                if "ssl" in str(exc).lower():
                    raise RequestFailure(
                        f"SSL/TLS失败：{url}", retryable=tls_failure_is_retryable(exc)
                    ) from exc
                raise RequestFailure(f"网络连接失败：{url}", retryable=True) from exc
            except httpx.TransportError as exc:
                fallback = self._real_ip_fallback(url)
                if fallback is not None:
                    return fallback
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

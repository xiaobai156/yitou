from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable
from urllib.parse import urlsplit

from .settings import USER_AGENT
from .transport_types import RenderedJsonPayload, RenderedPayload, RequestFailure


_BLOCKED_RESOURCE_TYPES = {"font", "image", "media"}
_JSON_RESOURCE_TYPES = {"fetch", "xhr"}


class BrowserService:
    """Small persistent browser pool used only by explicitly dynamic pages."""

    def __init__(self, renderer: Callable[[str, float], Any] | None = None, max_workers: int = 2) -> None:
        self._renderer = renderer
        self._workers = 1
        self._executor = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="lottery-head-browser")
        self._slots = threading.BoundedSemaphore(self._workers)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._closed = False

    def render(self, url: str, timeout: float, *, insecure: bool = False) -> RenderedPayload:
        with self._lock:
            if self._closed:
                raise RequestFailure("浏览器运行时已关闭")
        # The executor is intentionally a single browser lane.  Queueing for
        # that lane is not page-render time; only the running render gets the
        # caller's timeout.
        self._slots.acquire()
        try:
            future = self._executor.submit(self._render, url, max(0.1, timeout), insecure)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(self._release_slot)
        try:
            return future.result(timeout=max(0.1, timeout))
        except FutureTimeoutError as exc:
            future.cancel()
            raise RequestFailure("单站总时限已用尽：浏览器渲染超时", retryable=True) from exc

    def _release_slot(self, _future: object) -> None:
        self._slots.release()

    def _render(self, url: str, timeout: float, insecure: bool = False) -> RenderedPayload:
        if self._renderer is not None:
            result = self._renderer(url, timeout)
            if isinstance(result, RenderedPayload):
                return result
            if isinstance(result, dict):
                return RenderedPayload(
                    str(result.get("html", "")),
                    tuple(result.get("payloads", ())),
                    str(result.get("url", url)),
                )
            return RenderedPayload(str(result), (), url)
        context = None
        page = None
        try:
            playwright, browser = self._ensure_browser()
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="zh-CN",
                ignore_https_errors=bool(insecure),
            )
            page = context.new_page()
            payloads: list[RenderedJsonPayload] = []

            route = getattr(page, "route", None)
            if callable(route):
                route("**/*", _route_non_content_request)

            def capture_response(response: Any) -> None:
                try:
                    if not _is_json_response(response):
                        return
                    payloads.append(
                        RenderedJsonPayload(
                            str(getattr(response, "url", "") or ""),
                            response.json(),
                        )
                    )
                except Exception:
                    return

            page.on("response", capture_response)
            timeout_ms = max(1, int(timeout * 1000))
            # Some target sites keep a broken/slow script pending forever even
            # though the main document already contains the records we need.
            # Commit gives us that document; DOM readiness remains a bounded
            # best-effort wait and parsing is the correctness gate.
            page.goto(url, wait_until="commit", timeout=timeout_ms)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 5000))
            except Exception:
                pass
            if urlsplit(url).scheme.lower() == "https" and urlsplit(page.url).scheme.lower() != "https":
                raise RequestFailure(f"HTTPS页面禁止降级到HTTP：{page.url}")
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 5000))
            except Exception:
                pass
            rendered = page.content()
            return RenderedPayload(rendered, tuple(payloads), str(page.url))
        except RequestFailure:
            raise
        except Exception as exc:
            raise RequestFailure(f"浏览器渲染失败：{exc}") from exc
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

    def _ensure_browser(self) -> tuple[Any, Any]:
        state = getattr(self._local, "browser_state", None)
        if state is not None:
            return state
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RequestFailure(f"浏览器渲染不可用：{exc}") from exc
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        state = (playwright, browser)
        self._local.browser_state = state
        return state

    def _close_worker_browser(self) -> None:
        state = getattr(self._local, "browser_state", None)
        if state is None:
            return
        self._local.browser_state = None
        playwright, browser = state
        try:
            browser.close()
        finally:
            playwright.stop()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._executor.submit(self._close_worker_browser).result(timeout=10.0)
        except Exception:
            pass
        self._executor.shutdown(wait=True, cancel_futures=True)


def _request_resource_type(request: Any) -> str:
    return str(getattr(request, "resource_type", "") or "").lower()


def _route_non_content_request(route: Any) -> None:
    if _request_resource_type(getattr(route, "request", None)) in _BLOCKED_RESOURCE_TYPES:
        route.abort()
        return
    route.continue_()


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", None) or {}
    try:
        value = headers.get("content-type") or headers.get("Content-Type")
    except AttributeError:
        value = ""
    return str(value or "").lower()


def _is_json_response(response: Any) -> bool:
    content_type = _response_content_type(response)
    resource_type = _request_resource_type(getattr(response, "request", None))
    if content_type:
        return "json" in content_type or resource_type in _JSON_RESOURCE_TYPES
    return not resource_type or resource_type in _JSON_RESOURCE_TYPES

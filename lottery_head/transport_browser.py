from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable
from urllib.parse import urlsplit

from .settings import MAX_WORKERS, USER_AGENT
from .transport_types import RenderedJsonPayload, RenderedPayload, RequestFailure


class BrowserService:
    """Small persistent browser pool used only by explicitly dynamic pages."""

    def __init__(self, renderer: Callable[[str, float], Any] | None = None, max_workers: int = 2) -> None:
        self._renderer = renderer
        self._workers = max(1, min(int(max_workers), MAX_WORKERS))
        self._executor = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="lottery-head-browser")
        self._slots = threading.BoundedSemaphore(self._workers)
        self._local = threading.local()
        self._resources: list[tuple[Any, Any]] = []
        self._lock = threading.Lock()
        self._closed = False

    def render(self, url: str, timeout: float) -> RenderedPayload:
        with self._lock:
            if self._closed:
                raise RequestFailure("浏览器运行时已关闭")
        self._slots.acquire()
        try:
            future = self._executor.submit(self._render, url, max(0.1, timeout))
            try:
                return future.result(timeout=max(0.1, timeout))
            except FutureTimeoutError as exc:
                future.cancel()
                raise RequestFailure("单站总时限已用尽：浏览器渲染超时", retryable=True) from exc
        finally:
            self._slots.release()

    def _render(self, url: str, timeout: float) -> RenderedPayload:
        if self._renderer is not None:
            result = self._renderer(url, timeout)
            if isinstance(result, RenderedPayload):
                return result
            if isinstance(result, dict):
                return RenderedPayload(str(result.get("html", "")), tuple(result.get("payloads", ())))
            return RenderedPayload(str(result))
        context = None
        try:
            playwright, browser = self._ensure_browser()
            context = browser.new_context(user_agent=USER_AGENT, locale="zh-CN", ignore_https_errors=False)
            page = context.new_page()
            payloads: list[RenderedJsonPayload] = []

            def capture_response(response: Any) -> None:
                try:
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
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if urlsplit(url).scheme.lower() == "https" and urlsplit(page.url).scheme.lower() != "https":
                raise RequestFailure(f"HTTPS页面禁止降级到HTTP：{page.url}")
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 5000))
            except Exception:
                pass
            rendered = page.content()
            return RenderedPayload(rendered, tuple(payloads))
        except RequestFailure:
            raise
        except Exception as exc:
            raise RequestFailure(f"浏览器渲染失败：{exc}") from exc
        finally:
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
        with self._lock:
            self._resources.append(state)
        return state

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            resources = list(self._resources)
            self._resources.clear()
        for playwright, browser in resources:
            try:
                browser.close()
            except Exception:
                pass
            try:
                playwright.stop()
            except Exception:
                pass
        self._executor.shutdown(wait=True, cancel_futures=True)

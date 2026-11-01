from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from ..models import SiteRule, SourceDocument
from ..network import get_text
from ..transport_types import normalize_request_url
from .admin import load_admin_article_fragment_result
from .admin_render import render_dynamic_page_result, should_render_admin_article_page
from .collector_assets import collect_linked_documents
from .collector_decode import _article_id_from_url, decode_inline_gbk_decrypt_blocks, should_collect_script_fragment
from .collector_details import FIRST_THREE_PAGES_PARSE_HINT, load_period_title_detail_fragments as _load_period_title_detail_fragments
from .forum import load_forum_article_documents, load_forum_target_history_documents, load_user_forum_documents


# 首页静态脚本块滞后一期的专属解析：静态脚本取不到目标期时渲染一次 DOM 再解析。
JS_LAG_RENDER_PARSE_HINTS = frozenset({"AI斩头"})


def _readable_text_length(html: str) -> int:
    """页面主文档的可读文本长度（剔除 script/style），用于识别纯 JS 渲染页。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(("script", "style")):
        tag.decompose()
    return len(re.sub(r"\s+", "", soup.get_text()))


def load_initial_source_html(client, source_url: str, *, get_text_fn=get_text) -> str:
    if re.search(r"/article/(?:admin|manager|lottery)/", source_url):
        return ""
    return get_text_fn(client, source_url)


def collect_fragments(
    html: str,
    *,
    client: httpx.Client,
    source_url: str = "",
    include_forum_history: bool = False,
    target_period: str = "",
    target_periods: list[str] | None = None,
    content_hint: str = "",
    field: str = "",
    admin_api_url: str = "",
    parse_hint: str = "",
    site_rule: SiteRule | None = None,
) -> list[SourceDocument]:
    is_admin_article = bool(re.search(r"/article/(?:admin|manager|lottery)/", source_url))
    uses_browser_page = bool(not is_admin_article and site_rule is not None and site_rule.browser_render)
    fragments: list[SourceDocument] = [] if is_admin_article or uses_browser_page else [
        SourceDocument(html, source_url, "page")
    ]
    inline_blocks = decode_inline_gbk_decrypt_blocks(html)
    if not is_admin_article and not uses_browser_page:
        fragments.extend(
            SourceDocument(
                block,
                source_url,
                "inline_script",
                parent_url=source_url,
                source_block_id=f"inline:{index}",
            )
            for index, block in enumerate(inline_blocks)
            if block.strip()
        )
    if uses_browser_page:
        fragments.append(_load_browser_page_document(client, source_url, site_rule.browser_selector))
    if not is_admin_article and not uses_browser_page and parse_hint in {"period_title_detail", FIRST_THREE_PAGES_PARSE_HINT}:
        fragments.extend(
            load_period_title_detail_fragments(
                client,
                html,
                source_url,
                content_hint,
                field,
                periods=target_periods or ([target_period] if target_period else None),
                position=site_rule.position if site_rule else "顶部",
                max_list_pages=3 if parse_hint == FIRST_THREE_PAGES_PARSE_HINT else None,
            )
        )
    if not is_admin_article and not uses_browser_page:
        fragments.extend(
            collect_linked_documents(
                html,
                client=client,
                source_url=source_url,
                include_scripts=True,
                get_text_fn=get_text,
                script_filter_fn=should_collect_script_fragment,
            )
        )
    browser_fallback_used = False
    has_script_error = any(
        fragment.route == "resource_error"
        and str(fragment.source_block_id).startswith("script:")
        for fragment in fragments
    )
    has_target_detail = any(
        fragment.route == "period_detail"
        and target_period
        and target_period in re.sub(r"\s+", "", fragment.source)
        for fragment in fragments
    )
    page_is_script_only = (
        bool(re.search(r"<script[^>]+src=", html, re.IGNORECASE))
        and _readable_text_length(html) < 200
    )
    target_in_html = target_period in re.sub(r"\s+", "", html)
    detail_missing = (
        parse_hint in {"period_title_detail", FIRST_THREE_PAGES_PARSE_HINT}
        and not has_target_detail
    )
    # 这类首页的静态脚本块会滞后一期，只有浏览器渲染后的 DOM 才含当期行；
    # 仅纯脚本页 + 目标期不在原始 HTML 时才渲染一次，避免全站无谓开销。
    static_script_lags_target = (
        bool(target_period)
        and page_is_script_only
        and parse_hint in JS_LAG_RENDER_PARSE_HINTS
        and not target_in_html
        and not (site_rule is not None and site_rule.tls_compat)
    )
    if (
        not is_admin_article
        and not uses_browser_page
        and bool(target_period)
        and (
            (not target_in_html and has_script_error)
            or (has_script_error and detail_missing)
            or static_script_lags_target
        )
    ):
        browser_document = _load_browser_fallback_document(client, source_url)
        if browser_document is not None:
            if parse_hint in {"period_title_detail", FIRST_THREE_PAGES_PARSE_HINT}:
                detail_fragments = load_period_title_detail_fragments(
                    client,
                    browser_document.source,
                    source_url,
                    content_hint,
                    field,
                    periods=target_periods or [target_period],
                    position=site_rule.position if site_rule else "顶部",
                    max_list_pages=3 if parse_hint == FIRST_THREE_PAGES_PARSE_HINT else None,
                    detail_get_text_fn=lambda detail_client, detail_url: _load_detail_text_with_browser_fallback(
                        detail_client, detail_url, target_period
                    ),
                )
                fragments = detail_fragments or [browser_document]
            else:
                fragments = [browser_document]
            browser_fallback_used = True
    admin_article = load_admin_article_fragment_result(
        client,
        source_url,
        admin_api_url=admin_api_url,
        rule=site_rule,
        target_period=target_period,
        target_periods=target_periods,
    )
    if admin_article.error and site_rule is not None:
        raise RuntimeError(admin_article.error)
    if admin_article.text:
        fragments.append(
            SourceDocument(
                admin_article.text,
                source_url,
                "admin_api",
                record_id=admin_article.record_id or _article_id_from_url(source_url),
                record_path=admin_article.record_path,
                api_url=admin_article.source,
                title=admin_article.title,
                author=admin_article.author,
                source_block_id=f"admin:{admin_article.record_id or _article_id_from_url(source_url)}",
                source_identity=f"article:{admin_article.record_id or _article_id_from_url(source_url)}",
            )
        )
    elif admin_article.allow_browser_fallback and should_render_admin_article_page(
        source_url,
        html,
        api_status=admin_article.api_status,
        target_period=target_period,
        content_hint=content_hint,
        field=field,
    ):
        browser_article = render_dynamic_page_result(
            source_url,
            context=client,
            rule=site_rule,
            target_period=target_period,
            target_periods=target_periods,
        )
        if browser_article.error and site_rule is not None:
            raise RuntimeError(browser_article.error)
        if browser_article.text:
            fragments.append(
                SourceDocument(
                    browser_article.text,
                    source_url,
                    "admin_browser",
                    record_id=browser_article.record_id or _article_id_from_url(source_url),
                    record_path=browser_article.record_path,
                    api_url=browser_article.source,
                    title=browser_article.title,
                    author=browser_article.author,
                    source_block_id=f"admin:{browser_article.record_id or _article_id_from_url(source_url)}",
                    source_identity=f"article:{browser_article.record_id or _article_id_from_url(source_url)}",
                )
            )
    if not browser_fallback_used:
        forum_documents = load_forum_article_documents(
            client,
            source_url,
            include_history=include_forum_history,
        )
        fragments.extend(forum_documents)
        if site_rule and site_rule.parse_hint == "full_period_list":
            history_documents = load_forum_target_history_documents(
                client,
                source_url,
                site_rule,
                target_periods or ([target_period] if target_period else []),
            )
            fragments.extend(history_documents)
        user_documents = load_user_forum_documents(
            client,
            source_url,
            rule=site_rule,
            target_periods=target_periods or ([target_period] if target_period else []),
        )
        fragments.extend(user_documents)
    return _finalize_document_order(fragments)


def _load_browser_page_document(client, source_url: str, selector: str) -> SourceDocument:
    if not source_url or not hasattr(client, "render_dynamic"):
        raise RuntimeError("配置要求浏览器渲染，但浏览器渲染不可用")
    try:
        rendered = client.render_dynamic(source_url)
    except Exception as exc:
        raise RuntimeError(f"浏览器渲染失败：{exc}") from exc
    final_url = str(getattr(rendered, "url", "") or "")
    if not final_url:
        raise RuntimeError("浏览器渲染未返回最终URL")
    if normalize_request_url(final_url) != normalize_request_url(source_url):
        raise RuntimeError(f"浏览器渲染URL不匹配：{final_url}")
    rendered_html = str(getattr(rendered, "html", "") or "")
    if not rendered_html.strip():
        raise RuntimeError("浏览器渲染页面为空")
    if not selector.strip():
        raise RuntimeError("浏览器渲染缺少唯一正文选择器")
    selected = BeautifulSoup(rendered_html, "html.parser").select(selector)
    if len(selected) != 1:
        raise RuntimeError(f"浏览器渲染正文选择器未唯一命中：{selector}（命中{len(selected)}处）")
    selected_html = str(selected[0])
    parsed = urlsplit(source_url)
    topic_match = re.search(r"/topic/(\d+)\.html$", parsed.path, re.IGNORECASE)
    if not topic_match:
        raise RuntimeError("浏览器渲染topic URL缺少唯一帖子ID")
    topic_id = topic_match.group(1)
    return SourceDocument(
        selected_html,
        source_url,
        "browser_page",
        record_id=topic_id,
        record_path=parsed.path,
        parent_url=source_url,
        source_block_id=f"browser_topic:{topic_id}",
        source_identity=f"topic:{topic_id}",
    )


def _load_browser_fallback_document(client, source_url: str) -> SourceDocument | None:
    if not source_url or not hasattr(client, "render_dynamic"):
        return None
    try:
        rendered = client.render_dynamic(source_url)
    except Exception as exc:
        return SourceDocument(
            "",
            source_url,
            "resource_error",
            source_block_id=f"browser:{source_url}",
            resource_error=f"浏览器渲染失败：{exc}",
            resource_required=True,
        )
    final_url = str(getattr(rendered, "url", "") or "")
    rendered_html = str(getattr(rendered, "html", "") or "")
    if normalize_request_url(final_url) != normalize_request_url(source_url):
        return SourceDocument(
            "",
            source_url,
            "resource_error",
            source_block_id=f"browser:{source_url}",
            resource_error=f"浏览器渲染URL不匹配：{final_url}",
            resource_required=True,
        )
    if not rendered_html.strip():
        return SourceDocument(
            "",
            source_url,
            "resource_error",
            source_block_id=f"browser:{source_url}",
            resource_error="浏览器渲染页面为空",
            resource_required=True,
        )
    parsed = urlsplit(source_url)
    topic_match = re.search(r"/topic/(\d+)\.html$", parsed.path, re.IGNORECASE)
    topic_id = topic_match.group(1) if topic_match else ""
    return SourceDocument(
        rendered_html,
        source_url,
        "browser_page" if topic_id else "page",
        record_id=topic_id,
        record_path=parsed.path if topic_id else "",
        parent_url=source_url,
        source_block_id=f"browser:{topic_id or source_url}",
        source_identity=f"topic:{topic_id}" if topic_id else "",
    )


def _finalize_document_order(fragments: list[SourceDocument]) -> list[SourceDocument]:
    finalized: list[SourceDocument] = []
    for index, document in enumerate(fragments):
        document_order = document.document_order if document.document_order >= 0 else index
        source_block_id = document.source_block_id or f"{document.route}:{document.url}:{index}"
        source_list_position = document.source_list_position
        if source_list_position < 0 and document.route in {"forum", "forum_history", "user_forum"}:
            source_list_position = index
        finalized.append(
            replace(
                document,
                document_order=document_order,
                source_block_id=source_block_id,
                source_list_position=source_list_position,
            )
        )
    return finalized


def load_period_title_detail_fragments(
    client: httpx.Client,
    html: str,
    source_url: str,
    content_hint: str,
    field: str,
    periods: list[str] | None = None,
    limit: int = 12,
    position: str = "顶部",
    *,
    max_list_pages: int | None = None,
    list_items_per_page: int = 20,
    detail_get_text_fn=get_text,
) -> list[SourceDocument]:
    return _load_period_title_detail_fragments(
        client,
        html,
        source_url,
        content_hint,
        field,
        periods,
        limit,
        position,
        get_text_fn=detail_get_text_fn,
        collect_fn=collect_fragments,
        max_list_pages=max_list_pages,
        list_items_per_page=list_items_per_page,
    )


def _load_detail_text_with_browser_fallback(client, detail_url: str, target_period: str) -> str:
    try:
        detail_html = get_text(client, detail_url)
        visible_text = re.sub(r"\s+", "", BeautifulSoup(detail_html, "html.parser").get_text(" ", strip=True))
        if target_period and target_period in visible_text:
            return detail_html
    except Exception:
        pass
    rendered = client.render_dynamic(detail_url)
    final_url = str(getattr(rendered, "url", "") or "")
    if normalize_request_url(final_url) != normalize_request_url(detail_url):
        raise RuntimeError(f"浏览器渲染详情URL不匹配：{final_url}")
    return str(getattr(rendered, "html", "") or "")

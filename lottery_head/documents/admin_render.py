from __future__ import annotations

import re

from ..models import AdminArticleFragmentResult, SiteRule
from ..parsers.common import contains_text, html_to_text
from ..settings import BARE_HEAD_VALUE_RE, FOUR_COMBO_RE, HEAD_VALUE_RE
from .admin_records import admin_article_author, admin_article_text, decode_admin_value, extract_embedded_json_documents, find_admin_article_matches, is_same_origin, rendered_payload_sources, unique_admin_article_matches_with_sources, validate_admin_article_record


def should_render_admin_article_page(
    source_url: str,
    html: str,
    *,
    api_status: int | None = None,
    target_period: str = "",
    content_hint: str = "",
    field: str = "",
) -> bool:
    if not re.search(r"/article/(?:admin|manager|lottery)/", source_url):
        return False
    if api_status == 404:
        return True
    text = html_to_text(html)
    required_markers = [marker for marker in (target_period, content_hint, field) if marker]
    if required_markers and not all(contains_text(text, marker) for marker in required_markers):
        return True
    return not page_has_head_data(text)


def page_has_head_data(text: str) -> bool:
    return bool(
        HEAD_VALUE_RE.search(text)
        or BARE_HEAD_VALUE_RE.search(text)
        or FOUR_COMBO_RE.search(re.sub(r"\s+", "", text))
    )


def render_dynamic_page(
    url: str,
    *,
    context=None,
    rule: SiteRule | None = None,
    target_period: str = "",
    target_periods: list[str] | None = None,
) -> str:
    return render_dynamic_page_result(
        url,
        context=context,
        rule=rule,
        target_period=target_period,
        target_periods=target_periods,
    ).text


def render_dynamic_page_result(
    url: str,
    *,
    context=None,
    rule: SiteRule | None = None,
    target_period: str = "",
    target_periods: list[str] | None = None,
) -> AdminArticleFragmentResult:
    if context is None or not hasattr(context, "render_dynamic"):
        return AdminArticleFragmentResult("", source=url, error="浏览器渲染不可用")
    article_match = re.search(r"/article/(?:admin|manager|lottery)/([^/?#]+)", url)
    if not article_match:
        return AdminArticleFragmentResult("", source=url, error="动态详情URL缺少记录ID")
    article_id = article_match.group(1)
    try:
        rendered = context.render_dynamic(url)
    except Exception as exc:
        return AdminArticleFragmentResult("", source=url, error=f"浏览器渲染失败：{exc}")
    matches, match_error = rendered_admin_article_matches(rendered, url, article_id)
    if match_error:
        return AdminArticleFragmentResult("", source=url, error=match_error)
    for _attempt in range(3):
        if matches or not hasattr(context, "render_dynamic_fresh"):
            break
        try:
            rendered = context.render_dynamic_fresh(url)
        except Exception as exc:
            return AdminArticleFragmentResult("", source=url, error=f"浏览器重试失败：{exc}")
        matches, match_error = rendered_admin_article_matches(rendered, url, article_id)
        if match_error:
            return AdminArticleFragmentResult("", source=url, error=match_error)
    if len(matches) != 1:
        return AdminArticleFragmentResult(
            "",
            source=url,
            error="浏览器未返回唯一且匹配详情URL的目标记录",
        )
    record_path, record, response_url = matches[0]
    valid, error = validate_admin_article_record(
        record,
        rule=rule,
        target_period=target_period,
        target_periods=target_periods,
        expected_article_id=article_id,
    )
    if not valid:
        return AdminArticleFragmentResult("", source=response_url or url, error=error)
    return AdminArticleFragmentResult(
        admin_article_text(record),
        source=response_url or url,
        record_id=str(record.get("id") or article_id),
        record_path=record_path,
        title=decode_admin_value(record.get("title", "")),
        author=admin_article_author(record),
    )


def rendered_admin_article_matches(
    rendered,
    url: str,
    article_id: str,
) -> tuple[list[tuple[str, dict, str]], str]:
    payloads = rendered_payload_sources(rendered, url)
    payloads.extend(
        (url, payload)
        for payload in extract_embedded_json_documents(getattr(rendered, "html", ""))
    )
    if any(
        not is_same_origin(response_url, url)
        and find_admin_article_matches(payload, article_id)
        for response_url, payload in payloads
    ):
        return [], "浏览器响应跨域且包含详情URL目标记录，拒绝使用"
    payloads = [
        (response_url, payload)
        for response_url, payload in payloads
        if is_same_origin(response_url, url)
    ]
    matches = unique_admin_article_matches_with_sources(payloads, article_id)
    return matches, ""


def dynamic_page_cache_key(url: str, rule: SiteRule | None) -> str:
    if rule is None:
        return url
    return "|".join((url, rule.section, rule.field, rule.position, rule.content_hint))


def sync_playwright():
    from playwright.sync_api import sync_playwright as playwright_sync

    return playwright_sync()

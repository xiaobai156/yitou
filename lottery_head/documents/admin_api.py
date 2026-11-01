from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from ..models import AdminArticleFragmentResult, SiteRule
from ..network import get_json
from ..transport import RequestFailure
from .admin_records import admin_article_author, admin_article_text, decode_admin_value, find_admin_article_matches, validate_admin_article_record


JsonLoader = Callable[[object, str], object]


def _is_empty_admin_article_record(record: dict, article_id: str) -> bool:
    return (
        str(record.get("id")) == str(article_id)
        and not admin_article_text(record).strip()
    )


def load_admin_article_fragment_result(
    client: httpx.Client,
    source_url: str,
    *,
    admin_api_url: str = "",
    rule: SiteRule | None = None,
    target_period: str = "",
    target_periods: list[str] | None = None,
    json_loader: JsonLoader = get_json,
) -> AdminArticleFragmentResult:
    match = re.search(r"/article/(admin|manager|lottery)/([^/?#]+)", source_url)
    if not match:
        return AdminArticleFragmentResult("")
    article_type = match.group(1)
    article_id = match.group(2)
    parsed = urlparse(source_url)
    endpoint = {
        "admin": "manager-articles",
        "manager": "manager-articles",
        "lottery": "lottery-articles",
    }[article_type]
    api_url = admin_api_url or f"{parsed.scheme}://{parsed.netloc}/api/proxy/{endpoint}/{article_id}"
    api_status = None
    try:
        data = json_loader(client, api_url)
        api_status = 200
    except RequestFailure as exc:
        api_status = exc.status_code
        data = None
        if api_status != 404:
            return AdminArticleFragmentResult(
                "",
                api_status=api_status,
                source=api_url,
                error=str(exc),
            )
    except Exception as exc:
        return AdminArticleFragmentResult(
            "",
            api_status=api_status,
            source=api_url,
            error=f"动态接口请求失败：{exc}",
        )
    if api_status == 404:
        return AdminArticleFragmentResult(
            "",
            api_status=api_status,
            source=api_url,
            allow_browser_fallback=True,
        )
    direct_matches = find_admin_article_matches(data, article_id)
    if len(direct_matches) > 1:
        return AdminArticleFragmentResult(
            "",
            api_status=api_status,
            source=api_url,
            error=f"目标记录ID匹配到{len(direct_matches)}条，拒绝使用聚合响应",
        )
    if len(direct_matches) == 1:
        record_path, record = direct_matches[0]
        if _is_empty_admin_article_record(record, article_id):
            return AdminArticleFragmentResult(
                "",
                api_status=api_status,
                source=api_url,
                record_id=article_id,
                record_path=record_path,
                allow_browser_fallback=True,
            )
        valid, error = validate_admin_article_record(
            record,
            rule=rule,
            target_period=target_period,
            target_periods=target_periods,
            expected_article_id=article_id,
        )
        if valid:
            return AdminArticleFragmentResult(
                admin_article_text(record),
                api_status=api_status,
                source=api_url,
                record_id=article_id,
                record_path=record_path,
                title=decode_admin_value(record.get("title", "")),
                author=admin_article_author(record),
            )
        return AdminArticleFragmentResult(
            "", api_status=api_status, source=api_url, error=error
        )
    return AdminArticleFragmentResult(
        "",
        api_status=api_status,
        source=api_url,
        error="专属接口未返回唯一目标记录，禁止浏览器兜底",
    )

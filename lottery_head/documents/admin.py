from __future__ import annotations

import httpx

from ..models import AdminArticleFragmentResult, SiteRule
from ..network import get_json
from .admin_api import load_admin_article_fragment_result as _load_admin_article_fragment_result


def load_admin_article_fragment(client: httpx.Client, source_url: str) -> str:
    return load_admin_article_fragment_result(client, source_url).text


def load_admin_article_fragment_result(
    client: httpx.Client,
    source_url: str,
    *,
    admin_api_url: str = "",
    rule: SiteRule | None = None,
    target_period: str = "",
    target_periods: list[str] | None = None,
) -> AdminArticleFragmentResult:
    return _load_admin_article_fragment_result(
        client,
        source_url,
        admin_api_url=admin_api_url,
        rule=rule,
        target_period=target_period,
        target_periods=target_periods,
        json_loader=get_json,
    )





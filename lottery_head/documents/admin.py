from __future__ import annotations

import httpx

from ..models import AdminArticleFragmentResult, SiteRule
from ..network import get_json
from ..transport import RequestFailure
from .admin_api import landing_page_data_api_url, load_admin_article_fragment_result as _load_admin_article_fragment_result, load_admin_article_from_landing_page_data as _load_admin_article_from_landing_page_data, load_admin_article_matches_from_landing_page_data as _load_admin_article_matches_from_landing_page_data
from .admin_records import admin_article_author, admin_article_text, admin_identity_markers, decode_admin_value, extract_embedded_json_documents, find_admin_article, find_admin_article_matches, is_admin_article_payload, is_same_origin, rendered_payload_sources, unique_admin_article_matches, unique_admin_article_matches_with_sources, validate_admin_article_record, validate_admin_article_text
from .admin_render import dynamic_page_cache_key, page_has_head_data, render_dynamic_page, render_dynamic_page_result, rendered_admin_article_matches, should_render_admin_article_page, sync_playwright


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
        landing_matches_loader=load_admin_article_matches_from_landing_page_data,
    )


def load_admin_article_from_landing_page_data(client: httpx.Client, parsed, article_id: str) -> dict | None:
    return _load_admin_article_from_landing_page_data(
        client,
        parsed,
        article_id,
        json_loader=get_json,
        matches_loader=load_admin_article_matches_from_landing_page_data,
    )


def load_admin_article_matches_from_landing_page_data(
    client: httpx.Client, parsed, article_id: str
) -> list[tuple[str, dict]] | None:
    return _load_admin_article_matches_from_landing_page_data(
        client,
        parsed,
        article_id,
        json_loader=get_json,
    )





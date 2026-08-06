from __future__ import annotations

import re
from dataclasses import replace

import httpx

from ..models import SiteRule, SourceDocument
from ..network import get_text
from .admin import load_admin_article_fragment_result, render_dynamic_page_result, should_render_admin_article_page
from .collector_assets import collect_linked_documents
from .collector_decode import _article_id_from_url, _forum_id_from_url, decode_inline_gbk_decrypt_blocks, decode_inline_gbk_decrypt_calls, decode_script_document_writes, should_collect_script_fragment
from .collector_details import FIRST_THREE_PAGES_PARSE_HINT, load_period_title_detail_fragments as _load_period_title_detail_fragments
from .forum import load_forum_article_documents, load_forum_article_fragments, load_forum_target_history_documents, load_forum_target_history_fragments, load_user_forum_documents, load_user_forum_fragments


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
    fragments: list[SourceDocument] = [] if is_admin_article else [
        SourceDocument(html, source_url, "page")
    ]
    inline_blocks = decode_inline_gbk_decrypt_blocks(html)
    if not is_admin_article and not inline_blocks:
        inline_decoded = decode_inline_gbk_decrypt_calls(html)
        inline_blocks = [inline_decoded] if inline_decoded.strip() else []
    if not is_admin_article:
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
    if not is_admin_article and parse_hint in {"period_title_detail", FIRST_THREE_PAGES_PARSE_HINT}:
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
    fragments.extend(
        collect_linked_documents(
            html,
            client=client,
            source_url=source_url,
            include_scripts=not is_admin_article,
            get_text_fn=get_text,
            script_filter_fn=should_collect_script_fragment,
            decode_script_fn=decode_script_document_writes,
        )
    )
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
    forum_record_id = _forum_id_from_url(source_url)
    forum_documents = load_forum_article_documents(
        client,
        source_url,
        include_history=include_forum_history,
    )
    if forum_documents:
        fragments.extend(forum_documents)
    else:
        fragments.extend(
            SourceDocument(
                fragment,
                source_url,
                "forum",
                record_id=forum_record_id,
                source_block_id=f"forum:{forum_record_id}:{index}",
                source_identity=f"forum:{forum_record_id}",
                source_list_position=index,
            )
            for index, fragment in enumerate(
                load_forum_article_fragments(client, source_url, include_history=include_forum_history)
            )
        )
    if site_rule and site_rule.parse_hint == "full_period_list":
        history_documents = load_forum_target_history_documents(
            client,
            source_url,
            site_rule,
            target_periods or ([target_period] if target_period else []),
        )
        if history_documents:
            fragments.extend(history_documents)
        elif not _forum_id_from_url(source_url):
            fragments.extend(
                SourceDocument(
                    fragment,
                    source_url,
                    "forum_history",
                    record_id=forum_record_id,
                    source_block_id=f"forum_history:{forum_record_id}:{index}",
                    source_identity=f"forum:{forum_record_id}",
                    source_list_position=index,
                )
                for index, fragment in enumerate(
                    load_forum_target_history_fragments(
                        client,
                        source_url,
                        site_rule,
                        target_periods or ([target_period] if target_period else []),
                    )
                )
            )
    user_documents = load_user_forum_documents(
        client,
        source_url,
        rule=site_rule,
        target_periods=target_periods or ([target_period] if target_period else []),
    )
    if user_documents:
        fragments.extend(user_documents)
    elif not re.search(r"/users/\d+", source_url):
        fragments.extend(
            SourceDocument(
                fragment,
                source_url,
                "user_forum",
                source_block_id=f"user_forum:{index}",
                source_list_position=index,
            )
            for index, fragment in enumerate(
                load_user_forum_fragments(
                    client,
                    source_url,
                    rule=site_rule,
                    target_periods=target_periods or ([target_period] if target_period else []),
                )
            )
        )
    return _finalize_document_order(fragments)


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
        get_text_fn=get_text,
        collect_fn=collect_fragments,
        max_list_pages=max_list_pages,
        list_items_per_page=list_items_per_page,
    )

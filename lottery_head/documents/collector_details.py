from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import SourceDocument
from ..network import get_text
from ..parsers.common import contains_text, period_matches
from ..settings import PERIOD_RE


FIRST_THREE_PAGES_PARSE_HINT = "period_title_detail_first_three_pages"


def load_period_title_detail_fragments(
    client,
    html: str,
    source_url: str,
    content_hint: str,
    field: str,
    periods: list[str] | None = None,
    limit: int = 12,
    position: str = "顶部",
    *,
    get_text_fn=get_text,
    collect_fn=None,
    max_list_pages: int | None = None,
    list_items_per_page: int = 20,
) -> list[SourceDocument]:
    if not source_url or not content_hint or not field:
        return []
    if collect_fn is None:
        from .collector import collect_fragments as collect_fn
    soup = BeautifulSoup(html, "html.parser")
    indexed_links: list[tuple[int, object]] = []
    if max_list_pages is not None:
        if max_list_pages <= 0 or list_items_per_page <= 0:
            return []
        list_items = soup.select(".title_list22_item")
        if not list_items:
            return []
        for item_index, item in enumerate(list_items[: max_list_pages * list_items_per_page]):
            indexed_links.extend((item_index, link) for link in item.find_all("a", href=True))
    else:
        indexed_links = list(enumerate(soup.find_all("a", href=True)))
    detail_links = []
    seen = set()
    for list_position, link in indexed_links:
        title = link.get_text(" ", strip=True)
        period_match = PERIOD_RE.search(title)
        if not period_match:
            continue
        if not contains_text(title, content_hint) or not contains_text(title, field):
            continue
        if (
            max_list_pages is not None
            and periods
            and not any(period_matches(period_match.group(1), period) for period in periods)
        ):
            continue
        detail_url = urljoin(source_url, link["href"])
        if detail_url in seen:
            continue
        seen.add(detail_url)
        detail_links.append((list_position, detail_url, title, period_match.group(1)))
    if max_list_pages is None:
        if position.strip().lower() in {"bottom", "尾部", "底部", "下"}:
            detail_links = detail_links[-1:]
        else:
            detail_links = detail_links[:1]
        if periods:
            detail_links = [
                item
                for item in detail_links
                if any(period_matches(item[3], period) for period in periods)
            ]
        detail_links = detail_links[:max(limit, 0)]
    else:
        detail_links = detail_links[: max_list_pages * list_items_per_page]
    fragments: list[SourceDocument] = []
    for list_position, detail_url, title, _period in detail_links:
        try:
            detail_html = get_text_fn(client, detail_url)
        except Exception as exc:
            if max_list_pages is not None:
                raise RuntimeError(f"目标详情请求失败：{detail_url}：{exc}") from exc
            continue
        nested = collect_fn(
            detail_html,
            client=client,
            source_url=detail_url,
            include_forum_history=False,
        )
        fragments.extend(
            SourceDocument(
                fragment.source,
                fragment.url,
                "period_detail" if fragment.route == "page" else fragment.route,
                record_id=fragment.record_id,
                record_path=fragment.record_path,
                api_url=fragment.api_url,
                title=title,
                author=fragment.author,
                parent_url=source_url,
                linked_urls=(detail_url,),
                document_order=list_position,
                source_block_id=fragment.source_block_id or f"detail:{detail_url}",
                source_identity=fragment.source_identity,
                user_id=fragment.user_id,
                forum_id=fragment.forum_id,
                source_list_position=list_position,
                resource_error=fragment.resource_error,
                resource_required=fragment.resource_required,
            )
            for fragment in nested
        )
    return fragments

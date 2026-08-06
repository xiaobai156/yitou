from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from ..network import get_json
from ..models import SiteRule, SourceDocument
from ..parsers.common import canonical_text, contains_text, html_to_text, period_matches
from ..selection import is_bottom_position
from ..settings import PERIOD_RE


def load_forum_article_fragment(client: httpx.Client, source_url: str) -> str:
    return "\n".join(load_forum_article_fragments(client, source_url))


def load_user_forum_fragments(
    client: httpx.Client,
    source_url: str,
    *,
    rule: SiteRule | None = None,
    target_periods: list[str] | None = None,
) -> list[str]:
    documents = load_user_forum_documents(
        client,
        source_url,
        rule=rule,
        target_periods=target_periods,
    )
    if not documents:
        return []
    return [
        "\n".join(part for part in (document.author, document.title, document.source) if part)
        for document in documents
    ]


def load_user_forum_documents(
    client: httpx.Client,
    source_url: str,
    *,
    rule: SiteRule | None = None,
    target_periods: list[str] | None = None,
) -> list[SourceDocument]:
    if rule is None or rule.parse_hint != "user_kill_head":
        return []
    parsed = urlparse(source_url)
    match = re.search(r"/users/(\d+)", parsed.fragment)
    if not match:
        return []
    user_id = match.group(1)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    user = get_json(client, f"{base_url}/api/v1/users/{user_id}")
    if not isinstance(user, dict) or str(user.get("id")) != user_id:
        raise RuntimeError("用户接口ID与URL不一致")
    nickname = str(user.get("nickname") or "")
    if rule.content_hint and not contains_text(nickname, rule.content_hint):
        raise RuntimeError("用户作者与配置锚点不一致")
    forums = get_json(client, f"{base_url}/api/v1/users/{user_id}/forums")
    if not isinstance(forums, list):
        raise RuntimeError("用户文章聚合接口格式无效")
    wanted_periods = list(dict.fromkeys(period for period in (target_periods or []) if period))
    if not wanted_periods:
        return []
    matching = []
    seen_ids: set[str] = set()
    forums_api_url = f"{base_url}/api/v1/users/{user_id}/forums"
    for list_position, forum in enumerate(forums):
        if not isinstance(forum, dict):
            continue
        topic = str(forum.get("topic") or "")
        if str(forum.get("user_id")) != user_id or normalize_user_forum_topic(topic) != normalize_user_forum_topic(rule.field):
            continue
        content = forum.get("content") if isinstance(forum.get("content"), str) else ""
        if not content:
            continue
        forum_id = str(forum.get("id") or "")
        if not forum_id:
            found_periods = PERIOD_RE.findall(html_to_text(content))
            if any(
                period_matches(str(forum.get("draw") or ""), wanted)
                or any(period_matches(found, wanted) for found in found_periods)
                for wanted in wanted_periods
            ):
                raise RuntimeError("用户文章聚合目标记录缺少帖子ID")
            matching.append((list_position, forum))
            continue
        if forum_id in seen_ids:
            raise RuntimeError(f"用户文章聚合中目标记录ID重复：{forum_id}")
        seen_ids.add(forum_id)
        matching.append((list_position, forum))
    for wanted in wanted_periods:
        matching_ids = {
            str(forum.get("id"))
            for _, forum in matching
            if forum.get("id") and period_matches(str(forum.get("draw") or ""), wanted)
        }
        if len(matching_ids) > 1:
            raise RuntimeError(f"用户聚合中{wanted}同栏目目标记录不唯一")
    window = matching[-1:] if is_bottom_position(rule.position) else matching[:1]
    selected = []
    selected_period_ids: dict[str, str] = {}
    for list_position, forum in window:
        content = forum.get("content") if isinstance(forum.get("content"), str) else ""
        found_periods = PERIOD_RE.findall(html_to_text(content))
        matching_periods = [
            wanted
            for wanted in wanted_periods
            if period_matches(str(forum.get("draw") or ""), wanted)
        ]
        if not matching_periods:
            continue
        for wanted in matching_periods:
            if not any(period_matches(found, wanted) for found in found_periods):
                raise RuntimeError(f"用户聚合{wanted}正文未包含目标期数")
            existing_id = selected_period_ids.get(wanted)
            if existing_id and existing_id != str(forum.get("id")):
                raise RuntimeError(f"用户聚合中{wanted}同栏目目标记录不唯一")
            selected_period_ids[wanted] = str(forum.get("id"))
        if matching_periods:
            selected.append((list_position, forum))
    matching = selected
    return [
        SourceDocument(
            forum.get("content") or "",
            source_url,
            "user_forum",
            record_id=str(forum.get("id") or ""),
            record_path=f"$[{list_position}]",
            api_url=forums_api_url,
            title=str(forum.get("topic") or ""),
            author=nickname,
            source_block_id=f"user:{user_id}:forum:{forum.get('id')}",
            source_identity=f"user:{user_id}:forum:{forum.get('id')}",
            user_id=user_id,
            forum_id=str(forum.get("id") or ""),
            source_list_position=list_position,
            document_order=list_position,
        )
        for list_position, forum in matching
    ]


def load_forum_article_documents(
    client: httpx.Client,
    source_url: str,
    *,
    include_current: bool = True,
    include_history: bool = False,
) -> list[SourceDocument]:
    parsed = urlparse(source_url)
    match = re.search(r"/forums/(\d+)", parsed.fragment)
    if not match:
        return []
    current_id = match.group(1)
    api_url = forum_api_url(parsed, current_id)
    try:
        current = get_json(client, api_url)
    except Exception as exc:
        return [
            SourceDocument(
                "",
                source_url,
                "resource_error",
                api_url=api_url,
                source_block_id=f"forum:{current_id}",
                resource_error=f"论坛详情接口请求失败：{exc}",
                resource_required=True,
            )
        ]
    if not isinstance(current, dict) or str(current.get("id")) != current_id:
        return [
            SourceDocument(
                "",
                source_url,
                "resource_error",
                api_url=api_url,
                source_block_id=f"forum:{current_id}",
                resource_error="论坛详情接口未返回与URL一致的目标记录",
                resource_required=True,
            )
        ]
    documents: list[SourceDocument] = []
    if include_current:
        documents.append(_forum_source_document(current, source_url, api_url, "forum", 0))
    if include_history:
        for list_position, detail in _load_forum_history_records(client, parsed, current):
            documents.append(
                _forum_source_document(
                    detail,
                    source_url,
                    forum_api_url(parsed, detail["id"]),
                    "forum_history",
                    list_position,
                    document_order=list_position + 1,
                )
            )
    return [document for document in documents if document.source.strip()]


def _forum_source_document(
    data: dict,
    source_url: str,
    api_url: str,
    route: str,
    list_position: int,
    *,
    document_order: int | None = None,
) -> SourceDocument:
    record_id = str(data.get("id") or "")
    user_id = str(data.get("user_id") or "")
    identity = f"user:{user_id}:forum:{record_id}" if user_id else f"forum:{record_id}"
    return SourceDocument(
        str(data.get("content") or ""),
        source_url,
        route,
        record_id=record_id,
        record_path="$",
        api_url=api_url,
        title="\n".join(part for part in (str(data.get("topic") or ""), str(data.get("sub_topic") or "")) if part),
        author=user_id,
        source_block_id=identity,
        source_identity=identity,
        user_id=user_id,
        forum_id=record_id,
        source_list_position=list_position,
        document_order=list_position if document_order is None else document_order,
    )


def _load_forum_history_records(client, parsed, current: dict) -> list[tuple[int, dict]]:
    user_id = current.get("user_id")
    sub_topic = current.get("sub_topic")
    topic = current.get("topic")
    if not user_id or not sub_topic:
        return []
    history_items = []
    for species in ("references", "forums"):
        try:
            data = get_json(client, f"{parsed.scheme}://{parsed.netloc}/api/v1/users/{user_id}/{species}/history")
        except Exception:
            continue
        if isinstance(data, list):
            history_items = data
            break
    matching_items = [
        (index, item)
        for index, item in enumerate(history_items)
        if isinstance(item, dict)
        and item.get("id")
        and item.get("id") != current.get("id")
        and item.get("sub_topic") == sub_topic
        and (not topic or item.get("topic") == topic)
    ]
    matching_items.sort(key=lambda item: int(item[1].get("draw") or 0), reverse=True)
    records = []
    for list_position, item in matching_items[:1]:
        try:
            detail = get_json(client, forum_api_url(parsed, item["id"]))
        except Exception:
            continue
        if (
            isinstance(detail, dict)
            and str(detail.get("id")) == str(item["id"])
            and str(detail.get("user_id")) == str(user_id)
            and str(detail.get("sub_topic")) == str(sub_topic)
            and (not topic or str(detail.get("topic")) == str(topic))
        ):
            records.append((list_position, detail))
    return records


def normalize_user_forum_topic(value: str) -> str:
    text = canonical_text(value)
    text = re.sub(r"^\d{2,3}期[:：]?", "", text)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff①④]+", "", text)


def load_forum_article_fragments(
    client: httpx.Client,
    source_url: str,
    *,
    include_current: bool = True,
    include_history: bool = False,
) -> list[str]:
    parsed = urlparse(source_url)
    match = re.search(r"/forums/(\d+)", parsed.fragment)
    if not match:
        return []
    api_url = forum_api_url(parsed, match.group(1))
    try:
        data = get_json(client, api_url)
    except Exception:
        return []
    if not isinstance(data, dict) or str(data.get("id")) != str(match.group(1)):
        return []
    fragments = []
    if include_current:
        fragments.append("\n".join(forum_article_parts(data)))
    if include_history:
        fragments.extend(load_forum_history_fragments(client, parsed, data))
    return [fragment for fragment in fragments if fragment.strip()]


def forum_api_url(parsed, forum_id: int | str) -> str:
    return f"{parsed.scheme}://{parsed.netloc}/api/v1/forums/{forum_id}"


def forum_article_parts(data: dict) -> list[str]:
    parts = []
    for key in ("topic", "sub_topic", "content"):
        value = data.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return parts


def load_forum_history_fragments(client: httpx.Client, parsed, current: dict) -> list[str]:
    user_id = current.get("user_id")
    sub_topic = current.get("sub_topic")
    topic = current.get("topic")
    if not user_id or not sub_topic:
        return []
    history_items = []
    for species in ("references", "forums"):
        history_url = f"{parsed.scheme}://{parsed.netloc}/api/v1/users/{user_id}/{species}/history"
        try:
            data = get_json(client, history_url)
        except Exception:
            continue
        if isinstance(data, list):
            history_items = data
            break
    matching_items = [
        item
        for item in history_items
        if item.get("id")
        and item.get("id") != current.get("id")
        and item.get("sub_topic") == sub_topic
        and (not topic or item.get("topic") == topic)
    ]
    matching_items.sort(key=lambda item: int(item.get("draw") or 0), reverse=True)
    fragments = []
    for item in matching_items[:1]:
        try:
            detail = get_json(client, forum_api_url(parsed, item["id"]))
        except Exception:
            continue
        fragment = "\n".join(forum_article_parts(detail))
        if fragment.strip():
            fragments.append(fragment)
    return fragments


def load_forum_target_history_fragments(
    client: httpx.Client,
    source_url: str,
    rule: SiteRule,
    target_periods: list[str],
) -> list[str]:
    if not target_periods:
        return []
    parsed = urlparse(source_url)
    match = re.search(r"/forums/(\d+)", parsed.fragment)
    if not match:
        return []
    current = get_json(client, forum_api_url(parsed, match.group(1)))
    if not isinstance(current, dict) or str(current.get("id")) != match.group(1):
        raise RuntimeError("论坛当前记录ID与URL不一致")
    user_id = str(current.get("user_id") or "")
    topic = str(current.get("topic") or "")
    sub_topic = str(current.get("sub_topic") or "")
    anchor_text = "\n".join(forum_article_parts(current))
    if not user_id or sub_topic != rule.field:
        raise RuntimeError("论坛历史记录栏目锚点与配置不一致")
    if rule.content_hint and not contains_text(anchor_text, rule.content_hint):
        raise RuntimeError("论坛历史记录站名锚点与配置不一致")
    history_items = []
    for species in ("references", "forums"):
        try:
            data = get_json(client, f"{parsed.scheme}://{parsed.netloc}/api/v1/users/{user_id}/{species}/history")
        except Exception:
            continue
        if isinstance(data, list) and data:
            history_items = data
            break
    fragments = []
    for wanted in list(dict.fromkeys(target_periods)):
        candidates = [
            item
            for item in history_items
            if isinstance(item, dict)
            and str(item.get("user_id")) == user_id
            and str(item.get("topic")) == topic
            and str(item.get("sub_topic")) == sub_topic
            and str(item.get("id")) != match.group(1)
            and period_matches(str(item.get("draw") or ""), wanted)
        ]
        if len(candidates) > 1:
            raise RuntimeError(f"论坛历史{wanted}存在多个同栏目目标记录")
        if not candidates:
            continue
        detail = get_json(client, forum_api_url(parsed, candidates[0]["id"]))
        if not isinstance(detail, dict) or str(detail.get("id")) != str(candidates[0]["id"]):
            raise RuntimeError(f"论坛历史{wanted}记录ID校验失败")
        if (
            str(detail.get("user_id")) != user_id
            or str(detail.get("topic")) != topic
            or str(detail.get("sub_topic")) != sub_topic
        ):
            raise RuntimeError(f"论坛历史{wanted}记录边界校验失败")
        content = detail.get("content") if isinstance(detail.get("content"), str) else ""
        if not any(period_matches(found, wanted) for found in PERIOD_RE.findall(html_to_text(content))):
            raise RuntimeError(f"论坛历史{wanted}正文未包含目标期数")
        fragments.append("\n".join(forum_article_parts(detail)))
    return fragments


def load_forum_target_history_documents(
    client: httpx.Client,
    source_url: str,
    rule: SiteRule,
    target_periods: list[str],
) -> list[SourceDocument]:
    if not target_periods:
        return []
    parsed = urlparse(source_url)
    match = re.search(r"/forums/(\d+)", parsed.fragment)
    if not match:
        return []
    current_id = match.group(1)
    current = get_json(client, forum_api_url(parsed, current_id))
    if not isinstance(current, dict) or str(current.get("id")) != current_id:
        raise RuntimeError("论坛当前记录ID与URL不一致")
    user_id = str(current.get("user_id") or "")
    topic = str(current.get("topic") or "")
    sub_topic = str(current.get("sub_topic") or "")
    anchor_text = "\n".join(forum_article_parts(current))
    if not user_id or sub_topic != rule.field:
        raise RuntimeError("论坛历史记录栏目锚点与配置不一致")
    if rule.content_hint and not contains_text(anchor_text, rule.content_hint):
        raise RuntimeError("论坛历史记录站名锚点与配置不一致")
    history_items = []
    history_errors = []
    for species in ("references", "forums"):
        try:
            data = get_json(client, f"{parsed.scheme}://{parsed.netloc}/api/v1/users/{user_id}/{species}/history")
        except Exception as exc:
            history_errors.append(f"{species}:{exc}")
            continue
        if isinstance(data, list) and data:
            history_items = data
            break
    if not history_items and history_errors:
        raise RuntimeError(f"论坛历史资源不完整：{'；'.join(history_errors)}")
    matching_items = [
        (index, item)
        for index, item in enumerate(history_items)
        if isinstance(item, dict)
        and item.get("id")
        and str(item.get("user_id")) == user_id
        and str(item.get("topic")) == topic
        and str(item.get("sub_topic")) == sub_topic
        and str(item.get("id")) != current_id
    ]
    wanted_periods = list(dict.fromkeys(target_periods))
    for wanted in wanted_periods:
        matching_ids = {
            str(item.get("id"))
            for _, item in matching_items
            if period_matches(str(item.get("draw") or ""), wanted)
        }
        if len(matching_ids) > 1:
            raise RuntimeError(f"论坛历史{wanted}存在多个同栏目目标记录")
    window = matching_items[-1:] if is_bottom_position(rule.position) else matching_items[:1]
    documents: list[SourceDocument] = []
    selected_period_ids: dict[str, str] = {}
    for list_position, candidate in window:
        candidate_periods = [
            wanted
            for wanted in wanted_periods
            if period_matches(str(candidate.get("draw") or ""), wanted)
        ]
        if not candidate_periods:
            continue
        detail = get_json(client, forum_api_url(parsed, candidate["id"]))
        if not isinstance(detail, dict) or str(detail.get("id")) != str(candidate["id"]):
            raise RuntimeError(f"论坛历史{candidate.get('draw', '')}记录ID校验失败")
        if (
            str(detail.get("user_id")) != user_id
            or str(detail.get("topic")) != topic
            or str(detail.get("sub_topic")) != sub_topic
        ):
            raise RuntimeError(f"论坛历史{candidate.get('draw', '')}记录边界校验失败")
        content = detail.get("content") if isinstance(detail.get("content"), str) else ""
        found_periods = PERIOD_RE.findall(html_to_text(content))
        for wanted in candidate_periods:
            if not any(period_matches(found, wanted) for found in found_periods):
                raise RuntimeError(f"论坛历史{wanted}正文未包含目标期数")
            existing_id = selected_period_ids.get(wanted)
            if existing_id and existing_id != str(detail["id"]):
                raise RuntimeError(f"论坛历史{wanted}存在多个同栏目目标记录")
            selected_period_ids[wanted] = str(detail["id"])
        documents.append(
            _forum_source_document(
                detail,
                source_url,
                forum_api_url(parsed, detail["id"]),
                "forum_history",
                list_position,
                document_order=list_position + 1,
            )
        )
    return documents

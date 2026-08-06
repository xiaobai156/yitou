from __future__ import annotations

import base64
import json
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..models import SiteRule
from ..parsers.common import contains_text, period_matches
from ..selection import is_bottom_position
from ..settings import PERIOD_RE


def is_admin_article_payload(data, article_id: str) -> bool:
    return (
        isinstance(data, dict)
        and str(data.get("id")) == str(article_id)
        and isinstance(data.get("title"), str)
        and bool(data.get("title"))
        and isinstance(data.get("html"), str)
        and bool(data.get("html"))
    )


def find_admin_article_matches(data, article_id: str) -> list[tuple[str, dict]]:
    matches: list[tuple[str, dict]] = []

    def walk(value, path: str) -> None:
        if isinstance(value, dict):
            if str(value.get("id")) == str(article_id):
                matches.append((path, value))
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(data, "$")
    return matches


def unique_admin_article_matches(data_items: list[object], article_id: str) -> list[tuple[str, dict]]:
    return [
        (path, record)
        for path, record, _source in unique_admin_article_matches_with_sources(
            [("", item) for item in data_items],
            article_id,
        )
    ]


def rendered_payload_sources(rendered, fallback_url: str) -> list[tuple[str, object]]:
    payloads: list[tuple[str, object]] = []
    for payload in getattr(rendered, "payloads", ()):
        response_url = str(getattr(payload, "url", "") or fallback_url)
        value = getattr(payload, "value", payload)
        payloads.append((response_url, value))
    return payloads


def is_same_origin(left_url: str, right_url: str) -> bool:
    left = urlparse(left_url)
    right = urlparse(right_url)
    if not left.scheme or not left.hostname or not right.scheme or not right.hostname:
        return False
    left_port = left.port or (443 if left.scheme.lower() == "https" else 80)
    right_port = right.port or (443 if right.scheme.lower() == "https" else 80)
    return (
        left.scheme.lower(), left.hostname.lower(), left_port
    ) == (
        right.scheme.lower(), right.hostname.lower(), right_port
    )


def unique_admin_article_matches_with_sources(
    data_items: list[tuple[str, object]], article_id: str
) -> list[tuple[str, dict, str]]:
    matches: list[tuple[str, dict, str]] = []
    for index, (source_url, data) in enumerate(data_items):
        for path, record in find_admin_article_matches(data, article_id):
            if not is_admin_article_payload(record, article_id):
                continue
            matches.append((f"payload[{index}]{path}", record, source_url))
    return matches


def find_admin_article(data, article_id: str) -> dict | None:
    matches = find_admin_article_matches(data, article_id)
    return matches[0][1] if len(matches) == 1 else None


def decode_admin_value(value: str) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except Exception:
        return value
    return decoded if decoded else value


def admin_article_author(data: dict) -> str:
    return decode_admin_value(data.get("authorNickname") or data.get("author") or "")


def validate_admin_article_record(
    data: dict,
    *,
    rule: SiteRule | None,
    target_period: str,
    target_periods: list[str] | None,
    expected_article_id: str = "",
) -> tuple[bool, str]:
    if not is_admin_article_payload(data, str(data.get("id"))):
        return False, "目标记录缺少同一对象的标题或正文"
    if expected_article_id and str(data.get("id")) != str(expected_article_id):
        return False, "目标记录ID与详情URL不一致"
    title = decode_admin_value(data.get("title", ""))
    author = admin_article_author(data)
    body = decode_admin_value(data.get("html", ""))
    if rule is None:
        return True, ""
    identity_markers = admin_identity_markers(rule)
    identity_text = "\n".join(part for part in (title, author, body) if part)
    if identity_markers and not any(contains_text(identity_text, marker) for marker in identity_markers):
        return False, "目标记录未同时命中站名锚点"
    if not author:
        return False, "目标记录缺少作者，无法完成身份校验"
    if author and identity_markers and not any(contains_text(author, marker) for marker in identity_markers):
        return False, "目标记录作者与站名锚点不一致"
    if rule.field and not any(contains_text(part, rule.field) for part in (title, body)):
        return False, "目标记录未命中指定栏目字段"
    wanted_periods = [target_period] if target_period else list(target_periods or [])
    if wanted_periods and not any(
        any(period_matches(found, wanted) for found in PERIOD_RE.findall(body))
        for wanted in wanted_periods
    ):
        return False, "目标记录未命中指定期数"
    expected_bottom = is_bottom_position(rule.position)
    for key in ("position", "region", "direction"):
        value = data.get(key)
        if not value:
            continue
        if is_bottom_position(str(value)) != expected_bottom:
            return False, "目标记录方向与配置不一致"
    return True, ""


def validate_admin_article_text(
    text: str,
    *,
    rule: SiteRule | None,
    target_period: str,
    target_periods: list[str] | None,
) -> tuple[bool, str]:
    if not text.strip():
        return False, "浏览器未返回目标记录"
    if rule is None:
        return True, ""
    identity_markers = admin_identity_markers(rule)
    if identity_markers and not any(contains_text(text, marker) for marker in identity_markers):
        return False, "浏览器结果未命中站名锚点"
    if rule.field and not contains_text(text, rule.field):
        return False, "浏览器结果未命中指定栏目字段"
    wanted_periods = [target_period] if target_period else list(target_periods or [])
    if wanted_periods and not any(
        any(period_matches(found, wanted) for found in PERIOD_RE.findall(text))
        for wanted in wanted_periods
    ):
        return False, "浏览器结果未命中指定期数"
    return True, ""


def admin_identity_markers(rule: SiteRule) -> list[str]:
    markers = [rule.content_hint]
    if rule.section and rule.section not in markers:
        markers.extend((rule.section, rule.section.split("-", 1)[0]))
    return [marker for marker in markers if marker]


def extract_embedded_json_documents(rendered_html: str) -> list[object]:
    documents = []
    soup = BeautifulSoup(rendered_html or "", "html.parser")
    for script in soup.find_all("script"):
        content = script.string or script.get_text()
        if not content:
            continue
        content = content.strip()
        if script.get("type", "").lower() != "application/json" and not content.startswith(("{", "[")):
            continue
        try:
            documents.append(json.loads(content))
        except Exception:
            continue
    return documents


def admin_article_text(data: dict) -> str:
    value = data.get("html")
    return decode_admin_value(value) if isinstance(value, str) else ""

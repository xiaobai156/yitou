from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


from .models import SiteRule
from .parsers.dispatch import has_dedicated_parser
from .parsers.registry import KNOWN_PARSE_HINTS
from .settings import SITES_PATH


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"URL无效：{value}")
    host = parsed.hostname.lower()
    port = parsed.port
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    netloc = host if port is None or port == default_port else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def canonical_source_url(value: str) -> str:
    """Normalize a source URL while retaining SPA/user identity fragments."""
    parsed = urlsplit(value.strip())
    base = canonical_url(value)
    return f"{base}#{parsed.fragment}" if parsed.fragment else base


def source_record_identity(value: str) -> tuple[str, ...] | None:
    parsed = urlsplit(value.strip())
    candidates = (
        ("article", r"/article/(?:admin|manager|lottery)/([^/?#]+)", parsed.path),
        ("topic", r"/topic/(\d+)(?:\.html)?$", parsed.path),
        ("article_content", r"/article/ar_content/id/(\d+)/tid/(\d+)(?:\.html)?$", parsed.path.lower()),
        ("user", r"/users/(\d+)", parsed.fragment),
        ("forum", r"/forums/(\d+)", parsed.fragment),
    )
    for kind, pattern, source in candidates:
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            return (kind, *match.groups())
    return None


def rule_identity(rule: SiteRule) -> tuple[str, str, str, str]:
    return (rule.section.strip(), canonical_url(rule.url), normalize_position(rule.position), rule.parse_hint.strip())


def normalize_position(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"top", "顶部", "上"}:
        return "top"
    if normalized in {"bottom", "尾部", "底部", "下"}:
        return "bottom"
    raise ValueError(f"抓取方向无效：{value}")


def validate_rules(rules: list[SiteRule]) -> None:
    identities: dict[tuple[str, str, str, str], SiteRule] = {}
    for rule in rules:
        label = rule.section or rule.url or "未知目录"
        if not rule.section.strip():
            raise ValueError(f"{label}缺少专属站点名称锚点")
        if not rule.field.strip() or not rule.url.strip():
            raise ValueError(f"{label}缺少字段或URL")
        normalize_position(rule.position)
        if not rule.parse_hint.strip():
            raise ValueError(f"{label}缺少专属解析")
        if rule.parse_hint not in KNOWN_PARSE_HINTS:
            raise ValueError(f"{label}专属解析未注册：{rule.parse_hint}")
        if not has_dedicated_parser(rule.parse_hint):
            raise ValueError(f"{label}专属解析未绑定实现：{rule.parse_hint}")
        if rule.browser_render and not rule.browser_selector:
            raise ValueError(f"{label}启用浏览器渲染但缺少唯一正文选择器")
        if rule.browser_selector and not rule.browser_render:
            raise ValueError(f"{label}配置了浏览器正文选择器但未启用浏览器渲染")
        identity = rule_identity(rule)
        if identity in identities:
            raise ValueError(f"业务身份重复：{rule.section} {rule.url} {rule.position} {rule.parse_hint}")
        identities[identity] = rule


def load_rules(path: Path = SITES_PATH) -> list[SiteRule]:
    items = json.loads(path.read_text(encoding="utf-8"))
    rules = [
        SiteRule(
            url=item["url"],
            position=item["position"],
            section=item["section"],
            field=item["field"],
            content_hint=item.get("content_hint", ""),
            parse_hint=item.get("parse_hint", ""),
            api_url=item.get("api_url", ""),
            tls_compat=bool(item.get("tls_compat", False)),
            browser_render=bool(item.get("browser_render", False)),
            browser_selector=str(item.get("browser_selector", "")).strip(),
        )
        for item in items
    ]
    validate_rules(rules)
    return rules


def rules_config_fingerprint(rules: list[SiteRule]) -> str:
    payload = [
        {
            "url": rule.url,
            "position": rule.position,
            "section": rule.section,
            "field": rule.field,
            "content_hint": rule.content_hint,
            "parse_hint": rule.parse_hint,
            "api_url": rule.api_url,
            "tls_compat": rule.tls_compat,
            **({"browser_render": True} if rule.browser_render else {}),
            **({"browser_selector": rule.browser_selector} if rule.browser_selector else {}),
        }
        for rule in rules
    ]
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


RULES = load_rules()

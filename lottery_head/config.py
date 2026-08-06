from __future__ import annotations

import hashlib
import json
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
        }
        for rule in rules
    ]
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


RULES = load_rules()

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import rule_identity, rules_config_fingerprint
from .models import SiteRule
from .validation import parse_target_period, validate_head_value


CACHE_SCHEMA = "lottery_head_recent_10.v3"
DYNAMIC_ROUTES = {"admin_api", "admin_browser", "forum", "forum_history", "user_forum"}
FORUM_ROUTES = {"forum", "forum_history", "user_forum"}
MAX_CACHE_PERIODS = 10


def read_validated_cache(path: Path, rules: list[SiteRule]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"近10期缓存无法读取：{path}") from exc
    return validate_cache_snapshot(snapshot, rules)


def validate_cache_snapshot(snapshot: dict[str, Any], rules: list[SiteRule]) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("schema") != CACHE_SCHEMA:
        raise ValueError("近10期缓存schema不兼容，必须重建后才能正式写入")
    periods = snapshot.get("periods")
    latest_period = snapshot.get("latest_period")
    try:
        normalized_periods = [parse_target_period(str(period)) for period in periods]
        normalized_latest = parse_target_period(str(latest_period))
    except (TypeError, ValueError) as exc:
        raise ValueError("近10期缓存期数窗口异常") from exc
    if (
        not normalized_periods
        or len(normalized_periods) > MAX_CACHE_PERIODS
        or len(set(normalized_periods)) != len(normalized_periods)
        or normalized_periods != sorted(normalized_periods, key=lambda period: int(period[:-1]), reverse=True)
        or normalized_latest != normalized_periods[0]
        or normalized_periods != [
            f"{int(normalized_latest[:-1]) - offset}期"
            for offset in range(len(normalized_periods))
        ]
    ):
        raise ValueError("近10期缓存期数窗口异常")
    if snapshot.get("period_count") != len(normalized_periods):
        raise ValueError("近10期缓存期数窗口异常")
    if snapshot.get("sites_count") != len(rules):
        raise ValueError("近10期缓存目录数或期数范围异常")
    if snapshot.get("rules_fingerprint") != rules_config_fingerprint(rules):
        raise ValueError("近10期缓存配置指纹不一致，必须重建")
    sites = snapshot.get("sites")
    if not isinstance(sites, list) or len(sites) != len(rules):
        raise ValueError("近10期缓存站点列表异常")
    expected = {rule_identity(rule) for rule in rules}
    observed: set[tuple[str, str, str, str]] = set()
    for site in sites:
        key = _entry_key(site)
        if key in observed:
            raise ValueError("近10期缓存站点身份重复")
        observed.add(key)
        _validate_cache_entry(site, normalized_periods)
    if observed != expected:
        raise ValueError("近10期缓存站点身份与配置不一致")
    return snapshot


def _entry_key(entry: dict[str, Any]) -> tuple[str, str, str, str]:
    identity = entry.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("近10期缓存缺少站点业务身份")
    try:
        return (
            str(identity["section"]),
            str(identity["url"]),
            str(identity["position"]),
            str(identity["parse_hint"]),
        )
    except KeyError as exc:
        raise ValueError("近10期缓存站点业务身份不完整") from exc


def _validate_cache_entry(entry: dict[str, Any], periods: list[str]) -> None:
    values = entry.get("values")
    positions = entry.get("positions")
    provenance = entry.get("provenance")
    missing = entry.get("missing")
    if not all(isinstance(value, dict) for value in (values, positions, provenance, missing)):
        raise ValueError("近10期缓存站点证据结构异常")
    value_periods = set(values)
    missing_periods = set(missing)
    allowed_periods = set(periods)
    if not value_periods.issubset(allowed_periods) or not missing_periods.issubset(allowed_periods):
        raise ValueError("近10期缓存包含窗口外期数")
    if value_periods & missing_periods:
        raise ValueError("近10期缓存同一期同时标记成功和缺失")
    if value_periods | missing_periods != allowed_periods:
        raise ValueError("近10期缓存缺少成功值或失败原因")
    if set(positions) != value_periods or set(provenance) != value_periods:
        raise ValueError("近10期缓存原始位置或来源证据期数不一致")
    for period, value in values.items():
        validate_head_value(str(value))
        if not isinstance(positions[period], int) or positions[period] < 0:
            raise ValueError("近10期缓存原始位置异常")
        source = provenance[period]
        if not isinstance(source, dict) or not source.get("route") or not source.get("source_url"):
            raise ValueError("近10期缓存来源证据异常")
        if not str(source.get("raw_line") or "").strip():
            raise ValueError("近10期缓存缺少候选原文证据")
        if str(source.get("route")) in DYNAMIC_ROUTES:
            required = ("record_id", "record_path", "api_url", "title", "author", "source_block_id")
            if any(not str(source.get(key) or "").strip() for key in required):
                raise ValueError("近10期缓存动态来源证据不完整")
        if str(source.get("route")) in FORUM_ROUTES:
            required_forum = ("source_user_id", "source_forum_id", "source_identity")
            if any(not str(source.get(key) or "").strip() for key in required_forum):
                raise ValueError("近10期缓存论坛来源身份不完整")
            if not isinstance(source.get("source_list_position"), int) or source["source_list_position"] < 0:
                raise ValueError("近10期缓存论坛原始列表位置异常")
    if any(not str(reason or "").strip() for reason in missing.values()):
        raise ValueError("近10期缓存缺少期数失败原因")

from __future__ import annotations

from datetime import datetime
from typing import Any

from .cache_validation import CACHE_SCHEMA, MAX_CACHE_PERIODS, _entry_key
from .config import rule_identity, rules_config_fingerprint
from .models import BaselineSitePeriodData, Candidate, HeadRecord, SiteRule
from .validation import parse_target_period, validate_head_value


CACHE_UPDATE_THRESHOLD_PERCENT = 85


def cache_update_allowed(success_count: int, total_count: int) -> bool:
    """Allow a single-period cache write only when success is strictly above 85%."""
    return (
        total_count > 0
        and success_count >= 0
        and success_count <= total_count
        and success_count * 100 > total_count * CACHE_UPDATE_THRESHOLD_PERCENT
    )


def recent_periods(latest_period: str, count: int = 10) -> list[str]:
    latest = int(parse_target_period(latest_period)[:-1])
    return [f"{latest - offset}期" for offset in range(count)]


def rolling_cache_periods(
    existing: dict[str, Any] | None,
    target_period: str,
    max_periods: int = MAX_CACHE_PERIODS,
) -> list[str]:
    """Build a contiguous descending period axis from the requested period."""
    target = parse_target_period(target_period)
    if not existing:
        return [target]
    latest = int(target[:-1])
    return [f"{latest - offset}期" for offset in range(max_periods)]


def cache_key(rule: SiteRule) -> tuple[str, str, str, str]:
    return rule_identity(rule)


def cache_entry_key_from_record(record: HeadRecord, rules: list[SiteRule]) -> tuple[str, str, str, str] | None:
    if not record.parse_hint.strip():
        return None
    matches = [
        rule
        for rule in rules
        if rule.section == record.section
        and rule.url == record.url
        and rule.position == record.position
        and rule.field == record.field
        and rule.parse_hint == record.parse_hint
    ]
    return cache_key(matches[0]) if len(matches) == 1 else None


def build_cache_payload(
    records: list[HeadRecord],
    rules: list[SiteRule],
    latest_period: str,
    existing: dict[str, Any] | None = None,
    *,
    attempted_period: str | None = None,
) -> dict[str, Any]:
    target = parse_target_period(attempted_period or latest_period)
    periods = rolling_cache_periods(existing, parse_target_period(latest_period))
    existing_by_key = _entries_by_key(existing) if existing else {}
    records_by_key: dict[tuple[str, str, str, str], HeadRecord] = {}
    for record in records:
        key = cache_entry_key_from_record(record, rules)
        if key is None:
            raise ValueError(f"当前结果没有唯一站点身份：{record.section}")
        if key in records_by_key:
            raise ValueError(f"当前结果包含重复站点：{record.section}")
        records_by_key[key] = record
    sites: list[dict[str, Any]] = []
    for rule in rules:
        key = cache_key(rule)
        old = existing_by_key.get(key, {})
        values = dict(old.get("values", {}))
        positions = dict(old.get("positions", {}))
        provenance = dict(old.get("provenance", {}))
        missing = dict(old.get("missing", {}))
        record = records_by_key.get(key)
        if record and record.status == "success":
            period = parse_target_period(record.period)
            if period != target:
                raise ValueError(f"当前成功记录期数不是手动指定期数：{period}，应为{target}")
            values[period] = validate_head_value(record.value)
            positions[period] = record.original_position
            provenance[period] = record_provenance(record)
            missing.pop(period, None)
        elif record:
            failed_period = target
            values.pop(failed_period, None)
            positions.pop(failed_period, None)
            provenance.pop(failed_period, None)
            missing[failed_period] = record.error or "失败原因：未知失败，未返回具体错误"
        for period in periods:
            if period not in values and period not in missing:
                missing[period] = "该期未由本轮真实抓取重建，不能作为成功缓存"
        values = {period: values[period] for period in periods if period in values}
        positions = {period: positions[period] for period in values if period in positions}
        provenance = {period: provenance[period] for period in values if period in provenance}
        missing = {period: missing[period] for period in periods if period in missing and period not in values}
        sites.append(
            {
                "identity": _identity_payload(rule),
                "values": values,
                "positions": positions,
                "provenance": provenance,
                "missing": missing,
            }
        )
    return {
        "schema": CACHE_SCHEMA,
        "latest_period": periods[0],
        "periods": periods,
        "period_count": len(periods),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "sites_count": len(sites),
        "rules_fingerprint": rules_config_fingerprint(rules),
        "sites": sites,
    }


def build_cache_payload_from_site_data(
    all_data: list[BaselineSitePeriodData],
    rules: list[SiteRule],
    latest_period: str,
    *,
    periods: list[str] | None = None,
) -> dict[str, Any]:
    """Create a fresh baseline from one real full-site collection pass."""
    normalized_latest = parse_target_period(latest_period)
    normalized_periods = [
        parse_target_period(period)
        for period in (periods or [normalized_latest])
    ]
    if (
        not normalized_periods
        or len(normalized_periods) > MAX_CACHE_PERIODS
        or len(set(normalized_periods)) != len(normalized_periods)
        or normalized_periods
        != sorted(normalized_periods, key=lambda period: int(period[:-1]), reverse=True)
        or normalized_periods[0] != normalized_latest
        or normalized_periods
        != [
            f"{int(normalized_latest[:-1]) - offset}期"
            for offset in range(len(normalized_periods))
        ]
    ):
        raise ValueError("近10期缓存期数窗口异常")
    data_by_site = {
        (item.section, item.url, item.position, item.parse_hint): item
        for item in all_data
    }
    sites: list[dict[str, Any]] = []
    for rule in rules:
        item = data_by_site.get((rule.section, rule.url, rule.position, rule.parse_hint))
        values: dict[str, str] = {}
        positions: dict[str, int] = {}
        provenance: dict[str, dict[str, str]] = {}
        missing: dict[str, str] = {}
        for period in normalized_periods:
            candidate = item.period_records.get(period) if item and period in item.period_values else None
            if candidate is not None:
                values[period] = validate_head_value(candidate.value)
                positions[period] = candidate.original_position
                provenance[period] = candidate_provenance(candidate, rule)
                continue
            reason = (
                item.missing_reasons.get(period)
                if item and item.missing_reasons.get(period)
                else item.error if item and item.error
                else "指定期数未解析出带原始位置和来源证据的候选"
            )
            missing[period] = reason
        sites.append(
            {
                "identity": _identity_payload(rule),
                "values": values,
                "positions": positions,
                "provenance": provenance,
                "missing": missing,
            }
        )
    return {
        "schema": CACHE_SCHEMA,
        "latest_period": normalized_latest,
        "periods": normalized_periods,
        "period_count": len(normalized_periods),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "sites_count": len(sites),
        "rules_fingerprint": rules_config_fingerprint(rules),
        "sites": sites,
    }


def record_provenance(record: HeadRecord) -> dict[str, Any]:
    return {
        "record_id": record.source_record_id,
        "record_path": record.source_record_path,
        "route": record.source_route or "page",
        "source_url": record.source_url or record.url,
        "api_url": record.source_api_url,
        "title": record.source_title,
        "author": record.source_author,
        "raw_line": record.raw_line,
        "document_order": record.document_order,
        "block_order": record.block_order,
        "record_order": record.record_order,
        "source_block_id": record.source_block_id or f"{record.source_route}:{record.source_record_id or record.source_url}",
        "source_identity": record.source_identity,
        "source_user_id": record.source_user_id,
        "source_forum_id": record.source_forum_id,
        "source_list_position": record.source_list_position,
    }


def candidate_provenance(candidate: Candidate, rule: SiteRule) -> dict[str, Any]:
    return {
        "record_id": candidate.source_record_id,
        "record_path": candidate.source_record_path,
        "route": candidate.source_route or "page",
        "source_url": candidate.source_url or rule.url,
        "api_url": candidate.source_api_url,
        "title": candidate.source_title,
        "author": candidate.source_author,
        "raw_line": candidate.raw_line,
        "document_order": candidate.document_order,
        "block_order": candidate.block_order,
        "record_order": candidate.record_order,
        "source_block_id": candidate.source_block_id or f"{candidate.source_route}:{candidate.source_record_id or candidate.source_url}",
        "source_identity": candidate.source_identity,
        "source_user_id": candidate.source_user_id,
        "source_forum_id": candidate.source_forum_id,
        "source_list_position": candidate.source_list_position,
    }


def _identity_payload(rule: SiteRule) -> dict[str, str]:
    section, url, position, parse_hint = cache_key(rule)
    return {"section": section, "url": url, "position": position, "parse_hint": parse_hint}


def _entries_by_key(snapshot: dict[str, Any] | None) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    if not snapshot:
        return {}
    return {_entry_key(entry): entry for entry in snapshot.get("sites", [])}

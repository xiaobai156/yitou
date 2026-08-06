from __future__ import annotations

from dataclasses import replace
from typing import Any

from .cache_payload import _entries_by_key, cache_entry_key_from_record
from .cache_validation import DYNAMIC_ROUTES, FORUM_ROUTES
from .models import HeadRecord, SiteRule
from .validation import parse_target_period, validate_head_value


def mark_records_conflicting_with_cache(
    records: list[HeadRecord],
    cache: dict[str, Any] | None,
    rules: list[SiteRule],
) -> list[HeadRecord]:
    if cache is None:
        return list(records)
    entries = _entries_by_key(cache)
    adjusted: list[HeadRecord] = []
    for record in records:
        if record.status != "success":
            adjusted.append(record)
            continue
        key = cache_entry_key_from_record(record, rules)
        entry = entries.get(key) if key else None
        period = parse_target_period(record.period)
        if not entry or period not in entry.get("values", {}):
            adjusted.append(record)
            continue
        old_value = validate_head_value(str(entry["values"][period]))
        new_value = validate_head_value(record.value)
        if old_value != new_value:
            adjusted.append(replace(record, status="failed", error=f"缓存冲突：{period}业务值不一致（缓存{old_value}，当前{new_value}）"))
            continue
        old_provenance = entry.get("provenance", {}).get(period, {})
        old_record_id = str(old_provenance.get("record_id") or "")
        old_route = str(old_provenance.get("route") or "")
        dynamic_record = old_route in DYNAMIC_ROUTES or record.source_route in DYNAMIC_ROUTES
        if dynamic_record and (
            not old_record_id
            or not record.source_record_id
            or old_record_id != record.source_record_id
        ):
            adjusted.append(replace(record, status="failed", error=f"缓存冲突：{period}来源记录ID不一致"))
            continue
        old_identity = str(old_provenance.get("source_identity") or "")
        if dynamic_record and old_identity and old_identity != record.source_identity:
            adjusted.append(replace(record, status="failed", error=f"缓存冲突：{period}来源身份不一致"))
            continue
        old_user_id = str(old_provenance.get("source_user_id") or "")
        if dynamic_record and old_user_id and old_user_id != record.source_user_id:
            adjusted.append(replace(record, status="failed", error=f"缓存冲突：{period}来源用户ID不一致"))
            continue
        old_forum_id = str(old_provenance.get("source_forum_id") or "")
        if dynamic_record and old_forum_id and old_forum_id != record.source_forum_id:
            adjusted.append(replace(record, status="failed", error=f"缓存冲突：{period}来源帖子ID不一致"))
            continue
        if old_route in FORUM_ROUTES or record.source_route in FORUM_ROUTES:
            if (
                not record.source_user_id
                or not record.source_forum_id
                or not record.source_identity
                or record.source_list_position < 0
            ):
                adjusted.append(replace(record, status="failed", error=f"缓存冲突：{period}论坛来源身份不完整"))
                continue
        if not dynamic_record and old_record_id and record.source_record_id and old_record_id != record.source_record_id:
            adjusted.append(replace(record, status="failed", error=f"缓存冲突：{period}来源记录ID不一致"))
            continue
        adjusted.append(record)
    return adjusted

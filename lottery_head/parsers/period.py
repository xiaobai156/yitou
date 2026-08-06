from __future__ import annotations

import re

from ..settings import BARE_HEAD_VALUE_RE, HEAD_VALUE_RE
from .common import canonical_text, display_head_value, has_open_marker, normalize_head_value, period_matches, unique_extracted_records
from .four_head import parse_four_combo_missing_head_records


SITE_SPECIFIC_CURRENT_WINDOW_PROFILES = {
    "fengmaolinjiao_top_kill_head": ("绝杀一头", "period_block", "first"),
    "weijujuzhi_bottom_current_list": ("大杀一头", "period_block", "first"),
    "renxinxiang_bottom_current_list": ("绝杀一头", "period_block", "first"),
    "yiwufangu_bottom_current_list": ("绝杀一头", "period_block", "first"),
    "meiyinian_bottom_current_list": ("精杀一头", "period_block", "first"),
    "duanganyifu_bottom_current_list": ("绝杀一头", "period_block", "first"),
    "jueshiyizhan_bottom_current_list": ("绝杀一头", "period_bracket", "first"),
    "piantingpianxin_bottom_current_list": ("四头中特", "missing_four", "first"),
    "zhangzuijieshe_bottom_current_list": ("绝杀一头", "period_bracket", "first"),
    "gongchengmingjiu_top_current_list": ("精杀一头", "period_block", "last"),
}


def limit_to_top_primary_ten_records(records: list[dict[str, str]], hint: str) -> list[dict[str, str]]:
    if hint == "top_primary_ten_periods":
        return records[:10]
    return records


def parse_period_blocks(compact: str, marker: str, target_period: str = "") -> dict[str, str] | None:
    records = parse_period_block_records(compact, marker, target_period)
    return records[0] if records else None


def parse_site_specific_current_window_records(
    compact: str,
    hint: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    marker, parser_kind, window = SITE_SPECIFIC_CURRENT_WINDOW_PROFILES[hint]
    if parser_kind == "missing_four":
        records = parse_four_combo_missing_head_records(compact, marker)
    elif parser_kind == "period_bracket":
        records = parse_period_bracket_head_records(compact, marker)
    else:
        records = parse_period_block_records(compact, marker)
    boundary = records[:1] if window == "first" else records[-1:]
    if not boundary:
        return []
    boundary_period = boundary[0]["period"]
    if target_period and not period_matches(boundary_period, target_period):
        return []
    return [record for record in records if period_matches(record["period"], boundary_period)]


def parse_period_block_records(compact: str, marker: str, target_period: str = "") -> list[dict[str, str]]:
    match_marker = canonical_text(marker)
    records = []
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        match_body = canonical_text(body)
        if match_marker not in match_body or not has_open_marker(body):
            continue
        value = find_non_marker_head_value(body, match_marker)
        if value:
            records.append({
                "period": period,
                "value": value,
                "raw_line": period + body,
            })
    return records


def parse_period_bracket_head_records(compact: str, marker: str, target_period: str = "") -> list[dict[str, str]]:
    match_marker = canonical_text(marker)
    records = []
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        match_body = canonical_text(body)
        if match_marker not in match_body or not has_open_marker(body):
            continue
        value = find_non_marker_head_value(body, match_marker)
        if not value:
            continue
        records.append({
            "period": period,
            "value": value,
            "raw_line": period + body,
        })
    return unique_extracted_records(records)


def find_non_marker_head_value(text: str, match_marker: str) -> str | None:
    match_text = canonical_text(text)
    marker_spans = [(match.start(), match.end()) for match in re.finditer(re.escape(match_marker), match_text)]
    raw_marker_suffixes = {
        match_marker[index:]
        for index in range(1, max(len(match_marker) - 2, 1))
    }
    for marker_suffix in raw_marker_suffixes:
        for marker_match in re.finditer(re.escape(marker_suffix), text):
            canonical_start = len(canonical_text(text[: marker_match.start()]))
            canonical_end = canonical_start + len(canonical_text(marker_match.group(0)))
            marker_spans.append((canonical_start, canonical_end))
    candidates: list[tuple[int, int, str]] = []
    for value_match in HEAD_VALUE_RE.finditer(text):
        canonical_start = len(canonical_text(text[: value_match.start()]))
        canonical_end = canonical_start + len(canonical_text(value_match.group(0)))
        overlaps_marker = any(
            canonical_start < end and canonical_end > start for start, end in marker_spans
        )
        if not overlaps_marker:
            candidates.append((canonical_start, canonical_end, normalize_head_value(value_match.group(0))))
    for value_match in BARE_HEAD_VALUE_RE.finditer(text):
        canonical_start = len(canonical_text(text[: value_match.start()]))
        canonical_end = canonical_start + len(canonical_text(value_match.group(0)))
        overlaps_marker = any(
            canonical_start < end and canonical_end > start for start, end in marker_spans
        )
        if not overlaps_marker:
            candidates.append((canonical_start, canonical_end, normalize_head_value(value_match.group(1))))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        return None
    open_marker = re.search(r"[开開]|开奖|開獎", text)
    open_position = len(canonical_text(text[: open_marker.start()])) if open_marker else len(match_text)
    before_open = [item for item in candidates if item[0] < open_position]
    if not before_open:
        return None
    marker_span = marker_spans[-1] if marker_spans else None
    after_marker = [item for item in before_open if marker_span and item[0] >= marker_span[1]]
    eligible = after_marker or before_open
    distinct_values = {item[2] for item in eligible if display_head_value(item[2])}
    if len(distinct_values) != 1:
        return None
    return next(iter(distinct_values))

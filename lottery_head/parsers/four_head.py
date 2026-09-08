from __future__ import annotations

import re

from ..settings import FOUR_COMBO_RE, FOUR_HEAD_FIELD_RE, PERIOD_RE
from .common import (
    canonical_text,
    contains_text,
    has_open_marker,
    period_matches,
    period_number,
    unique_extracted_records,
)


def parse_four_combo_after_marker_records(
    compact: str, field: str, target_period: str = ""
) -> list[dict[str, str]]:
    source_compact = compact.replace("㊣", "")
    match_marker = canonical_text(field)
    match_compact = canonical_text(source_compact)
    marker_index = match_compact.find(match_marker)
    source = source_compact[marker_index:] if marker_index >= 0 else source_compact
    records = []
    all_heads = {"0", "1", "2", "3", "4"}
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", source):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if "头" not in body and "頭" not in body:
            continue
        values = extract_four_combo_values(body)
        if len(values) != 4 or len(set(values)) != 4:
            continue
        missing = sorted(all_heads - set(values))
        if len(missing) != 1:
            continue
        records.append(
            {
                "period": period,
                "value": f"{missing[0]}头",
                "raw_line": period + body,
            }
        )
    return unique_extracted_records(records)


def parse_four_combo_missing_head_records(
    compact: str,
    field: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    records = []
    all_heads = {"0", "1", "2", "3", "4"}
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if not contains_text(body, field) or not has_open_marker(body):
            continue
        values = extract_four_combo_values_after_field(body, field)
        if len(values) != 4 or len(set(values)) != 4:
            continue
        missing = sorted(all_heads - set(values))
        if len(missing) != 1:
            continue
        records.append(
            {
                "period": period,
                "value": f"{missing[0]}头",
                "raw_line": period + body,
            }
        )
    return records


def parse_anchored_four_combo_missing_head_records(
    compact: str,
    anchor_marker: str,
    field: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    source = anchored_four_combo_source(compact, anchor_marker)
    if not source:
        return []
    return parse_four_combo_missing_head_records(source, field, target_period)


def anchored_four_combo_source(compact: str, anchor_marker: str) -> str:
    source_compact = compact.replace("㊣", "")
    match_compact = canonical_text(source_compact)
    match_anchor = canonical_text(anchor_marker)
    anchor_index = match_compact.find(match_anchor)
    if anchor_index < 0:
        return ""
    source = source_compact[anchor_index + len(match_anchor) :]
    first_period = PERIOD_RE.search(source)
    if not first_period:
        return ""
    next_section = re.search(
        r"[【\[](?![0-4０-４.\s]+[头頭]?[】\]])[^】\]]{1,30}[】\]]",
        source[first_period.start() + 1 :],
    )
    if next_section:
        source = source[: first_period.start() + 1 + next_section.start()]
    return source


def parse_anchored_four_combo_shapes(
    compact: str,
    anchor_marker: str,
    field: str,
) -> list[dict[str, object]]:
    """Return positioned four-head shapes, including malformed duplicates."""
    source = anchored_four_combo_source(compact, anchor_marker)
    if not source:
        return []
    records: list[dict[str, object]] = []
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", source):
        body = block.group(2)
        if not contains_text(body, field) or not has_open_marker(body):
            continue
        values = extract_four_combo_values_after_field(body, field)
        if len(values) != 4:
            continue
        records.append(
            {
                "period": block.group(1),
                "values": values,
                "raw_line": block.group(1) + body,
            }
        )
    return records


def parse_manager_anchored_four_combo_missing_head_records(
    compact: str,
    anchor_marker: str,
    field: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    records = []
    all_heads = {"0", "1", "2", "3", "4"}
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if (
            not contains_text(body, anchor_marker)
            or not contains_text(body, field)
            or not has_open_marker(body)
        ):
            continue
        values = extract_four_combo_values_after_field(body, field)
        if len(values) != 4 or len(set(values)) != 4:
            continue
        missing = sorted(all_heads - set(values))
        if len(missing) != 1:
            continue
        records.append(
            {
                "period": period,
                "value": f"{missing[0]}头",
                "raw_line": period + body,
            }
        )
    return unique_extracted_records(records)


def parse_topic_title_anchored_four_combo_missing_head_records(
    compact: str,
    anchor_marker: str,
    field: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    source_compact = compact.replace("㊣", "")
    match_compact = canonical_text(source_compact)
    match_anchor = canonical_text(anchor_marker)
    anchor_index = match_compact.find(match_anchor)
    if anchor_index < 0:
        return []
    source = source_compact[anchor_index + len(match_anchor) :]
    all_records = parse_four_combo_missing_head_records(source, field)
    if not all_records:
        return []
    current_records = [all_records[0]]
    for record in all_records[1:]:
        previous_period = period_number(current_records[-1]["period"])
        record_period = period_number(record["period"])
        if previous_period - record_period != 1:
            break
        current_records.append(record)
    return [
        record
        for record in current_records
        if period_matches(record["period"], target_period)
    ]


def should_parse_missing_head_from_four_combo(field: str, hint: str = "") -> bool:
    return hint in {
        "missing_head_from_four_combo",
        "missing_head_from_four_combo_full_period_list",
        "strict_position_three_missing_head_from_four_combo",
        "topic_title_anchored_missing_head_from_four_combo",
    } or bool(FOUR_HEAD_FIELD_RE.search(field))


def extract_four_combo_values(text: str) -> list[str]:
    combo_match = FOUR_COMBO_RE.search(text)
    if combo_match:
        return combo_match.group(1).split(".")
    separator_combo_match = re.search(
        r"[〓=＝]\s*([0-4](?:\s*(?:[.、,，-]\s*)?[0-4]){3})\s*[〓=＝]",
        text,
    )
    if separator_combo_match:
        return re.findall(r"[0-4]", separator_combo_match.group(1))
    for bracket_match in re.finditer(
        r"[【\[〖［\(（《〈]([^】\]〗］\)）》〉]{1,30})[】\]〗］\)）》〉]", text
    ):
        body = bracket_match.group(1)
        digits = re.findall(r"[0-4]", body)
        if len(digits) == 4:
            return digits
    return []


def extract_four_combo_values_after_field(text: str, field: str) -> list[str]:
    source_text = text.replace("㊣", "")
    canonical_body = canonical_text(source_text)
    marker = canonical_text(field)
    marker_index = canonical_body.find(marker)
    if marker_index < 0:
        return []
    return extract_four_combo_values(source_text[marker_index + len(marker) :])


def parse_three_combo_excluded_head_records(
    compact: str,
    anchor_marker: str,
    field: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    records = []
    all_heads = {"0", "1", "2", "3", "4"}
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2).replace(anchor_marker, "")
        if not contains_text(body, field) or not has_open_marker(body):
            continue
        values = extract_three_combo_values_after_field(body, field)
        if len(values) != 3 or len(set(values)) != 3:
            continue
        excluded = sorted(all_heads - set(values))
        if len(excluded) != 2:
            continue
        records.append(
            {
                "period": period,
                "value": "、".join(f"{head}头" for head in excluded),
                "raw_line": period + block.group(2),
            }
        )
    return unique_extracted_records(records)


def extract_three_combo_values_after_field(text: str, field: str) -> list[str]:
    source_text = text.replace("㊣", "")
    canonical_body = canonical_text(source_text)
    marker = canonical_text(field)
    marker_index = canonical_body.find(marker)
    if marker_index < 0:
        return []
    source = source_text[marker_index + len(marker) :]
    for bracket_match in re.finditer(
        r"[【\[〖［\(（《〈]([^】\]〗］\)）》〉]{1,30})[】\]〗］\)）》〉]",
        source,
    ):
        digits = re.findall(r"[0-4]", bracket_match.group(1))
        if len(digits) == 3 and len(set(digits)) == 3:
            return digits
    return []

from __future__ import annotations

import re
from collections.abc import Callable

from ..settings import PERIOD_RE
from .common import canonical_text, has_open_marker, looks_like_result_line, period_matches, unique_extracted_records
from .period import find_non_marker_head_value, limit_to_top_primary_ten_records, parse_period_block_records
from .tables import parse_fragment_table_records


RecordParser = Callable[[str, str, str], list[dict[str, str]]]


def parse_generic_head_records(
    fragment_html: str,
    text: str,
    compact: str,
    field: str,
    marker: str,
    hint: str = "",
    target_period: str = "",
    *,
    period_block_parser: RecordParser = parse_period_block_records,
    table_parser: RecordParser = parse_fragment_table_records,
) -> list[dict[str, str]]:
    block_records = period_block_parser(compact, marker, target_period)
    if block_records:
        return limit_to_top_primary_ten_records(block_records, hint)

    table_records = table_parser(fragment_html, field, target_period)
    if table_records:
        return limit_to_top_primary_ten_records(table_records, hint)

    records = []
    match_compact = canonical_text(compact)
    match_marker = canonical_text(marker)
    marker_indexes = [match.start() for match in re.finditer(re.escape(match_marker), match_compact)]
    for marker_index in marker_indexes:
        previous_periods = list(PERIOD_RE.finditer(compact[:marker_index]))
        if previous_periods:
            previous_period = previous_periods[-1]
            if not period_matches(previous_period.group(1), target_period):
                continue
            if marker_index - previous_period.end() <= 30:
                next_period = PERIOD_RE.search(compact, marker_index + len(marker))
                end = next_period.start() if next_period else len(compact)
                body = compact[previous_period.end() : end]
                value = find_non_marker_head_value(body, match_marker)
                if has_open_marker(body) and value:
                    records.append({
                        "period": previous_period.group(1),
                        "value": value,
                        "raw_line": previous_period.group(1) + body,
                    })

    for marker_index in marker_indexes:
        tail = compact[marker_index:]
        for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", tail):
            period = block.group(1)
            if not period_matches(period, target_period):
                continue
            body = block.group(2)
            if not has_open_marker(body):
                continue
            value = find_non_marker_head_value(body, match_marker)
            if value:
                records.append({
                    "period": period,
                    "value": value,
                    "raw_line": period + body,
                })

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    period_lines = [line for line in lines if PERIOD_RE.search(line)]
    preferred_lines = [line for line in period_lines if looks_like_result_line(line)]
    for line in preferred_lines + period_lines:
        period_match = PERIOD_RE.search(line)
        if period_match and not period_matches(period_match.group(1), target_period):
            continue
        value = find_non_marker_head_value(line[period_match.end() :], match_marker) if period_match else None
        if period_match and has_open_marker(line) and value and match_marker in canonical_text(line):
            records.append({
                "period": period_match.group(1),
                "value": value,
                "raw_line": line,
            })
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if not has_open_marker(body):
            continue
        if match_marker not in canonical_text(body):
            continue
        value = find_non_marker_head_value(body, match_marker)
        if value:
            records.append({
                "period": period,
                "value": value,
                "raw_line": period + body,
            })
    return limit_to_top_primary_ten_records(unique_extracted_records(records), hint)

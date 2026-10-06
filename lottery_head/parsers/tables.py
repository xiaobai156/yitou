from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..settings import BARE_HEAD_VALUE_RE, HEAD_VALUE_RE, PERIOD_RE
from .common import canonical_text, contains_text, display_head_value, has_open_marker, normalize_head_value, period_matches, unique_extracted_records
from .period import find_non_marker_head_value

# 极窄容错：站方把「指定列」单元格写成缺左括号的形式（如 275期 杀一头 `4)`），
# 只在整格文本恰为单个 0-4 数字、可选跟一个右括号时取值，不放宽全局正则。
CELL_BARE_HEAD_VALUE_RE = re.compile(r"\s*([0-4０-４])\s*[)）]?\s*")


def parse_fragment_tables(fragment_html: str, field: str, target_period: str = "") -> dict[str, str] | None:
    records = parse_fragment_table_records(fragment_html, field, target_period)
    return records[0] if records else None


def parse_caifu_gaoshou_kill_head_table_records(
    fragment_html: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    soup = BeautifulSoup(fragment_html, "html.parser")
    records: list[dict[str, str]] = []
    for panel in soup.select("div.jszq"):
        title_node = panel.select_one(".jszq-tit")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        if not contains_text(title, "财富高手论坛") or not contains_text(title, "绝杀专区"):
            continue
        for table in panel.find_all("table"):
            rows = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in table.find_all("tr")
            ]
            rows = [row for row in rows if row]
            if not rows:
                continue
            headers = rows[0]
            required_headers = {"期数", "杀一肖", "杀一尾", "杀一头", "开奖结果"}
            if not required_headers.issubset(set(headers)):
                continue
            period_index = headers.index("期数")
            head_index = headers.index("杀一头")
            result_index = headers.index("开奖结果")
            for cells in rows[1:]:
                if max(period_index, head_index, result_index) >= len(cells):
                    continue
                period_match = PERIOD_RE.fullmatch(cells[period_index].strip())
                if not period_match or not period_matches(period_match.group(1), target_period):
                    continue
                if not has_open_marker(cells[result_index]):
                    continue
                value = display_head_value(cells[head_index])
                if not value:
                    continue
                records.append(
                    {
                        "period": period_match.group(1),
                        "value": value,
                        "raw_line": " ".join(cells),
                    }
                )
    return unique_extracted_records(records)


def parse_fragment_table_records(fragment_html: str, field: str, target_period: str = "") -> list[dict[str, str]]:
    soup = BeautifulSoup(fragment_html, "html.parser")
    records = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if len(rows) < 2:
            continue
        header = rows[0]
        try:
            target_index = next(i for i, cell in enumerate(header) if contains_text(cell, field))
        except StopIteration:
            continue
        for row in rows[1:]:
            if len(row) <= target_index:
                continue
            period = next((PERIOD_RE.search(cell).group(1) for cell in row if PERIOD_RE.search(cell)), "")
            if not period_matches(period, target_period):
                continue
            value = extract_head_value_from_cell(row[target_index], field)
            if period and value:
                records.append({
                    "period": period,
                    "value": value,
                    "raw_line": " ".join(row),
                })
    return unique_extracted_records(records)


def parse_vertical_table_column_records(text: str, field: str, target_period: str = "") -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records = []
    for header_index, line in enumerate(lines):
        if not contains_text(line, "期数"):
            continue
        header_end = header_index + 1
        while header_end < len(lines) and not PERIOD_RE.search(lines[header_end]):
            header_end += 1
        header = lines[header_index:header_end]
        try:
            field_offset = next(index for index, cell in enumerate(header) if contains_text(cell, field))
        except StopIteration:
            continue
        header_width = len(header)
        period_index = header_end
        while period_index < len(lines):
            period_match = PERIOD_RE.search(lines[period_index])
            if not period_match:
                period_index += 1
                continue
            value_index = period_index + field_offset
            if value_index >= len(lines):
                break
            next_period_index = None
            for index in range(period_index + 1, min(period_index + header_width + 2, len(lines))):
                if PERIOD_RE.search(lines[index]):
                    next_period_index = index
                    break
            row_end = next_period_index or min(period_index + header_width, len(lines))
            row = lines[period_index:row_end]
            period = period_match.group(1)
            if not period_matches(period, target_period):
                if next_period_index is None:
                    period_index += max(1, len(row))
                else:
                    period_index = next_period_index
                continue
            value = extract_head_value_from_cell(lines[value_index], field)
            if value:
                records.append({
                    "period": period,
                    "value": value,
                    "raw_line": " ".join(row),
                })
            if next_period_index is None:
                period_index += max(1, len(row))
            else:
                period_index = next_period_index
    return unique_extracted_records(records)


def extract_head_value_from_cell(text: str, field: str = "") -> str | None:
    if field:
        value = find_non_marker_head_value(text, canonical_text(field))
        if value:
            return display_head_value(value)
        bare_match = CELL_BARE_HEAD_VALUE_RE.fullmatch(text)
        if not bare_match:
            return None
        bare_value = display_head_value(normalize_head_value(bare_match.group(1)))
        return bare_value or None
    values = {
        display_head_value(normalize_head_value(match.group(0)))
        for match in HEAD_VALUE_RE.finditer(text)
    }
    values.update(
        display_head_value(normalize_head_value(match.group(1)))
        for match in BARE_HEAD_VALUE_RE.finditer(text)
    )
    values.discard("")
    return next(iter(values)) if len(values) == 1 else None

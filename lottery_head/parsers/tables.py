from __future__ import annotations

from bs4 import BeautifulSoup

from ..settings import BARE_HEAD_VALUE_RE, HEAD_VALUE_RE, PERIOD_RE
from .common import contains_text, display_head_value, has_open_marker, normalize_head_value, period_matches, unique_extracted_records


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
            value_matches = list(HEAD_VALUE_RE.finditer(row[target_index]))
            if period and value_matches:
                records.append({
                    "period": period,
                    "value": normalize_head_value(value_matches[-1].group(0)),
                    "raw_line": " ".join(row),
                })
                continue
            bare_value_matches = list(BARE_HEAD_VALUE_RE.finditer(row[target_index]))
            if period and bare_value_matches:
                records.append({
                    "period": period,
                    "value": normalize_head_value(bare_value_matches[-1].group(1)),
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
            value = extract_head_value_from_cell(lines[value_index])
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


def extract_head_value_from_cell(text: str) -> str | None:
    value_matches = list(HEAD_VALUE_RE.finditer(text))
    if value_matches:
        return normalize_head_value(value_matches[-1].group(0))
    bare_value_matches = list(BARE_HEAD_VALUE_RE.finditer(text))
    if bare_value_matches:
        return normalize_head_value(bare_value_matches[-1].group(1))
    return None

from __future__ import annotations

import re

from .common import contains_text, display_head_value, has_open_marker, normalize_head_value, period_matches, unique_extracted_records


def _single_head_record(
    period: str,
    value: str,
    raw_line: str,
    target_period: str,
) -> dict[str, str] | None:
    if not period_matches(period, target_period):
        return None
    display_value = display_head_value(normalize_head_value(value))
    if not display_value:
        return None
    return {"period": period, "value": display_value, "raw_line": raw_line}


def parse_ai_kill_head_records(
    compact: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    pattern = re.compile(
        r"(?P<period>\d{2,3}期)[:：]?AI斩头[【\[](?P<value>[0-4０-４零一二三四两]{1,4})头[】\]][开開]"
    )
    records = []
    for match in pattern.finditer(compact):
        record = _single_head_record(
            match.group("period"),
            match.group("value"),
            match.group(0),
            target_period,
        )
        if record:
            records.append(record)
    return unique_extracted_records(records)


def parse_huakai_kill_head_records(
    compact: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    pattern = re.compile(
        r"(?P<period>\d{2,3}期)[:：]?绝杀[①1]头杀?[「『【\[（(《〈](?P<value>[0-4０-４零一二三四两]{1,4})头[」』】\]）)》〉][开開]"
    )
    records = []
    for match in pattern.finditer(compact):
        record = _single_head_record(
            match.group("period"),
            match.group("value"),
            match.group(0),
            target_period,
        )
        if record:
            records.append(record)
    return unique_extracted_records(records)


def parse_zhimubifa_kill_head_records(
    compact: str,
    anchor_marker: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    if not anchor_marker or not contains_text(compact, anchor_marker):
        return []
    pattern = re.compile(
        r"(?P<period>\d{2,3}期)[:：]?[【\[]杀一头[】\]][《〈](?P<value>[0-4０-４零一二三四两]{1,4})头[》〉][开開]"
    )
    records = []
    for match in pattern.finditer(compact):
        record = _single_head_record(
            match.group("period"),
            match.group("value"),
            match.group(0),
            target_period,
        )
        if record:
            records.append(record)
    return unique_extracted_records(records)


def parse_weilairiji_kill_head_records(
    compact: str,
    anchor_marker: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    if not anchor_marker or not contains_text(compact, anchor_marker):
        return []
    pattern = re.compile(
        r"(?P<period>\d{2,3}期)[:：]?[【\[]未来日记杀一头[】\]][【\[](?P<value>[0-4０-４零一二三四两]{1,4})[】\]][开開]"
    )
    records = []
    for match in pattern.finditer(compact):
        record = _single_head_record(
            match.group("period"),
            match.group("value"),
            match.group(0),
            target_period,
        )
        if record:
            records.append(record)
    return unique_extracted_records(records)


def parse_xiaomiao_kill_head_records(
    compact: str,
    field: str,
    anchor_marker: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    if not anchor_marker or not contains_text(compact, anchor_marker):
        return []
    records = []
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if not contains_text(body, field) or not has_open_marker(body):
            continue
        value_matches = re.findall(
            r"[【\[]绝杀一头[】\]][【\[]杀([0-4０-４零一二三四两]{1,4})[头頭][】\]]",
            body,
        )
        values = {
            display_head_value(normalize_head_value(value))
            for value in value_matches
            if display_head_value(normalize_head_value(value))
        }
        if len(values) != 1:
            continue
        records.append({
            "period": period,
            "value": next(iter(values)),
            "raw_line": period + body,
        })
    return unique_extracted_records(records)


def parse_jingshendousou_kill_head_records(
    compact: str,
    anchor_marker: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    if not anchor_marker or not contains_text(compact, anchor_marker):
        return []
    result_tail = (
        r"(?:[:：]?(?:[0-9０-９?？]{0,8}|"
        r"[鼠牛虎兔龙龍蛇马馬羊猴鸡雞狗猪豬][0-9０-９]{1,2})?"
        r"(?:准|对|對|错|錯|中)?)"
    )
    pattern = re.compile(
        r"(?P<period>\d{2,3}期)"
        r"绝[杀殺]一[头頭]"
        r"[【\[](?P<value>[0-4０-４零一二三四两]{1,4})[头頭][】\]]"
        r"[开開]" + result_tail
    )
    records = []
    for match in pattern.finditer(compact):
        period = match.group("period")
        if not period_matches(period, target_period):
            continue
        value = display_head_value(normalize_head_value(match.group("value")))
        if not value:
            continue
        records.append({
            "period": period,
            "value": value,
            "raw_line": match.group(0),
        })
    return unique_extracted_records(records)

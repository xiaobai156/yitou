from __future__ import annotations

import re

from .common import canonical_text, contains_text, display_head_value, has_open_marker, normalize_head_value, period_matches, unique_extracted_records


_USER_KILL_HEAD_FIELD_ALIASES = {
    "刚猛面食": ("必杀一头",),
    "亲切典礼": ("必杀一头",),
    "主要针": ("杀①头",),
    "害怕国王": ("杀一头",),
    "易逝婴儿": ("杀一头",),
    "不幸月会": ("杀一头",),
}


def parse_head_tail_phrase_records(
    compact: str,
    field: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    match_marker = canonical_text("输尽光" if "输尽光" in field or "輸盡光" in field else field)
    records = []
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if match_marker not in canonical_text(body):
            continue
        phrase_match = re.search(r"([0-4０-４零一二三四两])头[0-9０-９零一二三四五六七八九十两二就]+尾", body)
        if phrase_match:
            records.append({
                "period": period,
                "value": display_head_value(normalize_head_value(phrase_match.group(1))),
                "raw_line": period + body,
            })
            continue
        code_match = re.search(r"([0-4０-４零一二三四两]{2,4})头", body)
        if code_match:
            records.append({
                "period": period,
                "value": display_head_value(normalize_head_value(code_match.group(1)[-1])),
                "raw_line": period + body,
            })
    return unique_extracted_records(records)


def parse_sword_head_records(compact: str, field: str, target_period: str = "") -> list[dict[str, str]]:
    match_marker = canonical_text(field)
    records = []
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if match_marker not in canonical_text(body):
            continue
        value_match = re.search(rf"{re.escape(field)}[:：]?杀([0-4０-４零一二三四两])头", body)
        if not value_match:
            continue
        records.append({
            "period": period,
            "value": display_head_value(normalize_head_value(value_match.group(1))),
            "raw_line": period + body,
        })
    return unique_extracted_records(records)


def parse_must_win_head_records(compact: str, target_period: str = "") -> list[dict[str, str]]:
    records = []
    pattern = re.compile(r"(\d{2,3}期)必中一头[:：]?([0-4０-４零一二三四两])")
    for match in pattern.finditer(compact):
        period = match.group(1)
        if not period_matches(period, target_period):
            continue
        records.append({
            "period": period,
            "value": display_head_value(normalize_head_value(match.group(2))),
            "raw_line": match.group(0),
        })
    return unique_extracted_records(records)


def parse_user_kill_head_records(
    compact: str,
    target_period: str = "",
    field: str = "",
    site_key: str = "",
) -> list[dict[str, str]]:
    records = []
    field_markers = (field, *_USER_KILL_HEAD_FIELD_ALIASES.get(site_key, ()))
    document_has_field = any(marker and contains_text(compact, marker) for marker in field_markers)
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        raw_line = period + body
        if not has_open_marker(raw_line):
            continue
        values = []
        broad_values = []
        if document_has_field:
            for value_match in re.finditer(
                r"(?:绝|精|必)?杀(?:一|1|①)头[^期]{0,16}?[〔【\[\(（《〈]([0-4０-４零一二三四两]{1,4})(?:[头頭])?[〕】\]\)）》〉](?:[头頭])?",
                body,
            ):
                value = display_head_value(normalize_head_value(value_match.group(1)))
                if value:
                    broad_values.append(value)
        values.extend(broad_values)
        for value_match in re.finditer(
            r"[〔【\[\(（《〈]杀([0-4０-４零一二三四两]{1,4})[头頭][〕】\]\)）》〉]",
            body,
        ):
            if broad_values and value_match.group(1) == "一":
                continue
            value = display_head_value(normalize_head_value(value_match.group(1)))
            if value:
                values.append(value)
        distinct_values = set(values)
        if len(distinct_values) != 1:
            continue
        records.append({
            "period": period,
            "value": next(iter(distinct_values)),
            "raw_line": raw_line,
        })
    return unique_extracted_records(records)


def parse_dash_head_phrase_records(
    compact: str,
    field: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    records = []
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if not contains_text(body, field) or not has_open_marker(body):
            continue
        matches = re.findall(
            r"[-—–－]{2,}([0-4０-４零一二三四两])[-—–－]{2,}[头頭]",
            body,
        )
        values = {
            display_head_value(normalize_head_value(value))
            for value in matches
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


def parse_kill_head_phrase_records(compact: str, target_period: str = "") -> list[dict[str, str]]:
    records = []
    pattern = re.compile(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)")
    for match in pattern.finditer(compact):
        period = match.group(1)
        if not period_matches(period, target_period):
            continue
        body = match.group(2)
        if not has_open_marker(body):
            continue
        value_match = re.search(r"(?:^|[〔【\[\(（《〈:：])杀([0-4０-４零一二三四两])头", body)
        if not value_match:
            continue
        records.append({
            "period": period,
            "value": normalize_head_value(value_match.group(1)),
            "raw_line": period + body,
        })
    return unique_extracted_records(records)


def parse_number_code_to_head_records(compact: str, field: str, target_period: str = "") -> list[dict[str, str]]:
    match_marker = canonical_text(field)
    records = []
    for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", compact):
        period = block.group(1)
        if not period_matches(period, target_period):
            continue
        body = block.group(2)
        if match_marker not in canonical_text(body) or not has_open_marker(body):
            continue
        value_match = re.search(r"[【\[〖]([0-4][0-9])[】\]〗]", body)
        if not value_match:
            continue
        records.append({
            "period": period,
            "value": f"{value_match.group(1)[0]}头",
            "raw_line": period + body,
        })
    return unique_extracted_records(records)


def parse_bracket_sha_yi_tou_records(compact: str, target_period: str = "") -> list[dict[str, str]]:
    records = []
    pattern = re.compile(
        r"(\d{2,3}期)[^期]{0,20}[【\[]杀一头[】\]][^期]{0,10}[【\[]([0-4０-４零一二三四两]{1,4})[头頭]?[】\]][^期]{0,30}?(?=\d{2,3}期|$)"
    )
    for match in pattern.finditer(compact):
        period = match.group(1)
        if not period_matches(period, target_period):
            continue
        raw_line = match.group(0)
        if not has_open_marker(raw_line):
            continue
        records.append({
            "period": period,
            "value": normalize_head_value(match.group(2)),
            "raw_line": raw_line,
        })
    return unique_extracted_records(records)


def parse_bisha_yitou_plain_records(compact: str, target_period: str = "") -> list[dict[str, str]]:
    records = []
    pattern = re.compile(
        r"(\d{2,3}期)[:：]必杀一头[【\[]([0-4０-４零一二三四两])[头頭][】\]][^期]{0,12}?([开開][^期]{0,20}?(?:准|錯|错|對|对|中))"
    )
    for match in pattern.finditer(compact):
        period = match.group(1)
        if not period_matches(period, target_period):
            continue
        records.append({
            "period": period,
            "value": normalize_head_value(match.group(2)),
            "raw_line": match.group(0),
        })
    return unique_extracted_records(records)


def parse_bisha_yitou_bracket_records(compact: str, target_period: str = "") -> list[dict[str, str]]:
    records = []
    pattern = re.compile(
        r"(\d{2,3}期)[【\[]必杀一头[】\]][【\[]杀([0-4０-４零一二三四两])[头頭][】\]][^期]{0,12}?([开開][^期]{0,20}?(?:准|錯|错|對|对|中))"
    )
    for match in pattern.finditer(compact):
        period = match.group(1)
        if not period_matches(period, target_period):
            continue
        records.append({
            "period": period,
            "value": normalize_head_value(match.group(2)),
            "raw_line": match.group(0),
        })
    return unique_extracted_records(records)


def parse_bracket_field_head_records(
    compact: str,
    field: str,
    target_period: str = "",
) -> list[dict[str, str]]:
    records = []
    escaped_field = re.escape(field)
    pattern = re.compile(
        rf"(\d{{2,3}}期)[^期]{{0,20}}[【\[]({escaped_field})[】\]][^期]{{0,10}}[【\[]([0-4０-４零一二三四两]{{1,4}})[头頭]?[】\]][^期]{{0,30}}?(?=\d{{2,3}}期|$)"
    )
    for match in pattern.finditer(compact):
        period = match.group(1)
        if not period_matches(period, target_period):
            continue
        raw_line = match.group(0)
        if not has_open_marker(raw_line):
            continue
        records.append({
            "period": period,
            "value": normalize_head_value(match.group(3)),
            "raw_line": raw_line,
        })
    return unique_extracted_records(records)


def parse_miaosha_bracket_head_records(compact: str, target_period: str = "") -> list[dict[str, str]]:
    records = []
    pattern = re.compile(r"(\d{2,3}期)㊣秒杀[【\[]([0-4０-４零一二三四两]{1,4})[头頭]?[】\]](.*?)(?=\d{2,3}期|$)")
    for match in pattern.finditer(compact):
        period = match.group(1)
        if not period_matches(period, target_period):
            continue
        value = normalize_head_value(match.group(2))
        raw_line = period + "㊣秒杀" + match.group(0).split("㊣秒杀", 1)[1]
        records.append({
            "period": period,
            "value": value,
            "raw_line": raw_line,
        })
    return unique_extracted_records(records)

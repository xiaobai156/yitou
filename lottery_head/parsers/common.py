from __future__ import annotations

import re

from bs4 import BeautifulSoup


_PERIOD_INPUT_RE = re.compile(r"^\s*(\d{1,3})\s*(?:期)?\s*$")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def looks_like_result_line(line: str) -> bool:
    return bool(re.search(r"[开開][:：]|开奖|開獎|[开開][鼠牛虎兔龙龍蛇马馬羊猴鸡雞狗猪豬0-9０-９]", line))


def has_open_marker(text: str) -> bool:
    return bool(re.search(r"[开開]|开奖|開獎", text))


def normalize_head_value(value: str) -> str:
    value = re.sub(r"[【】\[\]()（）「」『』\s]", "", value)
    value = value.replace("頭", "头")
    return value if value.endswith("头") else f"{value}头"


def display_head_value(value: str) -> str:
    replacements = {
        "零": "0",
        "一": "1",
        "二": "2",
        "两": "2",
        "三": "3",
        "四": "4",
    }
    value = normalize_head_value(value)
    value = value.translate(str.maketrans("０１２３４", "01234"))
    for chinese, digit in replacements.items():
        value = value.replace(chinese, digit)
    digits = re.fullmatch(r"([0-4]+)头", value)
    if not digits:
        return ""
    raw_digits = digits.group(1)
    if len(set(raw_digits)) != 1:
        return ""
    return f"{raw_digits[0]}头"


def contains_text(text: str, needle: str) -> bool:
    return canonical_text(needle) in canonical_text(text)


def normalize_target_period(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    digits = _PERIOD_INPUT_RE.fullmatch(value)
    if not digits:
        return value
    return f"{int(digits.group(1))}期"


def period_matches(period: str, target_period: str = "") -> bool:
    if not target_period:
        return True
    period_digits = _PERIOD_INPUT_RE.fullmatch(period or "")
    target_digits = _PERIOD_INPUT_RE.fullmatch(target_period or "")
    if not period_digits or not target_digits:
        return period.strip() == target_period.strip()
    return int(period_digits.group(1)) == int(target_digits.group(1))


def canonical_text(text: str) -> str:
    return (
        text.replace("殺", "杀")
        .replace("絕", "绝")
        .replace("頭", "头")
        .replace("1头", "一头")
        .replace("開", "开")
        .replace("獎", "奖")
        .replace("㊣", "")
    )


def period_number(period: str) -> int:
    match = _PERIOD_INPUT_RE.fullmatch(period or "")
    return int(match.group(1)) if match else 0


def unique_extracted_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = []
    seen = set()
    for record in records:
        key = (record.get("period", ""), record.get("value", ""), record.get("raw_line", ""))
        if key in seen:
            continue
        raw_line = record.get("raw_line", "")
        if raw_line:
            duplicate_index = next(
                (
                    index
                    for index, existing in enumerate(unique)
                    if record.get("period", "") == existing.get("period", "")
                    and record.get("value", "") == existing.get("value", "")
                    and (
                        raw_line in existing.get("raw_line", "")
                        or existing.get("raw_line", "") in raw_line
                    )
                ),
                None,
            )
            if duplicate_index is not None:
                if len(raw_line) < len(unique[duplicate_index].get("raw_line", "")):
                    unique[duplicate_index] = record
                seen.add(key)
                continue
        seen.add(key)
        unique.append(record)
    return unique

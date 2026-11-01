from __future__ import annotations

import re


_PERIOD_INPUT_RE = re.compile(r"^\s*([1-9]\d{0,2})\s*(?:期|qi)?\s*$", re.IGNORECASE)
_HEAD_RE = re.compile(r"^([0-4０-４零一二三四两]+)\s*[头頭]$")
_TWO_HEAD_RE = re.compile(
    r"^([0-4０-４零一二三四两])\s*[头頭]\s*[、,，/]\s*"
    r"([0-4０-４零一二三四两])\s*[头頭]$"
)


def _normalize_head_digit(value: str) -> str:
    return (
        value.translate(str.maketrans("０１２３４", "01234"))
        .replace("零", "0")
        .replace("一", "1")
        .replace("二", "2")
        .replace("两", "2")
        .replace("三", "3")
        .replace("四", "4")
    )


def parse_target_period(value: str) -> str:
    """Accept only a complete user-entered period, never a substring from other text."""
    match = _PERIOD_INPUT_RE.fullmatch(value or "")
    if not match:
        raise ValueError("期数格式无效，只能输入1至3位期数，例如201或201期")
    return f"{int(match.group(1))}期"


def validate_head_value(value: str) -> str:
    raw = (value or "").strip()
    two_head_match = _TWO_HEAD_RE.fullmatch(raw)
    if two_head_match:
        heads = sorted({_normalize_head_digit(item) for item in two_head_match.groups()})
        if len(heads) != 2:
            raise ValueError("排除两头必须是两个不同的0至4头值")
        return "、".join(f"{head}头" for head in heads)
    match = _HEAD_RE.fullmatch(raw)
    if not match:
        raise ValueError("头值格式无效，必须是单头或两个不同的0至4头值")
    normalized = _normalize_head_digit(match.group(1))
    if len(set(normalized)) != 1 or normalized[0] not in "01234":
        raise ValueError("头值必须是同一个0至4的头")
    return f"{normalized[0]}头"

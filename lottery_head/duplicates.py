from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .validation import parse_target_period, validate_head_value


@dataclass(frozen=True)
class DuplicateFinding:
    left: str
    right: str
    periods: tuple[str, ...]
    streak: int
    status: str


def longest_equal_streak(left: dict[str, Any], right: dict[str, Any], periods: list[str]) -> list[str]:
    best: list[str] = []
    current: list[str] = []
    previous_number: int | None = None
    left_values = left.get("values", {})
    right_values = right.get("values", {})
    for period in periods:
        number = int(parse_target_period(period)[:-1])
        same_sequence = previous_number is None or previous_number == number + 1
        left_value = left_values.get(period)
        right_value = right_values.get(period)
        matches = (
            same_sequence
            and left_value is not None
            and right_value is not None
            and validate_head_value(str(left_value)) == validate_head_value(str(right_value))
        )
        if matches:
            current.append(period)
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
        previous_number = number
    return best


def missing_duplicate_evidence(entry: dict[str, Any], periods: list[str]) -> list[str]:
    values = entry.get("values", {})
    missing = entry.get("missing", {})
    return [period for period in periods if period not in values or period in missing]


def common_contiguous_periods(
    left: dict[str, Any],
    right: dict[str, Any],
    periods: list[str],
) -> list[str]:
    left_values = left.get("values", {})
    right_values = right.get("values", {})
    best: list[str] = []
    current: list[str] = []
    previous_number: int | None = None
    for period in periods:
        number = int(parse_target_period(period)[:-1])
        if period not in left_values or period not in right_values:
            current = []
            previous_number = number
            continue
        if previous_number is None or previous_number != number + 1:
            current = []
        current.append(period)
        if len(current) > len(best):
            best = list(current)
        previous_number = number
    return best


def longest_available_streak(entry: dict[str, Any], periods: list[str]) -> list[str]:
    values = entry.get("values", {})
    best: list[str] = []
    current: list[str] = []
    previous_number: int | None = None
    for period in periods:
        number = int(parse_target_period(period)[:-1])
        if period in values and (previous_number is None or previous_number == number + 1):
            current.append(period)
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
        previous_number = number
    return best


def find_duplicate_findings(sites: list[dict[str, Any]], periods: list[str]) -> list[DuplicateFinding]:
    findings: list[DuplicateFinding] = []
    for left, right in combinations(sites, 2):
        matched = longest_equal_streak(left, right, periods)
        streak = len(matched)
        if streak < 3:
            continue
        status = "重复拒收" if streak >= 6 else "疑似重复"
        findings.append(
            DuplicateFinding(
                left=str(left.get("identity", {}).get("section", "未知目录")),
                right=str(right.get("identity", {}).get("section", "未知目录")),
                periods=tuple(matched),
                streak=streak,
                status=status,
            )
        )
    return findings

from __future__ import annotations

from collections import Counter
import re


from .models import Candidate, SiteRule, SourceDocument
from .parsers import extract_head_records
from .parsers.common import contains_text, display_head_value, html_to_text, looks_like_result_line, period_matches, period_number
from .settings import (
    HEAD_VALUE_RE,
    PERIOD_RE,
    POSITION_SCOPE_LIMIT,
    WIDE_CANDIDATE_LIMIT,
)


def extract_period_records_by_period(
    fragments: list[str],
    rule: SiteRule,
    periods: list[str],
) -> dict[str, dict[str, str]]:
    return select_period_records(extract_period_candidates_by_period(fragments, rule, periods))


def extract_period_candidates_by_period(
    fragments: list[str | SourceDocument],
    rule: SiteRule,
    periods: list[str],
) -> dict[str, list[dict[str, str]]]:
    wanted_periods = list(dict.fromkeys(periods))
    candidates_by_period: dict[str, list[dict[str, str]]] = {period: [] for period in wanted_periods}
    ordered_records = _collect_ordered_candidates(fragments, rule)
    boundary = _global_direction_window(ordered_records, rule.position)
    for period in wanted_periods:
        if not any(period_matches(record.get("period", ""), period) for record in boundary):
            continue
        candidates_by_period[period] = [
            record
            for record in ordered_records
            if period_matches(record.get("period", ""), period)
        ]
    return candidates_by_period


def extract_single_period_candidates_by_period(
    fragments: list[str | SourceDocument],
    rule: SiteRule,
    periods: list[str],
) -> dict[str, list[dict[str, str]]]:
    wanted_periods = list(dict.fromkeys(periods))
    if len(wanted_periods) != 1:
        raise ValueError("单期方向取位只能接收一个目标期数")
    target_period = wanted_periods[0]
    return extract_period_candidates_by_period(fragments, rule, [target_period])


def _collect_ordered_candidates(
    fragments: list[str | SourceDocument],
    rule: SiteRule,
) -> list[dict[str, str]]:
    ordered: list[dict[str, str]] = []
    for fragment_index, fragment in enumerate(fragments):
        document = _as_source_document(fragment, fragment_index)
        if document.resource_error:
            continue
        evidence_text = _document_evidence_text(document)
        if (
            not contains_text(evidence_text, rule.anchor)
            and rule.parse_hint != "caifu_gaoshou_bottom_kill_head_table"
        ):
            continue
        all_records = extract_head_records(
            document.source,
            rule.field,
            rule.parse_hint,
            anchor_marker=rule.anchor,
        )
        document_order = document.document_order if document.document_order >= 0 else fragment_index
        document_records = []
        for record_index, record in enumerate(all_records):
            document_records.append(
                {
                    **record,
                    "original_position": int(record.get("original_position", record_index)),
                    "document_order": document_order,
                    "block_order": int(record.get("block_order", record_index)),
                    "record_order": int(record.get("record_order", record_index)),
                    "source_block_id": document.source_block_id or document.key,
                    "source_identity": document.source_identity,
                    "source_user_id": document.user_id,
                    "source_forum_id": document.forum_id,
                    "source_list_position": document.source_list_position,
                    "document_key": document.key,
                    "source_record_id": document.record_id,
                    "source_record_path": document.record_path,
                    "source_route": document.route,
                    "source_url": document.url,
                    "source_api_url": document.api_url,
                    "source_title": document.title,
                    "source_author": document.author,
                }
            )
        ordered.extend(_select_direction_period_cycle(document_records, rule.position))
    ordered.sort(key=_candidate_order_key)
    return _deduplicate_ordered_candidates(ordered)


def collect_ordered_candidates(
    fragments: list[str | SourceDocument],
    rule: SiteRule,
) -> list[dict[str, str]]:
    return _collect_ordered_candidates(fragments, rule)


def _candidate_order_key(candidate: dict[str, str]) -> tuple[int, int, int, str]:
    return (
        int(candidate.get("document_order", 0)),
        int(candidate.get("block_order", candidate.get("original_position", 0))),
        int(candidate.get("record_order", candidate.get("original_position", 0))),
        str(candidate.get("document_key", "")),
    )


def _select_direction_period_cycle(
    candidates: list[dict[str, str]],
    position: str,
) -> list[dict[str, str]]:
    if len(candidates) < 2 or not is_strict_position_three_position(position):
        return candidates
    boundaries = [
        index
        for index in range(1, len(candidates))
        if {
            period_number(candidates[index - 1].get("period", "")),
            period_number(candidates[index].get("period", "")),
        }
        == {1, 365}
    ]
    if not boundaries:
        return candidates
    if is_bottom_position(position):
        return candidates[boundaries[-1] :]
    return candidates[: boundaries[0]]


def _deduplicate_ordered_candidates(
    candidates: list[dict[str, str]],
) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, str]] = []
    for candidate in candidates:
        raw_line = str(candidate.get("raw_line", ""))
        if not raw_line.strip():
            result.append(candidate)
            continue
        key = (
            str(candidate.get("period", "")),
            display_head_value(candidate.get("value", "")),
            re.sub(r"\s+", "", raw_line),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _global_direction_window(
    candidates: list[dict[str, str]],
    position: str,
) -> list[dict[str, str]]:
    if not is_strict_position_three_position(position):
        return candidates
    if is_bottom_position(position):
        return candidates[-1:]
    return candidates[:1]


def is_strict_position_three_position(position: str) -> bool:
    return position.strip().lower() in {
        "top",
        "顶部",
        "上",
        "bottom",
        "尾部",
        "底部",
        "下",
    }


def _document_evidence_text(document: SourceDocument) -> str:
    return "\n".join(
        part
        for part in (document.title, document.author, document.source)
        if part
    )


def select_period_records(candidates_by_period: dict[str, list[dict[str, str]]]) -> dict[str, dict[str, str]]:
    records_by_period = {}
    for period, candidates in candidates_by_period.items():
        if candidates:
            selected = dict(candidates[0])
            selected["value"] = display_head_value(selected.get("value", "")) or selected.get("value", "")
            records_by_period[period] = selected
    return records_by_period


def select_target_candidate(candidates: list[Candidate], target_period: str) -> Candidate:
    matched = [candidate for candidate in candidates if period_matches(candidate.period, target_period)]
    if not matched:
        raise ValueError(f"方向候选内未找到指定期数：{target_period}")
    signatures = {display_head_value(item.value) for item in matched}
    if len(signatures) > 1:
        raise ValueError(f"{target_period}同一期候选值冲突")
    if len({_candidate_position_key(item) for item in matched}) > 1:
        raise ValueError(f"{target_period}同一期原始边界不唯一")
    return matched[0]


def period_value_conflict(candidates: list[dict[str, str]]) -> bool:
    signatures = {
        std
        for candidate in candidates
        if (std := display_head_value(candidate.get("value", "")))
    }
    return len(signatures) > 1


def period_boundary_ambiguity(candidates: list[dict[str, str]]) -> bool:
    positions = {
        _candidate_position_key(candidate)
        for candidate in candidates
        if display_head_value(candidate.get("value", ""))
    }
    return len(positions) > 1


def _candidate_position_key(candidate) -> tuple[str, int, int, int]:
    return (
        str(candidate.get("source_block_id", "")) if isinstance(candidate, dict) else candidate.document_key,
        int(candidate.get("document_order", -1)) if isinstance(candidate, dict) else int(getattr(candidate, "document_order", -1)),
        int(candidate.get("block_order", candidate.get("original_position", -1))) if isinstance(candidate, dict) else int(getattr(candidate, "block_order", -1)),
        int(candidate.get("original_position", -1)) if isinstance(candidate, dict) else candidate.original_position,
    )


def describe_conflicting_candidates(candidates: list[dict[str, str]]) -> str:
    details = []
    seen = set()
    for candidate in candidates:
        value = display_head_value(candidate.get("value", ""))
        raw_line = candidate.get("raw_line", "")
        if not value:
            continue
        key = (value, raw_line)
        if key in seen:
            continue
        seen.add(key)
        position = candidate.get("original_position", "?")
        details.append(f"{value}@原始位置{position}: {raw_line}" if raw_line else f"{value}@原始位置{position}")
    return "；".join(details) if details else "候选值不一致但未保留原始行"


def select_period_values(
    period_candidates: dict[str, list[dict[str, str]]],
    records_by_period: dict[str, dict[str, str]],
    periods: list[str],
) -> tuple[dict[str, str], list[str], list[str]]:
    values = {}
    missing = []
    conflict_errors = []
    for period in periods:
        candidates = period_candidates.get(period, [])
        if period_value_conflict(candidates):
            missing.append(period)
            conflict_errors.append(
                f"{period}同一期出现多个冲突候选（{describe_conflicting_candidates(candidates)}）"
            )
            continue
        if period_boundary_ambiguity(candidates):
            missing.append(period)
            conflict_errors.append(f"{period}同一期原始边界不唯一（相同标准化数据出现在多个来源位置）")
            continue
        period_record = records_by_period.get(period)
        raw = period_record["value"] if period_record and period_record.get("value") else ""
        std = display_head_value(raw) if raw else ""
        if std:
            values[period] = std
        else:
            missing.append(period)
    return values, missing, conflict_errors


def is_strict_position_three(rule: SiteRule) -> bool:
    return is_strict_position_three_position(rule.position)


def is_full_period_list(rule: SiteRule) -> bool:
    return rule.parse_hint in {
        "full_period_list",
        "missing_head_from_four_combo_full_period_list",
        "manager_anchored_missing_head_from_four_combo",
        "admin_anchored_missing_head_from_four_combo",
        "topic_title_anchored_missing_head_from_four_combo",
        "top_primary_ten_periods",
        "caifu_gaoshou_bottom_kill_head_table",
        "jingshendousou_kill_head_line",
    }


def limit_records_to_strict_three(
    indexed_records: list[tuple[int, dict[str, str]]],
    total_records: int,
    position: str,
) -> list[tuple[int, dict[str, str]]]:
    if is_bottom_position(position):
        start_index = max(total_records - 1, 0)
        return [(index, record) for index, record in indexed_records if index >= start_index]
    return [(index, record) for index, record in indexed_records if index < 1]


def position_three_label(position: str) -> str:
    return "底部最后一条" if is_bottom_position(position) else "顶部第一条"


def find_target_fragment(fragments: list[str | SourceDocument], rule: SiteRule, target_period: str = "") -> str | None:
    if not target_period:
        return None
    documents = [_as_source_document(fragment, index) for index, fragment in enumerate(fragments)]
    candidates = extract_single_period_candidates_by_period(documents, rule, [target_period]).get(target_period, [])
    if not candidates:
        return None
    selected_key = candidates[0].get("document_key", "")
    selected = next((document for document in documents if document.key == selected_key), None)
    return selected.source if selected else None


def find_target_record(fragments: list[str | SourceDocument], rule: SiteRule, target_period: str) -> dict[str, str] | None:
    candidates_by_period = extract_single_period_candidates_by_period(fragments, rule, [target_period])
    candidates = candidates_by_period.get(target_period, [])
    if not candidates:
        return None
    if period_value_conflict(candidates):
        raise ValueError(
            f"{target_period}同一期出现多个冲突候选（{describe_conflicting_candidates(candidates)}）"
        )
    if period_boundary_ambiguity(candidates):
        raise ValueError(f"{target_period}同一期原始边界不唯一（相同标准化数据出现在多个来源位置）")
    return select_period_records(candidates_by_period).get(target_period)


def find_latest_available_record(fragments: list[str | SourceDocument], rule: SiteRule) -> dict[str, str] | None:
    candidates = _global_direction_window(_collect_ordered_candidates(fragments, rule), rule.position)
    return candidates[0] if candidates else None


def limit_records_to_position_scope(
    target_records: list[tuple[int, dict[str, str]]],
    all_records: list[dict[str, str]],
    total_records: int,
    position: str,
) -> list[tuple[int, dict[str, str]]]:
    if is_bottom_position(position):
        start_index = max(total_records - POSITION_SCOPE_LIMIT, 0)
        return [(index, record) for index, record in target_records if index >= start_index]
    return [(index, record) for index, record in target_records if index < POSITION_SCOPE_LIMIT]


def should_limit_to_position_scope(records: list[dict[str, str]]) -> bool:
    if len(records) > WIDE_CANDIDATE_LIMIT:
        return True
    period_counts = Counter(record["period"] for record in records)
    return any(count > 1 for count in period_counts.values())


def is_bottom_position(position: str) -> bool:
    return position.strip().lower() in {"bottom", "尾部", "底部", "下"}


def select_position_match(matches: list[tuple[int, str | SourceDocument]], rule: SiteRule, target_period: str = "") -> str | None:
    data_matches = [
        (index, _as_source_document(fragment, index))
        for index, fragment in matches
        if extract_head_records(
            _as_source_document(fragment, index).source,
            rule.field,
            rule.parse_hint,
            target_period,
            anchor_marker=rule.anchor,
        )
    ]
    if not data_matches:
        return None
    data_matches.sort(key=lambda item: item[0], reverse=is_bottom_position(rule.position))
    return data_matches[0][1].source


def _as_source_document(fragment: str | SourceDocument, index: int) -> SourceDocument:
    if isinstance(fragment, SourceDocument):
        return fragment
    return SourceDocument(str(fragment), "", f"legacy-{index}", document_order=index)


def fragment_has_result_data(fragment_html: str) -> bool:
    text = html_to_text(fragment_html)
    return bool(PERIOD_RE.search(text) and HEAD_VALUE_RE.search(text))


def score_fragment(fragment_html: str, rule: SiteRule) -> tuple[int, int, int]:
    text = html_to_text(fragment_html)
    return (
        1 if contains_text(text, rule.field) or contains_text(fragment_html, rule.field) else 0,
        1 if rule.content_hint and contains_text(text, rule.content_hint) else 0,
        sum(1 for line in text.splitlines() if looks_like_result_line(line)),
        len(PERIOD_RE.findall(text)) + len(HEAD_VALUE_RE.findall(text)),
    )


def extract_latest_head_record(
    fragment_html: str,
    field: str,
    hint: str = "",
    target_period: str = "",
    anchor_marker: str = "",
) -> dict[str, str] | None:
    records = extract_head_records(fragment_html, field, hint, target_period, anchor_marker=anchor_marker)
    return records[0] if records else None

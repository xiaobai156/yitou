from __future__ import annotations

import re


from .models import Candidate, SiteRule, SourceDocument
from .parsers import extract_head_records
from .parsers.common import (
    contains_text,
    display_head_value,
    html_to_text,
    period_matches,
    period_number,
)
from .parsers.four_head import parse_anchored_four_combo_shapes


def extract_period_records_by_period(
    fragments: list[str],
    rule: SiteRule,
    periods: list[str],
) -> dict[str, dict[str, str]]:
    return select_period_records(
        extract_period_candidates_by_period(fragments, rule, periods)
    )


def extract_period_candidates_by_period(
    fragments: list[str | SourceDocument],
    rule: SiteRule,
    periods: list[str],
    *,
    strict_conflict_periods: list[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """按方向窗口提取候选。

    strict_conflict_periods 限定“冲突即整站失败”的期数；默认只对全部请求期
    严格（单期抓取时即目标期）。多期批量场景应只传目标期，避免非目标期的
    历史冲突把整站拖垮。
    """
    wanted_periods = list(dict.fromkeys(periods))
    strict = (
        list(strict_conflict_periods)
        if strict_conflict_periods is not None
        else list(wanted_periods)
    )

    def _is_strict(period: str) -> bool:
        # 用 period_matches 做归一化比较，避免 "298" 与 "298期" 静默失配。
        return any(period_matches(period, candidate) for candidate in strict)

    candidates_by_period: dict[str, list[dict[str, str]]] = {
        period: [] for period in wanted_periods
    }
    ordered_records = _collect_ordered_candidates(fragments, rule)
    # 单期：整体窗口固定为 1，只认方向边界那一条。
    # 多期：其它期各取自己的方向边界，但**严格期必须落在整体方向边界上**，
    # 否则就是“只要文档里出现过就算命中”的取首尾凑成功（AGENTS 明令禁止）。
    overall_boundary = _global_direction_window(
        ordered_records,
        rule.position,
        rule.parse_hint,
        per_period=False,
    )
    per_period_boundary = _global_direction_window(
        ordered_records,
        rule.position,
        rule.parse_hint,
        per_period=len(wanted_periods) > 1,
    )
    for period in wanted_periods:
        # 冲突检查必须早于窗口切片：否则窗口外的冲突值会被静默丢弃。
        # 但范围要与窗口一致——只在本站主来源（含同文档派生块）内比对，
        # 否则 forum/forum_history 里别的文章会被误判成本站冲突。
        all_for_period = [
            record
            for record in ordered_records
            if period_matches(record.get("period", ""), period)
            and _is_conflict_scope_route(str(record.get("source_route", "")), rule.parse_hint)
        ]
        if period_value_conflict(all_for_period):
            if _is_strict(period):
                raise ValueError(
                    f"{period}同一期出现多个冲突候选"
                    f"（{describe_conflicting_candidates(all_for_period)}）"
                )
            # 非指定期冲突：不静默取值，留空交由 select_period_values 记为 missing。
            continue
        # 严格期必须同时命中整体方向边界，防止多期模式下越界取数。
        if _is_strict(period):
            if not any(
                period_matches(record.get("period", ""), period)
                for record in overall_boundary
            ):
                continue
        selected_boundary = [
            record
            for record in per_period_boundary
            if period_matches(record.get("period", ""), period)
        ]
        if not selected_boundary:
            continue
        candidates_by_period[period] = selected_boundary
    return candidates_by_period


def extract_historical_period_candidates_by_period(
    fragments: list[str | SourceDocument],
    rule: SiteRule,
    periods: list[str],
) -> dict[str, list[dict[str, str]]]:
    """Collect validated history after direction was confirmed separately."""
    ordered_records = _collect_ordered_candidates(fragments, rule)
    return {
        period: [
            record
            for record in ordered_records
            if period_matches(record.get("period", ""), period)
        ]
        for period in dict.fromkeys(periods)
    }


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
        if document.resource_required and document.resource_error:
            raise ValueError(f"页面资源不完整：{document.resource_error}")
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
        document_order = (
            document.document_order if document.document_order >= 0 else fragment_index
        )
        document_records = []
        for record_index, record in enumerate(all_records):
            document_records.append(
                {
                    **record,
                    "original_position": int(
                        record.get("original_position", record_index)
                    ),
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
    seen: set[tuple[str, str, str, tuple[str, int, int, int]]] = set()
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
            _candidate_position_key(candidate),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


AUTHORITATIVE_ROUTES = frozenset(
    {"page", "admin_api", "admin_browser", "browser_page", "period_detail"}
)

# 路由 -> 只有该 parse_hint 的站点才把它当主来源。
# user_forum 仅在 user_kill_head 时产生（forum.py 已做用户ID/锚点/字段三重校验），
# 对这类站它就是权威来源，不能当“别的文章”排除。
PRIMARY_ROUTE_BY_HINT = {
    "user_kill_head": "user_forum",
}

# 主来源文档无候选时允许回退的路由：同一文档派生的数据块。
# 不含 forum / forum_history / period_detail（那是别的文章）。
FALLBACK_ROUTES = frozenset(
    {"script", "inline_script", "iframe", "admin_script"}
)


def _is_primary_route(route: str, parse_hint: str) -> bool:
    if route in AUTHORITATIVE_ROUTES:
        return True
    return PRIMARY_ROUTE_BY_HINT.get(parse_hint.strip()) == route


def _is_conflict_scope_route(route: str, parse_hint: str) -> bool:
    """冲突比对范围 = 主来源 + 同文档派生块，与方向窗口保持一致。

    forum/forum_history/period_detail 是别的文章，不参与本站冲突判定，
    否则会把别家站点的值误判成本站同期冲突。
    """
    return _is_primary_route(route, parse_hint) or route in FALLBACK_ROUTES


def _global_direction_window(
    candidates: list[dict[str, str]],
    position: str,
    parse_hint: str = "",
    *,
    per_period: bool = False,
) -> list[dict[str, str]]:
    """方向窗口只在“本站主来源文档”内定界。

    主来源 = AUTHORITATIVE_ROUTES（page/admin_api/admin_browser/browser_page）
    + 该 parse_hint 专属的主来源路由（如 user_kill_head 的 user_forum）。

    为什么不能“全局取末条”：document_order 是收集顺序，page 恒为 0，辅助文档
    排在后面，取全局末条就等于取辅助文档的最后一行——底部方向仍会跨文档借值，
    且当辅助文档比权威页滞后时，还会把有权威值的站误判为失败。

    为什么不能“按文档分组各取一条”：主页面缺目标期、辅助文档恰好含目标期时，
    会把辅助文档的值当成本期结果，同期不同值也不会报冲突。

    回退：大量站（本批 149/240）的真实数据只存在于同一文档派生的脚本块，
    主来源文档无候选。此时放行 script/inline_script/iframe/admin_script，
    但绝不回退到“别的文章”（forum/forum_history/period_detail）。

    per_period=True 时按每个期数各取一条（顶部取该期首条、底部取该期末条），
    供多期取数使用；否则整体只返回首/末一条（单期语义，窗口固定为 1）。
    """
    if not is_strict_position_three_position(position):
        return candidates
    ordered = sorted(candidates, key=_candidate_order_key)
    if not ordered:
        return []
    primary = [
        candidate
        for candidate in ordered
        if _is_primary_route(str(candidate.get("source_route", "")), parse_hint)
    ]
    if primary:
        scoped = primary
    else:
        scoped = [
            candidate
            for candidate in ordered
            if str(candidate.get("source_route", "")) in FALLBACK_ROUTES
        ]
    if not scoped:
        # 既无主来源、也无同文档派生的数据块：宁可失败，不回退到别的文章。
        return []
    if not per_period:
        return [scoped[-1] if is_bottom_position(position) else scoped[0]]
    # 多期：每个期数在自己的主来源候选里取方向边界那一条。
    grouped: dict[str, list[dict[str, str]]] = {}
    for candidate in scoped:
        grouped.setdefault(str(candidate.get("period", "")), []).append(candidate)
    selected = [
        items[-1] if is_bottom_position(position) else items[0]
        for items in grouped.values()
        if items
    ]
    return sorted(selected, key=_candidate_order_key)


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
        part for part in (document.title, document.author, document.source) if part
    )


def select_period_records(
    candidates_by_period: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, str]]:
    records_by_period = {}
    for period, candidates in candidates_by_period.items():
        if candidates:
            selected = dict(candidates[0])
            selected["value"] = display_head_value(
                selected.get("value", "")
            ) or selected.get("value", "")
            records_by_period[period] = selected
    return records_by_period


def select_target_candidate(
    candidates: list[Candidate], target_period: str
) -> Candidate:
    matched = [
        candidate
        for candidate in candidates
        if period_matches(candidate.period, target_period)
    ]
    if not matched:
        raise ValueError(f"方向候选内未找到指定期数：{target_period}")
    signatures = {display_head_value(item.value) for item in matched}
    if len(signatures) > 1:
        raise ValueError(f"{target_period}同一期候选值冲突")
    if len({_candidate_position_key(item) for item in matched}) > 1:
        raise ValueError(f"{target_period}同一期原始边界不唯一")
    return matched[0]


def period_value_conflict(candidates: list[dict[str, str]]) -> bool:
    # 归一化后为空（非法值，如 5头）也要参与比较：否则两边都归一成空串，
    # 冲突判定失效，错误会被推迟到更泛化的地方暴露。
    signatures = {
        (display_head_value(str(candidate.get("value") or "")) or str(candidate.get("value") or "").strip())
        for candidate in candidates
    }
    signatures.discard("")
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
        str(candidate.get("source_block_id", ""))
        if isinstance(candidate, dict)
        else candidate.document_key,
        int(candidate.get("document_order", -1))
        if isinstance(candidate, dict)
        else int(getattr(candidate, "document_order", -1)),
        int(candidate.get("block_order", candidate.get("original_position", -1)))
        if isinstance(candidate, dict)
        else int(getattr(candidate, "block_order", -1)),
        int(candidate.get("original_position", -1))
        if isinstance(candidate, dict)
        else candidate.original_position,
    )


def describe_conflicting_candidates(candidates: list[dict[str, str]]) -> str:
    details = []
    seen = set()
    for candidate in candidates:
        raw_value = str(candidate.get("value") or "")
        # 非法值（如 5头）归一化后为空，但必须出现在报错里，否则排障看不到原文。
        value = display_head_value(raw_value) or raw_value.strip()
        raw_line = candidate.get("raw_line", "")
        if not value:
            continue
        key = (value, raw_line)
        if key in seen:
            continue
        seen.add(key)
        position = candidate.get("original_position", "?")
        details.append(
            f"{value}@原始位置{position}: {raw_line}"
            if raw_line
            else f"{value}@原始位置{position}"
        )
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
            conflict_errors.append(
                f"{period}同一期原始边界不唯一（相同标准化数据出现在多个来源位置）"
            )
            continue
        period_record = records_by_period.get(period)
        raw = (
            period_record["value"]
            if period_record and period_record.get("value")
            else ""
        )
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
        "excluded_heads_from_three_combo",
    }


def limit_records_to_strict_three(
    indexed_records: list[tuple[int, dict[str, str]]],
    total_records: int,
    position: str,
) -> list[tuple[int, dict[str, str]]]:
    if is_bottom_position(position):
        start_index = max(total_records - 1, 0)
        return [
            (index, record) for index, record in indexed_records if index >= start_index
        ]
    return [(index, record) for index, record in indexed_records if index < 1]


def position_three_label(position: str) -> str:
    return "底部最后一条" if is_bottom_position(position) else "顶部第一条"


def find_target_fragment(
    fragments: list[str | SourceDocument], rule: SiteRule, target_period: str = ""
) -> str | None:
    if not target_period:
        return None
    documents = [
        _as_source_document(fragment, index) for index, fragment in enumerate(fragments)
    ]
    candidates = extract_single_period_candidates_by_period(
        documents, rule, [target_period]
    ).get(target_period, [])
    if not candidates:
        return None
    selected_key = candidates[0].get("document_key", "")
    selected = next(
        (document for document in documents if document.key == selected_key), None
    )
    return selected.source if selected else None


def find_target_record(
    fragments: list[str | SourceDocument], rule: SiteRule, target_period: str
) -> dict[str, str] | None:
    candidates_by_period = extract_single_period_candidates_by_period(
        fragments, rule, [target_period]
    )
    candidates = candidates_by_period.get(target_period, [])
    if not candidates:
        return None
    if period_value_conflict(candidates):
        raise ValueError(
            f"{target_period}同一期出现多个冲突候选（{describe_conflicting_candidates(candidates)}）"
        )
    if period_boundary_ambiguity(candidates):
        raise ValueError(
            f"{target_period}同一期原始边界不唯一（相同标准化数据出现在多个来源位置）"
        )
    return select_period_records(candidates_by_period).get(target_period)


def find_latest_available_record(
    fragments: list[str | SourceDocument], rule: SiteRule
) -> dict[str, str] | None:
    candidates = _global_direction_window(
        _collect_ordered_candidates(fragments, rule), rule.position, rule.parse_hint
    )
    return candidates[0] if candidates else None


def invalid_target_value_error(
    fragments: list[str | SourceDocument], rule: SiteRule, target_period: str
) -> str:
    if (
        not target_period
        or rule.parse_hint != "anchored_missing_head_from_four_combo"
    ):
        return ""
    reasons: set[str] = set()
    for index, fragment in enumerate(fragments):
        document = _as_source_document(fragment, index)
        if document.resource_error or not contains_text(
            _document_evidence_text(document), rule.anchor
        ):
            continue
        compact = re.sub(r"\s+", "", html_to_text(document.source))
        shapes = parse_anchored_four_combo_shapes(compact, rule.anchor, rule.field)
        boundary = shapes[-1:] if is_bottom_position(rule.position) else shapes[:1]
        for shape in boundary:
            if not period_matches(str(shape["period"]), target_period):
                continue
            values = [str(value) for value in shape["values"]]
            if len(set(values)) != 4:
                reasons.add(
                    f"{target_period}四头组合包含重复头值（{'.'.join(values)}），"
                    "无法唯一得到缺失头"
                )
    return next(iter(reasons)) if len(reasons) == 1 else ""


def is_bottom_position(position: str) -> bool:
    return position.strip().lower() in {"bottom", "尾部", "底部", "下"}


def _as_source_document(fragment: str | SourceDocument, index: int) -> SourceDocument:
    if isinstance(fragment, SourceDocument):
        return fragment
    return SourceDocument(str(fragment), "", f"legacy-{index}", document_order=index)

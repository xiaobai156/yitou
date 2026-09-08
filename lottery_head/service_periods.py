from __future__ import annotations

import httpx

from .documents import collect_fragments, load_initial_source_html, load_period_title_detail_fragments
from .documents.collector_details import FIRST_THREE_PAGES_PARSE_HINT
from .models import HeadRecord, SitePeriodData, SiteRule
from .network import build_client, get_text
from .selection import describe_conflicting_candidates, extract_period_candidates_by_period, find_latest_available_record, invalid_target_value_error, period_boundary_ambiguity, period_value_conflict, position_three_label, select_period_records, select_period_values
from .service_results import failed_head_record, head_record_from_extracted, locked_target_period_error, make_site_period_data, required_resource_error


def fetch_rule_with_period_data(
    rule: SiteRule,
    *,
    client: httpx.Client,
    target_period: str,
    periods: list[str],
    get_text_fn=get_text,
    collect_fragments_fn=collect_fragments,
    extract_candidates_fn=extract_period_candidates_by_period,
    select_records_fn=select_period_records,
    conflict_check_fn=period_value_conflict,
    boundary_check_fn=period_boundary_ambiguity,
    describe_conflicts_fn=describe_conflicting_candidates,
    failed_record_fn=failed_head_record,
    success_record_fn=head_record_from_extracted,
    locked_error_fn=locked_target_period_error,
    invalid_error_fn=invalid_target_value_error,
    position_label_fn=position_three_label,
    select_values_fn=select_period_values,
    make_period_data_fn=make_site_period_data,
):
    try:
        html = load_initial_source_html(client, rule.url, get_text_fn=get_text_fn)
        fragments = collect_fragments_fn(
            html,
            client=client,
            source_url=rule.url,
            include_forum_history=False,
            target_period=target_period,
            target_periods=list(dict.fromkeys([target_period, *periods])),
            content_hint=rule.content_hint,
            field=rule.field,
            admin_api_url=rule.api_url,
            parse_hint=rule.parse_hint,
            site_rule=rule,
        )
        resource_error = required_resource_error(fragments)
        if resource_error:
            raise RuntimeError(resource_error)
        period_candidates = extract_candidates_fn(fragments, rule, [target_period, *periods])
        records_by_period = select_records_fn(period_candidates)
        target_conflict = conflict_check_fn(period_candidates.get(target_period, []))
        extracted = records_by_period.get(target_period)
        target_error = ""
        target_boundary = boundary_check_fn(period_candidates.get(target_period, []))
        if target_conflict:
            conflict_detail = describe_conflicts_fn(period_candidates.get(target_period, []))
            target_error = f"{target_period}同一期出现多个冲突候选（{conflict_detail}），已拒绝写入成功"
            record = failed_record_fn(
                rule,
                target_error,
            )
        elif target_boundary:
            target_error = f"{target_period}同一期原始边界不唯一（相同标准化数据出现在多个来源位置），已拒绝写入成功"
            record = failed_record_fn(
                rule,
                target_error,
            )
        elif extracted:
            record = success_record_fn(rule, extracted)
        else:
            target_error = invalid_error_fn(fragments, rule, target_period) or locked_error_fn(fragments, target_period) or (
                f"{target_period}不在{position_label_fn(rule.position)}"
            )
            record = failed_record_fn(
                rule,
                target_error,
            )
        values, missing, conflict_errors = select_values_fn(period_candidates, records_by_period, periods)
        return record, make_period_data_fn(
            rule,
            values,
            missing,
            "；".join(conflict_errors),
            records_by_period,
            {target_period: target_error} if target_error else {},
        )
    except Exception as exc:
        error = str(exc)
        return failed_record_fn(rule, error), make_period_data_fn(
            rule,
            {},
            list(periods),
            error,
            missing_reasons={period: error for period in periods},
        )


def fetch_rule_for_any_period(
    rule: SiteRule,
    *,
    client: httpx.Client,
    periods: list[str],
    get_text_fn=get_text,
    collect_fragments_fn=collect_fragments,
    load_period_details_fn=load_period_title_detail_fragments,
    extract_candidates_fn=extract_period_candidates_by_period,
    select_records_fn=select_period_records,
    conflict_check_fn=period_value_conflict,
    boundary_check_fn=period_boundary_ambiguity,
    describe_conflicts_fn=describe_conflicting_candidates,
    success_record_fn=head_record_from_extracted,
    failed_record_fn=failed_head_record,
    latest_record_fn=find_latest_available_record,
    invalid_error_fn=invalid_target_value_error,
) -> HeadRecord:
    wanted_periods = list(dict.fromkeys(period for period in periods if period))
    if not wanted_periods:
        return failed_record_fn(rule, "没有指定可抓取期数")
    try:
        html = load_initial_source_html(client, rule.url, get_text_fn=get_text_fn)
        if rule.parse_hint in {"period_title_detail", FIRST_THREE_PAGES_PARSE_HINT}:
            conflict_details = []
            for period in wanted_periods:
                fragments = load_period_details_fn(
                    client,
                    html,
                    rule.url,
                    rule.content_hint,
                    rule.field,
                    periods=[period],
                    position=rule.position,
                    max_list_pages=3 if rule.parse_hint == FIRST_THREE_PAGES_PARSE_HINT else None,
                )
                resource_error = required_resource_error(fragments)
                if resource_error:
                    raise RuntimeError(resource_error)
                period_candidates = extract_candidates_fn(fragments, rule, [period])
                candidates = period_candidates.get(period, [])
                if conflict_check_fn(candidates):
                    conflict_details.append(f"{period}（{describe_conflicts_fn(candidates)}）")
                    continue
                if boundary_check_fn(candidates):
                    conflict_details.append(f"{period}（原始边界不唯一）")
                    continue
                extracted = select_records_fn(period_candidates).get(period)
                if extracted:
                    return success_record_fn(rule, extracted)
            if conflict_details:
                return failed_record_fn(
                    rule,
                    f"指定期数均未得到唯一结果；冲突候选：{'；'.join(conflict_details)}",
                )
            return failed_record_fn(rule, f"指定期数{'、'.join(wanted_periods)}均未解析出目标值")
        fragments = collect_fragments_fn(
            html,
            client=client,
            source_url=rule.url,
            include_forum_history=False,
            target_period="",
            target_periods=wanted_periods,
            content_hint=rule.content_hint,
            field=rule.field,
            admin_api_url=rule.api_url,
            parse_hint=rule.parse_hint,
            site_rule=rule,
        )
        resource_error = required_resource_error(fragments)
        if resource_error:
            raise RuntimeError(resource_error)
        period_candidates = extract_candidates_fn(fragments, rule, wanted_periods)
        records_by_period = select_records_fn(period_candidates)
        conflict_details = []
        for period in wanted_periods:
            candidates = period_candidates.get(period, [])
            if conflict_check_fn(candidates):
                conflict_details.append(f"{period}（{describe_conflicts_fn(candidates)}）")
                continue
            if boundary_check_fn(candidates):
                conflict_details.append(f"{period}（原始边界不唯一）")
                continue
            extracted = records_by_period.get(period)
            if extracted:
                return success_record_fn(rule, extracted)
        if conflict_details:
            return failed_record_fn(
                rule,
                f"指定期数均未得到唯一结果；冲突候选：{'；'.join(conflict_details)}",
            )
        invalid_details = [
            reason
            for period in wanted_periods
            if (reason := invalid_error_fn(fragments, rule, period))
        ]
        if invalid_details:
            return failed_record_fn(rule, "；".join(invalid_details))
        latest_record = latest_record_fn(fragments, rule)
        latest_text = f"，页面最新为{latest_record['period']}" if latest_record else ""
        return failed_record_fn(rule, f"指定期数{'、'.join(wanted_periods)}均未解析出目标值{latest_text}")
    except Exception as exc:
        return failed_record_fn(rule, str(exc))


def fetch_site_period_data(
    rule: SiteRule,
    periods: list[str],
    client: httpx.Client | None = None,
    *,
    client_factory=build_client,
    period_fetcher=fetch_rule_with_period_data,
):
    if not periods:
        return SitePeriodData(
            section=rule.section,
            field=rule.field,
            position=rule.position,
            url=rule.url,
            parse_hint=rule.parse_hint,
            period_values={},
            missing=[],
            error="没有可检测期数",
        )
    try:
        if client is None:
            with client_factory() as owned_client:
                return fetch_site_period_data(
                    rule,
                    periods,
                    client=owned_client,
                    client_factory=client_factory,
                    period_fetcher=period_fetcher,
                )
        _, baseline = period_fetcher(
            rule,
            client=client,
            target_period=periods[0],
            periods=periods,
        )
        return SitePeriodData(
            section=rule.section,
            field=rule.field,
            position=rule.position,
            url=rule.url,
            parse_hint=rule.parse_hint,
            period_values=dict(baseline.period_values),
            missing=list(baseline.missing),
            error=baseline.error,
            period_records=dict(baseline.period_records),
            missing_reasons=dict(baseline.missing_reasons),
        )
    except Exception as exc:
        return SitePeriodData(
            section=rule.section,
            field=rule.field,
            position=rule.position,
            url=rule.url,
            parse_hint=rule.parse_hint,
            period_values={},
            missing=list(periods),
            error=str(exc),
            missing_reasons={period: str(exc) for period in periods},
        )

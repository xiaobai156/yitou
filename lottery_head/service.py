from __future__ import annotations

import httpx

from .documents import collect_fragments, load_period_title_detail_fragments
from .models import HeadRecord, SitePeriodData, SiteRule
from .network import build_client, get_text
from .parsers.common import period_number
from .selection import describe_conflicting_candidates, extract_period_candidates_by_period, find_latest_available_record, find_target_record, period_boundary_ambiguity, period_value_conflict, position_three_label, select_period_records, select_period_values
from .service_periods import fetch_rule_for_any_period as _fetch_rule_for_any_period, fetch_rule_with_period_data as _fetch_rule_with_period_data, fetch_site_period_data as _fetch_site_period_data
from .service_results import contains_access_denied_message, failed_head_record, fragment_source, head_record_from_extracted, locked_target_period_error, make_site_period_data, unresolved_rule_error
from .service_single import fetch_rule as _fetch_rule


def fetch_rule(rule: SiteRule, *, client: httpx.Client, target_period: str = "") -> HeadRecord:
    return _fetch_rule(
        rule,
        client=client,
        target_period=target_period,
        get_text_fn=get_text,
        collect_fragments_fn=collect_fragments,
        find_target_fn=find_target_record,
        find_latest_fn=find_latest_available_record,
        period_number_fn=period_number,
        unresolved_error_fn=unresolved_rule_error,
        failed_record_fn=failed_head_record,
        success_record_fn=head_record_from_extracted,
    )


def fetch_rule_with_period_data(
    rule: SiteRule,
    *,
    client: httpx.Client,
    target_period: str,
    periods: list[str],
):
    return _fetch_rule_with_period_data(
        rule,
        client=client,
        target_period=target_period,
        periods=periods,
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
        position_label_fn=position_three_label,
        select_values_fn=select_period_values,
        make_period_data_fn=make_site_period_data,
    )


def fetch_rule_for_any_period(
    rule: SiteRule,
    *,
    client: httpx.Client,
    periods: list[str],
) -> HeadRecord:
    return _fetch_rule_for_any_period(
        rule,
        client=client,
        periods=periods,
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
    )


def fetch_rule_with_new_client(rule: SiteRule, target_period: str) -> HeadRecord:
    with build_client() as client:
        return fetch_rule(rule, client=client, target_period=target_period)


def fetch_rule_with_period_data_new_client(rule: SiteRule, target_period: str, periods: list[str]):
    with build_client() as client:
        return fetch_rule_with_period_data(rule, client=client, target_period=target_period, periods=periods)


def fetch_site_period_data(rule: SiteRule, periods: list[str], client: httpx.Client | None = None):
    return _fetch_site_period_data(
        rule,
        periods,
        client=client,
        client_factory=build_client,
        period_fetcher=fetch_rule_with_period_data,
    )

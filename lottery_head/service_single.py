from __future__ import annotations

import httpx

from .documents import collect_fragments
from .models import HeadRecord, SiteRule
from .network import get_text
from .parsers.common import period_number
from .selection import find_latest_available_record, find_target_record
from .service_results import failed_head_record, head_record_from_extracted, unresolved_rule_error


def fetch_rule(
    rule: SiteRule,
    *,
    client: httpx.Client,
    target_period: str = "",
    get_text_fn=get_text,
    collect_fragments_fn=collect_fragments,
    find_target_fn=find_target_record,
    find_latest_fn=find_latest_available_record,
    period_number_fn=period_number,
    unresolved_error_fn=unresolved_rule_error,
    failed_record_fn=failed_head_record,
    success_record_fn=head_record_from_extracted,
) -> HeadRecord:
    try:
        html = get_text_fn(client, rule.url)
        fragments = collect_fragments_fn(
            html,
            client=client,
            source_url=rule.url,
            include_forum_history=False,
            target_period=target_period,
            target_periods=[target_period] if target_period else None,
            content_hint=rule.content_hint,
            field=rule.field,
            admin_api_url=rule.api_url,
            parse_hint=rule.parse_hint,
            site_rule=rule,
        )
        extracted = find_target_fn(fragments, rule, target_period)
        if not extracted:
            latest_record = find_latest_fn(fragments, rule)
            if target_period and latest_record and period_number_fn(latest_record["period"]) < period_number_fn(target_period):
                error = f"未更新到{target_period}，最新为{latest_record['period']}"
            else:
                error = unresolved_error_fn(rule, fragments, target_period)
            return failed_record_fn(rule, error)
        return success_record_fn(rule, extracted)
    except Exception as exc:
        return failed_record_fn(rule, str(exc))

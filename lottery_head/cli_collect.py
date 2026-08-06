from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .cli_support import format_completion_summary, format_progress_line
from .models import HeadRecord
from .service import fetch_rule_with_period_data
from .transport import FetchContext


def collect_rules(
    rules,
    target_period: str,
    periods: list[str],
    workers: int,
    *,
    context_factory=FetchContext,
    fetcher=fetch_rule_with_period_data,
    progress_formatter=format_progress_line,
    summary_formatter=format_completion_summary,
    clock=time.monotonic,
    print_fn=print,
) -> tuple[list[HeadRecord], list[object]]:
    records: list[HeadRecord | None] = [None] * len(rules)
    baseline_data: list[object | None] = [None] * len(rules)
    started_at = clock()
    with context_factory(max_workers=workers) as context:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    fetcher,
                    rule,
                    client=context,
                    target_period=target_period,
                    periods=periods,
                ): index
                for index, rule in enumerate(rules)
            }
            finished = success_count = failed_count = 0
            for future in as_completed(futures):
                index = futures[future]
                try:
                    record, site_data = future.result()
                except Exception as exc:
                    rule = rules[index]
                    record = HeadRecord(
                        rule.url,
                        rule.position,
                        rule.section,
                        rule.field,
                        "",
                        "",
                        "",
                        "failed",
                        f"运行异常：{exc}",
                        parse_hint=rule.parse_hint,
                    )
                    site_data = None
                records[index] = record
                baseline_data[index] = site_data
                finished += 1
                if record.status == "success":
                    success_count += 1
                else:
                    failed_count += 1
                print_fn(
                    "\r" + progress_formatter(
                        finished,
                        len(rules),
                        success_count,
                        failed_count,
                        clock() - started_at,
                        record.section,
                    ),
                    end="",
                    flush=True,
                )
    print_fn()
    print_fn(summary_formatter(success_count, failed_count), flush=True)
    return [record for record in records if record is not None], [item for item in baseline_data if item is not None]

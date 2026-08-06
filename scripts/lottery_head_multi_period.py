from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lottery_head.cli import format_completion_summary, format_progress_line
from lottery_head.config import load_rules
from lottery_head.models import HeadRecord, SiteRule
from lottery_head.output import commit_artifacts_transaction, format_failure_reason
from lottery_head.service import fetch_rule_for_any_period
from lottery_head.settings import FAILURE_SUMMARY_DIR, MAX_WORKERS, SUCCESS_TAIL_LINES, SUMMARY_DIR
from lottery_head.transport import FetchContext
from lottery_head.validation import parse_target_period


def build_failed_records(records: list[HeadRecord]) -> list[HeadRecord]:
    return [record for record in records if record.status != "success"]


def output_label(periods: list[str]) -> str:
    return "_".join(periods)


def write_multi_period_outputs(
    records: list[HeadRecord],
    periods: list[str],
) -> tuple[Path, Path, Path]:
    label = output_label(periods)
    json_path = Path(".tmp") / f"multi_period_any_{label}.json"
    success_path = SUMMARY_DIR / f"{label}多期抓取成功-一头.txt"
    failed_path = FAILURE_SUMMARY_DIR / f"{label}多期汇总失败-一头.txt"
    success_lines = ["名称 字段 命中期数 数据 网站"]
    success_lines.extend(
        f"{record.section} {record.field} {record.period} {record.value} {record.url}"
        for record in records
        if record.status == "success"
    )
    success_lines.extend(SUCCESS_TAIL_LINES)
    failed_lines = [
        f"多期范围：{' '.join(periods)}",
        "规则：每个目录只抓取一次；任意一期成功即通过；全部指定期数失败才进入本报告",
        "",
        "名称 字段 原因 网站",
    ]
    failed_entries = [
        f"{record.section} {record.field} {format_failure_reason(record.error)} {record.url}"
        for record in build_failed_records(records)
    ]
    failed_text = "\n".join(failed_lines)
    if failed_entries:
        failed_text += "\n" + "\n\n".join(failed_entries)
    commit_artifacts_transaction(
        {
            json_path: json.dumps(
                [asdict(record) for record in records],
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            success_path: "\n".join(success_lines).encode("utf-8"),
            failed_path: failed_text.encode("utf-8"),
        }
    )
    return json_path, success_path, failed_path


def _failed_record(rule: SiteRule, error: str) -> HeadRecord:
    return HeadRecord(
        rule.url,
        rule.position,
        rule.section,
        rule.field,
        "",
        "",
        "",
        "failed",
        error,
        parse_hint=rule.parse_hint,
    )


def _collect(rules: list[SiteRule], periods: list[str], workers: int) -> list[HeadRecord]:
    records: list[HeadRecord | None] = [None] * len(rules)
    started_at = time.monotonic()
    with FetchContext(max_workers=workers) as client:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    fetch_rule_for_any_period,
                    rule,
                    client=client,
                    periods=periods,
                ): index
                for index, rule in enumerate(rules)
            }
            finished = success_count = failed_count = 0
            for future in as_completed(futures):
                index = futures[future]
                try:
                    record = future.result()
                except Exception as exc:
                    record = _failed_record(rules[index], f"运行异常：{exc}")
                records[index] = record
                finished += 1
                if record.status == "success":
                    success_count += 1
                else:
                    failed_count += 1
                print(
                    "\r"
                    + format_progress_line(
                        finished,
                        len(rules),
                        success_count,
                        failed_count,
                        time.monotonic() - started_at,
                        record.section,
                    ),
                    end="",
                    flush=True,
                )
    print()
    print(format_completion_summary(success_count, failed_count), flush=True)
    return [record for record in records if record is not None]


def main(argv: list[str] | None = None) -> int:
    raw_periods = argv if argv is not None else sys.argv[1:]
    try:
        periods = list(
            dict.fromkeys(
                parse_target_period(period)
                for period in raw_periods
                if period.strip()
            )
        )
        rules = load_rules()
    except ValueError as exc:
        print(f"期数或站点配置无效：{exc}")
        return 2
    if not periods:
        print("必须指定多个期数，例如：py -3 scripts\\lottery_head_multi_period.py 187 188 189")
        return 2
    print(f"multi-period | {' '.join(periods)}", flush=True)
    print(f"start | sites={len(rules)} | workers={MAX_WORKERS}", flush=True)
    records = _collect(rules, periods, MAX_WORKERS)
    json_path, success_path, failed_path = write_multi_period_outputs(records, periods)
    print(f"json | {json_path}")
    print(f"success | {success_path}")
    print(f"failed | {failed_path}")
    print("baseline | skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import re
from pathlib import Path

import sys


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from lottery_head.output import format_failure_reason
from lottery_head.settings import FAILURE_SUMMARY_DIR


TMP_DIR = PROJECT_DIR / ".tmp"


def period_label(value: str) -> str:
    match = re.search(r"\d{1,3}", value)
    return f"{match.group(0)}期" if match else value


def snapshot_path(period: str) -> Path:
    return TMP_DIR / f"multi_period_records_{period_label(period)}.json"


def snapshot_paths(period: str) -> list[Path]:
    label = period_label(period)
    raw = period.replace("期", "")
    return [
        TMP_DIR / f"multi_period_records_{label}.json",
        TMP_DIR / f"multi_period_records_{period}.json",
        TMP_DIR / f"multi_period_records_{raw}.json",
    ]


def record_key(record: dict) -> tuple[str, str, str]:
    return (
        str(record.get("section", "")),
        str(record.get("field", "")),
        str(record.get("url", "")),
    )


def load_period_records(periods: list[str]) -> dict[str, list[dict]]:
    loaded = {}
    for period in periods:
        label = period_label(period)
        path = next((candidate for candidate in snapshot_paths(period) if candidate.exists()), None)
        if not path:
            raise FileNotFoundError(f"缺少{label}抓取快照，无法生成多期汇总")
        loaded[label] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def build_all_failed_rows(period_records: dict[str, list[dict]]) -> list[dict]:
    successes = set()
    failures: dict[tuple[str, str, str], dict[str, object]] = {}
    for period, records in period_records.items():
        for record in records:
            key = record_key(record)
            if record.get("status") == "success":
                successes.add(key)
                continue
            item = failures.setdefault(
                key,
                {
                    "section": key[0],
                    "field": key[1],
                    "url": key[2],
                    "period_errors": {},
                },
            )
            item["period_errors"][period] = format_failure_reason(str(record.get("error", "")))
    return [
        item
        for key, item in failures.items()
        if key not in successes and len(item["period_errors"]) == len(period_records)
    ]


def write_summary(periods: list[str], rows: list[dict]) -> Path:
    labels = [period_label(period) for period in periods]
    output_path = FAILURE_SUMMARY_DIR / f"{'_'.join(labels)}多期汇总失败-一头.txt"
    FAILURE_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"多期范围：{' '.join(labels)}",
        "规则：任意一期成功=通过；全部期数失败=失败",
        "",
        "名称 字段 网站 各期失败原因",
    ]
    if not rows:
        lines.append("无全部失败目录")
    for row in rows:
        period_errors = "；".join(
            f"{period}:{row['period_errors'][period]}"
            for period in labels
            if period in row["period_errors"]
        )
        lines.append(f"{row['section']} {row['field']} {row['url']} {period_errors}")
    header = "\n".join(lines[:4])
    row_lines = lines[4:]
    output = header
    if row_lines:
        output += "\n" + "\n\n".join(row_lines)
    output_path.write_text(output, encoding="utf-8")
    return output_path


def main() -> int:
    periods = [arg for arg in sys.argv[1:] if arg.strip()]
    if not periods:
        print("必须指定多个期数，例如：py -3.10 scripts\\summarize_multi_period_failures.py 187 188 189")
        return 2
    rows = build_all_failed_rows(load_period_records(periods))
    output_path = write_summary(periods, rows)
    print(f"multi-period failed summary | {output_path}")
    print(f"all-period failed sites | {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

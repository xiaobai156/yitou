from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lottery_head.cache import build_cache_payload, read_validated_cache
from lottery_head.cli_collect import collect_rules
from lottery_head.cli_support import _period_number
from lottery_head.config import load_rules
from lottery_head.output import commit_artifacts_transaction
from lottery_head.retry_failed import (
    match_failed_rules,
    merge_failed_txt,
    merge_success_txt,
    read_failed_targets,
)
from lottery_head.settings import (
    FAILURE_SUMMARY_DIR,
    RECENT_10_CACHE_PATH,
    SUMMARY_DIR,
)
from lottery_head.validation import parse_target_period


def validate_retry_window(existing: dict, target_period: str) -> None:
    if target_period not in existing.get("periods", []):
        raise ValueError(f"目标期数{target_period}不在缓存窗口")


def ensure_retry_inputs_unchanged(expected: dict[Path, bytes | None]) -> None:
    for path, original in expected.items():
        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise RuntimeError(f"正式文件在重抓期间发生变化，已停止写入：{path}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("用法：python -u scripts/retry_failed_sites.py 251期")
        return 2
    target_period = parse_target_period(argv[0])
    period_number = _period_number(target_period)
    failure_path = FAILURE_SUMMARY_DIR / f"{period_number}期失败-一头.txt"
    if not failure_path.exists():
        print(f"失败TXT不存在：{failure_path}")
        return 2
    targets = read_failed_targets(failure_path, target_period)
    if not targets:
        print(f"失败TXT中没有{target_period}的失败站点")
        return 2
    all_rules = load_rules()
    rules = match_failed_rules(targets, all_rules)
    cache_original = RECENT_10_CACHE_PATH.read_bytes() if RECENT_10_CACHE_PATH.exists() else None
    if cache_original is None:
        existing = None
    else:
        from lottery_head.cache_validation import validate_cache_snapshot
        existing = validate_cache_snapshot(json.loads(cache_original.decode("utf-8")), all_rules)
    if existing is None:
        print("缓存无效，未写入任何结果")
        return 1
    try:
        validate_retry_window(existing, target_period)
    except ValueError:
        print(f"目标期数{target_period}不在缓存窗口，三份文件保持原样")
        return 1
    success_path = SUMMARY_DIR / f"{period_number}期-头.txt"
    failed_path = FAILURE_SUMMARY_DIR / f"{period_number}期失败-一头.txt"
    expected = {path: path.read_bytes() if path.exists() else None for path in (success_path, failed_path)}
    expected[RECENT_10_CACHE_PATH] = cache_original
    print(f"retry-failed | period={target_period} sites={len(rules)}", flush=True)

    records, _ = collect_rules(rules, target_period, [target_period], 1)
    records = [record for record in records if record.status == "success"]
    if not records:
        print("本轮全部仍失败，所有正式文件保持不变")
        return 1

    cache = build_cache_payload(
        records,
        all_rules,
        existing["latest_period"],
        existing,
        attempted_period=target_period,
    )
    from copy import deepcopy
    merged = deepcopy(existing)
    generated = {
        (entry["identity"]["section"], entry["identity"]["url"], entry["identity"]["position"], entry["identity"]["parse_hint"]): entry
        for entry in cache["sites"]
    }
    for entry in merged["sites"]:
        identity = entry["identity"]
        key = (identity["section"], identity["url"], identity["position"], identity["parse_hint"])
        if key in generated:
            for key in ("values", "positions", "provenance", "missing"):
                new = generated[(identity["section"], identity["url"], identity["position"], identity["parse_hint"])] [key]
                if target_period in new:
                    entry[key][target_period] = new[target_period]
                else:
                    entry[key].pop(target_period, None)
    from lottery_head.cache import validate_cache_snapshot
    validate_cache_snapshot(merged, all_rules)
    artifacts = {
        success_path: merge_success_txt(success_path, records),
        failed_path: merge_failed_txt(failed_path, records, target_period),
        RECENT_10_CACHE_PATH: json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8"),
    }
    try:
        ensure_retry_inputs_unchanged(expected)
        commit_artifacts_transaction(artifacts)
    except RuntimeError as exc:
        print(f"写入停止：{exc}")
        return 1
    success = sum(record.status == "success" for record in records)
    print(f"完成 | 成功={success} 失败={len(rules) - success}", flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

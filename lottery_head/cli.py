from __future__ import annotations

from pathlib import Path

from .cache import (
    build_cache_payload,
    cache_update_allowed,
    read_validated_cache,
    validate_cache_snapshot,
)
from .config import load_rules
from .cli_collect import collect_rules
from .cli_support import _next_cache_latest, _period_number, _reject_historical_period, format_completion_summary, format_progress_line, parse_args
from .output import build_single_period_artifacts, commit_artifacts_transaction
from .service import fetch_rule_with_period_data
from .settings import MAX_WORKERS, RECENT_10_CACHE_PATH
from .transport import FetchContext
from .validation import parse_target_period


def _collect(
    rules,
    target_period: str,
    periods: list[str],
    workers: int,
) -> tuple[list[object], list[object]]:
    return collect_rules(
        rules,
        target_period,
        periods,
        workers,
        context_factory=FetchContext,
        fetcher=fetch_rule_with_period_data,
        progress_formatter=format_progress_line,
        summary_formatter=format_completion_summary,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        target_period = parse_target_period(args.period)
        workers = int(args.workers)
        if workers < 1 or workers > MAX_WORKERS:
            raise ValueError(f"并发必须在1到{MAX_WORKERS}之间")
        rules = load_rules()
    except (ValueError, SystemExit) as exc:
        print(exc)
        return 2

    collection_periods = [target_period]
    print(f"target_period | {target_period}", flush=True)
    print(f"start | sites={len(rules)} | workers={workers}", flush=True)

    records, site_data = _collect(rules, target_period, collection_periods, workers)
    # Decide the live outcome before touching the optional duplicate-check cache.
    adjusted_records = records
    success_count = sum(
        record.status == "success"
        and record.period
        and parse_target_period(record.period) == target_period
        for record in adjusted_records
    )
    total_count = len(rules)
    current_success = success_count > 0
    cache_allowed = cache_update_allowed(success_count, total_count)
    success_rate = (success_count * 100 / total_count) if total_count else 0.0
    print(
        f"cache-policy | success={success_count}/{total_count} rate={success_rate:.2f}% threshold=>85% allowed={cache_allowed}",
        flush=True,
    )

    existing_cache = None
    cache_problem = ""
    # The live records are authoritative for this single-period run.  The
    # cache is read only after collection and is never allowed to alter them.
    cache_payload = None
    if not cache_allowed:
        print("cache | 成功率不超过85%，保持原缓存不变", flush=True)
    else:
        try:
            existing_cache = read_validated_cache(RECENT_10_CACHE_PATH, rules)
        except ValueError as exc:
            cache_problem = str(exc)
        if cache_problem:
            print(f"cache | {cache_problem}；仅作为缓存更新诊断，不影响本轮实时结果", flush=True)
    if cache_allowed and current_success:
        try:
            cache_latest = _next_cache_latest(existing_cache, target_period)
            cache_payload = build_cache_payload(
                adjusted_records,
                rules,
                cache_latest,
                existing_cache,
                attempted_period=target_period,
            )
            validate_cache_snapshot(cache_payload, rules)
            if not any(site.get("values") for site in cache_payload.get("sites", [])):
                raise ValueError("近10期缓存没有任何带来源证据的有效数据，拒绝写入")
        except ValueError as exc:
            cache_payload = None
            print(f"cache | {exc}；本轮实时结果不受影响，缓存不更新", flush=True)
    elif cache_allowed and existing_cache is not None:
        print("cache | 本轮没有可写入的唯一成功证据，保持原缓存不变", flush=True)
    elif cache_allowed:
        print("cache | 本轮没有可写入的唯一成功证据，不创建缓存", flush=True)
    if args.dry_run:
        print("dry-run | 已完成真实抓取和缓存门禁校验，未写TXT和缓存", flush=True)
        return 0

    artifacts = build_single_period_artifacts(
        adjusted_records,
        target_period,
        RECENT_10_CACHE_PATH,
        cache_payload,
        Path(".tmp"),
    )
    cache_artifact = {}
    if cache_payload is not None:
        cache_bytes = artifacts.pop(RECENT_10_CACHE_PATH, None)
        if cache_bytes is not None:
            cache_artifact[RECENT_10_CACHE_PATH] = cache_bytes
    try:
        commit_artifacts_transaction(artifacts)
    except Exception as exc:
        print(f"事务写入失败，已尝试恢复原文件：{exc}", flush=True)
        return 1
    cache_write_error = ""
    if cache_artifact:
        try:
            commit_artifacts_transaction(cache_artifact)
        except Exception as exc:
            cache_write_error = str(exc)
            print(f"cache | 缓存更新失败：{exc}；本轮实时结果已保留", flush=True)
    print(f"success | {next(path for path in artifacts if path.name == f'{target_period}-头.txt')}")
    print(f"failed | {next(path for path in artifacts if path.name == f'{target_period}失败-一头.txt')}")
    if current_success and cache_artifact and not cache_write_error:
        print(f"baseline | {RECENT_10_CACHE_PATH}")
        return 0
    print("baseline | 本轮未更新缓存" if not cache_write_error else "baseline | 缓存更新失败，实时结果不变")
    return 0 if current_success else 1

from __future__ import annotations

import argparse

from .settings import MAX_WORKERS
from .validation import parse_target_period


def format_progress_line(
    finished: int,
    total: int,
    success_count: int,
    failed_count: int,
    elapsed_seconds: float,
    section: str,
) -> str:
    percent = int(finished * 100 / total) if total else 100
    return (
        f"[进度 {finished}/{total} {percent}% 成功 {success_count} 失败 {failed_count} "
        f"用时 {elapsed_seconds:.1f}s] 当前：{section}"
    )


def format_completion_summary(success_count: int, failed_count: int) -> str:
    return f"完成：成功 {success_count} 条，失败 {failed_count} 条"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="严格抓取指定期杀一头数据")
    parser.add_argument("period", help="指定期数，例如201或201期")
    parser.add_argument("--dry-run", action="store_true", help="真实抓取但不写TXT和缓存")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"站点并发，默认{MAX_WORKERS}")
    return parser.parse_args(argv)


def _period_number(period: str) -> int:
    return int(parse_target_period(period)[:-1])


def _next_cache_latest(cache: dict | None, target_period: str) -> str:
    if cache is None:
        return target_period
    cached = parse_target_period(str(cache["latest_period"]))
    return target_period if _period_number(target_period) > _period_number(cached) else cached


def _reject_historical_period(cache: dict | None, target_period: str) -> str:
    if cache is None:
        return ""
    latest = parse_target_period(str(cache["latest_period"]))
    if _period_number(target_period) < _period_number(latest):
        return f"缓存最新为{latest}，本次指定{target_period}属于历史期数，禁止回抓"
    return ""

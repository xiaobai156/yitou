from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .cache import build_cache_payload_from_site_data, recent_periods, validate_cache_snapshot
from .config import RULES
from .models import SiteRule
from .output import commit_artifacts_transaction
from .service import fetch_site_period_data
from .settings import MAX_WORKERS, RECENT_10_CACHE_PATH
from .transport import FetchContext
from .validation import parse_target_period


def generate_periods(latest_period: str) -> list[str]:
    return recent_periods(parse_target_period(latest_period))


def atomic_write_json(path: Path, payload: object) -> None:
    commit_artifacts_transaction({path: json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")})


def write_baseline_snapshot(
    all_data,
    periods: list[str],
    latest_period: str,
    rules: list[SiteRule] | None = None,
) -> Path:
    active_rules = rules or RULES
    normalized_latest = parse_target_period(latest_period)
    normalized_periods = [parse_target_period(period) for period in periods]
    if normalized_periods != generate_periods(normalized_latest):
        raise ValueError("近10期缓存期数窗口异常，拒绝写入")
    if len(all_data) != len(active_rules):
        raise ValueError(f"近10期缓存目录数异常：配置{len(active_rules)}条，抓取结果{len(all_data)}条")
    payload = build_cache_payload_from_site_data(
        all_data,
        active_rules,
        normalized_latest,
        periods=normalized_periods,
    )
    validate_cache_snapshot(payload, active_rules)
    if not any(site["values"] for site in payload["sites"]):
        raise ValueError("近10期缓存没有任何带来源证据的数据，拒绝写入")
    atomic_write_json(RECENT_10_CACHE_PATH, payload)
    return RECENT_10_CACHE_PATH


def sync_site_period_baseline(target_period: str, rules: list[SiteRule] | None = None) -> Path:
    active_rules = rules or RULES
    periods = generate_periods(target_period)
    all_data = [None] * len(active_rules)
    with FetchContext(max_workers=MAX_WORKERS) as context:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(fetch_site_period_data, rule, periods, context): index
                for index, rule in enumerate(active_rules)
            }
            for future in as_completed(futures):
                all_data[futures[future]] = future.result()
    return write_baseline_snapshot([item for item in all_data if item is not None], periods, target_period, active_rules)

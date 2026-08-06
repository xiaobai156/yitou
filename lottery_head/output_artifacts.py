from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import HeadRecord
from .output_text import format_debug_txt, format_failed_txt, format_success_txt, result_file_period_label
from .settings import FAILURE_SUMMARY_DIR, SUMMARY_DIR


def build_single_period_artifacts(
    records: list[HeadRecord],
    target_period: str,
    cache_path: Path,
    cache_payload: object | None,
    debug_dir: Path,
) -> dict[Path, bytes | None]:
    period_label = result_file_period_label(target_period)
    success_path = SUMMARY_DIR / f"{period_label}-头.txt"
    failed_path = FAILURE_SUMMARY_DIR / f"{period_label}失败-一头.txt"
    debug_json_path = debug_dir / "lottery_head_records.json"
    debug_txt_path = debug_dir / "lottery_head_records.txt"
    artifacts = {
        success_path: format_success_txt(records).encode("utf-8"),
        failed_path: format_failed_txt(records, target_period).encode("utf-8") if any(record.status != "success" for record in records) else None,
        debug_json_path: json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2).encode("utf-8"),
        debug_txt_path: format_debug_txt(records).encode("utf-8"),
    }
    if cache_payload is not None:
        artifacts[cache_path] = json.dumps(cache_payload, ensure_ascii=False, indent=2).encode("utf-8")
    return artifacts


def write_success_txt(records: list[HeadRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_success_txt(records), encoding="utf-8")


def write_failed_txt(records: list[HeadRecord], path: Path, target_period: str = "") -> None:
    failed_records = [record for record in records if record.status != "success"]
    if not failed_records:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_failed_txt(records, target_period), encoding="utf-8")

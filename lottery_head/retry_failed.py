from __future__ import annotations

import re
from pathlib import Path

from .config import canonical_url, normalize_position
from .models import HeadRecord, SiteRule
from collections import Counter
from .output_text import failure_category, format_head_ranking


def record_identity(record: HeadRecord) -> tuple[str, str, str, str]:
    return (record.section, canonical_url(record.url), normalize_position(record.position), record.parse_hint)


FAILURE_ROW_RE = re.compile(
    r"^失败 (?P<section>.*?) (?P<url>https?://\S+) 方向: (?P<position>顶部|尾部) 期数: (?P<period>\d+期)\s*$"
)


def read_failed_targets(path: Path, target_period: str) -> list[tuple[str, str, str]]:
    targets = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = FAILURE_ROW_RE.match(line.strip())
        if not match or match.group("period") != target_period:
            continue
        target = (match.group("section"), match.group("url"), match.group("position"))
        if target not in targets:
            targets.append(target)
    return targets


def match_failed_rules(targets, rules: list[SiteRule]) -> list[SiteRule]:
    selected = []
    for section, url, position in targets:
        matches = [
            rule for rule in rules
            if rule.section == section
            and canonical_url(rule.url) == canonical_url(url)
            and normalize_position(rule.position) == normalize_position(position)
        ]
        if len(matches) != 1:
            raise ValueError(f"失败TXT中的站点无法唯一匹配正式配置：{section}")
        selected.append(matches[0])
    return selected


def merge_success_txt(path: Path, records: list[HeadRecord]) -> bytes:
    raw = path.read_bytes() if path.exists() else b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8-sig") if raw else ""
    marker_text = next((line for line in text.splitlines() if "内容" in line and "次数" in line and "排名" in line), None)
    if marker_text is None:
        raise ValueError(f"成功TXT缺少排行榜边界：{path}")
    prefix = text[: text.find(marker_text)]
    newline = "\r\n" if "\r\n" in text else "\n"
    existing = {}
    values = []
    for line in prefix.splitlines():
        match = re.match(r"^((?:[0-4]头)(?:、[0-4]头)*) (.+)$", line.strip())
        if match:
            existing[match.group(2)] = match.group(1)
            values.extend(re.findall(r"[0-4]头", match.group(1)))
    additions = []
    batch = {}
    for record in records:
        if record.status != "success":
            continue
        if record.section in batch and batch[record.section] != record.value:
            raise ValueError(f"本批成功值冲突：{record.section}")
        batch[record.section] = record.value
        old = existing.get(record.section)
        if old is None:
            if f"{record.value} {record.section}" not in additions:
                additions.append(f"{record.value} {record.section}")
            values.extend(re.findall(r"[0-4]头", record.value))
        elif old != record.value:
            raise ValueError(f"成功TXT已有同期值冲突：{record.section} 当前{old}，实抓{record.value}")
    body = prefix.rstrip("\r\n") + (newline + newline.join(additions) if additions else "") + newline + newline
    result = (body + newline.join(format_head_ranking(values)) + newline).encode("utf-8")
    return (b"\xef\xbb\xbf" if bom else b"") + result


def merge_failed_txt(path: Path, target_records: list[HeadRecord], target_period: str) -> bytes | None:
    raw = path.read_bytes() if path.exists() else b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    old = raw.decode("utf-8-sig") if raw else ""
    old = re.split(r"(?m)^失败分类统计\s*$", old)[0]
    blocks = re.split(r"(?m)(?=^失败 )", old)
    target_ids = {(record.section, canonical_url(record.url), normalize_position(record.position)) for record in target_records if record.status == "success"}
    kept = []
    for block in blocks:
        first = block.splitlines()[0] if block.splitlines() else ""
        match = FAILURE_ROW_RE.match(first.strip())
        if match and (match.group("section"), canonical_url(match.group("url")), normalize_position(match.group("position"))) in target_ids and match.group("period") == target_period:
            continue
        if block.strip() and not block.lstrip().startswith("失败分类统计"):
            kept.append(re.split(r"(?m)^失败分类统计\s*$", block)[0].strip())
    if not kept:
        return None
    categories = Counter(failure_category(block) for block in kept)
    kept.append("\n".join(["失败分类统计", *[f"{key} {count}条" for key, count in categories.items()]]))
    result = (newline + newline).join(item.replace("\r\n", "\n").replace("\n", newline) for item in kept).encode("utf-8") + newline.encode("utf-8")
    return (b"\xef\xbb\xbf" if bom else b"") + result

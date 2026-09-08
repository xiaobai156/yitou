from __future__ import annotations

import re
from pathlib import Path

from .config import canonical_url, normalize_position, rule_identity
from .models import HeadRecord, SiteRule
from collections import Counter
from .output_text import failure_category


def format_head_ranking(values: list[str]) -> list[str]:
    counts = Counter(value for value in values if re.fullmatch(r"[0-4]头", value))
    return ["内容\t次数\t排名", *[f"{value}\t{count}\t{rank}" for rank, (value, count) in enumerate(sorted(counts.items(), key=lambda item: (-item[1], item[0])), 1)]]


def record_identity(record: HeadRecord) -> tuple[str, str, str, str]:
    return (record.section, canonical_url(record.url), normalize_position(record.position), record.parse_hint)


FAILURE_ROW_RE = re.compile(
    r"^\s*失败\s+(?P<section>.*?)\s+(?P<url>https?://\S+)\s+方向:\s*(?P<position>\S+)\s+期数:\s*(?P<period>\d+期)\s*$",
    re.IGNORECASE,
)


def _parse_failure_header(line: str, target_period: str | None = None):
    match = FAILURE_ROW_RE.match(line.rstrip("\r\n"))
    if not match:
        return None
    try:
        position = normalize_position(match.group("position"))
        url = canonical_url(match.group("url"))
    except ValueError as exc:
        raise ValueError(f"失败TXT记录无法解析：{line.strip()}") from exc
    if target_period and match.group("period") != target_period:
        return None
    return (match.group("section").strip(), url, position, match.group("period"))


def read_failed_targets(path: Path | bytes, target_period: str) -> list[tuple[str, str, str]]:
    targets = []
    raw = path if isinstance(path, bytes) else path.read_bytes()
    for line in raw.decode("utf-8-sig").splitlines():
        if line.lstrip().startswith("失败") and not line.lstrip().startswith("失败分类统计") and _parse_failure_header(line) is None:
            raise ValueError(f"失败TXT存在无法解析的记录：{line.strip()}")
        parsed = _parse_failure_header(line, target_period)
        if parsed is None:
            continue
        target = parsed[:3]
        if target not in targets:
            targets.append(target)
    return targets


def match_failed_rules(targets, rules: list[SiteRule]) -> list[SiteRule]:
    selected = []
    seen = set()
    for section, url, position in targets:
        matches = [
            rule for rule in rules
            if rule.section == section
            and canonical_url(rule.url) == canonical_url(url)
            and normalize_position(rule.position) == normalize_position(position)
        ]
        if len(matches) != 1:
            raise ValueError(f"失败TXT中的站点无法唯一匹配正式配置：{section}")
        rule = matches[0]
        identity = rule_identity(rule)
        if identity not in seen:
            selected.append(rule)
            seen.add(identity)
    return selected


def merge_success_txt(path: Path, records: list[HeadRecord]) -> bytes:
    raw = path.read_bytes() if path.exists() else b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8-sig") if raw else ""
    marker = next(((offset, line) for offset, line in _lines_with_offsets(text) if re.fullmatch(r"内容[\t ]+次数[\t ]+排名[\t ]*", line.rstrip("\r\n"))), None)
    if marker is None:
        raise ValueError(f"成功TXT缺少排行榜边界：{path}")
    prefix = text[: marker[0]]
    newline = "\r\n" if "\r\n" in text else "\n"
    existing = {}
    values = []
    for line in prefix.splitlines():
        match = re.match(r"^((?:[0-4]头)(?:、[0-4]头)*) (.+)$", line.strip())
        if match:
            if match.group(2) in existing and existing[match.group(2)] != match.group(1):
                raise ValueError(f"成功TXT已有同名冲突：{match.group(2)}")
            existing[match.group(2)] = match.group(1)
            values.extend(re.findall(r"[0-4]头", match.group(1)))
    additions = []
    batch = {}
    batch_sections = {}
    for record in records:
        if record.status != "success":
            continue
        identity = record_identity(record)
        if record.section in batch_sections and batch_sections[record.section] != identity:
            raise ValueError(f"成功TXT无法同时表示同名不同身份站点：{record.section}")
        batch_sections[record.section] = identity
        if identity in batch:
            if batch[identity] != record.value:
                raise ValueError(f"本批成功值冲突：{record.section}")
            continue
        batch[identity] = record.value
        old = existing.get(record.section)
        if old is None:
            if f"{record.value} {record.section}" not in additions:
                additions.append(f"{record.value} {record.section}")
            values.append(record.value)
        elif old != record.value:
            raise ValueError(f"成功TXT已有同期值冲突：{record.section} 当前{old}，实抓{record.value}")
    body = prefix.rstrip("\r\n") + (newline + newline.join(additions) if additions else "") + newline + newline
    result = (body + newline.join(format_head_ranking(values)) + newline).encode("utf-8")
    return (b"\xef\xbb\xbf" if bom else b"") + result


def _lines_with_offsets(text: str):
    offset = 0
    for line in text.splitlines(keepends=True):
        yield offset, line
        offset += len(line)


def merge_failed_txt(path: Path, target_records: list[HeadRecord], target_period: str) -> bytes | None:
    raw = path.read_bytes() if path.exists() else b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    old = raw.decode("utf-8-sig") if raw else ""
    blocks = _failure_blocks(old)
    target_ids = {(record.section, canonical_url(record.url), normalize_position(record.position)) for record in target_records if record.status == "success"}
    kept = []
    for block in blocks:
        first = block.splitlines()[0] if block.splitlines() else ""
        parsed = _parse_failure_header(first)
        if first.lstrip().startswith("失败") and parsed is None:
            raise ValueError(f"失败TXT存在无法解析的记录：{first.strip()}")
        if parsed and parsed[:3] in target_ids and parsed[3] == target_period:
            continue
        if block.strip():
            kept.append(block.strip())
    if not kept:
        return None
    categories = Counter(failure_category(_failure_reason(block)) for block in kept)
    kept.append("\n".join(["失败分类统计", *[f"{key} {count}条" for key, count in categories.items()]]))
    result = (newline + newline).join(item.replace("\r\n", "\n").replace("\n", newline) for item in kept).encode("utf-8") + newline.encode("utf-8")
    return (b"\xef\xbb\xbf" if bom else b"") + result


def _failure_blocks(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.lstrip().startswith("失败")]
    blocks = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        block = "".join(lines[start:end])
        block = re.split(r"(?m)^\s*失败分类统计\s*$", block)[0]
        if block.strip():
            blocks.append(block)
    if not starts and text.strip():
        return [text]
    return blocks


def _failure_reason(block: str) -> str:
    match = re.search(r"(?m)^\s*阶段:.*?原因:\s*(.*?)\s*$", block)
    return match.group(1).strip() if match else block

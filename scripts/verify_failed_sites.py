from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lottery_head.config import load_rules
from lottery_head.documents import collect_fragments
from lottery_head.models import SiteRule, SourceDocument
from lottery_head.network import get_text
from lottery_head.parsers import extract_head_records
from lottery_head.parsers.common import contains_text, display_head_value, html_to_text
from lottery_head.selection import (
    describe_conflicting_candidates,
    collect_ordered_candidates,
    extract_period_candidates_by_period,
    period_boundary_ambiguity,
    period_value_conflict,
    position_three_label,
    select_period_records,
)
from lottery_head.transport import FetchContext
from lottery_head.validation import parse_target_period, validate_head_value


@dataclass(frozen=True)
class SiteVerification:
    section: str
    url: str
    position: str
    period: str
    status: str
    actual_value: str
    anchor_ok: bool
    field_ok: bool
    head_ok: bool
    position_ok: bool
    conflict: bool
    window: tuple[str, ...]
    error: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读验证失败站点，不写缓存或正式TXT")
    parser.add_argument("period", help="指定期数，例如 202 或 202期")
    parser.add_argument("--site", action="append", default=[], help="站名或URL；可重复填写")
    parser.add_argument("--failure-file", type=Path, help="失败TXT路径，从中读取站名和URL")
    return parser.parse_args(argv)


def read_failure_identifiers(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"失败TXT无法读取：{path}") from exc
    identifiers: set[str] = set()
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        identifiers.add(parts[0])
        identifiers.update(part for part in parts if part.startswith(("http://", "https://")))
    return identifiers


def select_rules(rules: list[SiteRule], sites: list[str], failure_file: Path | None) -> list[SiteRule]:
    identifiers = set(sites)
    if failure_file is not None:
        identifiers.update(read_failure_identifiers(failure_file))
    if not identifiers:
        raise ValueError("没有指定待验证站点")
    selected = [rule for rule in rules if rule.section in identifiers or rule.url in identifiers]
    matched = {identifier for rule in selected for identifier in (rule.section, rule.url)}
    missing = sorted(identifier for identifier in identifiers if identifier not in matched)
    if missing:
        raise ValueError(f"配置中未找到站点：{'、'.join(missing)}")
    return selected


def verify_rule(rule: SiteRule, target_period: str, client: FetchContext) -> SiteVerification:
    try:
        html = get_text(client, rule.url)
        fragments = collect_fragments(
            html,
            client=client,
            source_url=rule.url,
            include_forum_history=False,
            target_period=target_period,
            target_periods=[target_period],
            content_hint=rule.content_hint,
            field=rule.field,
            admin_api_url=rule.api_url,
            parse_hint=rule.parse_hint,
            site_rule=rule,
        )
        anchor_ok, field_ok, head_ok, window = inspect_direction_window(fragments, rule)
        candidates_by_period = extract_period_candidates_by_period(fragments, rule, [target_period])
        candidates = candidates_by_period.get(target_period, [])
        if period_value_conflict(candidates):
            return failed_verification(
                rule,
                target_period,
                anchor_ok,
                field_ok,
                head_ok,
                window,
                f"{target_period}同一期出现多个冲突候选（{describe_conflicting_candidates(candidates)}）",
                conflict=True,
            )
        if period_boundary_ambiguity(candidates):
            return failed_verification(
                rule,
                target_period,
                anchor_ok,
                field_ok,
                head_ok,
                window,
                f"{target_period}同一期原始边界不唯一（相同标准化数据出现在多个来源位置）",
            )
        extracted = select_period_records(candidates_by_period).get(target_period)
        if extracted is None:
            return failed_verification(
                rule,
                target_period,
                anchor_ok,
                field_ok,
                head_ok,
                window,
                f"{target_period}不在{position_three_label(rule.position)}",
            )
        return SiteVerification(
            rule.section,
            rule.url,
            rule.position,
            target_period,
            "success",
            validate_head_value(extracted["value"]),
            anchor_ok,
            field_ok,
            head_ok,
            True,
            False,
            window,
            "",
        )
    except Exception as exc:
        return failed_verification(rule, target_period, False, False, False, (), str(exc))


def inspect_direction_window(fragments: list[str | SourceDocument], rule: SiteRule) -> tuple[bool, bool, bool, tuple[str, ...]]:
    documents = [as_document(fragment, index) for index, fragment in enumerate(fragments)]
    evidence_texts = [
        "\n".join(
            part
            for part in (document.title, document.author, html_to_text(document.source))
            if part
        )
        for document in documents
    ]
    anchor_ok = any(contains_text(text, rule.anchor) for text in evidence_texts)
    field_ok = any(contains_text(text, rule.field) for text in evidence_texts)
    ordered = collect_ordered_candidates(documents, rule)
    window = tuple(
        f"{candidate.get('source_route', 'page')}: {candidate.get('period', '?')}="
        f"{display_head_value(candidate.get('value', '')) or candidate.get('value', '?')}@"
        f"{candidate.get('original_position', '?')}"
        for candidate in ordered[:1] if rule.position.strip().lower() not in {"bottom", "尾部", "底部", "下"}
    )
    if rule.position.strip().lower() in {"bottom", "尾部", "底部", "下"}:
        window = tuple(
            f"{candidate.get('source_route', 'page')}: {candidate.get('period', '?')}="
            f"{display_head_value(candidate.get('value', '')) or candidate.get('value', '?')}@"
            f"{candidate.get('original_position', '?')}"
            for candidate in ordered[-1:]
        )
    if not window:
        fallback_records = []
        for document in documents:
            fallback_records.extend(
                extract_head_records(document.source, rule.field, rule.parse_hint, anchor_marker=rule.anchor)
            )
        fallback_records = fallback_records[-1:] if rule.position.strip().lower() in {"bottom", "尾部", "底部", "下"} else fallback_records[:1]
        fallback_values = " | ".join(
            f"{record.get('period', '?')}={display_head_value(record.get('value', '')) or record.get('value', '?')}@{index}"
            for index, record in enumerate(fallback_records)
        )
        window = (f"page: {fallback_values}",) if fallback_values else ()
    head_ok = bool(ordered) or any(
        bool(extract_head_records(document.source, rule.field, rule.parse_hint, anchor_marker=rule.anchor))
        for document in documents
    )
    return anchor_ok, field_ok, head_ok, tuple(window)


def as_document(fragment: str | SourceDocument, index: int) -> SourceDocument:
    if isinstance(fragment, SourceDocument):
        return fragment
    return SourceDocument(str(fragment), "", f"legacy-{index}")


def failed_verification(
    rule: SiteRule,
    target_period: str,
    anchor_ok: bool,
    field_ok: bool,
    head_ok: bool,
    window: tuple[str, ...],
    error: str,
    *,
    conflict: bool = False,
) -> SiteVerification:
    return SiteVerification(
        rule.section,
        rule.url,
        rule.position,
        target_period,
        "failed",
        "",
        anchor_ok,
        field_ok,
        head_ok,
        False,
        conflict,
        window,
        error or "失败原因：未知失败，未返回具体错误",
    )


def format_result(index: int, total: int, result: SiteVerification) -> str:
    window = "；".join(result.window) if result.window else "无可用候选"
    return "\n".join(
        (
            f"[{index}/{total}] {result.section} | {result.period} | {result.status}",
            f"  实际头：{result.actual_value or '-'}；方向：{result.position}；方向边界：{'通过' if result.position_ok else '不通过'}",
            f"  锚点：{'通过' if result.anchor_ok else '不通过'}；字段：{'通过' if result.field_ok else '不通过'}；头值：{'通过' if result.head_ok else '不通过'}；同期冲突：{'是' if result.conflict else '否'}",
            f"  候选窗口：{window}",
            f"  失败原因：{result.error}" if result.error else "  失败原因：无",
        )
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        target_period = parse_target_period(args.period)
        rules = select_rules(load_rules(), args.site, args.failure_file)
    except ValueError as exc:
        print(exc)
        return 2
    results: list[SiteVerification] = []
    with FetchContext(max_workers=1) as client:
        for index, rule in enumerate(rules, start=1):
            result = verify_rule(rule, target_period, client)
            results.append(result)
            print(format_result(index, len(rules), result), flush=True)
    success_count = sum(result.status == "success" for result in results)
    print(f"验证完成：成功 {success_count} 条，失败 {len(results) - success_count} 条", flush=True)
    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

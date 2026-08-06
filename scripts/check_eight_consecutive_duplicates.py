from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lottery_head.cache import cache_key, read_validated_cache
from lottery_head.config import canonical_url, load_rules, validate_rules
from lottery_head.duplicates import DuplicateFinding, common_contiguous_periods, find_duplicate_findings, longest_available_streak
from lottery_head.models import SiteRule
from lottery_head.service import fetch_site_period_data
from lottery_head.transport import FetchContext


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只按recent_10_cache.json检测连续重复")
    parser.add_argument("--candidate-url")
    parser.add_argument("--candidate-position")
    parser.add_argument("--candidate-section")
    parser.add_argument("--candidate-field")
    parser.add_argument("--candidate-content-hint")
    parser.add_argument("--candidate-parse-hint")
    parser.add_argument("--candidate-api-url", default="")
    return parser.parse_args(argv)


def build_candidate_rule(args: argparse.Namespace, rules: list[SiteRule]) -> SiteRule | None:
    values = {
        "url": args.candidate_url,
        "position": args.candidate_position,
        "section": args.candidate_section,
        "field": args.candidate_field,
        "content_hint": args.candidate_content_hint,
        "parse_hint": args.candidate_parse_hint,
    }
    provided = [name for name, value in values.items() if value]
    if not provided:
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"候选站缺少专属信息：{'、'.join(missing)}")
    candidate = SiteRule(
        url=str(args.candidate_url),
        position=str(args.candidate_position),
        section=str(args.candidate_section),
        field=str(args.candidate_field),
        content_hint=str(args.candidate_content_hint),
        parse_hint=str(args.candidate_parse_hint),
        api_url=str(args.candidate_api_url or ""),
    )
    validate_rules([*rules, candidate])
    duplicate_name = next((rule for rule in rules if rule.section == candidate.section), None)
    if duplicate_name:
        raise ValueError(f"候选站目录名称重复：{candidate.section}，必须先由用户决定改名")
    candidate_url = canonical_url(candidate.url)
    duplicate_url = next((rule for rule in rules if canonical_url(rule.url) == candidate_url), None)
    if duplicate_url:
        raise ValueError(f"候选站来源URL重复：{duplicate_url.section}")
    return candidate


def candidate_entry(rule: SiteRule, site_data) -> dict:
    values = {}
    positions = {}
    provenance = {}
    for period, candidate in site_data.period_records.items():
        if period not in site_data.period_values:
            continue
        values[period] = site_data.period_values[period]
        positions[period] = candidate.original_position
        provenance[period] = {
            "route": candidate.source_route,
            "record_id": candidate.source_record_id,
            "record_path": candidate.source_record_path,
            "source_block_id": candidate.source_block_id or f"{candidate.source_route}:{candidate.source_record_id or candidate.source_url}",
            "source_identity": candidate.source_identity,
            "source_user_id": candidate.source_user_id,
            "source_forum_id": candidate.source_forum_id,
            "source_list_position": candidate.source_list_position,
            "source_url": candidate.source_url,
            "api_url": candidate.source_api_url,
            "title": candidate.source_title,
            "author": candidate.source_author,
            "raw_line": candidate.raw_line,
        }
    section, url, position, parse_hint = cache_key(rule)
    return {
        "identity": {"section": section, "url": url, "position": position, "parse_hint": parse_hint},
        "values": values,
        "positions": positions,
        "provenance": provenance,
        "missing": {period: "候选站未抓到" for period in site_data.missing},
    }


def print_findings(findings: list[DuplicateFinding]) -> None:
    if not findings:
        print("未发现连续3期及以上、且标准化业务值一致的重复目录。")
        return
    for finding in findings:
        print(
            f"{finding.status}：{finding.left} == {finding.right} | 连续{finding.streak}期 | "
            f"{' '.join(finding.periods)}"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        rules = load_rules()
        cache = read_validated_cache(PROJECT_ROOT / ".tmp" / "recent_10_cache.json", rules)
        if cache is None:
            raise ValueError("近10期缓存不存在，不能进行新增判重")
        candidate = build_candidate_rule(args, rules)
    except ValueError as exc:
        print(f"检测拒绝：{exc}")
        return 2
    periods = list(cache["periods"])
    sites = list(cache["sites"])
    if candidate is None:
        insufficient = [
            (str(site.get("identity", {}).get("section", "未知目录")), longest_available_streak(site, periods))
            for site in sites
            if len(longest_available_streak(site, periods)) < 6
        ]
        if insufficient:
            print("判重证据不足：以下目录没有连续6期统一验证数据，不能判定不重复：")
            for section, streak in insufficient:
                print(f"- {section}：连续有效{len(streak)}期")
            return 2
        print(f"缓存基准：{cache['latest_period']}，范围：{' '.join(periods)}")
        print_findings(find_duplicate_findings(sites, periods))
        return 0

    latest_two = periods[:2]
    print(f"候选站真实验证：{candidate.section} | 基准仅允许 {'、'.join(latest_two)}")
    with FetchContext(max_workers=8) as context:
        newest = fetch_site_period_data(candidate, latest_two, client=context)
        if newest.error or not newest.period_values:
            print(f"候选站拒绝：最新两期真实抓取失败：{newest.error or '未抓到有效期数'}")
            return 2
        if not any(period in newest.period_values for period in latest_two):
            print("候选站拒绝：未按指定方向抓到缓存最新期或上一期")
            return 2
        candidate_data = fetch_site_period_data(candidate, periods, client=context)
    if candidate_data.error or not candidate_data.period_values:
        print(f"候选站拒绝：近10期真实抓取失败：{candidate_data.error or '未抓到有效期数'}")
        return 2
    candidate_entry_data = candidate_entry(candidate, candidate_data)
    candidate_streak = longest_available_streak(candidate_entry_data, periods)
    if len(candidate_streak) < 6:
        print(
            f"候选站拒绝：历史证据不足，仅有连续{len(candidate_streak)}期有效数据，"
            "重复拒收阈值需要至少连续6期"
        )
        return 2
    entry = candidate_entry_data
    if not entry["values"]:
        print("候选站拒绝：近10期没有带原始位置和来源证据的数据")
        return 2
    insufficient_comparisons = [
        str(site.get("identity", {}).get("section", "未知目录"))
        for site in sites
        if len(common_contiguous_periods(entry, site, periods)) < 6
    ]
    if insufficient_comparisons:
        print(
            "候选站拒绝：与以下目录没有至少连续6期共同有效数据，不能判定不重复："
            + "、".join(insufficient_comparisons)
        )
        return 2
    findings = find_duplicate_findings([*sites, entry], periods)
    candidate_findings = [
        finding
        for finding in findings
        if candidate.section in {finding.left, finding.right}
    ]
    print_findings(candidate_findings)
    if any(finding.status == "重复拒收" for finding in candidate_findings):
        return 4
    if any(finding.status == "疑似重复" for finding in candidate_findings):
        return 3
    print("候选站重复检测通过；本脚本未写入sites.json、recent_10_cache.json或正式TXT。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

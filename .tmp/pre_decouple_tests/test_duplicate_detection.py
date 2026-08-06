import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.check_eight_consecutive_duplicates import (
    SitePeriodData,
    auto_detect_latest_period,
    build_baseline_snapshot,
    candidate_result_code,
    fetch_site_period_data,
    find_match_pairs,
    load_sites_from_snapshot,
    snapshot_matches_periods,
)
from scripts.lottery_head_scraper import SiteRule, rules_config_fingerprint


def make_site(section: str, values: dict[str, str]) -> SitePeriodData:
    return SitePeriodData(
        section=section,
        field="绝杀一头",
        position="顶部",
        url=f"https://example.test/{section}",
        period_values=values,
        missing=[],
    )


def test_common_period_alignment_marks_suspect_for_three_to_five_periods() -> None:
    periods = [f"{period}期" for period in range(155, 145, -1)]
    site_a = make_site("甲", {"154期": "1头", "153期": "2头", "152期": "3头"})
    site_b = make_site("乙", {"154期": "1头", "153期": "2头", "152期": "3头", "151期": "4头"})

    duplicates, suspects = find_match_pairs([site_a, site_b], periods)

    assert duplicates == []
    assert len(suspects) == 1
    assert suspects[0].periods == ["154期", "153期", "152期"]
    assert suspects[0].streak == 3


def test_common_period_alignment_rejects_for_six_or_more_periods() -> None:
    periods = [f"{period}期" for period in range(155, 145, -1)]
    values = {
        "154期": "1头",
        "153期": "2头",
        "152期": "3头",
        "151期": "4头",
        "150期": "0头",
        "149期": "1头",
    }
    site_a = make_site("甲", values)
    site_b = make_site("乙", values)

    duplicates, suspects = find_match_pairs([site_a, site_b], periods)

    assert len(duplicates) == 1
    assert suspects == []
    assert duplicates[0].streak == 6


def test_missing_period_breaks_consecutive_streak() -> None:
    periods = [f"{period}期" for period in range(155, 145, -1)]
    site_a = make_site("甲", {"154期": "1头", "153期": "2头", "151期": "3头", "150期": "4头"})
    site_b = make_site("乙", {"154期": "1头", "153期": "2头", "151期": "3头", "150期": "4头"})

    duplicates, suspects = find_match_pairs([site_a, site_b], periods)

    assert duplicates == []
    assert suspects == []


def test_baseline_snapshot_keeps_only_recent_ten_periods() -> None:
    periods = [f"{period}期" for period in range(157, 147, -1)]
    site = make_site("甲", {**{period: "1头" for period in periods}, "147期": "2头"})

    snapshot = build_baseline_snapshot([site], periods, "157期")

    assert snapshot["latest_period"] == "157期"
    assert snapshot["periods"] == periods
    assert list(snapshot["sites"][0]["period_values"]) == periods
    assert "147期" not in snapshot["sites"][0]["period_values"]


def test_load_sites_from_snapshot_restores_site_period_data() -> None:
    snapshot = {
        "latest_period": "157期",
        "periods": ["157期", "156期"],
        "sites": [
            {
                "section": "甲",
                "field": "绝杀一头",
                "position": "顶部",
                "url": "https://example.test/a",
                "period_values": {"157期": "1头"},
                "missing": ["156期"],
                "error": "",
            }
        ],
    }

    sites = load_sites_from_snapshot(snapshot)

    assert len(sites) == 1
    assert sites[0].section == "甲"
    assert sites[0].period_values == {"157期": "1头"}


def test_duplicate_fetch_rejects_conflicting_same_period_candidates(monkeypatch) -> None:
    import scripts.check_eight_consecutive_duplicates as duplicate_checker
    import scripts.lottery_head_scraper as scraper

    rule = SiteRule("https://example.test/topic/1.html", "顶部", "甲", "绝杀一头")
    monkeypatch.setattr(
        duplicate_checker,
        "fetch_rule_with_period_data",
        lambda *args, **kwargs: (
            scraper.HeadRecord(rule.url, rule.position, rule.section, rule.field, "", "", "", "failed", "冲突"),
            scraper.BaselineSitePeriodData(
                rule.section,
                rule.field,
                rule.position,
                rule.url,
                {},
                ["158期"],
                "158期同一期出现多个冲突候选（1头；2头）",
            ),
        ),
    )

    site = fetch_site_period_data(rule, ["158期"])

    assert site.period_values == {}
    assert site.missing == ["158期"]
    assert "158期同一期出现多个冲突候选" in site.error


def test_snapshot_requires_matching_rule_fingerprint_and_site_count() -> None:
    rules = [
        SiteRule(
            "https://example.test/a",
            "顶部",
            "甲",
            "绝杀一头",
            content_hint="甲栏目",
            parse_hint="period_bracket_head",
        )
    ]
    periods = ["158期", "157期"]
    snapshot = build_baseline_snapshot(
        [make_site("甲", {"158期": "1头"})],
        periods,
        "158期",
        rules=rules,
    )

    assert snapshot["rules_fingerprint"] == rules_config_fingerprint(rules)
    assert snapshot_matches_periods(snapshot, periods, rules)

    changed_rules = [
        SiteRule(
            "https://example.test/a",
            "顶部",
            "甲",
            "绝杀一头",
            content_hint="新栏目",
            parse_hint="period_bracket_head",
        )
    ]
    assert not snapshot_matches_periods(snapshot, periods, changed_rules)
    assert not snapshot_matches_periods({**snapshot, "sites_count": 0}, periods, rules)


def test_candidate_result_code_blocks_empty_suspect_and_duplicate_candidates() -> None:
    periods = [f"{period}期" for period in range(158, 148, -1)]
    baseline = make_site("旧站", {period: "1头" for period in periods})

    assert candidate_result_code(make_site("空站", {}), [baseline], periods) == 4
    assert candidate_result_code(
        make_site("疑似站", {period: "1头" for period in periods[:3]}),
        [baseline],
        periods,
    ) == 2
    assert candidate_result_code(
        make_site("重复站", {period: "1头" for period in periods[:6]}),
        [baseline],
        periods,
    ) == 3


def test_candidate_result_code_distinguishes_same_name_by_url() -> None:
    periods = [f"{period}期" for period in range(158, 148, -1)]
    baseline_same_name = make_site("候选站", {period: "1头" for period in periods[:6]})
    another_baseline = make_site("旧站", {period: "1头" for period in periods[:6]})
    candidate = SitePeriodData(
        section="候选站",
        field="绝杀一头",
        position="顶部",
        url="https://candidate.test/new",
        period_values={period: f"{index % 5}头" for index, period in enumerate(periods)},
        missing=[],
    )

    assert candidate_result_code(candidate, [baseline_same_name, another_baseline], periods) == 0


def test_candidate_result_code_only_compares_candidate_when_url_is_shared() -> None:
    periods = [f"{period}期" for period in range(158, 148, -1)]
    shared_url = "https://example.test/shared"
    old_shared_section = SitePeriodData(
        section="旧栏目",
        field="四头中特",
        position="顶部",
        url=shared_url,
        period_values={period: "1头" for period in periods[:6]},
        missing=[],
    )
    duplicate_of_old = make_site("另一站", {period: "1头" for period in periods[:6]})
    candidate = SitePeriodData(
        section="新栏目",
        field="绝杀一头",
        position="尾部",
        url=shared_url,
        period_values={period: f"{index % 5}头" for index, period in enumerate(periods)},
        missing=[],
    )

    assert candidate_result_code(candidate, [old_shared_section, duplicate_of_old], periods) == 0


def test_candidate_rule_requires_dedicated_parse_hint() -> None:
    import argparse
    from scripts.check_eight_consecutive_duplicates import build_candidate_rule

    args = argparse.Namespace(
        candidate_url="https://example.test/a",
        candidate_position="顶部",
        candidate_section="甲",
        candidate_field="绝杀一头",
        candidate_content_hint="甲栏目",
        candidate_parse_hint="",
    )

    with pytest.raises(ValueError, match="专属解析"):
        build_candidate_rule(args)


def test_auto_detect_latest_period_does_not_guess_when_every_site_fails(monkeypatch) -> None:
    import scripts.check_eight_consecutive_duplicates as duplicate_checker

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(duplicate_checker, "build_client", DummyClient)
    monkeypatch.setattr(duplicate_checker, "fetch_rule_latest_period", lambda rule, client=None: "")

    assert auto_detect_latest_period([SiteRule("https://example.test", "顶部", "甲", "绝杀一头")]) == ""

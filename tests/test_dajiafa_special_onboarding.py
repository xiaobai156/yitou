from __future__ import annotations

from lottery_head.config import load_rules
from lottery_head.models import SiteRule, SourceDocument
from lottery_head.selection import extract_period_candidates_by_period, select_period_records


URL = "https://ssytmks.kcyub-abvtn-uvalbe.xyz:16677/topic/732181.html"


def make_rule(position: str = "顶部") -> SiteRule:
    return SiteRule(
        url=URL,
        position=position,
        section="大家发",
        field="绝杀一头",
        content_hint="大家發",
        parse_hint="full_period_list",
    )


def test_dajiafa_special_entry_keeps_the_verified_identity_and_top_direction() -> None:
    matches = [rule for rule in load_rules() if rule.section == "大家发"]

    assert matches == [make_rule()]


def test_dajiafa_accepts_only_the_first_valid_period_in_its_own_script_document() -> None:
    rule = make_rule()
    document = SourceDocument(
        "大家發\n217期:【绝杀一头】··【3头】开\n216期:【绝杀一头】··【4头】开",
        "https://xia02.cosds.ahsccn.com/upload/script/08/ba05c667162f83f7.js",
        "script",
    )

    candidates = extract_period_candidates_by_period([document], rule, ["217期", "216期"])

    assert select_period_records(candidates)["217期"]["value"] == "3头"
    assert candidates["216期"] == []


def test_dajiafa_rejects_bottom_direction_and_cross_document_borrowed_anchor() -> None:
    bottom = make_rule("尾部")
    anchored_only = SourceDocument("大家發", "https://example.test/anchor", "script")
    data_only = SourceDocument(
        "217期:【绝杀一头】··【3头】开",
        "https://example.test/data",
        "script",
    )
    same_document = SourceDocument(
        "大家發\n217期:【绝杀一头】··【3头】开\n216期:【绝杀一头】··【4头】开",
        "https://example.test/combined",
        "script",
    )

    borrowed = extract_period_candidates_by_period(
        [anchored_only, data_only],
        make_rule(),
        ["217期"],
    )
    wrong_direction = extract_period_candidates_by_period(
        [same_document],
        bottom,
        ["217期"],
    )

    assert borrowed["217期"] == []
    assert wrong_direction["217期"] == []


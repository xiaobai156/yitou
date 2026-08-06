from pathlib import Path

import pytest

from scripts.lottery_head_scraper import (
    HeadRecord,
    RULES,
    SiteRule,
    collect_fragments,
    decode_script_document_writes,
    decode_inline_gbk_decrypt_calls,
    display_head_value,
    extract_latest_head_record,
    extract_head_records,
    extract_period_candidates_by_period,
    format_progress_line,
    fetch_rule,
    fetch_rule_for_any_period,
    fetch_rule_with_period_data,
    find_target_record,
    find_target_fragment,
    format_completion_summary,
    get_text,
    load_rules,
    main,
    parse_fragment_tables,
    protect_baseline_quality,
    sync_site_period_baseline,
    tls_verification_enabled,
    unique_success_records,
    write_baseline_snapshot,
    write_failed_txt,
    write_success_txt,
)


class FakeResponse:
    def __init__(self, text="", data=None, status_code=200):
        self.text = text
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_format_progress_line_includes_counts_elapsed_and_current_section() -> None:
    assert format_progress_line(2, 120, 2, 0, 17.1, "亡魂驶魄") == (
        "[进度 2/120 1% 成功 2 失败 0 用时 17.1s] 当前：亡魂驶魄"
    )


def test_format_completion_summary_reports_success_and_failure_counts() -> None:
    assert format_completion_summary(168, 0) == "完成：成功 168 条，失败 0 条"


class FakeClient:
    def __init__(self, responses):
        import scripts.lottery_head_scraper as scraper

        scraper.API_JSON_CACHE.clear()
        self.responses = responses
        self.requested_urls = []

    def get(self, url):
        self.requested_urls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_parse_fragment_tables_extracts_target_column() -> None:
    html = """
    <table>
      <tr><td>期数</td><td>杀肖</td><td>杀半波</td><td>杀一尾</td><td>禁一头</td><td>开奖结果</td></tr>
      <tr><td>151期</td><td>狗肖</td><td>红单</td><td>6尾</td><td>3头</td><td>开0000准</td></tr>
      <tr><td>150期</td><td>龙肖</td><td>绿双</td><td>8尾</td><td>4头</td><td>开狗09准</td></tr>
    </table>
    """

    record = parse_fragment_tables(html, "禁一头")

    assert record is not None
    assert record["period"] == "151期"
    assert record["value"] == "3头"


def test_parse_fragment_tables_extracts_bare_digit_cell() -> None:
    html = """
    <table>
      <tr><td>期数</td><td>杀一肖</td><td>杀半波</td><td>杀一尾</td><td>杀一头</td><td>开奖结果</td></tr>
      <tr><td>150期</td><td>(兔)</td><td>(蓝波双)</td><td>(2)</td><td>(1)</td><td>开:0000准</td></tr>
      <tr><td>149期</td><td>(羊)</td><td>(红波单)</td><td>(8)</td><td>(4)</td><td>开:龙27准</td></tr>
    </table>
    """

    record = parse_fragment_tables(html, "杀一头", "150期")

    assert record is not None
    assert record["period"] == "150期"
    assert record["value"] == "1头"


def test_table_column_hint_extracts_vertical_table_layout() -> None:
    html = """
    <div>澳门男人味【综合绝杀】实力证明</div>
    <div>期数</div>
    <div>杀一肖</div>
    <div>杀半波</div>
    <div>杀一尾</div>
    <div>杀一头</div>
    <div>开奖结果</div>
    <div>152期</div>
    <div>(猴)</div>
    <div>(蓝波双)</div>
    <div>(9)</div>
    <div>(0)</div>
    <div>开:0000准</div>
    <div>151期</div>
    <div>(兔)</div>
    <div>(红单)</div>
    <div>(8)</div>
    <div>(4)</div>
    <div>开鼠31准</div>
    """

    record = extract_latest_head_record(html, "杀一头", "table_column", "152期")

    assert record is not None
    assert record["period"] == "152期"
    assert record["value"] == "0头"


def test_load_rules_from_sites_json() -> None:
    rules = load_rules(Path("sites.json"))

    assert len(rules) == len(RULES)
    assert len(rules) > 0
    assert rules[0].section == "熊出没"


@pytest.mark.parametrize(
    ("html", "field", "expected"),
    [
        ("203期:◆杀①头◆【444】开马25准", "精杀一头", "4头"),
        ("203期绝杀一头《3》开马25准", "绝杀一头", "3头"),
        ("203期：【杀一头】《2头》开马25准", "绝杀一头", "2头"),
        ("203期（必杀一头）【1】头（开马25准）", "必杀一头", "1头"),
        ("203期：绝杀一头（2头）开马25错", "绝杀一头", "2头"),
    ],
)
def test_user_kill_head_parser_supports_user_page_formats(html, field, expected) -> None:
    records = extract_head_records(html, field, "user_kill_head", "203期")

    assert len(records) == 1
    assert display_head_value(records[0]["value"]) == expected


def test_user_top_page_uses_first_contiguous_period_document() -> None:
    source_url = "https://example.test/#/users/1747"
    client = FakeClient(
        {
            source_url: FakeResponse(text=""),
            "https://example.test/api/v1/users/1747": FakeResponse(
                data={"id": 1747, "nickname": "主要针"}
            ),
            "https://example.test/api/v1/users/1747/forums": FakeResponse(
                data=[
                    {
                        "id": 1001,
                        "user_id": 1747,
                        "draw": 204,
                        "topic": "204期:【精杀一头】",
                        "content": (
                            "<p>204期:◆杀①头◆【111】开000准</p>"
                            "<p>203期:◆杀①头◆【444】开马25准</p>"
                            "<p>202期:◆杀①头◆【222】开兔40准</p>"
                            "<p>201期:◆杀①头◆【333】开猪32准</p>"
                            "<p>365期:◆杀①头◆【000】开鼠18准</p>"
                            "<p>364期:◆杀①头◆【000】开牛29准</p>"
                            "<p>203期:◆杀①头◆【000】开诱饵准</p>"
                        ),
                    }
                ]
            ),
        }
    )
    rule = SiteRule(
        source_url,
        "顶部",
        "主要针",
        "精杀一头",
        content_hint="主要针",
        parse_hint="user_kill_head",
    )

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="203期",
        periods=["203期", "202期"],
    )

    assert record.status == "success"
    assert record.value == "4头"
    assert site_data.period_values == {"203期": "4头", "202期": "2头"}


def test_forum_fragments_do_not_include_history_topic_for_same_sub_topic() -> None:
    source_url = "https://example.test/#/forums/15501"
    client = FakeClient({
        "https://example.test/api/v1/forums/15501": FakeResponse(data={
            "id": 15501,
            "user_id": 88,
            "topic": "澳门挂牌",
            "sub_topic": "绝杀一头",
            "content": "<p>155期：《绝杀一头》【333头】开：000准</p>",
        }),
        "https://example.test/api/v1/users/88/references/history": FakeResponse(data=[
            {"id": 15601, "user_id": 88, "draw": 156, "topic": "澳门挂牌", "sub_topic": "绝杀一头"},
            {"id": 15602, "user_id": 88, "draw": 156, "topic": "澳门挂牌", "sub_topic": "杀一尾"},
        ]),
        "https://example.test/api/v1/forums/15601": FakeResponse(data={
            "id": 15601,
            "user_id": 88,
            "topic": "澳门挂牌",
            "sub_topic": "绝杀一头",
            "content": "<p>156期：《绝杀一头》【444头】开：000准</p>",
        }),
    })

    fragments = collect_fragments("", client=client, source_url=source_url)
    assert find_target_record(fragments, SiteRule(source_url, "顶部", "澳门挂椅", "绝杀一头"), "156期") is None
    assert "references/history" not in "\n".join(client.requested_urls)


def test_user_top_forum_fragment_parses_kill_head_rows() -> None:
    source_url = "https://example.test/#/users/3727"
    client = FakeClient({
        source_url: FakeResponse(text=""),
        "https://example.test/api/v1/users/3727": FakeResponse(data={"id": 3727, "nickname": "喜欢药"}),
        "https://example.test/api/v1/users/3727/forums": FakeResponse(data=[
            {
                "id": 15564740,
                "topic": "绝杀一头",
                "content": (
                    "<p>188期〔杀1头〕开0000准</p>"
                    "<p>187期〔杀4头〕开马01准</p>"
                    "<p>186期〔杀0头〕开猴23准</p>"
                ),
            },
        ]),
    })
    rule = SiteRule(
        source_url,
        "顶部",
        "喜欢药",
        "绝杀一头",
        content_hint="喜欢药",
        parse_hint="user_kill_head",
    )

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="187期",
        periods=["187期", "186期"],
    )

    assert record.status == "failed"
    assert site_data.period_values == {}
    assert site_data.missing == ["187期", "186期"]


def test_period_bracket_head_treats_digit_one_head_as_yi_tou_marker() -> None:
    html = "<p>189期精杀1头【333】开龙15准</p><p>188期精杀1头【222】开猴23准</p>"
    rule = SiteRule(
        "https://example.test/topic/1.html",
        "顶部",
        "老中医生",
        "精杀一头",
        content_hint="老中医生",
        parse_hint="period_bracket_head",
    )
    client = FakeClient({rule.url: FakeResponse(text=f"<div>老中医生</div>{html}")})

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="189期",
        periods=["189期", "188期"],
    )

    assert record.status == "success"
    assert record.value == "3头"
    assert site_data.period_values == {"189期": "3头", "188期": "2头"}


def test_kill_head_phrase_parses_short_kill_zero_head_format() -> None:
    html = "<p>189期〔杀零头〕开:0000准</p><p>188期〔杀四头〕开:0000准</p>"
    rule = SiteRule(
        "https://example.test/",
        "顶部",
        "赤兔",
        "绝杀一头",
        content_hint="赤兔",
        parse_hint="kill_head_phrase",
    )
    client = FakeClient({rule.url: FakeResponse(text=f"<div>赤兔</div>{html}")})

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="189期",
        periods=["189期", "188期"],
    )

    assert record.status == "success"
    assert record.value == "0头"
    assert site_data.period_values == {"189期": "0头", "188期": "4头"}


def test_dash_head_phrase_parses_explicit_separator_format() -> None:
    html = "<p>203期：绝杀一头--2-- 头开：马25错</p><p>202期：绝杀一头--4-- 头开：兔40错</p>"

    records = extract_head_records(html, "绝杀一头", "dash_head_phrase", "203期")

    assert records == [{
        "period": "203期",
        "value": "2头",
        "raw_line": "203期：绝杀一头--2--头开：马25错",
    }]


def test_fetch_rule_skips_forum_history_when_current_topic_has_target_period() -> None:
    source_url = "https://example.test/#/forums/15601"
    client = FakeClient({
        source_url: FakeResponse(text=""),
        "https://example.test/api/v1/forums/15601": FakeResponse(data={
            "id": 15601,
            "user_id": 88,
            "topic": "澳门挂牌",
            "sub_topic": "绝杀一头",
            "content": "<p>156期：《绝杀一头》【444头】开：000准</p>",
        }),
    })
    rule = SiteRule(source_url, "顶部", "澳门挂椅", "绝杀一头")

    record = fetch_rule(rule, client=client, target_period="156期")

    assert record.status == "success"
    assert record.period == "156期"
    assert "history" not in "\n".join(client.requested_urls)


def test_extract_latest_head_record_reads_latest_line_text() -> None:
    html = """
    <div>热门高手💎151期:【精品好料-稳杀一头】震撼六和界！</div>
    <div>151期【稳杀一头】【杀1头】开:0000准</div>
    <div>150期【稳杀一头】【杀2头】开:狗09准</div>
    """

    record = extract_latest_head_record(html, "稳杀一头")

    assert record is not None
    assert record["period"] == "151期"
    assert record["value"] == "1头"
    assert "151期" in record["raw_line"]


def test_extract_latest_head_record_reads_multiline_block_text() -> None:
    html = """
    <div>♣天下彩♣【【砍杀一头】】</div>
    <div>151期</div>
    <div>【杀一头】</div>
    <div>【3头】</div>
    <div>开0000准</div>
    <div>150期</div>
    <div>【杀一头】</div>
    <div>【1头】</div>
    <div>开狗09准</div>
    """

    record = extract_latest_head_record(html, "砍杀一头")

    assert record is not None
    assert record["period"] == "151期"
    assert record["value"] == "3头"


def test_tianxiacai_sha_yi_tou_hint_ignores_unrelated_head_values() -> None:
    html = """
    <div>香港天下彩</div>
    <div>163期【金行.3头.红双.大单】开？00准</div>
    <div>163期【杀一头】【4头】开0000准</div>
    <div>162期【杀一头】【1头】开猪32准</div>
    """
    rule = SiteRule(
        "https://example.test/",
        "顶部",
        "天下彩",
        "砍杀一头",
        content_hint="天下彩",
        parse_hint="bracket_sha_yi_tou",
    )

    candidates = extract_period_candidates_by_period([html], rule, ["163期"])

    assert candidates["163期"] == [
        {
            "period": "163期",
            "value": "4头",
            "raw_line": "163期【杀一头】【4头】开0000准",
        }
    ]


def test_bracket_field_head_hint_uses_exact_field_bracket_value() -> None:
    html = """
    <div>三阳开泰</div>
    <div>165期【规律三头】【4头】开0000准</div>
    <div>165期【绝杀一头】【222】开0000准</div>
    <div>164期【绝杀一头】【333】开狗32准</div>
    """
    rule = SiteRule(
        "https://example.test/topic/356092.html",
        "顶部",
        "三阳开泰",
        "绝杀一头",
        parse_hint="bracket_field_head",
    )

    candidates = extract_period_candidates_by_period([html], rule, ["165期"])

    assert candidates["165期"] == [
        {
            "period": "165期",
            "value": "222头",
            "raw_line": "165期【绝杀一头】【222】开0000准",
        }
    ]


def test_extract_latest_head_record_ignores_marker_head_value() -> None:
    html = """
    <div>澳门蓝月亮--绝杀一头</div>
    <div>150期绝杀一头</div>
    <div>【三头】</div>
    <div>开:0000准</div>
    <div>149期绝杀一头</div>
    <div>【零头】</div>
    <div>开:龙27准</div>
    """

    record = extract_latest_head_record(html, "绝杀一头")

    assert record is not None
    assert record["period"] == "150期"
    assert record["value"] == "三头"


def test_extract_latest_head_record_reads_bare_bracket_digit() -> None:
    html = """
    <div>151期:◆绝杀一头◆【1】开:??准</div>
    <div>150期:◆绝杀一头◆【4】开:09准</div>
    """

    record = extract_latest_head_record(html, "绝杀一头")

    assert record is not None
    assert record["period"] == "151期"
    assert record["value"] == "1头"


def test_extract_latest_head_record_reads_repeated_bare_bracket_digits() -> None:
    html = """
    <div>151期【精杀一头】[444]开:0000准</div>
    <div>150期【精杀一头】[000]开:狗09错</div>
    """

    record = extract_latest_head_record(html, "精杀一头", target_period="150期")

    assert record is not None
    assert record["period"] == "150期"
    assert record["value"] == "000头"


def test_period_bracket_head_hint_reads_yiyidaishui_format() -> None:
    html = """
    <div>149期精杀一头【4头】开：龙27准</div>
    <div>150期精杀一头【2头】开：狗09准</div>
    <div>155期精杀一头【0头】开：？00准</div>
    """

    record = extract_latest_head_record(html, "精杀一头", "period_bracket_head", "155期")

    assert record is not None
    assert record["period"] == "155期"
    assert record["value"] == "0头"


def test_period_bracket_head_hint_reads_minglieqianmao_format() -> None:
    html = """
    <div>155期「精杀一头」【222】开：0000准</div>
    <div>154期「精杀一头」【000】开：虎41准</div>
    """

    record = extract_latest_head_record(html, "精杀一头", "period_bracket_head", "155期")

    assert record is not None
    assert record["period"] == "155期"
    assert record["value"] == "222头"


def test_period_bracket_head_hint_reads_guanyunchang_format() -> None:
    html = """
    <div>155期绝杀一头【444头】开0000准</div>
    <div>154期绝杀一头【333头】开虎41准</div>
    """

    record = extract_latest_head_record(html, "绝杀一头", "period_bracket_head", "155期")

    assert record is not None
    assert record["period"] == "155期"
    assert record["value"] == "444头"

def test_period_bracket_head_hint_does_not_fallback_to_table_column() -> None:
    html = """
    <table>
      <tr><td>期数</td><td>绝杀一头</td><td>开奖结果</td></tr>
      <tr><td>155期</td><td>4头</td><td>开0000准</td></tr>
    </table>
    """

    record = extract_latest_head_record(html, "绝杀一头", "period_bracket_head", "155期")

    assert record is None


def test_extract_latest_head_record_does_not_use_field_marker_as_value() -> None:
    html = """
    <div>151期【精杀一头】开:0000准</div>
    """

    record = extract_latest_head_record(html, "精杀一头", target_period="151期")

    assert record is None


def test_extract_latest_head_record_ignores_ad_head_after_open_result() -> None:
    html = """
    <div>151期：【杀一头】《0头》开:0000准 推荐澳彩【三头中特】万事俱备</div>
    """

    record = extract_latest_head_record(html, "杀一头", target_period="151期")

    assert record is not None
    assert record["value"] == "0头"


def test_extract_latest_head_record_reads_missing_head_from_four_combo() -> None:
    html = """
    <div>151期:《奋起直追》✨④头中特✨【1.2.3.4】开:00准</div>
    <div>150期:《奋起直追》✨④头中特✨【0.2.3.4】开:09准</div>
    """

    record = extract_latest_head_record(html, "④头中特", "missing_head_from_four_combo", "151期")

    assert record is not None
    assert record["value"] == "0头"


def test_extract_latest_head_record_auto_reads_missing_head_from_four_combo() -> None:
    html = """
    <div>151期:《随风细雨》✨④头中特✨【1.2.3.4】开:00准</div>
    <div>150期:《随风细雨》✨④头中特✨【0头2头3头4头】开:09准</div>
    """

    record = extract_latest_head_record(html, "④头中特", target_period="150期")

    assert record is not None
    assert record["value"] == "1头"


def test_extract_latest_head_record_reads_missing_head_from_white_swan_brackets() -> None:
    html = """
    <div>温婉如水（四头中特）</div>
    <div>160期:※特码(4)头〖2.3.4.1头〗开:？00准</div>
    """

    record = extract_latest_head_record(html, "特码(4)头", "missing_head_from_four_combo", "160期")

    assert record is not None
    assert record["period"] == "160期"
    assert record["value"] == "0头"


def test_extract_latest_head_record_reads_requested_period() -> None:
    html = """
    <div>151期【稳杀一头】【杀1头】开:0000准</div>
    <div>150期【稳杀一头】【杀2头】开:狗09准</div>
    """

    record = extract_latest_head_record(html, "稳杀一头", target_period="150期")

    assert record is not None
    assert record["period"] == "150期"
    assert record["value"] == "2头"


def test_extract_latest_head_record_reads_17tuku_forum_content() -> None:
    html = """
    <div>惠泽社群</div>
    <div>绝杀①头</div>
    <p>152期:绝杀①头 杀「2头」 开:0000准</p>
    <p>151期:绝杀①头 杀「3头」 开:鼠31错</p>
    """

    record = extract_latest_head_record(html, "绝杀①头", target_period="152期")

    assert record is not None
    assert record["value"] == "2头"


def test_extract_latest_head_record_does_not_fallback_to_other_period() -> None:
    html = """
    <div>151期【稳杀一头】【杀1头】开:0000准</div>
    <div>149期【稳杀一头】【杀2头】开:龙27准</div>
    """

    record = extract_latest_head_record(html, "稳杀一头", target_period="150期")

    assert record is None


def test_extract_latest_head_record_ignores_zheng_marker() -> None:
    html = """
    <div>029期:【绝杀㊣一头】【0】开：蛇13准</div>
    <div>030期:【绝杀㊣一头】【1】开：蛇25准</div>
    """

    record = extract_latest_head_record(html, "绝杀一头")

    assert record is not None
    assert record["period"] == "029期"
    assert record["value"] == "0头"


def test_find_target_fragment_requires_last_match_for_bottom() -> None:
    fragments = [
        "<div>澳门底部样例</div><div>151期:绝杀一头【1头】开:0000准</div><div>151期:绝杀一头【2头】开:0000准</div>",
        "<div>广告</div>",
        "<div>澳门底部样例</div><div>151期:绝杀一头【3头】开:0000准</div>",
    ]

    rule = SiteRule(
        url="https://example.test/",
        position="尾部",
        section="底部样例",
        field="绝杀一头",
    )

    selected = find_target_fragment(fragments, rule)

    assert selected is not None
    assert "3头" in selected


def test_find_target_fragment_requires_first_match_for_top() -> None:
    fragments = [
        "<div>澳门熊出没</div><div>外壳，没有期号数据</div>",
        "<div>澳门熊出没</div><div>151期:禁一头【1头】开:0000准</div>",
        "<div>广告</div>",
        "<div>澳门熊出没</div><div>151期:禁一头【3头】开:0000准</div><div>151期:禁一头【4头】开:0000准</div>",
    ]

    rule = SiteRule(
        url="https://example.test/",
        position="顶部",
        section="熊出没",
        field="禁一头",
    )

    selected = find_target_fragment(fragments, rule)

    assert selected is not None
    assert "1头" in selected


def test_find_target_record_requires_position_within_valid_period_candidates() -> None:
    fragments = [
        """
        <div>151期:绝杀一头【1头】开:0000准</div>
        <div>150期:绝杀一头【2头】开:狗09准</div>
        <div>150期:绝杀一头【4头】开:狗09准</div>
        """,
    ]
    rule = SiteRule(
        url="https://example.test/",
        position="尾部",
        section="测试",
        field="绝杀一头",
    )

    selected = find_target_record(fragments, rule, "150期")

    assert selected is not None
    assert selected["period"] == "150期"
    assert selected["value"] == "4头"


def test_find_target_record_accepts_bottom_alias() -> None:
    fragments = [
        """
        <div>150期:绝杀一头【2头】开:狗09准</div>
        <div>150期:绝杀一头【4头】开:狗09准</div>
        """,
    ]
    rule = SiteRule(
        url="https://example.test/",
        position="bottom",
        section="测试",
        field="绝杀一头",
    )

    selected = find_target_record(fragments, rule, "150期")

    assert selected is not None
    assert selected["value"] == "4头"


def test_find_target_record_rejects_top_candidate_outside_latest_five_when_period_repeats() -> None:
    html = "\n".join(
        [
            '<div>152期:绝杀一头【1头】开:0000准</div>',
            '<div>151期:绝杀一头【2头】开:0000准</div>',
            '<div>150期:绝杀一头【3头】开:0000准</div>',
            '<div>149期:绝杀一头【4头】开:0000准</div>',
            '<div>148期:绝杀一头【0头】开:0000准</div>',
            '<div>147期:绝杀一头【1头】开:0000准</div>',
            '<div>147期:绝杀一头【2头】开:0000准</div>',
        ]
    )
    rule = SiteRule(
        url="https://example.test/",
        position="顶部",
        section="测试",
        field="绝杀一头",
    )

    selected = find_target_record([html], rule, "147期")

    assert selected is None


def test_find_target_record_rejects_bottom_candidate_outside_latest_five_when_page_is_wide() -> None:
    rows = [
        f'<div>{period}期:绝杀一头【{period % 5}头】开:0000准</div>'
        for period in range(152, 117, -1)
    ]
    rule = SiteRule(
        url="https://example.test/",
        position="尾部",
        section="测试",
        field="绝杀一头",
    )

    selected = find_target_record(["\n".join(rows)], rule, "140期")

    assert selected is None


def test_find_target_record_rejects_top_candidate_outside_top_five_even_if_period_is_latest() -> None:
    rows = [
        f'<div>{period}期:绝杀一头【{period % 5}头】开:0000准</div>'
        for period in range(21, 153)
    ]
    rule = SiteRule(
        url="https://example.test/",
        position="顶部",
        section="测试",
        field="绝杀一头",
    )

    selected = find_target_record(["\n".join(rows)], rule, "152期")

    assert selected is None


def test_find_target_record_limits_when_any_period_has_multiple_candidates() -> None:
    html = "\n".join(
        [
            '<div>152期:绝杀一头【1头】开:0000准</div>',
            '<div>151期:绝杀一头【2头】开:0000准</div>',
            '<div>150期:绝杀一头【3头】开:0000准</div>',
            '<div>149期:绝杀一头【4头】开:0000准</div>',
            '<div>148期:绝杀一头【0头】开:0000准</div>',
            '<div>147期:绝杀一头【1头】开:0000准</div>',
            '<div>146期:绝杀一头【2头】开:0000准</div>',
            '<div>146期:绝杀一头【3头】开:0000准</div>',
        ]
    )
    rule = SiteRule(
        url="https://example.test/",
        position="顶部",
        section="测试",
        field="绝杀一头",
    )

    selected = find_target_record([html], rule, "147期")

    assert selected is None


def test_output_helpers_normalize_and_dedupe_success_records() -> None:
    records = [
        HeadRecord("https://a.test", "顶部", "甲", "绝杀一头", "150期", "一头", "", "success", ""),
        HeadRecord("https://b.test", "顶部", "甲", "绝杀一头", "149期", "三头", "", "success", ""),
        HeadRecord("https://c.test", "顶部", "乙", "绝杀一头", "150期", "444头", "", "success", ""),
    ]

    unique_records = unique_success_records(records)

    assert [record.section for record in unique_records] == ["甲", "乙"]
    assert display_head_value(unique_records[0].value) == "1头"
    assert display_head_value(unique_records[1].value) == "4头"
    assert display_head_value("000头") == "0头"
    assert display_head_value("3333头") == "3头"
    assert display_head_value("45头") == ""


def test_sync_site_period_baseline_writes_recent_ten_periods(monkeypatch) -> None:
    calls = {}

    def fake_generate_periods(latest_period):
        calls["latest_period"] = latest_period
        return [f"{period}期" for period in range(158, 148, -1)]

    def fake_fetch_site_period_data(rule, periods, client=None):
        return {
            "section": rule.section,
            "periods": periods,
        }

    def fake_write_baseline_snapshot(all_data, periods, latest_period, rules=None):
        calls["all_data"] = all_data
        calls["periods"] = periods
        calls["written_latest_period"] = latest_period
        return Path(".tmp/recent_10_cache.json")

    import scripts.lottery_head_scraper as scraper

    monkeypatch.setattr(scraper, "generate_periods", fake_generate_periods)
    monkeypatch.setattr(scraper, "fetch_site_period_data", fake_fetch_site_period_data)
    monkeypatch.setattr(scraper, "write_baseline_snapshot", fake_write_baseline_snapshot)

    path = sync_site_period_baseline("158期", [SiteRule("https://example.test", "顶部", "甲", "绝杀一头")])

    assert path == Path(".tmp/recent_10_cache.json")
    assert calls["periods"] == ["158期", "157期", "156期", "155期", "154期", "153期", "152期", "151期", "150期", "149期"]
    assert calls["written_latest_period"] == "158期"
    assert calls["all_data"] == [{"section": "甲", "periods": calls["periods"]}]


def test_main_skips_recent_cache_when_env_flag_is_set(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    calls = {"write_outputs": 0, "write_baseline": 0, "periods": None}
    rule = SiteRule("https://example.test", "顶部", "甲", "绝杀一头")

    def fake_fetch_rule_with_period_data(rule, *, client, target_period, periods):
        calls["periods"] = periods
        return (
            HeadRecord(rule.url, rule.position, rule.section, rule.field, target_period, "1头", "", "success", ""),
            scraper.BaselineSitePeriodData(rule.section, rule.field, rule.position, rule.url, {target_period: "1头"}, []),
        )

    def fake_write_outputs(records, output_dir, target_period):
        calls["write_outputs"] += 1

    def fake_write_baseline_snapshot(all_data, periods, latest_period, rules=None):
        calls["write_baseline"] += 1
        return Path(".tmp/recent_10_cache.json")

    monkeypatch.setattr(scraper, "RULES", [rule])
    monkeypatch.setattr(scraper, "fetch_rule_with_period_data", fake_fetch_rule_with_period_data)
    monkeypatch.setattr(scraper, "build_client", lambda: FakeClient({}))
    monkeypatch.setattr(scraper, "write_outputs", fake_write_outputs)
    monkeypatch.setattr(scraper, "write_baseline_snapshot", fake_write_baseline_snapshot)
    monkeypatch.setenv("LOTTERY_SKIP_RECENT_10_CACHE", "1")
    monkeypatch.setattr("sys.argv", ["lottery_head_scraper.py", "158期"])

    assert main() == 0
    assert calls == {"write_outputs": 1, "write_baseline": 0, "periods": ["158期"]}


def test_get_text_rejects_http_error_pages(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    client = FakeClient({"https://example.test/missing": FakeResponse("404 page 158期 1头", status_code=404)})

    def fail_requests_get(*args, **kwargs):
        raise RuntimeError("fallback failed")

    monkeypatch.setattr(scraper.requests, "get", fail_requests_get)

    with pytest.raises(Exception, match="HTTP 404"):
        get_text(client, "https://example.test/missing")


def test_tls_verification_is_strict_by_default_and_requires_explicit_opt_out(monkeypatch) -> None:
    monkeypatch.delenv("LOTTERY_ALLOW_INSECURE_TLS", raising=False)
    assert tls_verification_enabled()

    monkeypatch.setenv("LOTTERY_ALLOW_INSECURE_TLS", "1")
    assert not tls_verification_enabled()


def test_write_baseline_snapshot_is_atomic_and_contains_rule_fingerprint(tmp_path, monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    path = tmp_path / "recent_10_cache.json"
    rule = SiteRule(
        "https://example.test/a",
        "顶部",
        "甲",
        "绝杀一头",
        content_hint="甲栏目",
        parse_hint="period_bracket_head",
    )
    site = scraper.BaselineSitePeriodData(
        rule.section,
        rule.field,
        rule.position,
        rule.url,
        {"158期": "1头"},
        [],
    )
    monkeypatch.setattr(scraper, "RECENT_10_CACHE_PATH", path)

    written = write_baseline_snapshot([site], ["158期"], "158期", rules=[rule])
    payload = __import__("json").loads(written.read_text(encoding="utf-8"))

    assert payload["sites_count"] == 1
    assert payload["rules_fingerprint"]
    assert not path.with_name(path.name + ".tmp").exists()


def test_initial_baseline_snapshot_rejects_all_empty_site_data(tmp_path) -> None:
    snapshot = {
        "sites_count": 2,
        "sites": [
            {"section": "甲", "period_values": {}},
            {"section": "乙", "period_values": {}},
        ],
    }

    with pytest.raises(RuntimeError, match="没有任何有效站点数据"):
        protect_baseline_quality(tmp_path / "recent_10_cache.json", snapshot)


def test_multi_period_summary_only_lists_all_failed_sites() -> None:
    from scripts.summarize_multi_period_failures import build_all_failed_rows

    period_records = {
        "187期": [
            {"section": "甲", "field": "绝杀一头", "url": "https://a.test", "status": "failed", "error": "未更新"},
            {"section": "乙", "field": "绝杀一头", "url": "https://b.test", "status": "failed", "error": "超时"},
        ],
        "188期": [
            {"section": "甲", "field": "绝杀一头", "url": "https://a.test", "status": "success", "error": ""},
            {"section": "乙", "field": "绝杀一头", "url": "https://b.test", "status": "failed", "error": "超时"},
        ],
        "189期": [
            {"section": "甲", "field": "绝杀一头", "url": "https://a.test", "status": "failed", "error": "未更新"},
            {"section": "乙", "field": "绝杀一头", "url": "https://b.test", "status": "failed", "error": "无权限"},
        ],
    }

    rows = build_all_failed_rows(period_records)

    assert [row["section"] for row in rows] == ["乙"]
    assert rows[0]["period_errors"] == {
        "187期": "失败原因：超时",
        "188期": "失败原因：超时",
        "189期": "失败原因：无权限",
    }


def test_multi_period_any_mode_only_reports_sites_with_no_success() -> None:
    from scripts.lottery_head_multi_period import build_failed_records

    records = [
        HeadRecord("https://a.test", "顶部", "甲", "绝杀一头", "189期", "1头", "", "success", ""),
        HeadRecord("https://b.test", "顶部", "乙", "绝杀一头", "", "", "", "failed", "指定期数均未解析出目标值"),
    ]

    failed = build_failed_records(records)

    assert [record.section for record in failed] == ["乙"]


def test_multi_period_snapshot_paths_accept_raw_and_labeled_periods() -> None:
    from scripts.summarize_multi_period_failures import snapshot_paths

    raw_names = [path.name for path in snapshot_paths("188")]
    labeled_names = [path.name for path in snapshot_paths("188期")]

    assert "multi_period_records_188.json" in raw_names
    assert "multi_period_records_188.json" in labeled_names


def test_fetch_rule_with_period_data_reuses_single_page_fetch_for_output_and_baseline() -> None:
    source_url = "https://example.test/topic/1.html"
    client = FakeClient({
        source_url: FakeResponse(text="""
        <div>158期:绝杀一头【1头】开:0000准</div>
        <div>157期:绝杀一头【2头】开:0000准</div>
        """),
    })
    rule = SiteRule(source_url, "顶部", "甲", "绝杀一头")

    record, site_data = fetch_rule_with_period_data(rule, client=client, target_period="158期", periods=["158期", "157期"])

    assert record.status == "success"
    assert record.period == "158期"
    assert record.value == "1头"
    assert site_data.period_values == {"158期": "1头", "157期": "2头"}
    assert client.requested_urls == [source_url]


def test_fetch_rule_for_any_period_fetches_page_once_and_uses_first_available_period() -> None:
    source_url = "https://example.test/topic/1.html"
    client = FakeClient({
        source_url: FakeResponse(text="""
        <div>189期:绝杀一头【2头】开:0000准</div>
        <div>188期:绝杀一头【3头】开:0000准</div>
        """),
    })
    rule = SiteRule(source_url, "顶部", "甲", "绝杀一头")

    record = fetch_rule_for_any_period(rule, client=client, periods=["190期", "189期", "188期"])

    assert record.status == "success"
    assert record.period == "189期"
    assert record.value == "2头"
    assert client.requested_urls == [source_url]


def test_fetch_rule_for_any_period_skips_conflicted_period_and_uses_next_period() -> None:
    source_url = "https://example.test/topic/1.html"
    client = FakeClient({
        source_url: FakeResponse(text="""
        <div>190期:绝杀一头【1头】开:0000准</div>
        <div>190期:绝杀一头【2头】开:0000准</div>
        <div>189期:绝杀一头【3头】开:0000准</div>
        """),
    })
    rule = SiteRule(source_url, "顶部", "甲", "绝杀一头")

    record = fetch_rule_for_any_period(rule, client=client, periods=["190期", "189期"])

    assert record.status == "success"
    assert record.period == "189期"
    assert record.value == "3头"


def test_fetch_rule_with_period_data_loads_forum_history_when_baseline_periods_are_missing() -> None:
    source_url = "https://example.test/#/forums/15801"
    client = FakeClient({
        source_url: FakeResponse(text=""),
        "https://example.test/api/v1/forums/15801": FakeResponse(data={
            "id": 15801,
            "user_id": 88,
            "topic": "澳门挂牌",
            "sub_topic": "绝杀一头",
            "content": "<p>158期：《绝杀一头》【111头】开：000准</p>",
        }),
        "https://example.test/api/v1/users/88/references/history": FakeResponse(data=[
            {"id": 15701, "user_id": 88, "draw": 157, "topic": "澳门挂牌", "sub_topic": "绝杀一头"},
        ]),
        "https://example.test/api/v1/forums/15701": FakeResponse(data={
            "id": 15701,
            "user_id": 88,
            "topic": "澳门挂牌",
            "sub_topic": "绝杀一头",
            "content": "<p>157期：《绝杀一头》【222头】开：000准</p>",
        }),
    })
    rule = SiteRule(source_url, "顶部", "澳门挂椅", "绝杀一头")

    record, site_data = fetch_rule_with_period_data(rule, client=client, target_period="158期", periods=["158期", "157期"])

    assert record.status == "success"
    assert record.period == "158期"
    assert site_data.period_values == {"158期": "1头"}
    assert site_data.missing == ["157期"]
    assert "https://example.test/api/v1/users/88/references/history" not in client.requested_urls


def test_fetch_rule_with_period_data_fails_when_same_period_has_conflicting_candidates() -> None:
    source_url = "https://example.test/topic/1.html"
    client = FakeClient({
        source_url: FakeResponse(text="""
        <div>158期:绝杀一头【1头】开:0000准</div>
        <div>158期:绝杀一头【2头】开:0000准</div>
        """),
    })
    rule = SiteRule(source_url, "顶部", "甲", "绝杀一头")

    record, site_data = fetch_rule_with_period_data(rule, client=client, target_period="158期", periods=["158期"])

    assert record.status == "failed"
    assert "同一期出现多个冲突候选" in record.error
    assert "1头" in record.error


def test_find_admin_article_rejects_duplicate_target_ids() -> None:
    from scripts.lottery_head_scraper import find_admin_article

    payload = {
        "data": [
            {"id": "article-123", "title": "target-a", "html": "body-a"},
            {"id": "article-123", "title": "target-b", "html": "body-b"},
        ]
    }

    assert find_admin_article(payload, "article-123") is None


def test_admin_aggregate_decoy_period_does_not_override_target_record() -> None:
    source_url = "https://example.test/article/admin/article-123?url=abc"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>loading</body></html>"),
        "https://example.test/api/proxy/admin-articles/article-123": FakeResponse(data={
            "items": [
                {
                    "id": "article-decoy",
                    "authorNickname": "其它站",
                    "title": "190期：④头中特",
                    "html": "190期：其它站④头中特【0.1.2.3】开:00准",
                },
                {
                    "id": "article-123",
                    "authorNickname": "赚发中彩",
                    "title": "190期：④头中特",
                    "html": "190期：赚发中彩④头中特【0.1.3.4】开:00准",
                },
            ]
        }),
    })
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )

    record, _ = fetch_rule_with_period_data(
        rule, client=client, target_period="190期", periods=["190期"]
    )

    assert record.status == "success"
    assert record.value == "2头"


def test_admin_aggregate_duplicate_target_ids_are_reported_as_failure() -> None:
    source_url = "https://example.test/article/admin/article-123?url=abc"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>loading</body></html>"),
        "https://example.test/api/proxy/admin-articles/article-123": FakeResponse(data={
            "items": [
                {
                    "id": "article-123",
                    "authorNickname": "赚发中彩",
                    "title": "190期：④头中特",
                    "html": "190期：赚发中彩④头中特【0.1.3.4】开:00准",
                },
                {
                    "id": "article-123",
                    "authorNickname": "赚发中彩",
                    "title": "190期：④头中特",
                    "html": "190期：赚发中彩④头中特【1.2.3.4】开:00准",
                },
            ]
        }),
    })
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )

    record, _ = fetch_rule_with_period_data(
        rule, client=client, target_period="190期", periods=["190期"]
    )

    assert record.status == "failed"
    assert "目标记录ID匹配到2条" in record.error


def test_admin_browser_fallback_rejects_unstructured_decoy_page(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/article/admin/article-123?url=abc"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>loading</body></html>"),
        "https://example.test/api/proxy/admin-articles/article-123": FakeResponse(
            data={"message": "Not Found"}, status_code=404
        ),
    })
    monkeypatch.setattr(
        scraper,
        "render_dynamic_page",
        lambda url: "<p>190期:〖赚发中彩〗④头中特【0.1.3.4】开:00准</p>",
    )
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )

    record, _ = fetch_rule_with_period_data(
        rule, client=client, target_period="190期", periods=["190期"]
    )

    assert record.status == "failed"


def test_admin_browser_fallback_uses_unique_structured_response_record(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/article/admin/article-123?url=abc"
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )
    target = {
        "id": "article-123",
        "authorNickname": "赚发中彩",
        "title": "190期：④头中特",
        "html": "190期：赚发中彩④头中特【0.1.3.4】开:00准",
    }
    decoy = {
        "id": "article-decoy",
        "authorNickname": "其它站",
        "title": "190期：④头中特",
        "html": "190期：其它站④头中特【1.2.3.4】开:00准",
    }

    class FakeResponse:
        def json(self):
            return {"items": [decoy, target]}

    class FakePage:
        def on(self, event, callback):
            self.response_callback = callback

        def goto(self, *args, **kwargs):
            self.response_callback(FakeResponse())

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def content(self):
            return "<html><body>190期 其它站 ④头中特【1头】</body></html>"

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, headless=True):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(scraper, "sync_playwright", lambda: FakePlaywright())
    scraper.DYNAMIC_PAGE_CACHE.clear()

    rendered = scraper.render_dynamic_page(
        source_url, rule=rule, target_period="190期", target_periods=["190期"]
    )

    assert "赚发中彩" in rendered
    assert "其它站" not in rendered


def test_user_forum_aggregate_rejects_ambiguous_target_topic() -> None:
    source_url = "https://example.test/#/users/3727"
    client = FakeClient({
        source_url: FakeResponse(text=""),
        "https://example.test/api/v1/users/3727": FakeResponse(
            data={"id": 3727, "nickname": "喜欢药"}
        ),
        "https://example.test/api/v1/users/3727/forums": FakeResponse(data=[
            {
                "id": 15564740,
                "user_id": 3727,
                "topic": "绝杀一头",
                "content": "<p>188期〔杀1头〕开0000准</p>",
            },
            {
                "id": 15564741,
                "user_id": 3727,
                "topic": "绝杀一头",
                "content": "<p>188期〔杀2头〕开0000准</p>",
            },
        ]),
    })
    rule = SiteRule(
        source_url,
        "顶部",
        "喜欢药",
        "绝杀一头",
        content_hint="喜欢药",
        parse_hint="user_kill_head",
    )

    record, _ = fetch_rule_with_period_data(
        rule, client=client, target_period="188期", periods=["188期"]
    )

    assert record.status == "failed"
    assert "最新同栏目目标记录不唯一" in record.error


def test_user_forum_dedicated_parser_selects_unique_target_topic() -> None:
    source_url = "https://example.test/#/users/3727"
    client = FakeClient({
        source_url: FakeResponse(text=""),
        "https://example.test/api/v1/users/3727": FakeResponse(
            data={"id": 3727, "nickname": "喜欢药"}
        ),
        "https://example.test/api/v1/users/3727/forums": FakeResponse(data=[
            {
                "id": 15650061,
                "user_id": 3727,
                "topic": "绝杀一头",
                "content": "<p>201期〔杀2头〕开0000准</p><p>200期〔杀4头〕开龙39准</p>",
            },
            {
                "id": 15650062,
                "user_id": 3727,
                "topic": "杀二头",
                "content": "<p>201期〔杀1头〕开0000准</p>",
            },
        ]),
    })
    rule = SiteRule(
        source_url,
        "顶部",
        "喜欢药",
        "绝杀一头",
        content_hint="喜欢药",
        parse_hint="user_kill_head",
    )

    record, site_data = fetch_rule_with_period_data(
        rule, client=client, target_period="201期", periods=["201期", "200期"]
    )

    assert record.status == "success"
    assert record.value == "2头"
    assert site_data.period_values == {"201期": "2头", "200期": "4头"}


def test_forum_history_dedicated_parser_uses_target_history_record() -> None:
    source_url = "https://example.test/#/forums/15356509"
    client = FakeClient({
        source_url: FakeResponse(text=""),
        "https://example.test/api/v1/forums/15356509": FakeResponse(data={
            "id": 15356509,
            "user_id": 11984,
            "topic": "福星报",
            "sub_topic": "必杀一头",
            "content": "<p>155期（必杀一头）【2】开00准</p>",
        }),
        "https://example.test/api/v1/users/11984/references/history": FakeResponse(data=[
            {"id": 15646772, "user_id": 11984, "draw": 201, "topic": "福星报", "sub_topic": "必杀一头"},
            {"id": 15646771, "user_id": 11984, "draw": 201, "topic": "福星报", "sub_topic": "20码中特"},
        ]),
        "https://example.test/api/v1/forums/15646772": FakeResponse(data={
            "id": 15646772,
            "user_id": 11984,
            "topic": "福星报",
            "sub_topic": "必杀一头",
            "content": "<p>201期（必杀一头）【3】开00准</p>",
        }),
    })
    rule = SiteRule(
        source_url,
        "顶部",
        "福星抱抱",
        "必杀一头",
        content_hint="福星报",
        parse_hint="full_period_list",
    )

    record, site_data = fetch_rule_with_period_data(
        rule, client=client, target_period="201期", periods=["201期"]
    )

    assert record.status == "success"
    assert record.value == "3头"
    assert site_data.period_values == {"201期": "3头"}


def test_forum_history_cannot_fill_missing_period_from_another_record() -> None:
    source_url = "https://example.test/#/forums/15801"
    client = FakeClient({
        source_url: FakeResponse(text=""),
        "https://example.test/api/v1/forums/15801": FakeResponse(data={
            "id": 15801,
            "user_id": 88,
            "topic": "澳门挂牌",
            "sub_topic": "绝杀一头",
            "content": "<p>158期：《绝杀一头》【111头】开：000准</p>",
        }),
        "https://example.test/api/v1/users/88/references/history": FakeResponse(data=[
            {"id": 15701, "user_id": 88, "draw": 157, "topic": "澳门挂牌", "sub_topic": "绝杀一头"},
        ]),
        "https://example.test/api/v1/forums/15701": FakeResponse(data={
            "id": 15701,
            "user_id": 88,
            "topic": "澳门挂牌",
            "sub_topic": "绝杀一头",
            "content": "<p>157期：《绝杀一头》【222头】开：000准</p>",
        }),
    })
    rule = SiteRule(source_url, "顶部", "澳门挂椅", "绝杀一头")

    record, site_data = fetch_rule_with_period_data(
        rule, client=client, target_period="158期", periods=["158期", "157期"]
    )

    assert record.status == "success"
    assert site_data.period_values == {"158期": "1头"}
    assert site_data.missing == ["157期"]
    assert "references/history" not in "\n".join(client.requested_urls)


def test_write_failed_txt_uses_explicit_reason_fallback(tmp_path) -> None:
    path = tmp_path / "failed.txt"
    records = [
        HeadRecord(
            url="https://example.test/",
            position="顶部",
            section="测试",
            field="绝杀一头",
            period="",
            value="",
            raw_line="",
            status="failed",
            error="",
        )
    ]

    write_failed_txt(records, path)

    assert "失败原因：未知失败，未返回具体错误" in path.read_text(encoding="utf-8")


def test_write_success_txt_appends_requested_tail_lines_before_ranking(tmp_path) -> None:
    path = tmp_path / "success.txt"
    records = [HeadRecord("https://example.test/", "顶部", "甲", "绝杀一头", "203期", "1头", "", "success", "")]

    write_success_txt(records, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[:5] == ["1头 甲", "开门", "四头开张", "极品大王", ""]
    assert lines[5].split() == ["内容", "次数", "排名"]


def test_write_failed_txt_separates_each_site_with_one_blank_line(tmp_path) -> None:
    path = tmp_path / "failed.txt"
    records = [
        HeadRecord("https://example.test/1", "顶部", "甲", "绝杀一头", "", "", "", "failed", "解析失败"),
        HeadRecord("https://example.test/2", "尾部", "乙", "绝杀一头", "", "", "", "failed", "网络失败"),
    ]

    write_failed_txt(records, path)

    content = path.read_text(encoding="utf-8")
    assert "名称 字段 原因 网站\n甲 绝杀一头 失败原因：解析失败 https://example.test/1\n\n乙 绝杀一头 失败原因：网络失败 https://example.test/2" == content


def test_failure_summary_dir_is_separate_from_success_summary_dir() -> None:
    import scripts.lottery_head_scraper as scraper

    assert scraper.FAILURE_SUMMARY_DIR == Path(
        r"C:\Users\Administrator\Desktop\每天工具\数据系列\七类数据统一归纳失败"
    )
    assert scraper.FAILURE_SUMMARY_DIR != scraper.SUMMARY_DIR


def test_multi_period_failure_outputs_use_failure_summary_dir(tmp_path, monkeypatch) -> None:
    import scripts.lottery_head_multi_period as multi
    from scripts.lottery_head_scraper import HeadRecord

    monkeypatch.setattr(multi, "SUMMARY_DIR", tmp_path / "success")
    monkeypatch.setattr(multi, "FAILURE_SUMMARY_DIR", tmp_path / "failed")
    record = HeadRecord("https://example.test/", "顶部", "测试", "绝杀一头", "", "", "", "failed", "解析失败")

    _, success_path, failed_path = multi.write_multi_period_outputs([record], ["192期", "191期"])

    assert success_path.parent == tmp_path / "success"
    assert failed_path.parent == tmp_path / "failed"
    assert "开门\n四头开张\n极品大王" in success_path.read_text(encoding="utf-8")


def test_multi_period_failure_summary_uses_failure_summary_dir(tmp_path, monkeypatch) -> None:
    import scripts.summarize_multi_period_failures as summary

    monkeypatch.setattr(summary, "FAILURE_SUMMARY_DIR", tmp_path / "failed")
    rows = [
        {
            "section": "甲",
            "field": "绝杀一头",
            "url": "https://example.test/1",
            "period_errors": {
                "192期": "失败原因：解析失败",
                "191期": "失败原因：网络失败",
            },
        },
        {
            "section": "乙",
            "field": "绝杀一头",
            "url": "https://example.test/2",
            "period_errors": {
                "192期": "失败原因：解析失败",
                "191期": "失败原因：网络失败",
            },
        },
    ]

    output_path = summary.write_summary(["192期", "191期"], rows)

    assert output_path.parent == tmp_path / "failed"
    assert "\n\n乙 绝杀一头" in output_path.read_text(encoding="utf-8")


def test_fetch_rule_with_period_data_uses_content_hint_to_avoid_unrelated_conflict() -> None:
    source_url = "https://example.test/"
    client = FakeClient({
        source_url: FakeResponse(text=""),
    })
    fragments = [
        "<div>澳门信封论坛『绝杀一头』</div><div>159期绝杀一头【2头】开:？00准</div>",
        "<div>澳门信封论坛『公式专区』</div><div>159期：絕殺一頭(444頭）開？00准</div>",
    ]
    rule = SiteRule(source_url, "顶部", "信封", "绝杀一头", content_hint="『绝杀一头』")

    candidates = extract_period_candidates_by_period(fragments, rule, ["159期"])

    assert [candidate["value"] for candidate in candidates["159期"]] == ["2头"]


def test_strict_position_three_target_period_rejects_target_outside_top_three() -> None:
    source_url = "https://example.test/"
    client = FakeClient({
        source_url: FakeResponse(text="""
        <div>159期绝杀一头【2头】开:？00准</div>
        <div>158期绝杀一头【3头】开:兔16准</div>
        <div>156期绝杀一头【1头】开:马01准</div>
        <div>153期绝杀一头【2头】开:虎41准</div>
        """),
    })
    rule = SiteRule(source_url, "顶部", "信封", "绝杀一头", parse_hint="strict_position_three")

    record, _ = fetch_rule_with_period_data(rule, client=client, target_period="153期", periods=["153期"])

    assert record.status == "failed"
    assert "不在顶部三条内" in record.error


def test_strict_position_three_miaosha_ignores_unrelated_same_period_list_items() -> None:
    source_url = "https://example.test/"
    client = FakeClient({
        source_url: FakeResponse(text="""
        <div>159期:精杀一头精准杀料【精杀一头】</div>
        <div>157期㊣秒杀【4头】开兔40对</div>
        <div>158期㊣秒杀【3头】开兔16对</div>
        <div>159期㊣秒杀【1头】开0000对</div>
        <div>159期:澳彩赤兔→◆三头四肖◆期期早公开</div>
        """),
    })
    rule = SiteRule(
        source_url,
        "尾部",
        "精准资料",
        "精杀一头",
        content_hint="精杀一头精准",
        parse_hint="strict_position_three_miaosha",
    )

    record, site_data = fetch_rule_with_period_data(rule, client=client, target_period="159期", periods=["159期"])

    assert record.status == "success"
    assert record.value == "1头"
    assert site_data.period_values == {"159期": "1头"}


def test_full_period_list_hint_keeps_target_period_for_bottom_long_history() -> None:
    source_url = "https://example.test/topic/248016.html"
    rows = "\n".join(
        f"<p>{period:03d}期 大杀一头『{period % 5}头』开0000准</p>"
        for period in range(160, 0, -1)
    )
    client = FakeClient({
        source_url: FakeResponse(text=f"<div>维鸠居之</div>{rows}"),
    })
    rule = SiteRule(source_url, "尾部", "维鸠居之", "大杀一头", parse_hint="full_period_list")

    record, site_data = fetch_rule_with_period_data(rule, client=client, target_period="160期", periods=["160期"])

    assert record.status == "success"
    assert record.period == "160期"
    assert record.value == "0头"
    assert site_data.period_values == {"160期": "0头"}


def test_missing_head_full_period_list_keeps_top_ten_history() -> None:
    source_url = "https://example.test/art_gsb/8160"
    rows = "\n".join(
        f"<p>{period}期：※特码四头※【0123】开 ?? 准</p>"
        for period in range(163, 153, -1)
    )
    client = FakeClient({
        source_url: FakeResponse(text=f"<div>作者：无名侠客</div>{rows}"),
    })
    rule = SiteRule(
        source_url,
        "顶部",
        "无名侠客",
        "特码四头",
        content_hint="无名侠客",
        parse_hint="missing_head_from_four_combo_full_period_list",
    )

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="163期",
        periods=[f"{period}期" for period in range(163, 153, -1)],
    )

    assert record.status == "success"
    assert record.value == "4头"
    assert len(site_data.period_values) == 10


def test_missing_head_full_period_list_parses_wumingxiake_current_multiline_format() -> None:
    source_url = "https://example.test/art_gsb/8160"
    html = """
    <div>187期:【特码四头】澳门资料大全</div>
    <div>作者：无名侠客</div>
    <p>★广告内容</p>
    <p>187期：</p>
    <p>※特码四头※</p>
    <p>【1234】</p>
    <p>开 ?? 准</p>
    <p>186期：</p>
    <p>※特码四头※</p>
    <p>【01<br>2<br>4】</p>
    <p>开 23 准</p>
    """
    client = FakeClient({source_url: FakeResponse(text=html)})
    rule = SiteRule(
        source_url,
        "顶部",
        "无名侠客",
        "特码四头",
        content_hint="无名侠客",
        parse_hint="missing_head_from_four_combo_full_period_list",
    )

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="187期",
        periods=["187期", "186期"],
    )

    assert record.status == "success"
    assert record.period == "187期"
    assert record.value == "0头"
    assert site_data.period_values == {"187期": "0头", "186期": "3头"}


def test_anchored_missing_head_four_combo_keeps_same_url_sections_separate() -> None:
    source_url = "https://example.test/"
    html = """
    <div>神童资讯【四头中特】</div>
    <p>190期四头中特【0134】开:??准</p>
    <p>189期四头中特【1234】开:15准</p>
    <div>【老五主四头】</div>
    <p>190期四头中特【0124】开:??准</p>
    <p>189期四头中特【0123】开:15准</p>
    """
    client = FakeClient({source_url: FakeResponse(text=html)})
    shentong = SiteRule(
        source_url,
        "顶部",
        "神童资讯",
        "四头中特",
        content_hint="神童资讯【四头中特】",
        parse_hint="anchored_missing_head_from_four_combo",
    )
    laowu = SiteRule(
        source_url,
        "顶部",
        "老五主",
        "四头中特",
        content_hint="【老五主四头】",
        parse_hint="anchored_missing_head_from_four_combo",
    )

    shentong_record, _ = fetch_rule_with_period_data(
        shentong,
        client=client,
        target_period="190期",
        periods=["190期", "189期"],
    )
    laowu_record, _ = fetch_rule_with_period_data(
        laowu,
        client=client,
        target_period="190期",
        periods=["190期", "189期"],
    )

    assert shentong_record.status == "success"
    assert shentong_record.value == "2头"
    assert laowu_record.status == "success"
    assert laowu_record.value == "3头"


def test_topic_title_anchored_four_combo_stops_before_old_article_navigation() -> None:
    html = """
    <div>高手料195期:【精英四头】琪花瑶草作者:琪花瑶草</div>
    <p>195期精英四头【0.2.3.1】开0000准</p>
    <p>194期精英四头【1.3.4.2】开蛇26准</p>
    <div>上一篇：高手料195期:【精英四头】旧文章 下一篇：其它栏目</div>
    <p>195期精英四头【1.3.0.4】开蛇25错</p>
    <p>194期精英四头【4.2.3.0】开牛29准</p>
    """

    records = extract_head_records(
        html,
        "精英四头",
        "topic_title_anchored_missing_head_from_four_combo",
        "195期",
        anchor_marker="琪花瑶草",
    )

    assert records == [
        {"period": "195期", "value": "4头", "raw_line": "195期精英四头【0.2.3.1】开0000准"}
    ]


def test_anchored_missing_head_four_combo_skips_ads_before_first_period() -> None:
    source_url = "https://example.test/art_gsb/8160"
    html = """
    <div>作者：无名侠客</div>
    <p>★[49彩票]广告</p>
    <p>190期：</p>
    <p>※特码四头※</p>
    <p>【0123】</p>
    <p>开 ?? 准</p>
    <p>189期：</p>
    <p>※特码四头※</p>
    <p>【0134】</p>
    <p>开 15 准</p>
    <p>★[49彩票]广告</p>
    """
    client = FakeClient({source_url: FakeResponse(text=html)})
    rule = SiteRule(
        source_url,
        "顶部",
        "无名侠客",
        "特码四头",
        content_hint="作者：无名侠客",
        parse_hint="anchored_missing_head_from_four_combo",
    )

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="190期",
        periods=["190期", "189期"],
    )

    assert record.status == "success"
    assert record.value == "4头"
    assert site_data.period_values == {"190期": "4头", "189期": "2头"}


def test_admin_article_falls_back_to_landing_page_data() -> None:
    source_url = "https://example.test/article/admin/article-123?url=abc"
    article_html = """
    <p>189期:<strong>〖赚发中彩〗</strong>④头中特【0.1.3.4】开:00准</p>
    <p>188期:<strong>〖赚发中彩〗</strong>④头中特【0.1.2.3】开:羊23准</p>
    """
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>loading</body></html>"),
        "https://example.test/api/proxy/admin-articles/article-123": FakeResponse(data=None),
        "https://example.test/api/proxy/landing-page-data?url=abc": FakeResponse(data={
            "sectionData": {
                "section-a": {
                    "adminArticles": [
                        {
                            "id": "article-123",
                            "authorNickname": "赚发中彩",
                            "title": "<p>190期：【④头中特】</p>",
                            "html": article_html,
                        }
                    ]
                }
            }
        }),
    })
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="189期",
        periods=["189期", "188期"],
    )

    assert record.status == "success"
    assert record.period == "189期"
    assert record.value == "2头"
    assert site_data.period_values == {"189期": "2头", "188期": "4头"}


def test_period_title_detail_opens_matching_period_and_title_link() -> None:
    source_url = "https://example.test/topic/257907.html"
    list_html = """
    <a href="/topic/1030726.html">
      <div>190期：【不如离去】☆绝杀一头☆实力见证！</div>
    </a>
    <a href="/topic/1030725.html">
      <div>190期：【阳光明媚】☆绝杀一头☆实力见证！</div>
    </a>
    <a href="/topic/1029651.html">
      <div>189期：【不如离去】☆绝杀一头☆实力见证！</div>
    </a>
    """
    client = FakeClient({
        source_url: FakeResponse(text=list_html),
        "https://example.test/topic/1030726.html": FakeResponse(
            text="<p>190期:◆绝杀一头◆【2】开0000准</p>"
        ),
        "https://example.test/topic/1029651.html": FakeResponse(
            text="<p>189期:◆绝杀一头◆【4】开龙15准</p>"
        ),
    })
    rule = SiteRule(
        source_url,
        "顶部",
        "不如离去",
        "绝杀一头",
        content_hint="不如离去",
        parse_hint="period_title_detail",
    )

    record, site_data = fetch_rule_with_period_data(
        rule,
        client=client,
        target_period="190期",
        periods=["190期", "189期"],
    )

    assert "https://example.test/topic/1030725.html" not in client.requested_urls
    assert record.status == "success"
    assert record.period == "190期"
    assert record.value == "2头"
    assert site_data.period_values == {"190期": "2头", "189期": "4头"}


def test_period_title_detail_any_mode_stops_after_first_successful_period() -> None:
    source_url = "https://example.test/topic/257907.html"
    list_html = """
    <a href="/topic/190.html"><div>190期：【不如离去】☆绝杀一头☆</div></a>
    <a href="/topic/189.html"><div>189期：【不如离去】☆绝杀一头☆</div></a>
    <a href="/topic/188.html"><div>188期：【不如离去】☆绝杀一头☆</div></a>
    """
    client = FakeClient({
        source_url: FakeResponse(text=list_html),
        "https://example.test/topic/190.html": FakeResponse(text="<p>190期:◆绝杀一头◆未开奖</p>"),
        "https://example.test/topic/189.html": FakeResponse(text="<p>189期:◆绝杀一头◆【3】开0000准</p>"),
        "https://example.test/topic/188.html": FakeResponse(text="<p>188期:◆绝杀一头◆【4】开0000准</p>"),
    })
    rule = SiteRule(
        source_url,
        "顶部",
        "不如离去",
        "绝杀一头",
        content_hint="不如离去",
        parse_hint="period_title_detail",
    )

    record = fetch_rule_for_any_period(rule, client=client, periods=["190期", "189期", "188期"])

    assert record.status == "success"
    assert record.period == "189期"
    assert "https://example.test/topic/188.html" not in client.requested_urls


def test_bisha_yitou_plain_hint_requires_exact_column_and_value_format() -> None:
    html = """
    <div>192期:杀一头【1头】开？00准</div>
    <div>192期:必杀一头【3头】开？00准</div>
    """

    records = extract_head_records(html, "杀一头", "bisha_yitou_plain", "192期")

    assert records == [{"period": "192期", "value": "3头", "raw_line": "192期:必杀一头【3头】开？00准"}]


def test_bisha_yitou_bracket_hint_requires_bisha_and_kill_value_brackets() -> None:
    html = """
    <div>192期【杀一头】【3头】开:？00准</div>
    <div>192期【必杀一头】【杀3头】开:？00准</div>
    """

    records = extract_head_records(html, "杀一头", "bisha_yitou_bracket", "192期")

    assert records == [{"period": "192期", "value": "3头", "raw_line": "192期【必杀一头】【杀3头】开:？00准"}]


def test_anchored_four_combo_hint_uses_section_anchor_before_missing_head() -> None:
    html = """
    <div>【其它】四头中特 192期：必中四头（0.1.2.3）开？00准</div>
    <div>【金多宝】四头中特 192期：必中四头（2.1.0.4）开？00准</div>
    """
    rule = SiteRule(
        "https://example.test/",
        "顶部",
        "金多宝四头中特",
        "必中四头",
        content_hint="【金多宝】四头中特",
        parse_hint="anchored_missing_head_from_four_combo",
    )

    records = extract_head_records(
        html,
        rule.field,
        rule.parse_hint,
        "192期",
        anchor_marker=rule.content_hint,
    )

    assert records == [{"period": "192期", "value": "3头", "raw_line": "192期：必中四头（2.1.0.4）开？00准"}]


def test_admin_article_prefers_api_and_does_not_render(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/article/admin/article-123?url=abc"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>loading</body></html>"),
        "https://example.test/api/proxy/admin-articles/article-123": FakeResponse(data={
            "id": "article-123",
            "authorNickname": "赚发中彩",
            "title": "<p>190期：【④头中特】</p>",
            "html": "<p>190期:<strong>〖赚发中彩〗</strong>④头中特【0.1.3.4】开:00准</p>",
        }),
    })
    monkeypatch.setattr(scraper, "render_dynamic_page", lambda url: (_ for _ in ()).throw(AssertionError("should not render")))
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )

    record, _ = fetch_rule_with_period_data(rule, client=client, target_period="190期", periods=["190期"])

    assert record.status == "success"
    assert record.value == "2头"


def test_admin_article_uses_configured_api_url_first(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/article/admin/article-123?url=abc"
    api_url = "https://api.example.test/article-123"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>loading</body></html>"),
        api_url: FakeResponse(data={
            "id": "article-123",
            "authorNickname": "赚发中彩",
            "title": "<p>190期：【④头中特】</p>",
            "html": "<p>190期:<strong>〖赚发中彩〗</strong>④头中特【0.1.3.4】开:00准</p>",
        }),
    })
    monkeypatch.setattr(scraper, "render_dynamic_page", lambda url: (_ for _ in ()).throw(AssertionError("should not render")))
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
        api_url=api_url,
    )

    record, _ = fetch_rule_with_period_data(rule, client=client, target_period="190期", periods=["190期"])

    assert api_url in client.requested_urls
    assert "https://example.test/api/proxy/admin-articles/article-123" not in client.requested_urls
    assert record.status == "success"
    assert record.value == "2头"


def test_admin_article_renders_only_after_api_404(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/article/admin/article-123?url=abc"
    rendered_html = "<p>190期:<strong>〖赚发中彩〗</strong>④头中特【0.1.3.4】开:00准</p>"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>loading</body></html>"),
        "https://example.test/api/proxy/admin-articles/article-123": FakeResponse(
            data={"message": "Not Found"},
            status_code=404,
        ),
    })
    rendered_urls = []
    monkeypatch.setattr(scraper, "render_dynamic_page", lambda url, **kwargs: rendered_urls.append(url) or rendered_html)
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )

    record, _ = fetch_rule_with_period_data(rule, client=client, target_period="190期", periods=["190期"])

    assert rendered_urls == [source_url]
    assert record.status == "success"
    assert record.value == "2头"


def test_manager_article_uses_manager_api_first(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/article/manager/article-123?url=abc"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>loading</body></html>"),
        "https://example.test/api/proxy/manager-articles/article-123": FakeResponse(data={
            "id": "article-123",
            "authorNickname": "随风细雨",
            "title": "193期：【④头中特】",
            "html": "192期:『随风细雨』④头中特【1.2.0.4】开:25准",
        }),
    })
    monkeypatch.setattr(scraper, "render_dynamic_page", lambda url: (_ for _ in ()).throw(AssertionError("should not render")))
    rule = SiteRule(
        source_url,
        "尾部",
        "随风细雨",
        "④头中特",
        content_hint="随风细雨",
        parse_hint="manager_anchored_missing_head_from_four_combo",
    )

    record, _ = fetch_rule_with_period_data(rule, client=client, target_period="192期", periods=["192期"])

    assert record.status == "success"
    assert record.value == "3头"


def test_manager_anchored_four_combo_binds_site_and_field_to_same_period() -> None:
    html = """
    <div>192期:『其它站』④头中特【0.1.2.3】开:25准</div>
    <div>192期:『随风细雨』④头中特【1.2.0.4】开:25准</div>
    <div>191期:『随风细雨』④头中特【1.2.3.4】开:29准</div>
    """

    records = extract_head_records(
        html,
        "④头中特",
        "manager_anchored_missing_head_from_four_combo",
        "192期",
        anchor_marker="随风细雨",
    )

    assert records == [{"period": "192期", "value": "3头", "raw_line": "192期:『随风细雨』④头中特【1.2.0.4】开:25准"}]


def test_admin_article_renders_when_page_shell_lacks_head_data(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/article/admin/article-123?url=abc"
    rendered_html = "<p>190期:<strong>〖赚发中彩〗</strong>④头中特【0.1.3.4】开:00准</p>"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>190期 赚发中彩 ④头中特 但没有头值</body></html>"),
        "https://example.test/api/proxy/admin-articles/article-123": FakeResponse(data=None),
        "https://example.test/api/proxy/landing-page-data?url=abc": FakeResponse(data=None),
    })
    rendered_urls = []
    monkeypatch.setattr(scraper, "render_dynamic_page", lambda url, **kwargs: rendered_urls.append(url) or rendered_html)
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )

    record, _ = fetch_rule_with_period_data(rule, client=client, target_period="190期", periods=["190期"])

    assert rendered_urls == [source_url]
    assert record.status == "success"
    assert record.value == "2头"


def test_admin_article_renders_when_page_shell_lacks_target_markers(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/article/admin/article-123?url=abc"
    rendered_html = "<p>190期:<strong>〖赚发中彩〗</strong>④头中特【0.1.3.4】开:00准</p>"
    client = FakeClient({
        source_url: FakeResponse(text="<html><body>搜索 首页 规则 充值 客服</body></html>"),
        "https://example.test/api/proxy/admin-articles/article-123": FakeResponse(data=None),
        "https://example.test/api/proxy/landing-page-data?url=abc": FakeResponse(data=None),
    })
    rendered_urls = []
    monkeypatch.setattr(scraper, "render_dynamic_page", lambda url, **kwargs: rendered_urls.append(url) or rendered_html)
    rule = SiteRule(
        source_url,
        "尾部",
        "赚发中彩",
        "④头中特",
        content_hint="赚发中彩",
        parse_hint="missing_head_from_four_combo",
    )

    record, _ = fetch_rule_with_period_data(rule, client=client, target_period="190期", periods=["190期"])

    assert rendered_urls == [source_url]
    assert record.status == "success"
    assert record.value == "2头"


def test_non_admin_page_does_not_render_when_empty(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    source_url = "https://example.test/topic/1.html"
    client = FakeClient({source_url: FakeResponse(text="<html><body>loading</body></html>")})
    monkeypatch.setattr(scraper, "render_dynamic_page", lambda url: (_ for _ in ()).throw(AssertionError("should not render")))
    rule = SiteRule(source_url, "顶部", "普通站", "绝杀一头", content_hint="普通站")

    record, _ = fetch_rule_with_period_data(rule, client=client, target_period="190期", periods=["190期"])

    assert record.status == "failed"


def test_empty_render_result_is_not_cached(monkeypatch) -> None:
    import scripts.lottery_head_scraper as scraper

    calls = {"count": 0}

    class FakePage:
        def goto(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def content(self):
            calls["count"] += 1
            return ""

        def locator(self, selector):
            return self

        def inner_text(self, timeout):
            return ""

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, headless=True):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(scraper, "sync_playwright", lambda: FakePlaywright(), raising=False)
    scraper.DYNAMIC_PAGE_CACHE.clear()

    assert scraper.render_dynamic_page("https://example.test/article/admin/1") == ""
    assert scraper.render_dynamic_page("https://example.test/article/admin/1") == ""
    assert calls["count"] == 4


def test_top_primary_ten_periods_ignores_later_pasted_history() -> None:
    rows = "\n".join(
        f"<p>{period}期 绝杀一头【{period % 5}头】开0000准</p>"
        for period in range(171, 161, -1)
    )
    html = f"{rows}<p>171期 绝杀一头【1头】开羊47准</p>"
    rule = SiteRule(
        "https://example.test/topic/1.html",
        "顶部",
        "肆言如狂",
        "绝杀一头",
        parse_hint="top_primary_ten_periods",
    )

    candidates = extract_period_candidates_by_period([html], rule, ["171期"])

    assert candidates["171期"] == [
        {
            "period": "171期",
            "value": "1头",
            "raw_line": "171期绝杀一头【1头】开0000准",
        }
    ]



def test_decode_script_document_writes_handles_plain_document_writeln() -> None:
    script = 'document.writeln("<p>181期：必中四头（2.1.0.4）开？00准</p>");'

    decoded = decode_script_document_writes(script)

    assert "181期：必中四头" in decoded
    assert "2.1.0.4" in decoded


def test_decode_inline_gbk_decrypt_calls() -> None:
    html = "<script>decrypt('de-content','MTgxxtrLxM23')</script>"

    decoded = decode_inline_gbk_decrypt_calls(html)

    assert "181期" in decoded
    assert "四头" in decoded


def test_missing_head_from_parentheses_four_combo() -> None:
    html = "<p>181期：必中四头（2.1.0.4）开？00准</p>"

    record = extract_latest_head_record(html, "必中四头", "missing_head_from_four_combo", "181期")

    assert record is not None
    assert record["value"] == "3头"


def test_missing_head_from_separator_four_combo() -> None:
    html = "<p>181期：公式四头〓4321〓开00准</p>"

    record = extract_latest_head_record(html, "公式四头", "missing_head_from_four_combo", "181期")

    assert record is not None
    assert record["value"] == "0头"


def test_missing_head_from_dot_separator_four_combo() -> None:
    html = "<p>203期：四头中特〓0.1.3.4〓开马25错</p>"

    record = extract_latest_head_record(
        html,
        "四头中特",
        "missing_head_from_four_combo",
        "203期",
    )

    assert record is not None
    assert record["value"] == "2头"


def test_sword_head_extracts_fourth_sword_head() -> None:
    html = """
    <div>180期 七剑 第一剑：买兔牛 特：？00 第四剑：杀二头 第五剑：杀二尾</div>
    <div>179期 七剑 第一剑：买猪狗 特：龙15 第四剑：杀三头 第五剑：杀五尾</div>
    """

    records = extract_period_candidates_by_period(
        [html],
        SiteRule("https://example.test/", "顶部", "七剑下天山", "第四剑", content_hint="七剑", parse_hint="sword_head"),
        ["180期", "179期"],
    )

    assert records["180期"][0]["value"] == "2头"
    assert records["179期"][0]["value"] == "3头"


def test_four_combo_after_marker_extracts_contiguous_combo_missing_head() -> None:
    html = """
    <div>【竞星剑稳中四头】</div>
    <p>181期〖3410头〗√</p>
    <p>180期〖1024头〗√</p>
    """

    records = extract_period_candidates_by_period(
        [html],
        SiteRule("https://example.test/", "顶部", "竞星剑", "中四头", content_hint="竞星剑", parse_hint="four_combo_after_marker"),
        ["181期", "180期"],
    )

    assert records["181期"][0]["value"] == "2头"
    assert records["180期"][0]["value"] == "3头"


def test_must_win_head_extracts_direct_head_value() -> None:
    html = "<p>180期必中一头：2</p>"

    records = extract_period_candidates_by_period(
        [html],
        SiteRule("https://example.test/", "顶部", "执笔抒情", "必中一头", content_hint="必中一头", parse_hint="must_win_head"),
        ["180期"],
    )

    assert records["180期"][0]["value"] == "2头"


def test_number_code_to_head_extracts_head_from_two_digit_code() -> None:
    html = """
    <div>不视邪色</div>
    <p>180期大杀一码【36】开000准</p>
    <p>179期大杀一码【04】开龙15准</p>
    """

    records = extract_period_candidates_by_period(
        [html],
        SiteRule("https://example.test/", "顶部", "不视邪色", "大杀一码", content_hint="不视邪色", parse_hint="number_code_to_head"),
        ["180期", "179期"],
    )

    assert records["180期"][0]["value"] == "3头"
    assert records["179期"][0]["value"] == "0头"

def test_strict_position_three_missing_head_ignores_later_same_period_conflict() -> None:
    source_url = "https://example.test/topic/503025.html"
    client = FakeClient({
        source_url: FakeResponse(text="""
        <p>181期：宁波商人【公式四头】值得信赖</p>
        <p>181期：公式四头〓4321〓开00准</p>
        <p>180期：公式四头〓3214〓开狗21准</p>
        <p>179期：公式四头〓2140〓开龙15准</p>
        <p>181期：公式四头〓4210〓开羊23准</p>
        """),
    })
    rule = SiteRule(
        source_url,
        "顶部",
        "宁波商人",
        "公式四头",
        content_hint="宁波商人",
        parse_hint="strict_position_three_missing_head_from_four_combo",
    )

    record, site_data = fetch_rule_with_period_data(rule, client=client, target_period="181期", periods=["181期"])

    assert record.status == "success"
    assert record.period == "181期"
    assert record.value == "0头"
    assert site_data.period_values == {"181期": "0头"}


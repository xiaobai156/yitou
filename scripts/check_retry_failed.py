from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lottery_head.models import HeadRecord, SiteRule
from lottery_head.output_transaction import commit_artifacts_transaction
from lottery_head.retry_failed import format_head_ranking, match_failed_rules, merge_failed_txt, merge_success_txt, read_failed_targets
from lottery_head.selection import _global_direction_window, collect_ordered_candidates
from lottery_head.models import SourceDocument
from scripts.retry_failed_sites import ensure_retry_inputs_unchanged, validate_retry_window


def main():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        failed = root / "failed.txt"
        a = "失败 A https://example.com/a 方向: 顶部 期数: 251期\r\n阶段: 指定期数校验 原因: 251期不在顶部第一条"
        b = "  " + a.replace(" A ", " B ").replace("/a ", "/b ")
        failed.write_bytes(b"\xef\xbb\xbf" + (a + "\r\n\r\n" + b + "\r\n\r\n失败分类统计\r\n方向范围外 2条").encode())
        rules = [SiteRule("https://example.com/" + name.lower(), "顶部", name, "头", parse_hint="period") for name in ("A", "B", "C")]
        assert [r.section for r in match_failed_rules(read_failed_targets(failed, "251期"), rules)] == ["A", "B"]
        record = HeadRecord(rules[0].url, "顶部", "A", "头", "251期", "2头", "", "success", "", parse_hint="period")
        remaining = merge_failed_txt(failed, [record], "251期")
        assert remaining.startswith(b"\xef\xbb\xbf") and b"\r\n" in remaining and "失败 B".encode() in remaining
        success = root / "success.txt"
        success.write_bytes(b"\xef\xbb\xbf" + "1头 旧站\r\n\r\n内容\t次数\t排名\r\n".encode())
        record_b = HeadRecord(rules[1].url, "顶部", "B", "头", "251期", "2头", "", "success", "", parse_hint="period")
        record_c = HeadRecord(rules[2].url, "顶部", "C", "头", "251期", "2头", "", "success", "", parse_hint="period")
        result = merge_success_txt(success, [record, record, record_b, record_c]).decode("utf-8-sig")
        assert result.count("2头 A") == 1 and "2头 B" in result and "2头 C" in result and "2头\t3\t1" in result
        deceptive = root / "deceptive.txt"
        deceptive.write_text("正文 内容 次数 排名 但不是表头\n2头 旧\n\n内容\t次数\t排名\n2头\t1\t1\n", encoding="utf-8")
        assert "2头 旧" in merge_success_txt(deceptive, [record]).decode()
        try:
            validate_retry_window({"periods": ["251期"]}, "241期")
        except ValueError:
            pass
        else:
            raise AssertionError("窗口外期数未拒绝")
        watched = root / "watched.json"
        watched.write_text("old", encoding="utf-8")
        expected = {watched: watched.read_bytes()}
        watched.write_text("other-update", encoding="utf-8")
        try:
            ensure_retry_inputs_unchanged(expected)
        except RuntimeError:
            pass
        else:
            raise AssertionError("抓取期间外部更新未被拒绝")
        first, second = root / "first.txt", root / "second.txt"
        first.write_text("old", encoding="utf-8")
        second.write_text("old2", encoding="utf-8")
        before = first.read_bytes()
        import lottery_head.output_transaction as transaction
        original_replace = Path.replace
        calls = [0]
        def fail_second_replace(self, target):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError("injected replace failure")
            return original_replace(self, target)
        Path.replace = fail_second_replace
        try:
            commit_artifacts_transaction({first: b"new", second: b"new2"})
        except Exception:
            pass
        else:
            raise AssertionError("事务失败未抛出")
        finally:
            Path.replace = original_replace
        assert first.read_bytes() == before
    assert format_head_ranking(["2头", "2头"]).count("2头\t2\t1") == 1
    _check_main_scope_and_snapshot()
    # 方向窗口只在权威文档内定界：page 各一条时顶部取首、底部取末。
    candidates = [{"period": "251期", "value": "2头", "document_key": "a", "source_route": "page", "document_order": 0, "original_position": 0}, {"period": "251期", "value": "2头", "document_key": "b", "source_route": "page", "document_order": 1, "original_position": 1}]
    windowed = _global_direction_window(candidates, "顶部", "period")
    assert len(windowed) == 1 and windowed[0]["document_key"] == "a", windowed
    windowed_bottom = _global_direction_window(candidates, "尾部", "period")
    assert len(windowed_bottom) == 1 and windowed_bottom[0]["document_key"] == "b", windowed_bottom
    # 跨文档借值回归（顶部/底部/冲突/非目标期冲突/find_latest）。
    _check_no_cross_document_borrowing()
    _check_success_txt_period_guard()
    _check_build_artifacts_period_guard()
    try:
        collect_ordered_candidates([SourceDocument("", "", "x", resource_error="script failed", resource_required=True)], rules[0])
    except ValueError:
        pass
    else:
        raise AssertionError("必需资源失败被跳过")
    print("PASS: 导入、定点身份、窗口、BOM/CRLF、精确表头、去重、回滚")


def _check_no_cross_document_borrowing():
    """跨文档借值回归：窗口只在权威文档内定界，冲突检查只对目标期严格。"""
    import lottery_head.selection as selection

    rule = SiteRule("https://example.com/a", "顶部", "A", "绝杀一头",
                    content_hint="A", parse_hint="period")
    original = selection._collect_ordered_candidates

    def cand(period, value, route, order, block=0):
        return {"period": period, "value": value, "raw_line": f"{period}{value}",
                "document_key": route, "source_route": route,
                "document_order": order, "block_order": block,
                "original_position": order}

    try:
        # 1) 权威页与脚本块同期同值 -> 窗口只输出 1 条且必须来自权威页（脚本记录被排除）。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "1头", "page", 0),
            cand("251期", "1头", "inline_script", 1),
        ]
        window1 = selection._global_direction_window(
            selection._collect_ordered_candidates([], rule), "顶部", rule.parse_hint
        )
        assert len(window1) == 1, window1
        assert window1[0]["source_route"] == "page", window1
        # 权威页缺目标期时，脚本记录绝不能进窗口（哪怕权威文档非空）。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("250期", "2头", "page", 0),
            cand("251期", "3头", "inline_script", 1),
        ]
        window1b = selection._global_direction_window(
            selection._collect_ordered_candidates([], rule), "顶部", rule.parse_hint
        )
        assert [c["source_route"] for c in window1b] == ["page"], window1b

        # 1c) 权威文档为空时回退到同文档派生的脚本块（149/240 站的实际形态）。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "3头", "script", 0),
        ]
        window1c = selection._global_direction_window(
            selection._collect_ordered_candidates([], rule), "顶部", rule.parse_hint
        )
        assert [c["value"] for c in window1c] == ["3头"], window1c

        # 1d) 非主来源路由（forum/forum_history）不得进窗口。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "3头", "forum", 0),
            cand("251期", "3头", "forum_history", 1),
        ]
        window1d = selection._global_direction_window(
            selection._collect_ordered_candidates([], rule), "顶部", rule.parse_hint
        )
        assert window1d == [], window1d

        # 1e) user_kill_head 的 user_forum 是主来源，必须能进窗口。
        user_rule = SiteRule("https://example.com/#/users/1", "顶部", "A", "绝杀一头",
                             content_hint="A", parse_hint="user_kill_head")
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "3头", "user_forum", 0),
        ]
        window1e = selection._global_direction_window(
            selection._collect_ordered_candidates([], user_rule), "顶部", user_rule.parse_hint
        )
        assert [c["value"] for c in window1e] == ["3头"], window1e

        # 2) 顶部：权威页只有 250 期、脚本块有 251 期 -> 不得借脚本的 251 期。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("250期", "2头", "page", 0),
            cand("251期", "3头", "inline_script", 1),
        ]
        assert not selection.extract_period_candidates_by_period([], rule, ["251期"]).get("251期")

        # 3) 底部：权威页末条 250 期、脚本块末条 251 期 -> 底部取权威页末条，不得借 251 期。
        bottom_rule = SiteRule("https://example.com/a", "尾部", "A", "绝杀一头",
                               content_hint="A", parse_hint="period")
        assert not selection.extract_period_candidates_by_period([], bottom_rule, ["251期"]).get("251期")
        # 反过来：权威页有 251 期、脚本块滞后到 250 期 -> 底部仍要取权威页的 251 期。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "4头", "page", 0),
            cand("250期", "1头", "inline_script", 1),
        ]
        got_bottom = selection.extract_period_candidates_by_period([], bottom_rule, ["251期"])
        assert [c["value"] for c in got_bottom.get("251期", [])] == ["4头"], got_bottom

        # 4) 目标期两个不同值 -> 必须失败。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "2头", "page", 0),
            cand("251期", "4头", "inline_script", 1),
        ]
        try:
            selection.extract_period_candidates_by_period([], rule, ["251期"])
        except ValueError:
            pass
        else:
            raise AssertionError("同期冲突值未被拒绝")

        # 5) 非目标期冲突不得拖垮整站：只对 strict 指定期严格。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "1头", "page", 0),
            cand("250期", "2头", "page", 1),
            cand("250期", "3头", "inline_script", 2),
        ]
        got5 = selection.extract_period_candidates_by_period(
            [], rule, ["251期", "250期"], strict_conflict_periods=["251期"]
        )
        assert [c["value"] for c in got5.get("251期", [])] == ["1头"], got5

        # 6) find_latest_available_record 底部语义：返回权威页末条，不返回辅助文档旧期。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "4头", "page", 0),
            cand("250期", "1头", "inline_script", 1),
        ]
        latest = selection.find_latest_available_record([], bottom_rule)
        assert latest and latest["period"] == "251期", latest

        # 7) 多期取数：每个请求期都能取到，不再只剩 1 期。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "1头", "page", 0),
            cand("250期", "2头", "page", 1),
            cand("249期", "3头", "page", 2),
        ]
        got7 = selection.extract_period_candidates_by_period(
            [], rule, ["251期", "250期", "249期"], strict_conflict_periods=["251期"]
        )
        assert [len(got7.get(p, [])) for p in ("251期", "250期", "249期")] == [1, 1, 1], got7
        assert [got7[p][0]["value"] for p in ("251期", "250期", "249期")] == ["1头", "2头", "3头"], got7

        # 8) 非目标期冲突不得静默取值（必须留空，交给 missing）。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "1头", "page", 0),
            cand("250期", "2头", "page", 1),
            cand("250期", "3头", "inline_script", 2),
        ]
        got8 = selection.extract_period_candidates_by_period(
            [], rule, ["251期", "250期"], strict_conflict_periods=["251期"]
        )
        assert got8.get("251期"), got8
        assert not got8.get("250期"), got8

        # 9) 非法值（5头）参与冲突判定，不得被归一成空串后漏判。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "5头", "page", 0),
            cand("251期", "4头", "inline_script", 1),
        ]
        try:
            selection.extract_period_candidates_by_period([], rule, ["251期"])
        except ValueError:
            pass
        else:
            raise AssertionError("非法值与合法值的冲突未被拒绝")

        # 10) 多期模式下严格期仍必须落在整体方向边界上（禁止取首尾凑成功）。
        #     page 顺序 249/250/251，顶部站整体边界是 249 -> 251 越界，必须取不到。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("249期", "4头", "page", 0),
            cand("250期", "2头", "page", 1),
            cand("251期", "1头", "page", 2),
        ]
        single10 = selection.extract_period_candidates_by_period([], rule, ["251期"])
        assert not single10.get("251期"), single10
        multi10 = selection.extract_period_candidates_by_period(
            [], rule, ["251期", "250期", "249期"], strict_conflict_periods=["251期"]
        )
        assert not multi10.get("251期"), multi10

        # 11) 多期底部语义：底部站整体边界是最后一期，严格期必须命中它。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("249期", "4头", "page", 0),
            cand("250期", "2头", "page", 1),
            cand("251期", "1头", "page", 2),
        ]
        bottom11 = selection.extract_period_candidates_by_period(
            [], bottom_rule, ["251期", "250期", "249期"], strict_conflict_periods=["251期"]
        )
        assert [c["value"] for c in bottom11.get("251期", [])] == ["1头"], bottom11

        # 12) 其它文章（forum/forum_history）同期不同值不得误判成本站冲突。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "1头", "page", 0),
            cand("251期", "4头", "forum_history", 1),
        ]
        got12 = selection.extract_period_candidates_by_period([], rule, ["251期"])
        assert [c["value"] for c in got12.get("251期", [])] == ["1头"], got12

        # 13) 非目标期非法值冲突：不得静默取值。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "1头", "page", 0),
            cand("250期", "5头", "page", 1),
            cand("250期", "4头", "inline_script", 2),
        ]
        got13 = selection.extract_period_candidates_by_period(
            [], rule, ["251期", "250期"], strict_conflict_periods=["251期"]
        )
        assert got13.get("251期"), got13
        assert not got13.get("250期"), got13

        # 14) 冲突留空后 select_period_values 必须真的记成 missing（不能回填）。
        vals14, missing14, _ = selection.select_period_values(
            {"251期": [cand("251期", "1头", "page", 0)], "250期": []},
            {"251期": cand("251期", "1头", "page", 0)},
            ["251期", "250期"],
        )
        assert vals14.get("251期") == "1头", vals14
        assert "250期" in missing14, missing14

        # 15) 非法值必须出现在冲突报错原文里（排障可见）。
        desc15 = selection.describe_conflicting_candidates([
            cand("251期", "5头", "page", 0),
            cand("251期", "4头", "inline_script", 1),
        ])
        assert "5头" in desc15 and "4头" in desc15, desc15

        # 16) period_detail 是主来源：详情页与派生脚本同期不同值必须报冲突，
        #     详情页有目标期、脚本滞后时必须取详情页。
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "2头", "period_detail", 0),
            cand("251期", "4头", "script", 1),
        ]
        try:
            selection.extract_period_candidates_by_period([], rule, ["251期"])
        except ValueError:
            pass
        else:
            raise AssertionError("详情页与脚本同期冲突未被拒绝")
        selection._collect_ordered_candidates = lambda fragments, rule: [
            cand("251期", "2头", "period_detail", 0),
            cand("250期", "1头", "script", 1),
        ]
        got16 = selection.extract_period_candidates_by_period([], rule, ["251期"])
        assert [c["value"] for c in got16.get("251期", [])] == ["2头"], got16
    finally:
        selection._collect_ordered_candidates = original


def _check_success_txt_period_guard():
    """输出层期数硬校验：记录期数不等于目标期时不得写入成功 TXT。"""
    from lottery_head.output_text import format_success_txt, unique_success_records

    def rec(section, period, value, status="success"):
        return HeadRecord("https://e.com/a", "顶部", section, "绝杀一头", period, value, "", status, "")

    records = [
        rec("A", "251期", "2头"),
        rec("B", "250期", "1头"),          # 期数不符，必须排除
        rec("C", "251期", "4头"),
        rec("D", "251期", "0头", "failed"),  # 失败记录，必须排除
    ]
    kept = [r.section for r in unique_success_records(records, "251期")]
    assert kept == ["A", "C"], kept
    text = format_success_txt(records, "251期")
    assert "1头 B" not in text, text
    assert "0头 D" not in text, text
    # 期数写法等价：251 与 251期
    assert [r.section for r in unique_success_records(records, "251")] == ["A", "C"]
    # 不传目标期时保持旧行为（只做去重与状态过滤）
    assert [r.section for r in unique_success_records(records)] == ["A", "B", "C"]
    # 子串/带前缀期数不得被子串误取：2989期、第251期、251期-头 都要按全等语义处理。
    # 无法归一的目标期（如 4 位 1298期）返回空 -> 不启用期数过滤，保持旧行为。
    assert [r.section for r in unique_success_records(records, "1298期")] == ["A", "B", "C"]
    assert [r.section for r in unique_success_records(
        [rec("E", "251期-头", "3头")], "251期")] == []
    assert [r.section for r in unique_success_records(
        [rec("F", "第251期", "3头")], "251期")] == []
    assert [r.section for r in unique_success_records(
        [rec("G", "2989期", "3头")], "251期")] == []


def _check_build_artifacts_period_guard():
    """端到端：build_single_period_artifacts 生成的成功 TXT 必须只含目标期记录。"""
    from tempfile import TemporaryDirectory

    from lottery_head.models import HeadRecord as _HR
    from lottery_head.output_artifacts import build_single_period_artifacts

    def rec(section, period, value):
        return _HR("https://e.com/a", "顶部", section, "绝杀一头", period, value, "", "success", "")

    records = [rec("A", "251期", "2头"), rec("B", "250期", "1头"), rec("C", "251期", "4头")]
    with TemporaryDirectory() as folder:
        root = Path(folder)
        artifacts = build_single_period_artifacts(
            records, "251期", root / "cache.json", None, root
        )
    success = next(
        payload for path, payload in artifacts.items() if path.name.endswith("-头.txt")
    ).decode("utf-8")
    assert "2头 A" in success and "4头 C" in success, success
    assert "1头 B" not in success, success


def _check_main_scope_and_snapshot():
    import json
    import scripts.retry_failed_sites as entry
    import lottery_head.cache_validation as validation
    import lottery_head.cache as cache_module
    rule = SiteRule("https://example.com/a", "顶部", "A", "头", parse_hint="period")
    record = HeadRecord(rule.url, "顶部", "A", "头", "251期", "2头", "", "success", "", parse_hint="period")
    snapshot = {"periods": ["251期"], "latest_period": "251期", "sites": [{"identity": {"section": "A", "url": rule.url, "position": "top", "parse_hint": "period"}, "values": {}, "positions": {}, "provenance": {}, "missing": {}}]}
    original = {name: getattr(entry, name) for name in ("FAILURE_SUMMARY_DIR", "SUMMARY_DIR", "RECENT_10_CACHE_PATH", "load_rules", "match_failed_rules", "collect_rules", "build_cache_payload", "merge_success_txt", "merge_failed_txt", "commit_artifacts_transaction")}
    original_validation = validation.validate_cache_snapshot
    original_cache_validation = cache_module.validate_cache_snapshot
    with TemporaryDirectory() as folder:
        root = Path(folder)
        failure_dir, success_dir = root / "failed", root / "success"
        failure_dir.mkdir(); success_dir.mkdir()
        failure_path = failure_dir / "251期失败-一头.txt"
        failure_path.write_text("失败 A https://example.com/a 方向: 顶部 期数: 251期\n阶段: 页面抓取 原因: 失败", encoding="utf-8")
        cache_path = root / "cache.json"
        cache_path.write_text(json.dumps(snapshot), encoding="utf-8")
        calls = []; committed = []
        entry.FAILURE_SUMMARY_DIR, entry.SUMMARY_DIR, entry.RECENT_10_CACHE_PATH = failure_dir, success_dir, cache_path
        entry.load_rules = lambda: [rule]
        entry.match_failed_rules = lambda targets, rules: (calls.append(targets) or rules)
        collect_calls = [0]
        def fake_collect(rules, *args):
            collect_calls[0] += 1
            if collect_calls[0] == 2:
                cache_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            return [record], []
        entry.collect_rules = fake_collect
        entry.build_cache_payload = lambda *args, **kwargs: snapshot
        entry.merge_success_txt = lambda path, records, target_period="": b"success"
        entry.merge_failed_txt = lambda path, records, period: b"failed"
        entry.commit_artifacts_transaction = lambda artifacts, **kwargs: committed.append(artifacts)
        validation.validate_cache_snapshot = lambda value, rules: value
        cache_module.validate_cache_snapshot = lambda value, rules: value
        assert entry.main(["251期"]) == 0
        assert len(calls) == 1 and len(calls[0]) == 1 and len(committed) == 1
        committed.clear()
        assert entry.main(["251期"]) == 1 and not committed
    for name, value in original.items():
        setattr(entry, name, value)
    validation.validate_cache_snapshot = original_validation
    cache_module.validate_cache_snapshot = original_cache_validation


if __name__ == "__main__":
    main()

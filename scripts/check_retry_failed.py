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
    candidates = [{"period": "251期", "value": "2头", "document_key": "a", "document_order": 0, "original_position": 0}, {"period": "251期", "value": "2头", "document_key": "b", "document_order": 1, "original_position": 1}]
    assert len(_global_direction_window(candidates, "顶部")) == 2
    try:
        collect_ordered_candidates([SourceDocument("", "", "x", resource_error="script failed", resource_required=True)], rules[0])
    except ValueError:
        pass
    else:
        raise AssertionError("必需资源失败被跳过")
    print("PASS: 导入、定点身份、窗口、BOM/CRLF、精确表头、去重、回滚")


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
        entry.merge_success_txt = lambda path, records: b"success"
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

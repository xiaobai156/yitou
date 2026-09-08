from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lottery_head.models import HeadRecord, SiteRule
from lottery_head.output_transaction import commit_artifacts_transaction
from lottery_head.retry_failed import format_head_ranking, match_failed_rules, merge_failed_txt, merge_success_txt, read_failed_targets
from scripts.retry_failed_sites import validate_retry_window


def main():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        failed = root / "failed.txt"
        a = "失败 A https://example.com/a 方向: 顶部 期数: 251期\r\n阶段: 指定期数校验 原因: 251期不在顶部第一条"
        b = a.replace(" A ", " B ").replace("/a ", "/b ")
        failed.write_bytes(b"\xef\xbb\xbf" + (a + "\r\n\r\n" + b + "\r\n\r\n失败分类统计\r\n方向范围外 2条").encode())
        rules = [SiteRule("https://example.com/" + name.lower(), "顶部", name, "头", parse_hint="period") for name in ("A", "B", "C")]
        assert [r.section for r in match_failed_rules(read_failed_targets(failed, "251期"), rules)] == ["A", "B"]
        record = HeadRecord(rules[0].url, "顶部", "A", "头", "251期", "2头", "", "success", "", parse_hint="period")
        remaining = merge_failed_txt(failed, [record], "251期")
        assert remaining.startswith(b"\xef\xbb\xbf") and b"\r\n" in remaining and "失败 B".encode() in remaining
        success = root / "success.txt"
        success.write_bytes(b"\xef\xbb\xbf" + "1头 旧站\r\n\r\n内容\t次数\t排名\r\n".encode())
        result = merge_success_txt(success, [record, record]).decode("utf-8-sig")
        assert result.count("2头 A") == 1 and "内容\t次数\t排名" in result
        deceptive = root / "deceptive.txt"
        deceptive.write_text("正文 内容 次数 排名 但不是表头\n2头 旧\n\n内容\t次数\t排名\n2头\t1\t1\n", encoding="utf-8")
        assert "2头 旧" in merge_success_txt(deceptive, [record]).decode()
        try:
            validate_retry_window({"periods": ["251期"]}, "241期")
        except ValueError:
            pass
        else:
            raise AssertionError("窗口外期数未拒绝")
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
    print("PASS: 导入、定点身份、窗口、BOM/CRLF、精确表头、去重、回滚")


if __name__ == "__main__":
    main()

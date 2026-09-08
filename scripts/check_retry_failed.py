"""Offline regression: only failed targets; preserve unrelated output."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lottery_head.models import HeadRecord, SiteRule
from lottery_head.retry_failed import read_failed_targets, match_failed_rules, merge_success_txt, merge_failed_txt


def main():
    with TemporaryDirectory() as folder:
        path = Path(folder) / "failed.txt"
        a = "失败 A https://example.com/a 方向: 顶部 期数: 251期\n阶段: 指定期数校验 原因: 251期不在顶部第一条"
        b = a.replace(" A ", " B ").replace("/a ", "/b ")
        path.write_text(a + "\n\n" + b + "\n\n失败分类统计\n方向范围外 2条", encoding="utf-8")
        rules = [SiteRule("https://example.com/" + name.lower(), "顶部", name, "头") for name in ("A", "B", "C")]
        assert [r.section for r in match_failed_rules(read_failed_targets(path, "251期"), rules)] == ["A", "B"]
        record = HeadRecord(rules[0].url, "顶部", "A", "头", "251期", "2头", "", "success", "")
        result = merge_failed_txt(path, [record], "251期").decode()
        assert a not in result and b in result and "方向范围外 1条" in result
        success = Path(folder) / "success.txt"
        success.write_text("1头 原站\n\n内容\t次数\t排名\n1头\t1\t1\n", encoding="utf-8")
        result = merge_success_txt(success, [record]).decode()
        assert result.startswith("1头 原站\n2头 A\n\n内容")
        success.write_text(result, encoding="utf-8")
        assert merge_success_txt(success, [record]).decode() == result
    print("PASS: 定点筛选、失败保留、成功追加、排行与幂等")


if __name__ == "__main__":
    main()

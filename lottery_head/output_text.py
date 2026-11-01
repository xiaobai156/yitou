from __future__ import annotations

import re
from collections import Counter

from .models import HeadRecord
from .parsers.common import display_head_value
from .settings import SUCCESS_TAIL_LINES
from .validation import parse_target_period


def format_success_txt(
    records: list[HeadRecord], target_period: str = ""
) -> str:
    success_records = unique_success_records(records, target_period)
    values = [
        value
        for record in success_records
        if (value := display_head_value(record.value))
    ]
    lines = [
        f"{display_head_value(record.value)} {record.section}"
        for record in success_records
        if display_head_value(record.value)
    ]
    lines.extend(SUCCESS_TAIL_LINES)
    lines.append("")
    lines.extend(format_head_ranking(values))
    return "\n".join(lines)


def format_head_ranking(values: list[str]) -> list[str]:
    counts = Counter(head for value in values for head in re.findall(r"[0-4]头", value))
    lines = ["内容\t次数\t排名"]
    for rank, (value, count) in enumerate(
        sorted(counts.items(), key=lambda item: (-item[1], item[0])), start=1
    ):
        lines.append(f"{value}\t{count}\t{rank}")
    return lines


def format_failed_txt(records: list[HeadRecord], target_period: str = "") -> str:
    failed_records = [record for record in records if record.status != "success"]
    if not failed_records:
        return ""
    categories = Counter()
    blocks = []
    for record in failed_records:
        error = _single_line(record.error)
        category = failure_category(error)
        categories[category] += 1
        period = target_period.strip() or record.period.strip() or "-"
        blocks.append(
            "\n".join(
                (
                    f"失败 {record.section} {record.url} 方向: {record.position} 期数: {period}",
                    f"阶段: {failure_stage(error)} 原因: {_failure_reason_text(error)}",
                )
            )
        )
    summary = "\n".join(
        ["失败分类统计", *[f"{category} {count}条" for category, count in categories.items()]]
    )
    return "\n\n".join([*blocks, summary])


def format_debug_txt(records: list[HeadRecord]) -> str:
    return "\n".join(
        f"{record.section} | {record.field} | {record.period or '-'} | {record.value or '-'} | "
        f"原始位置 {record.original_position} | 来源 {record.source_route or '-'} | {record.error or '成功'}"
        for record in records
    )


def result_file_period_label(target_period: str) -> str:
    digits = re.search(r"\d{1,3}", target_period)
    return f"{digits.group(0)}期" if digits else target_period


def unique_success_records(
    records: list[HeadRecord], target_period: str = ""
) -> list[HeadRecord]:
    """去重并做期数硬校验：记录期数必须等于目标期，否则不写入成功 TXT。

    缓存侧对同样的不一致会抛错，输出侧若不校验就会出现「TXT 写了、缓存拒绝」
    的两边结论不一致。
    """
    wanted = _period_number(target_period)
    seen: set[str] = set()
    unique_records = []
    for record in records:
        if record.status != "success" or record.section in seen:
            continue
        if wanted and _period_number(record.period) != wanted:
            continue
        seen.add(record.section)
        unique_records.append(record)
    return unique_records


def _period_number(value: str) -> str:
    """归一化期数：优先走项目统一的 parse_target_period（全等匹配）。

    不要用 re.search(r"\\d{1,3}") 这种子串提取——"1298期" 会取成 129、
    "2989期" 会取成 298，与 selection 侧的 period_matches 结论相反。
    """
    try:
        return parse_target_period(str(value or ""))
    except ValueError:
        return ""


def format_failure_reason(error: str) -> str:
    error = error.strip()
    if not error:
        return "失败原因：未知失败，未返回具体错误"
    if error.startswith("失败原因："):
        return error
    return f"失败原因：{error}"


def failure_stage(error: str) -> str:
    if _is_direction_error(error):
        return "指定期数校验"
    if _is_conflict_error(error):
        return "同期冲突校验"
    if _is_access_error(error):
        return "页面抓取"
    if "缓存" in error:
        return "缓存更新"
    return "字段解析"


def failure_category(error: str) -> str:
    if _is_direction_error(error):
        return "方向范围外"
    if _is_conflict_error(error):
        return "同期冲突"
    if _is_access_error(error):
        return "页面抓取失败"
    if "缓存" in error:
        return "缓存更新失败"
    if any(marker in error for marker in ("锚点", "栏目", "作者", "站名")):
        return "身份或锚点失败"
    if any(marker in error for marker in ("数量", "四头", "头值", "合法")):
        return "数据格式失败"
    return "字段解析失败"


def _is_direction_error(error: str) -> bool:
    return any(
        marker in error
        for marker in (
            "不在顶部",
            "不在尾部",
            "不在底部",
            "不是第一条",
            "不是最后一条",
            "方向候选",
            "方向范围",
        )
    )


def _is_conflict_error(error: str) -> bool:
    return any(marker in error for marker in ("冲突", "边界不唯一", "同期"))


def _is_access_error(error: str) -> bool:
    return any(
        marker in error
        for marker in (
            "网络",
            "TLS",
            "HTTP",
            "页面资源",
            "浏览器",
            "接口请求",
            "专属接口",
            "接口未返回",
            "记录ID",
            "跨域",
            "权限",
            "链接无效",
        )
    )


def _failure_reason_text(error: str) -> str:
    reason = error.strip() or "未知失败，未返回具体错误"
    if reason.startswith("失败原因："):
        return reason[len("失败原因：") :].strip()
    return reason


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

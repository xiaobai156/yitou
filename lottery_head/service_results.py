from __future__ import annotations

import re

from .models import BaselineSitePeriodData, Candidate, HeadRecord, SiteRule
from .parsers.common import html_to_text, period_matches
from .selection import position_three_label
from .validation import validate_head_value


def make_site_period_data(
    rule: SiteRule,
    period_values: dict[str, str],
    missing: list[str],
    error: str = "",
    extracted_records: dict[str, dict[str, str]] | None = None,
    missing_reasons: dict[str, str] | None = None,
):
    period_records: dict[str, Candidate] = {}
    for period, extracted in (extracted_records or {}).items():
        if period not in period_values:
            continue
        period_records[period] = Candidate(
            period=period,
            value=period_values[period],
            raw_line=extracted.get("raw_line", ""),
            original_position=int(extracted.get("original_position", -1)),
            document_key=extracted.get("document_key", ""),
            source_record_id=extracted.get("source_record_id", ""),
            source_record_path=extracted.get("source_record_path", ""),
            source_route=extracted.get("source_route", "") or "page",
            source_url=extracted.get("source_url", "") or rule.url,
            source_api_url=extracted.get("source_api_url", ""),
            source_title=extracted.get("source_title", ""),
            source_author=extracted.get("source_author", ""),
            document_order=int(extracted.get("document_order", -1)),
            block_order=int(extracted.get("block_order", -1)),
            record_order=int(extracted.get("record_order", -1)),
            source_block_id=extracted.get("source_block_id", ""),
            source_identity=extracted.get("source_identity", ""),
            source_user_id=extracted.get("source_user_id", ""),
            source_forum_id=extracted.get("source_forum_id", ""),
            source_list_position=int(extracted.get("source_list_position", -1)),
        )
    return BaselineSitePeriodData(
        section=rule.section,
        field=rule.field,
        position=rule.position,
        url=rule.url,
        parse_hint=rule.parse_hint,
        period_values=period_values,
        missing=missing,
        error=error,
        period_records=period_records,
        missing_reasons=dict(missing_reasons or {}),
    )


def failed_head_record(rule: SiteRule, error: str) -> HeadRecord:
    return HeadRecord(
        rule.url,
        rule.position,
        rule.section,
        rule.field,
        "",
        "",
        "",
        "failed",
        error,
        parse_hint=rule.parse_hint,
    )


def unresolved_rule_error(rule: SiteRule, fragments: list[str], target_period: str = "") -> str:
    resource_errors = [
        str(getattr(fragment, "resource_error", ""))
        for fragment in fragments
        if str(getattr(fragment, "resource_error", "")).strip()
    ]
    if resource_errors:
        return f"页面资源不完整：{'；'.join(dict.fromkeys(resource_errors))}"
    locked_error = locked_target_period_error(fragments, target_period)
    if locked_error:
        return locked_error
    combined_text = "\n".join(html_to_text(fragment_source(fragment)) for fragment in fragments)
    if contains_access_denied_message(combined_text):
        return "页面提示无权限或链接无效，无法读取目标原始内容"
    if "/#/users/" in rule.url:
        if target_period and rule.parse_hint == "user_kill_head":
            return f"{target_period}不在{position_three_label(rule.position)}"
        return "用户聚合页没有唯一文章ID，拒绝使用聚合记录"
    if re.search(r"/article/(?:admin|manager|lottery)/", rule.url):
        return "admin文章接口未返回目标文章，无法读取目标原始内容"
    return f"已定位栏目，但未解析出{target_period or '一头'}值"


def fragment_source(fragment) -> str:
    return str(getattr(fragment, "source", fragment) or "")


def locked_target_period_error(fragments, target_period: str) -> str:
    if not target_period:
        return ""
    locked_markers = ("购买后可查看", "付费后可查看", "登录后可查看")
    for fragment in fragments:
        text = re.sub(r"\s+", "", html_to_text(fragment_source(fragment)))
        for block in re.finditer(r"(\d{2,3}期)(.*?)(?=\d{2,3}期|$)", text):
            if not period_matches(block.group(1), target_period):
                continue
            if any(marker in block.group(2) for marker in locked_markers):
                return f"{target_period}目标数据被购买权限锁定，无法读取原始值"
    return ""


def contains_access_denied_message(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "没有权限访问此页面",
            "读取数据错误",
            "链接无效",
            "数据已被删除",
            "还不是论坛会员",
        )
    )


def head_record_from_extracted(rule: SiteRule, extracted: dict[str, str]) -> HeadRecord:
    return HeadRecord(
        url=rule.url,
        position=rule.position,
        section=rule.section,
        field=rule.field,
        period=extracted["period"],
        value=validate_head_value(extracted["value"]),
        raw_line=extracted["raw_line"],
        status="success",
        error="",
        original_position=int(extracted.get("original_position", -1)),
        source_record_id=extracted.get("source_record_id", ""),
        source_record_path=extracted.get("source_record_path", ""),
        source_route=extracted.get("source_route", "") or "page",
        source_url=extracted.get("source_url", "") or rule.url,
        source_api_url=extracted.get("source_api_url", ""),
        source_title=extracted.get("source_title", ""),
        source_author=extracted.get("source_author", ""),
        parse_hint=rule.parse_hint,
        document_order=int(extracted.get("document_order", -1)),
        block_order=int(extracted.get("block_order", -1)),
        record_order=int(extracted.get("record_order", -1)),
        source_block_id=extracted.get("source_block_id", ""),
        source_identity=extracted.get("source_identity", ""),
        source_user_id=extracted.get("source_user_id", ""),
        source_forum_id=extracted.get("source_forum_id", ""),
        source_list_position=int(extracted.get("source_list_position", -1)),
    )

from __future__ import annotations

from .four_head import parse_anchored_four_combo_missing_head_records, parse_four_combo_after_marker_records, parse_four_combo_missing_head_records, parse_manager_anchored_four_combo_missing_head_records, parse_topic_title_anchored_four_combo_missing_head_records, should_parse_missing_head_from_four_combo
from .period import SITE_SPECIFIC_CURRENT_WINDOW_PROFILES, parse_period_bracket_head_records, parse_site_specific_current_window_records
from .phrases import parse_bisha_yitou_bracket_records, parse_bisha_yitou_plain_records, parse_bracket_field_head_records, parse_bracket_sha_yi_tou_records, parse_dash_head_phrase_records, parse_head_tail_phrase_records, parse_kill_head_phrase_records, parse_miaosha_bracket_head_records, parse_must_win_head_records, parse_number_code_to_head_records, parse_sword_head_records, parse_user_kill_head_records
from .site_specific import (
    parse_ai_kill_head_records,
    parse_huakai_kill_head_records,
    parse_jingshendousou_kill_head_records,
    parse_weilairiji_kill_head_records,
    parse_xiaomiao_kill_head_records,
    parse_zhimubifa_kill_head_records,
)
from .tables import parse_caifu_gaoshou_kill_head_table_records, parse_fragment_table_records, parse_vertical_table_column_records


FIELD_MARKER_HINTS = {
    "missing_head_from_four_combo",
    "period_bracket_head",
    "table_column",
    "strict_position_three",
    "strict_position_three_miaosha",
    "strict_position_three_missing_head_from_four_combo",
    "full_period_list",
    "missing_head_from_four_combo_full_period_list",
    "top_primary_ten_periods",
    "bracket_field_head",
    "dash_head_phrase",
    "head_tail_phrase",
    "jingshendousou_kill_head_line",
    "sword_head",
    "four_combo_after_marker",
    "number_code_to_head",
    "must_win_head",
    "user_kill_head",
    "xiaomiao_kill_head_brackets",
    "kill_head_phrase",
    "admin_anchored_missing_head_from_four_combo",
    "anchored_missing_head_from_four_combo",
    "manager_anchored_missing_head_from_four_combo",
    "topic_title_anchored_missing_head_from_four_combo",
    "period_title_detail",
    "period_title_detail_first_three_pages",
    "AI斩头",
    "绝杀①头",
}


KNOWN_PARSE_HINTS = {
    "AI斩头",
    "绝杀①头",
    "admin_anchored_missing_head_from_four_combo",
    "anchored_missing_head_from_four_combo",
    "bisha_yitou_bracket",
    "bisha_yitou_plain",
    "bracket_field_head",
    "bracket_sha_yi_tou",
    "caifu_gaoshou_bottom_kill_head_table",
    "dash_head_phrase",
    "four_combo_after_marker",
    "full_period_list",
    "head_tail_phrase",
    "jingshendousou_kill_head_line",
    "kill_head_phrase",
    "manager_anchored_missing_head_from_four_combo",
    "missing_head_from_four_combo",
    "missing_head_from_four_combo_full_period_list",
    "must_win_head",
    "number_code_to_head",
    "period_bracket_head",
    "period_title_detail",
    "period_title_detail_first_three_pages",
    "strict_position_three",
    "strict_position_three_miaosha",
    "strict_position_three_missing_head_from_four_combo",
    "sword_head",
    "table_column",
    "top_primary_ten_periods",
    "topic_title_anchored_missing_head_from_four_combo",
    "user_kill_head",
    "xiaomiao_kill_head_brackets",
    *SITE_SPECIFIC_CURRENT_WINDOW_PROFILES,
}


DEDICATED_PARSE_HINTS = frozenset(
    {
        "AI斩头",
        "绝杀①头",
        "admin_anchored_missing_head_from_four_combo",
        "anchored_missing_head_from_four_combo",
        "bisha_yitou_bracket",
        "bisha_yitou_plain",
        "bracket_field_head",
        "bracket_sha_yi_tou",
        "caifu_gaoshou_bottom_kill_head_table",
        "dash_head_phrase",
        "four_combo_after_marker",
        "full_period_list",
        "head_tail_phrase",
        "jingshendousou_kill_head_line",
        "kill_head_phrase",
        "manager_anchored_missing_head_from_four_combo",
        "missing_head_from_four_combo",
        "missing_head_from_four_combo_full_period_list",
        "must_win_head",
        "number_code_to_head",
        "period_bracket_head",
        "period_title_detail",
        "period_title_detail_first_three_pages",
        "strict_position_three",
        "strict_position_three_miaosha",
        "strict_position_three_missing_head_from_four_combo",
        "sword_head",
        "table_column",
        "top_primary_ten_periods",
        "topic_title_anchored_missing_head_from_four_combo",
        "user_kill_head",
        "xiaomiao_kill_head_brackets",
        *SITE_SPECIFIC_CURRENT_WINDOW_PROFILES,
    }
)


def has_dedicated_parser(hint: str) -> bool:
    return hint in DEDICATED_PARSE_HINTS


def resolve_marker(field: str, hint: str) -> str:
    return field if hint in FIELD_MARKER_HINTS else hint or field


def dispatch_specialized_head_records(
    *,
    fragment_html: str,
    text: str,
    compact: str,
    field: str,
    hint: str,
    target_period: str,
    anchor_marker: str,
    marker: str,
) -> tuple[bool, list[dict[str, str]]]:
    if hint == "AI斩头":
        return True, parse_ai_kill_head_records(compact, target_period)
    if hint == "绝杀①头":
        return True, parse_huakai_kill_head_records(compact, target_period)
    if hint == "full_period_list" and anchor_marker == "直木必伐":
        return True, parse_zhimubifa_kill_head_records(compact, anchor_marker, target_period)
    if hint == "full_period_list" and anchor_marker == "未来日记":
        return True, parse_weilairiji_kill_head_records(compact, anchor_marker, target_period)
    if hint in {
        "AI斩头",
        "绝杀①头",
        "full_period_list",
        "period_title_detail",
        "period_title_detail_first_three_pages",
        "strict_position_three",
    }:
        records = parse_period_bracket_head_records(compact, marker, target_period)
        if hint == "top_primary_ten_periods":
            records = records[:10]
        return True, records
    if hint == "top_primary_ten_periods":
        return True, parse_period_bracket_head_records(compact, marker, target_period)[:10]
    if hint == "caifu_gaoshou_bottom_kill_head_table":
        return True, parse_caifu_gaoshou_kill_head_table_records(fragment_html, target_period)
    if hint in SITE_SPECIFIC_CURRENT_WINDOW_PROFILES:
        return True, parse_site_specific_current_window_records(compact, hint, target_period)
    if hint == "anchored_missing_head_from_four_combo":
        return True, parse_anchored_four_combo_missing_head_records(compact, anchor_marker or field, field, target_period)
    if hint == "admin_anchored_missing_head_from_four_combo":
        return True, parse_manager_anchored_four_combo_missing_head_records(compact, anchor_marker or field, field, target_period)
    if hint == "manager_anchored_missing_head_from_four_combo":
        return True, parse_manager_anchored_four_combo_missing_head_records(compact, anchor_marker or field, field, target_period)
    if hint == "topic_title_anchored_missing_head_from_four_combo":
        return True, parse_topic_title_anchored_four_combo_missing_head_records(compact, anchor_marker or field, field, target_period)
    if hint == "strict_position_three_miaosha":
        return True, parse_miaosha_bracket_head_records(compact, target_period)
    if hint == "bracket_sha_yi_tou":
        return True, parse_bracket_sha_yi_tou_records(compact, target_period)
    if hint == "bisha_yitou_plain":
        return True, parse_bisha_yitou_plain_records(compact, target_period)
    if hint == "bisha_yitou_bracket":
        return True, parse_bisha_yitou_bracket_records(compact, target_period)
    if hint == "bracket_field_head":
        return True, parse_bracket_field_head_records(compact, field, target_period)
    if hint == "head_tail_phrase":
        return True, parse_head_tail_phrase_records(compact, field, target_period)
    if hint == "jingshendousou_kill_head_line":
        return True, parse_jingshendousou_kill_head_records(compact, anchor_marker, target_period)
    if hint == "sword_head":
        return True, parse_sword_head_records(compact, field, target_period)
    if hint == "four_combo_after_marker":
        return True, parse_four_combo_after_marker_records(compact, field, target_period)
    if hint == "number_code_to_head":
        return True, parse_number_code_to_head_records(compact, field, target_period)
    if hint == "must_win_head":
        return True, parse_must_win_head_records(compact, target_period)
    if hint == "user_kill_head":
        return True, parse_user_kill_head_records(compact, target_period, field, anchor_marker)
    if hint == "xiaomiao_kill_head_brackets":
        return True, parse_xiaomiao_kill_head_records(compact, field, anchor_marker, target_period)
    if hint == "dash_head_phrase":
        return True, parse_dash_head_phrase_records(compact, field, target_period)
    if hint == "kill_head_phrase":
        return True, parse_kill_head_phrase_records(compact, target_period)
    if should_parse_missing_head_from_four_combo(field, hint):
        return True, parse_four_combo_missing_head_records(compact, field, target_period)
    if hint == "period_bracket_head":
        return True, parse_period_bracket_head_records(compact, marker, target_period)
    if hint == "table_column":
        table_records = parse_fragment_table_records(fragment_html, field, target_period)
        if table_records:
            return True, table_records
        return True, parse_vertical_table_column_records(text, field, target_period)
    return False, []

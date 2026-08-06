from __future__ import annotations

import re

from .common import html_to_text, unique_extracted_records
from .dispatch import KNOWN_PARSE_HINTS, dispatch_specialized_head_records, resolve_marker
from .four_head import extract_four_combo_values, parse_anchored_four_combo_missing_head_records, parse_four_combo_after_marker_records, parse_four_combo_missing_head_records, parse_manager_anchored_four_combo_missing_head_records, parse_topic_title_anchored_four_combo_missing_head_records, should_parse_missing_head_from_four_combo
from .generic import parse_generic_head_records
from .period import SITE_SPECIFIC_CURRENT_WINDOW_PROFILES, find_non_marker_head_value, limit_to_top_primary_ten_records, parse_period_block_records, parse_period_blocks, parse_period_bracket_head_records, parse_site_specific_current_window_records
from .phrases import parse_bisha_yitou_bracket_records, parse_bisha_yitou_plain_records, parse_bracket_field_head_records, parse_bracket_sha_yi_tou_records, parse_dash_head_phrase_records, parse_head_tail_phrase_records, parse_kill_head_phrase_records, parse_miaosha_bracket_head_records, parse_must_win_head_records, parse_number_code_to_head_records, parse_sword_head_records, parse_user_kill_head_records
from .site_specific import parse_jingshendousou_kill_head_records, parse_xiaomiao_kill_head_records
from .tables import extract_head_value_from_cell, parse_caifu_gaoshou_kill_head_table_records, parse_fragment_table_records, parse_fragment_tables, parse_vertical_table_column_records


def extract_head_records(
    fragment_html: str,
    field: str,
    hint: str = "",
    target_period: str = "",
    anchor_marker: str = "",
) -> list[dict[str, str]]:
    marker = resolve_marker(field, hint)
    text = html_to_text(fragment_html)
    compact = re.sub(r"\s+", "", text)
    handled, records = dispatch_specialized_head_records(
        fragment_html=fragment_html,
        text=text,
        compact=compact,
        field=field,
        hint=hint,
        target_period=target_period,
        anchor_marker=anchor_marker,
        marker=marker,
    )
    if handled:
        return records

    return parse_generic_head_records(
        fragment_html,
        text,
        compact,
        field,
        marker,
        hint,
        target_period,
        period_block_parser=parse_period_block_records,
        table_parser=parse_fragment_table_records,
    )



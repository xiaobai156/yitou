# -*- coding: utf-8 -*-
"""从近10期缓存重建指定期的成功 TXT（不联网、不抓取）。身份按规范化 identity 匹配。"""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lottery_head.cache_payload import _identity_payload
from lottery_head.cache_validation import read_validated_cache
from lottery_head.config import load_rules
from lottery_head.models import HeadRecord
from lottery_head.output_text import format_success_txt
from lottery_head.settings import RECENT_10_CACHE_PATH, SUMMARY_DIR

PERIOD = sys.argv[1] if len(sys.argv) > 1 else "303期"
rules = load_rules()
snap = read_validated_cache(RECENT_10_CACHE_PATH, rules)
assert PERIOD in snap["periods"], f"{PERIOD} 不在缓存窗口 {snap['periods']}"


def key_of(identity: dict) -> tuple:
    return (
        identity["section"].strip(),
        identity["url"].strip(),
        identity["position"].strip(),
        identity["parse_hint"].strip(),
    )


by_key = {key_of(e["identity"]): e for e in snap["sites"]}
records: list[HeadRecord] = []
unmatched: list[str] = []
no_value: list[str] = []
for rule in rules:
    e = by_key.get(key_of(_identity_payload(rule)))
    if e is None:
        unmatched.append(rule.section)
        continue
    value = e["values"].get(PERIOD)
    if not value:
        no_value.append(rule.section)
        continue
    prov = e["provenance"].get(PERIOD, {})
    records.append(
        HeadRecord(
            url=rule.url,
            position=rule.position,
            section=rule.section,
            field=rule.field,
            period=PERIOD,
            value=value,
            raw_line=prov.get("raw_line", ""),
            status="success",
            error="",
            original_position=e["positions"].get(PERIOD, 0),
            source_route=prov.get("route", ""),
            source_url=prov.get("source_url", ""),
            parse_hint=rule.parse_hint,
        )
    )

text = format_success_txt(records, PERIOD)
out = Path(SUMMARY_DIR) / f"{PERIOD}-头.txt"
out.write_text(text, encoding="utf-8")

lines = text.splitlines()
mi = next(i for i, l in enumerate(lines) if l.startswith("内容\t次数\t排名"))
st = [l for l in lines[:mi] if l.strip()]
vals = [l.split(" ")[0] for l in st]
rank = {r.split("\t")[0]: int(r.split("\t")[1]) for r in lines[mi + 1:] if r.strip()}
print(f"缓存 {len(snap['sites'])} 站 | {PERIOD} 取值 {len(records)} 站")
print(f"未匹配 {len(unmatched)}: {unmatched}")
print(f"该期无值 {len(no_value)}: {no_value}")
print(f"写出: {out}")
print(f"  {out.stat().st_size}B | 站点行 {len(st)}")
print("排行:", rank, "| 合计", sum(rank.values()), "| 逐项一致", dict(Counter(vals)) == rank)
print("首3行:", st[:3])
print("末3行:", st[-3:])

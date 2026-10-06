from __future__ import annotations

import re
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
MAX_WORKERS = 16
SUMMARY_DIR = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳")
FAILURE_SUMMARY_DIR = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳失败")
# 自定义尾注已按用户要求移除（原为 ("老二", "四头开张", "极品大王")），成功 TXT 不再追加这三行。
SUCCESS_TAIL_LINES: tuple[str, ...] = ()
SCRIPT_SRC_RE = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
EMBEDDED_SCRIPT_SRC_RE = re.compile(r"<script[^>]+src=\\?[\"']([^\"']+)[\"']", re.IGNORECASE)
IFRAME_SRC_RE = re.compile(r"<iframe[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
DOCUMENT_WRITE_RE = re.compile(r'document\.write(?:ln)?\(("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')\);?', re.IGNORECASE | re.DOTALL)
PAGE_DATA_RE = re.compile(r"window\.__PAGE_DATA__\s*=\s*\'([^\']+)\'")
STRDECODE_RE = re.compile(r'strdecode\("([A-Za-z0-9+/=]+)"\)')
PERIOD_RE = re.compile(r"(?<!\d)(\d{2,3}期)")
HEAD_VALUE_RE = re.compile(r"([0-9０-９零一二三四五六七八九十两]+)\s*[头頭]")
BARE_HEAD_VALUE_RE = re.compile(r"[【\[\(（《〈]\s*([0-4０-４零一二三四]{1,4})\s*[头頭]?\s*[】\]\)）》〉]")
FOUR_COMBO_RE = re.compile(r"[【\[〖［]([0-4](?:\.[0-4]){3})(?:[头頭])?(?:[】\]〗］]|(?=开|开奖|開|開獎))")
FOUR_HEAD_FIELD_RE = re.compile(r"(?:④|4|四)[头頭]中特")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = PROJECT_ROOT / ".tmp"
SITES_PATH = PROJECT_ROOT / "sites.json"
RECENT_10_CACHE_PATH = TMP_DIR / "recent_10_cache.json"

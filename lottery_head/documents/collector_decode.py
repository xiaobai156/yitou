from __future__ import annotations

import ast
import base64
import html as html_lib
import re

from ..settings import DOCUMENT_WRITE_RE, PAGE_DATA_RE, STRDECODE_RE


def should_collect_script_fragment(src: str, absolute_src: str) -> bool:
    marker = f"{src} {absolute_src}".lower()
    return any(
        token in marker
        for token in (
            "upload/script",
            "contenttype=js",
            "view_content.php",
            "bbs/xqfn.js",
            "/4tzt.aspx",
        )
    )


def _article_id_from_url(source_url: str) -> str:
    match = re.search(r"/article/(?:admin|manager|lottery)/([^/?#]+)", source_url)
    return match.group(1) if match else ""


def _forum_id_from_url(source_url: str) -> str:
    match = re.search(r"/forums/(\d+)", source_url)
    return match.group(1) if match else ""


def decode_inline_gbk_decrypt_calls(html: str) -> str:
    return "\n".join(decode_inline_gbk_decrypt_blocks(html))


def decode_inline_gbk_decrypt_blocks(html: str) -> list[str]:
    parts = []
    for encoded in re.findall(r"decrypt\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", html):
        try:
            decoded = base64.b64decode(encoded).decode("gb18030", "ignore")
        except Exception:
            continue
        if decoded.strip():
            parts.append(decoded)
    return parts


def decode_script_document_writes(script_text: str) -> str:
    return "\n".join(decode_script_document_write_blocks(script_text)) or script_text


def decode_script_document_write_blocks(script_text: str) -> list[str]:
    parts = []
    for encoded in STRDECODE_RE.findall(script_text):
        try:
            decoded = base64.b64decode(encoded).decode("utf-8", "ignore")
        except Exception:
            continue
        if decoded.strip():
            parts.append(decoded)
    for encoded in PAGE_DATA_RE.findall(script_text):
        try:
            parts.append(base64.b64decode(encoded).decode("utf-8", "ignore"))
        except Exception:
            continue
    for quoted in DOCUMENT_WRITE_RE.findall(script_text):
        try:
            value = html_lib.unescape(ast.literal_eval(quoted))
        except Exception:
            continue
        if value.strip():
            parts.append(value)
    return parts

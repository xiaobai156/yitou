from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from ..models import SourceDocument
from ..network import get_text
from ..settings import EMBEDDED_SCRIPT_SRC_RE, IFRAME_SRC_RE, SCRIPT_SRC_RE
from .collector_decode import (
    decode_script_document_write_blocks,
    should_collect_script_fragment,
)


def collect_linked_documents(
    html: str,
    *,
    client,
    source_url: str,
    include_scripts: bool,
    get_text_fn=get_text,
    script_filter_fn=should_collect_script_fragment,
    decode_script_blocks_fn=decode_script_document_write_blocks,
) -> list[SourceDocument]:
    fragments: list[SourceDocument] = []
    script_sources = []
    seen_script_urls = set()
    for pattern in (SCRIPT_SRC_RE, EMBEDDED_SCRIPT_SRC_RE) if include_scripts else ():
        for src in pattern.findall(html):
            absolute_src = urljoin(source_url, src) if source_url else src
            if absolute_src in seen_script_urls:
                continue
            seen_script_urls.add(absolute_src)
            script_sources.append((src, absolute_src))
    for src, absolute_src in script_sources:
        if not script_filter_fn(src, absolute_src):
            continue
        try:
            script_text = get_text_fn(client, absolute_src)
        except Exception as exc:
            fragments.append(
                SourceDocument(
                    "",
                    absolute_src,
                    "resource_error",
                    parent_url=source_url,
                    linked_urls=(absolute_src,),
                    source_block_id=f"script:{absolute_src}",
                    resource_error=f"脚本资源请求失败：{exc}",
                    # 页面主文档可能已经包含完整业务数据；缺失的附属脚本
                    # 只能作为诊断，不能在解析前直接否决整页。
                    resource_required=False,
                )
            )
            continue
        if not script_text.strip():
            fragments.append(
                SourceDocument(
                    "",
                    absolute_src,
                    "resource_error",
                    parent_url=source_url,
                    linked_urls=(absolute_src,),
                    source_block_id=f"script:{absolute_src}",
                    resource_error="脚本资源为空",
                    resource_required=False,
                )
            )
            continue
        decoded_blocks = decode_script_blocks_fn(script_text)
        decoded_blocks = [block for block in decoded_blocks if block.strip()]
        if not decoded_blocks:
            continue
        fragments.append(
            SourceDocument(
                "\n".join(decoded_blocks),
                absolute_src,
                "script",
                parent_url=source_url,
                linked_urls=(absolute_src,),
                source_block_id=f"script:{absolute_src}",
            )
        )
    iframe_sources: list[str] = []
    seen_iframe_urls = set()
    for src in IFRAME_SRC_RE.findall(html):
        absolute_src = urljoin(source_url, src) if source_url else src
        if source_url and not _same_origin(source_url, absolute_src):
            continue
        if absolute_src in seen_iframe_urls:
            continue
        seen_iframe_urls.add(absolute_src)
        iframe_sources.append(absolute_src)
    for absolute_src in iframe_sources[:12]:
        try:
            iframe_text = get_text_fn(client, absolute_src)
        except Exception as exc:
            fragments.append(
                SourceDocument(
                    "",
                    absolute_src,
                    "resource_error",
                    parent_url=source_url,
                    linked_urls=(absolute_src,),
                    source_block_id=f"iframe:{absolute_src}",
                    resource_error=f"iframe资源请求失败：{exc}",
                    resource_required=True,
                )
            )
            continue
        if not iframe_text.strip():
            fragments.append(
                SourceDocument(
                    "",
                    absolute_src,
                    "resource_error",
                    parent_url=source_url,
                    linked_urls=(absolute_src,),
                    source_block_id=f"iframe:{absolute_src}",
                    resource_error="iframe资源为空",
                    resource_required=True,
                )
            )
            continue
        fragments.append(
            SourceDocument(
                iframe_text,
                absolute_src,
                "iframe",
                parent_url=source_url,
                linked_urls=(absolute_src,),
                source_block_id=f"iframe:{absolute_src}",
            )
        )
    return fragments


def _same_origin(left_url: str, right_url: str) -> bool:
    left = urlsplit(left_url)
    right = urlsplit(right_url)
    if not left.scheme or not left.hostname or not right.scheme or not right.hostname:
        return False
    left_port = left.port or (443 if left.scheme.lower() == "https" else 80)
    right_port = right.port or (443 if right.scheme.lower() == "https" else 80)
    return (left.scheme.lower(), left.hostname.lower(), left_port) == (
        right.scheme.lower(),
        right.hostname.lower(),
        right_port,
    )

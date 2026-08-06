from __future__ import annotations

from urllib.parse import urljoin

from ..models import SourceDocument
from ..network import get_text
from ..settings import EMBEDDED_SCRIPT_SRC_RE, IFRAME_SRC_RE, SCRIPT_SRC_RE
from .collector_decode import decode_script_document_write_blocks, decode_script_document_writes, should_collect_script_fragment


def collect_linked_documents(
    html: str,
    *,
    client,
    source_url: str,
    include_scripts: bool,
    get_text_fn=get_text,
    script_filter_fn=should_collect_script_fragment,
    decode_script_fn=decode_script_document_writes,
    decode_script_blocks_fn=decode_script_document_write_blocks,
) -> list[SourceDocument]:
    fragments: list[SourceDocument] = []
    script_sources = []
    for pattern in (SCRIPT_SRC_RE, EMBEDDED_SCRIPT_SRC_RE) if include_scripts else ():
        for src in pattern.findall(html):
            if src not in script_sources:
                script_sources.append(src)
    for src in script_sources:
        absolute_src = urljoin(source_url, src) if source_url else src
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
                    resource_required=True,
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
                    resource_required=True,
                )
            )
            continue
        decoded_blocks = decode_script_blocks_fn(script_text)
        if decoded_blocks == [script_text] and decode_script_fn is not decode_script_document_writes:
            decoded_blocks = [decode_script_fn(script_text)]
        if not decoded_blocks:
            decoded = decode_script_fn(script_text)
            decoded_blocks = [decoded] if decoded.strip() else []
        decoded_blocks = [block for block in decoded_blocks if block.strip()]
        if decoded_blocks:
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
    for src in IFRAME_SRC_RE.findall(html):
        if src not in iframe_sources:
            iframe_sources.append(src)
    for src in iframe_sources[:12]:
        absolute_src = urljoin(source_url, src) if source_url else src
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

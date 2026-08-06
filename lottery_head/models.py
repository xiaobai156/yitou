from __future__ import annotations

from dataclasses import dataclass, field




@dataclass(frozen=True)
class SiteRule:
    url: str
    position: str
    section: str
    field: str
    content_hint: str = ""
    parse_hint: str = ""
    api_url: str = ""
    tls_compat: bool = False

    @property
    def anchor(self) -> str:
        return self.content_hint or self.section


@dataclass(frozen=True)
class SourceDocument:
    source: str
    url: str
    route: str
    record_id: str = ""
    record_path: str = ""
    api_url: str = ""
    title: str = ""
    author: str = ""
    parent_url: str = ""
    linked_urls: tuple[str, ...] = ()
    document_order: int = -1
    source_block_id: str = ""
    source_identity: str = ""
    user_id: str = ""
    forum_id: str = ""
    source_list_position: int = -1
    resource_error: str = ""
    resource_required: bool = False

    @property
    def key(self) -> str:
        return "|".join(
            (
                self.route,
                self.record_id,
                self.url,
                self.record_path,
                self.source_identity,
                self.source_block_id,
            )
        )


@dataclass(frozen=True)
class Candidate:
    period: str
    value: str
    raw_line: str
    original_position: int
    document_key: str
    source_record_id: str = ""
    source_record_path: str = ""
    source_route: str = ""
    source_url: str = ""
    source_api_url: str = ""
    source_title: str = ""
    source_author: str = ""
    document_order: int = -1
    block_order: int = -1
    record_order: int = -1
    source_block_id: str = ""
    source_identity: str = ""
    source_user_id: str = ""
    source_forum_id: str = ""
    source_list_position: int = -1


@dataclass(frozen=True)
class AdminArticleFragmentResult:
    text: str
    api_status: int | None = None
    source: str = ""
    error: str = ""
    allow_browser_fallback: bool = False
    record_id: str = ""
    record_path: str = ""
    title: str = ""
    author: str = ""


@dataclass(frozen=True)
class HeadRecord:
    url: str
    position: str
    section: str
    field: str
    period: str
    value: str
    raw_line: str
    status: str
    error: str
    original_position: int = -1
    source_record_id: str = ""
    source_record_path: str = ""
    source_route: str = ""
    source_url: str = ""
    source_api_url: str = ""
    source_title: str = ""
    source_author: str = ""
    parse_hint: str = ""
    document_order: int = -1
    block_order: int = -1
    record_order: int = -1
    source_block_id: str = ""
    source_identity: str = ""
    source_user_id: str = ""
    source_forum_id: str = ""
    source_list_position: int = -1


@dataclass
class BaselineSitePeriodData:
    section: str
    field: str
    position: str
    url: str
    parse_hint: str
    period_values: dict[str, str]
    missing: list[str]
    error: str = ""
    period_records: dict[str, Candidate] = field(default_factory=dict)
    missing_reasons: dict[str, str] = field(default_factory=dict)


SitePeriodData = BaselineSitePeriodData

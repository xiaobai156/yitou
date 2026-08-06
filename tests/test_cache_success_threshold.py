from __future__ import annotations

from pathlib import Path

import lottery_head.cli as cli
from lottery_head.cache_payload import build_cache_payload, cache_update_allowed
from lottery_head.models import HeadRecord, SiteRule


def make_rule(section: str) -> SiteRule:
    return SiteRule(
        url=f"https://example.test/{section}",
        position="顶部",
        section=section,
        field="杀一头",
        content_hint=section,
        parse_hint="period_bracket_head",
    )


def make_record(rule: SiteRule, status: str, *, value: str = "1头", error: str = "") -> HeadRecord:
    return HeadRecord(
        url=rule.url,
        position=rule.position,
        section=rule.section,
        field=rule.field,
        period="217期" if status == "success" else "",
        value=value if status == "success" else "",
        raw_line="217期 杀一头 1头" if status == "success" else "",
        status=status,
        error=error,
        original_position=0 if status == "success" else -1,
        parse_hint=rule.parse_hint,
        source_route="script" if status == "success" else "",
        source_url=rule.url,
    )


def test_cache_update_requires_strictly_more_than_85_percent() -> None:
    assert not cache_update_allowed(17, 20)
    assert cache_update_allowed(18, 20)
    assert not cache_update_allowed(0, 0)


def test_failed_site_replaces_an_old_value_with_a_missing_failure_marker() -> None:
    success_rule = make_rule("成功站")
    failed_rule = make_rule("失败站")
    existing = {
        "sites": [
            {
                "identity": {
                    "section": failed_rule.section,
                    "url": failed_rule.url,
                    "position": "top",
                    "parse_hint": failed_rule.parse_hint,
                },
                "values": {"217期": "4头"},
                "positions": {"217期": 0},
                "provenance": {"217期": {"raw_line": "旧缓存"}},
                "missing": {},
            }
        ]
    }

    payload = build_cache_payload(
        [
            make_record(success_rule, "success", value="2头"),
            make_record(failed_rule, "failed", error="217期不在顶部第一条"),
        ],
        [success_rule, failed_rule],
        "217期",
        existing,
        attempted_period="217期",
    )

    failed_site = next(site for site in payload["sites"] if site["identity"]["section"] == "失败站")
    assert failed_site["values"] == {}
    assert failed_site["positions"] == {}
    assert failed_site["provenance"] == {}
    assert failed_site["missing"]["217期"] == "217期不在顶部第一条"
    assert set(failed_site["missing"]) >= {"217期"}


def test_cli_keeps_the_old_cache_when_success_rate_is_exactly_85_percent(monkeypatch) -> None:
    rules = [make_rule(f"站点{i}") for i in range(20)]
    records = [make_record(rule, "success") for rule in rules[:17]]
    records.extend(
        make_record(rule, "failed", error="指定期数失败")
        for rule in rules[17:]
    )
    commits: list[set[Path]] = []
    artifact_cache_payloads: list[object] = []

    monkeypatch.setattr(cli, "load_rules", lambda: rules)
    monkeypatch.setattr(cli, "_collect", lambda *_args, **_kwargs: (records, []))
    monkeypatch.setattr(
        cli,
        "read_validated_cache",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("85%时不应读取缓存")),
    )

    def build_artifacts(_records, _period, _cache_path, cache_payload, _debug_dir):
        artifact_cache_payloads.append(cache_payload)
        return {
            Path("217期-头.txt"): b"success",
            Path("217期失败-一头.txt"): b"failed",
            Path("lottery_head_records.json"): b"json",
        }

    monkeypatch.setattr(cli, "build_single_period_artifacts", build_artifacts)
    monkeypatch.setattr(cli, "commit_artifacts_transaction", lambda artifacts: commits.append(set(artifacts)))

    assert cli.main(["217期", "--workers", "1"]) == 0
    assert artifact_cache_payloads == [None]
    assert all(cli.RECENT_10_CACHE_PATH not in committed for committed in commits)


def test_cli_writes_cache_when_success_rate_is_strictly_above_85_percent(monkeypatch) -> None:
    rules = [make_rule(f"站点{i}") for i in range(20)]
    records = [make_record(rule, "success") for rule in rules[:18]]
    records.extend(
        make_record(rule, "failed", error="指定期数失败")
        for rule in rules[18:]
    )
    commits: list[set[Path]] = []
    artifact_cache_payloads: list[object] = []
    cache_builds: list[object] = []

    monkeypatch.setattr(cli, "load_rules", lambda: rules)
    monkeypatch.setattr(cli, "_collect", lambda *_args, **_kwargs: (records, []))
    monkeypatch.setattr(cli, "read_validated_cache", lambda *_args, **_kwargs: None)
    cache_payload = {"cache": True, "sites": [{"values": {"217期": "1头"}}]}
    monkeypatch.setattr(cli, "build_cache_payload", lambda *_args, **_kwargs: cache_builds.append(True) or cache_payload)
    monkeypatch.setattr(cli, "validate_cache_snapshot", lambda *_args, **_kwargs: None)

    def build_artifacts(_records, _period, cache_path, cache_payload, _debug_dir):
        artifact_cache_payloads.append(cache_payload)
        return {
            Path("217期-头.txt"): b"success",
            Path("217期失败-一头.txt"): b"failed",
            Path("lottery_head_records.json"): b"json",
            cache_path: b"cache",
        }

    monkeypatch.setattr(cli, "build_single_period_artifacts", build_artifacts)
    monkeypatch.setattr(cli, "commit_artifacts_transaction", lambda artifacts: commits.append(set(artifacts)))

    assert cli.main(["217期", "--workers", "1"]) == 0
    assert artifact_cache_payloads == [cache_payload]
    assert cache_builds == [True]
    assert any(cli.RECENT_10_CACHE_PATH in committed for committed in commits)

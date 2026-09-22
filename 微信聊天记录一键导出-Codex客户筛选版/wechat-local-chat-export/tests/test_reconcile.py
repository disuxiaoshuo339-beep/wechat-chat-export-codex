from __future__ import annotations

from wechat_export.reconcile import reconcile_counts, validate_archive_members


def test_reconcile_requires_every_source_message_to_be_accounted_for():
    assert reconcile_counts(source=100, exported=70, excluded=25, review=5).ok
    assert not reconcile_counts(source=100, exported=70, excluded=20, review=5).ok


def test_archive_rejects_databases_secrets_and_internal_logs():
    members = [
        "客户聊天索引.xlsx",
        "聊天记录_CSV/a.csv",
        "source_copy/message.db",
    ]
    result = validate_archive_members(members)
    assert not result.ok
    assert "source_copy/message.db" in result.forbidden


def test_archive_accepts_only_user_facing_deliverables():
    members = [
        "客户聊天索引.xlsx",
        "聊天记录_CSV/a.csv",
        "聊天记录_HTML/a.html",
        "使用说明.md",
        "导出摘要.json",
    ]
    assert validate_archive_members(members).ok

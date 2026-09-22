from __future__ import annotations

from pathlib import Path

import pytest

from wechat_export.discovery import (
    AccountCandidate,
    authorize_account,
    discover_accounts,
)


def test_discovers_accounts_by_db_storage_not_folder_prefix(tmp_path):
    account = tmp_path / "custom-account_ab12"
    message = account / "db_storage" / "message"
    message.mkdir(parents=True)
    (message / "message_0.db").write_bytes(b"x" * 4096)

    found = discover_accounts([tmp_path])

    assert [item.account_id for item in found] == ["custom-account_ab12"]
    assert found[0].has_message_db


def test_discovery_deduplicates_the_same_resolved_account(tmp_path):
    account = tmp_path / "xwechat_files" / "wxid_fixture_ab12"
    (account / "db_storage" / "message").mkdir(parents=True)
    (account / "db_storage" / "message" / "message_0.db").write_bytes(b"x" * 4096)

    found = discover_accounts([tmp_path, tmp_path / "xwechat_files"])

    assert len(found) == 1


def test_authorization_requires_exact_discovered_account(tmp_path):
    candidate = AccountCandidate(
        account_id="wxid_fixture_ab12",
        db_storage=tmp_path / "db_storage",
        weixin_version="4.1.13.6",
        has_contact_db=True,
        has_session_db=True,
        has_message_db=True,
        process_count=1,
    )

    assert authorize_account([candidate], "wxid_fixture_ab12") == candidate
    with pytest.raises(ValueError, match="explicitly discovered"):
        authorize_account([candidate], "wxid_other")


def test_authorization_rejects_ambiguous_duplicate_identifiers(tmp_path):
    candidates = [
        AccountCandidate("same", tmp_path / "a" / "db_storage"),
        AccountCandidate("same", tmp_path / "b" / "db_storage"),
    ]

    with pytest.raises(ValueError, match="not unique"):
        authorize_account(candidates, "same")

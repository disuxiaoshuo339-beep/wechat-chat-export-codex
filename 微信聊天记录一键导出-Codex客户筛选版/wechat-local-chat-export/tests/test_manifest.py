from __future__ import annotations

import hashlib

import pytest

from wechat_export.config import ExportConfig
from wechat_export.manifest import copy_with_manifest, validate_source


def test_manifest_rejects_source_outside_authorized_account(tmp_path):
    allowed = tmp_path / "allowed" / "db_storage"
    allowed.mkdir(parents=True)
    config = ExportConfig.for_authorized_account(allowed, tmp_path / "work")

    with pytest.raises(ValueError, match="authorized account"):
        validate_source(config, tmp_path / "other")


def test_copy_keeps_relative_paths_hashes_and_does_not_overwrite(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "copy"
    (source / "message").mkdir(parents=True)
    source_file = source / "message" / "message_0.db"
    source_file.write_bytes(b"abc")

    rows = copy_with_manifest(source, destination)

    assert rows[0].relative_path == "message/message_0.db"
    assert rows[0].sha256 == hashlib.sha256(b"abc").hexdigest()
    assert (destination / "message" / "message_0.db").read_bytes() == b"abc"

    source_file.write_bytes(b"changed")
    with pytest.raises(FileExistsError, match="different content"):
        copy_with_manifest(source, destination)

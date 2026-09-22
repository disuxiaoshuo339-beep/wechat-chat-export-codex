from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from wechat_export.runtime_paths import (
    TOOL_ROOT,
    default_output_root,
    validate_runtime_directory,
)


def test_default_uses_local_appdata_even_when_cwd_is_repository(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    local = tmp_path / "local-appdata"
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert default_output_root() == local / "WeChatChatExport" / "runs"
    assert not local.exists()


def test_missing_localappdata_does_not_fall_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert default_output_root() == tmp_path / "home/AppData/Local/WeChatChatExport/runs"


@pytest.mark.parametrize("git_is_file", [False, True])
def test_rejects_git_checkout_and_worktree_before_creating_data(tmp_path, git_is_file):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    marker = checkout / ".git"
    if git_is_file:
        marker.write_text("gitdir: ../metadata", encoding="utf-8")
    else:
        marker.mkdir()
    target = checkout / "new/deep/run"
    with pytest.raises(ValueError, match="Git"):
        validate_runtime_directory(target)
    assert not target.exists()


def test_rejects_tool_folder_without_relying_on_git():
    with pytest.raises(ValueError, match="工具目录"):
        validate_runtime_directory(TOOL_ROOT / "private-output")


def test_rejects_overlap_with_wechat_source(tmp_path):
    source_db = tmp_path / "wechat-account/db_storage"
    for target in [source_db, source_db.parent / "output", tmp_path]:
        with pytest.raises(ValueError, match="源账号"):
            validate_runtime_directory(target, source_db)
    safe = tmp_path / "separate-output"
    assert validate_runtime_directory(safe, source_db) == safe


def test_resolves_directory_link_before_git_check(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    link = tmp_path / "alias"
    try:
        link.symlink_to(checkout, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is unavailable")
    with pytest.raises(ValueError, match="Git"):
        validate_runtime_directory(link / "output")


@pytest.mark.parametrize(
    "script", ["prepare_snapshot.py", "list_conversations.py", "run_export.py",
               "build_index.py", "finalize_delivery.py"]
)
def test_cli_rejects_repository_path_without_reading_or_writing_chat(script, tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    target = checkout / "run"
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    args = [sys.executable, str(scripts / script)]
    if script == "prepare_snapshot.py":
        args += ["--account-id", "wxid_fixture", "--output-root", str(target)]
    else:
        args += ["--run-root", str(target)]
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode != 0
    assert "运行数据不得写入 Git 仓库" in result.stderr
    assert not target.exists()

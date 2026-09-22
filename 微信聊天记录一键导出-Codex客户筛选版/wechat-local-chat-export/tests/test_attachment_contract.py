from __future__ import annotations

import re
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]
SKILL = PACKAGE / "wechat-local-chat-export"


def test_attachment_package_has_single_bootstrap_and_no_account_data():
    assert (PACKAGE / "START_HERE.md").is_file()
    assert (SKILL / "SKILL.md").is_file()
    assert (SKILL / "scripts" / "run_export.py").is_file()
    assert (SKILL / "scripts" / "prepare_snapshot.py").is_file()
    assert (SKILL / "scripts" / "list_conversations.py").is_file()
    # 原版这里把打包者本人的真实 wxid 写死成了对照字符串，等于随包一起发出去。
    # 改成通用规则：真实微信号形如 wxid_ + 16 位以上小写字母数字，
    # 测试夹具用的短名（wxid_customer / wxid_coatings 等）不会命中。
    real_account_pattern = re.compile(r"wxid_[0-9a-z]{16,}")
    for path in PACKAGE.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".py", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not real_account_pattern.search(text), f"疑似真实微信号泄漏：{path}"
    assert not any(path.name.lower() == "keys.json" for path in PACKAGE.rglob("*"))


def test_package_has_no_database_or_process_dump_files():
    forbidden = {".db", ".db-wal", ".db-shm", ".dmp"}
    files = [path for path in PACKAGE.rglob("*") if path.is_file()]
    assert not [path for path in files if any(path.name.lower().endswith(x) for x in forbidden)]

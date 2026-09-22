from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import sys
import zipfile

from wechat_export.export import export_private_chats, scan_private_conversations
from wechat_export.reconcile import validate_archive_members
from wechat_export.screening import read_selection, write_screening_csv

import build_index as build_index_module
import finalize_delivery as finalize_delivery_module


SENTINEL = "SENTINEL_PRIVATE_MSG_798431_DO_NOT_LEAK"

# username -> (remark, nick_name, alias)
CONTACTS = {
    "wxid_coatings": ("华东涂料有限公司", "老王", ""),
    "wxid_phone": ("13812345678", "小李", ""),
    "wxid_family": ("老公", "老公", ""),
    "wxid_undecided": ("老李", "老李", ""),
}

# usernames excluded from the "private" classification entirely
GROUP_USERNAME = "12345@chatroom"
PUBLIC_USERNAME = "gh_test123"

# real_sender_id -> username, shared Name2Id mapping for the shard
SENDER_IDS = {
    1: "wxid_me",
    2: "wxid_coatings",
    3: "wxid_phone",
    4: "wxid_family",
    5: "wxid_undecided",
    6: GROUP_USERNAME,
    7: PUBLIC_USERNAME,
}


def _msg_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def _build_decrypted_root(tmp_path):
    decrypted = tmp_path / "decrypted"
    (decrypted / "contact").mkdir(parents=True)
    (decrypted / "session").mkdir(parents=True)
    (decrypted / "message").mkdir(parents=True)

    # contact.db
    contact_conn = sqlite3.connect(decrypted / "contact" / "contact.db")
    contact_conn.execute(
        "CREATE TABLE contact (username TEXT, remark TEXT, nick_name TEXT, "
        "alias TEXT, local_type INTEGER, verify_flag INTEGER)"
    )
    for username, (remark, nick_name, alias) in CONTACTS.items():
        contact_conn.execute(
            "INSERT INTO contact VALUES (?, ?, ?, ?, ?, ?)",
            (username, remark, nick_name, alias, 3, 0),
        )
    contact_conn.commit()
    contact_conn.close()

    # session.db: empty placeholder table, not read by the scripts under test
    session_conn = sqlite3.connect(decrypted / "session" / "session.db")
    session_conn.execute("CREATE TABLE session (username TEXT)")
    session_conn.commit()
    session_conn.close()

    # message_0.db
    message_conn = sqlite3.connect(decrypted / "message" / "message_0.db")
    message_conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
    for rowid, username in SENDER_IDS.items():
        message_conn.execute(
            "INSERT INTO Name2Id (rowid, user_name) VALUES (?, ?)", (rowid, username)
        )

    def _create_msg_table(username: str):
        message_conn.execute(
            f'CREATE TABLE "{_msg_table(username)}" ('
            "local_id INTEGER, server_id INTEGER, local_type INTEGER, "
            "sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER, "
            "status INTEGER, message_content TEXT, compress_content BLOB)"
        )

    def _insert_msg(username, local_id, real_sender_id, create_time, content):
        message_conn.execute(
            f'INSERT INTO "{_msg_table(username)}" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (local_id, local_id, 1, local_id, real_sender_id, create_time, 2, content, None),
        )

    base_time = 1_700_000_000

    _create_msg_table("wxid_coatings")
    _insert_msg("wxid_coatings", 1, 1, base_time + 10, "在的，牌号有货")
    _insert_msg("wxid_coatings", 2, 2, base_time + 20, "好的，麻烦发一下报价")

    _create_msg_table("wxid_phone")
    _insert_msg("wxid_phone", 1, 1, base_time + 30, "已收到")
    _insert_msg("wxid_phone", 2, 3, base_time + 40, "谢谢")

    _create_msg_table("wxid_family")
    _insert_msg("wxid_family", 1, 1, base_time + 50, "今晚回家吃饭")
    _insert_msg("wxid_family", 2, 4, base_time + 60, SENTINEL)
    _insert_msg("wxid_family", 3, 4, base_time + 70, "好的")

    _create_msg_table("wxid_undecided")
    _insert_msg("wxid_undecided", 1, 1, base_time + 80, "在吗")
    _insert_msg("wxid_undecided", 2, 5, base_time + 90, "在的")

    _create_msg_table(GROUP_USERNAME)
    _insert_msg(GROUP_USERNAME, 1, 6, base_time + 100, "群消息一")
    _insert_msg(GROUP_USERNAME, 2, 6, base_time + 110, "群消息二")

    _create_msg_table(PUBLIC_USERNAME)
    _insert_msg(PUBLIC_USERNAME, 1, 7, base_time + 120, "公众号推送")

    message_conn.commit()
    message_conn.close()

    return decrypted


def test_scan_private_conversations_metadata_only(tmp_path):
    decrypted = _build_decrypted_root(tmp_path)
    rows = scan_private_conversations(decrypted)

    by_username = {row["微信号"]: row for row in rows}
    assert set(by_username) == {
        "wxid_coatings",
        "wxid_phone",
        "wxid_family",
        "wxid_undecided",
    }
    assert by_username["wxid_coatings"]["消息数"] == 2
    assert by_username["wxid_phone"]["消息数"] == 2
    assert by_username["wxid_family"]["消息数"] == 3
    assert by_username["wxid_undecided"]["消息数"] == 2

    assert by_username["wxid_coatings"]["自动判定"] == "疑似客户"
    assert by_username["wxid_phone"]["自动判定"] == "疑似客户"
    assert by_username["wxid_family"]["自动判定"] == "私人"
    assert by_username["wxid_undecided"]["自动判定"] == "待定"

    # 隐私铁律：扫描结果里不允许出现任何正文
    dumped = json.dumps(rows, ensure_ascii=False)
    assert SENTINEL not in dumped
    assert "message_content" not in dumped


def test_screening_csv_roundtrip_with_manual_override(tmp_path):
    decrypted = _build_decrypted_root(tmp_path)
    rows = scan_private_conversations(decrypted)
    csv_path = tmp_path / "会话清单.csv"
    counts = write_screening_csv(rows, csv_path)

    assert counts == {
        "total": 4,
        "auto_customer": 2,
        "auto_private": 1,
        "auto_undecided": 1,
    }

    # 人工复核：把「待定」的 wxid_undecided 手工改成 Y
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        edited_rows = list(reader)
    for row in edited_rows:
        if row["微信号"] == "wxid_undecided":
            row["是否客户"] = "Y"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(edited_rows)

    selected = read_selection(csv_path)
    assert selected == {"wxid_coatings", "wxid_phone", "wxid_undecided"}


def test_export_only_selected_and_never_leaks_screened_out_content(tmp_path):
    decrypted = _build_decrypted_root(tmp_path)
    rows = scan_private_conversations(decrypted)
    csv_path = tmp_path / "会话清单.csv"
    write_screening_csv(rows, csv_path)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        edited_rows = list(reader)
    for row in edited_rows:
        if row["微信号"] == "wxid_undecided":
            row["是否客户"] = "Y"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(edited_rows)

    selected = read_selection(csv_path)
    assert selected == {"wxid_coatings", "wxid_phone", "wxid_undecided"}

    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "private" / "decrypted").parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(decrypted, run_root / "private" / "decrypted")

    delivery = run_root / "delivery"
    summary = export_private_chats(
        run_root / "private" / "decrypted", delivery, allowed_usernames=selected
    )

    assert summary["private_conversations"] == 3
    assert summary["private_messages"] == 2 + 2 + 2  # coatings + phone + undecided
    assert summary["screened_out_conversations"] == 1  # wxid_family
    assert summary["screened_out_messages"] == 3
    assert summary["selection_not_found"] == 0

    exported_usernames = {row["微信号"] for row in summary["index_rows"]}
    assert exported_usernames == {"wxid_coatings", "wxid_phone", "wxid_undecided"}

    # 隐私回归测试：未选中的私人会话（wxid_family）的正文一个字都不能出现在交付目录里
    for path in delivery.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert SENTINEL.encode("utf-8") not in content


def _prepare_exported_run(tmp_path):
    decrypted = _build_decrypted_root(tmp_path)
    rows = scan_private_conversations(decrypted)
    csv_path = tmp_path / "会话清单.csv"
    write_screening_csv(rows, csv_path)
    selected = read_selection(csv_path)  # auto Y rows: coatings + phone
    assert selected == {"wxid_coatings", "wxid_phone"}

    run_root = tmp_path / "run"
    run_root.mkdir()
    import shutil

    shutil.copytree(decrypted, run_root / "private" / "decrypted")
    delivery = run_root / "delivery"
    export_private_chats(
        run_root / "private" / "decrypted", delivery, allowed_usernames=selected
    )
    return run_root


def test_build_index_produces_index_file(tmp_path):
    run_root = _prepare_exported_run(tmp_path)
    result = build_index_module.build_index(run_root)
    assert result["status"] == "ok"
    assert (run_root / "delivery" / "客户聊天索引.xlsx").is_file()
    assert result["rows"] == 2


def test_finalize_delivery_produces_zip_and_rejects_screening_csv_member(tmp_path):
    run_root = _prepare_exported_run(tmp_path)
    build_index_module.build_index(run_root)

    result = finalize_delivery_module.finalize(run_root)
    assert result["status"] == "complete"
    archive_path = run_root / "微信客户聊天记录_交付.zip"
    assert archive_path.is_file()

    check_ok = validate_archive_members(["客户聊天索引.xlsx", "聊天记录_CSV/a.csv"])
    assert check_ok.ok

    check_bad = validate_archive_members(["会话清单.csv", "客户聊天索引.xlsx"])
    assert not check_bad.ok
    assert "会话清单.csv" in check_bad.forbidden


def test_finalize_purge_workspace_removes_plaintext_databases(tmp_path):
    run_root = _prepare_exported_run(tmp_path)
    build_index_module.build_index(run_root)

    # 模拟快照阶段留下的明文中间产物：source_copy 与 private 里含未导出的私人会话
    source_copy = run_root / "source_copy"
    source_copy.mkdir()
    (source_copy / "message_0.db").write_text(SENTINEL, encoding="utf-8")
    leftover = run_root / "private" / "decrypted" / "leftover.txt"
    leftover.write_text(SENTINEL, encoding="utf-8")

    result = finalize_delivery_module.finalize(run_root, purge_workspace=True)

    assert result["status"] == "complete"
    assert sorted(result["purged"]) == ["private", "source_copy"]
    assert not source_copy.exists()
    assert not (run_root / "private").exists()
    # 交付 ZIP 仍在，且哨兵字符串在整个 run_root 里已无残留
    assert (run_root / "微信客户聊天记录_交付.zip").is_file()
    for path in run_root.rglob("*"):
        if path.is_file():
            assert SENTINEL.encode("utf-8") not in path.read_bytes()


def test_finalize_purge_workspace_is_opt_in(tmp_path):
    run_root = _prepare_exported_run(tmp_path)
    build_index_module.build_index(run_root)
    (run_root / "source_copy").mkdir()

    result = finalize_delivery_module.finalize(run_root)

    assert result["purged"] == []
    assert (run_root / "source_copy").exists()
    assert (run_root / "private").exists()


def test_build_index_falls_back_to_csv_without_openpyxl(tmp_path, monkeypatch):
    run_root = _prepare_exported_run(tmp_path)
    monkeypatch.setitem(sys.modules, "openpyxl", None)

    result = build_index_module.build_index(run_root)

    assert result["status"] == "csv_fallback"
    csv_index = run_root / "delivery" / "客户聊天索引.csv"
    assert csv_index.is_file()
    assert not (run_root / "delivery" / "客户聊天索引.xlsx").exists()
    header = csv_index.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.startswith("序号,客户显示名,备注名")

    # 降级后 finalize 仍应通过对账，并把 CSV 索引打进交付包
    finalize_result = finalize_delivery_module.finalize(run_root)
    assert finalize_result["status"] == "complete"
    with zipfile.ZipFile(run_root / "微信客户聊天记录_交付.zip") as archive:
        members = archive.namelist()
    assert "客户聊天索引.csv" in members
    assert "客户聊天索引.xlsx" not in members

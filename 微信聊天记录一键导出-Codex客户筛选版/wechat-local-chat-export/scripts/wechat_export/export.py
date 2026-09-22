from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .messages import direction_for_private_chat, summarize_content
from .screening import guess_category


SYSTEM_ACCOUNTS = {
    "weixin",
    "filehelper",
    "fmessage",
    "medianote",
    "floatbottle",
    "newsapp",
    "qmessage",
    "qqmail",
    "tmessage",
    "exmail_tool",
    "brandsessionholder",
    "notification_messages",
    "officialaccounts",
    "helper_entry",
}


def classify_conversation(username: str) -> str:
    if username.endswith("@chatroom"):
        return "group"
    if username.startswith("gh_"):
        return "public"
    if username in SYSTEM_ACCOUNTS:
        return "system"
    return "private"


def display_name(
    username: str, remark: object, nickname: object, alias: object
) -> str:
    for value in (remark, nickname, alias, username):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return username


def safe_file_stem(sequence: int, name: str, username: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    clean = re.sub(r"\s+", " ", clean) or "未命名客户"
    digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:10]
    prefix = f"{sequence:04d}_{clean[:68]}_{digest}"
    return prefix[:90].rstrip(" .")


def _format_time(timestamp: object) -> str:
    try:
        value = int(timestamp or 0)
        if value > 10_000_000_000:
            value //= 1000
        return datetime.fromtimestamp(value, ZoneInfo("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (ValueError, TypeError, OSError, OverflowError):
        return ""


def _csv_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _contact_map(contact_db: Path) -> dict[str, dict[str, object]]:
    connection = sqlite3.connect(contact_db)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT username, remark, nick_name, alias, local_type, verify_flag "
            "FROM contact"
        )
        return {str(row["username"]): dict(row) for row in rows if row["username"]}
    finally:
        connection.close()


def scan_private_conversations(decrypted_root: Path) -> list[dict]:
    # 隐私铁律：本函数只允许 COUNT(*)/MIN(create_time)/MAX(create_time) 聚合查询，
    # 禁止读取 message_content / compress_content 字段。
    contacts = _contact_map(decrypted_root / "contact" / "contact.db")
    shard_paths = sorted(
        path
        for path in (decrypted_root / "message").glob("message_*.db")
        if path.stem[len("message_"):].isdigit()
    )
    if not shard_paths:
        raise RuntimeError("no message_N.db shards found")
    connections: list[sqlite3.Connection] = []
    try:
        all_names: set[str] = set(contacts)
        shards: list[tuple[sqlite3.Connection, list[str]]] = []
        for shard_path in shard_paths:
            connection = sqlite3.connect(shard_path)
            connection.row_factory = sqlite3.Row
            connections.append(connection)
            sender_names = {
                str(row["user_name"])
                for row in connection.execute("SELECT user_name FROM Name2Id")
                if row["user_name"]
            }
            all_names |= sender_names
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'Msg_%'"
                )
            ]
            shards.append((connection, tables))
        hash_to_name = {
            hashlib.md5(name.encode("utf-8")).hexdigest(): name for name in all_names
        }

        user_count: dict[str, int] = {}
        user_first: dict[str, int] = {}
        user_last: dict[str, int] = {}
        for connection, tables in shards:
            for table in tables:
                username = hash_to_name.get(table[4:])
                if not username or classify_conversation(username) != "private":
                    continue
                count, min_time, max_time = connection.execute(
                    f'SELECT COUNT(*), COALESCE(MIN(NULLIF(create_time, 0)), 0), '
                    f'COALESCE(MAX(create_time), 0) FROM "{table}"'
                ).fetchone()
                user_count[username] = user_count.get(username, 0) + int(count)
                if int(min_time):
                    user_first[username] = min(
                        user_first.get(username, int(min_time)), int(min_time)
                    )
                user_last[username] = max(user_last.get(username, 0), int(max_time))
    finally:
        for connection in connections:
            connection.close()

    usernames = sorted(user_count, key=lambda u: (-user_last.get(u, 0), u))
    rows: list[dict] = []
    for sequence, username in enumerate(usernames, start=1):
        contact = contacts.get(username, {})
        remark = contact.get("remark")
        nickname = contact.get("nick_name")
        alias = contact.get("alias")
        name = display_name(username, remark, nickname, alias)
        rows.append(
            {
                "序号": sequence,
                "显示名": name,
                "备注名": str(remark or ""),
                "昵称": str(nickname or ""),
                "微信号": username,
                "消息数": user_count[username],
                "首条时间": _format_time(user_first.get(username, 0)),
                "末条时间": _format_time(user_last.get(username, 0)),
                "自动判定": guess_category(remark, nickname, alias, username),
            }
        )
    return rows


def export_private_chats(
    decrypted_root: Path,
    output_dir: Path,
    allowed_usernames: set[str] | None = None,
) -> dict[str, object]:
    # 本地调整：微信 4.x 按年份把消息分到 message_0.db … message_N.db 多个分库，
    # 原版只读 message_0.db 会漏掉最新分库；这里遍历全部 message_[数字].db 并按会话合并。
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    html_dir = output_dir / "聊天记录_HTML"
    csv_dir = output_dir / "聊天记录_CSV"
    html_dir.mkdir(parents=True)
    csv_dir.mkdir(parents=True)

    contacts = _contact_map(decrypted_root / "contact" / "contact.db")
    shard_paths = sorted(
        path
        for path in (decrypted_root / "message").glob("message_*.db")
        if path.stem[len("message_"):].isdigit()
    )
    if not shard_paths:
        raise RuntimeError("no message_N.db shards found")
    connections: list[sqlite3.Connection] = []
    try:
        # 每个分库各自维护 Name2Id，real_sender_id 必须用所在分库的映射解析
        shards: list[tuple[sqlite3.Connection, dict[int, str], list[str]]] = []
        all_names: set[str] = set(contacts)
        for shard_path in shard_paths:
            connection = sqlite3.connect(shard_path)
            connection.row_factory = sqlite3.Row
            connections.append(connection)
            sender_names = {
                int(row["rowid"]): str(row["user_name"])
                for row in connection.execute("SELECT rowid, user_name FROM Name2Id")
                if row["user_name"]
            }
            all_names |= set(sender_names.values())
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'Msg_%'"
                )
            ]
            shards.append((connection, sender_names, tables))
        hash_to_name = {
            hashlib.md5(name.encode("utf-8")).hexdigest(): name for name in all_names
        }

        # username -> [(connection, sender_names, table)]
        per_user: dict[str, list[tuple[sqlite3.Connection, dict[int, str], str]]] = {}
        user_count: dict[str, int] = {}
        user_last: dict[str, int] = {}
        excluded_seen: dict[str, set[str]] = {"group": set(), "public": set(), "system": set(), "unknown": set()}
        excluded_messages = {"group": 0, "public": 0, "system": 0, "unknown": 0}
        screened_out_seen: set[str] = set()
        screened_out_messages = 0
        seen_private_usernames: set[str] = set()
        for connection, sender_names, tables in shards:
            for table in tables:
                username = hash_to_name.get(table[4:])
                count, last_time = connection.execute(
                    f'SELECT COUNT(*), COALESCE(MAX(create_time), 0) FROM "{table}"'
                ).fetchone()
                if not username:
                    excluded_seen["unknown"].add(table[4:])
                    excluded_messages["unknown"] += int(count)
                    continue
                kind = classify_conversation(username)
                if kind != "private":
                    excluded_seen[kind].add(username)
                    excluded_messages[kind] += int(count)
                    continue
                seen_private_usernames.add(username)
                if allowed_usernames is not None and username not in allowed_usernames:
                    # 已被人工筛选排除：只累加会话表的 COUNT(*)，不发出任何正文 SELECT
                    screened_out_seen.add(username)
                    screened_out_messages += int(count)
                    continue
                per_user.setdefault(username, []).append((connection, sender_names, table))
                user_count[username] = user_count.get(username, 0) + int(count)
                user_last[username] = max(user_last.get(username, 0), int(last_time))
        excluded = {key: len(value) for key, value in excluded_seen.items()}
        screened_out_conversations = len(screened_out_seen)
        selection_not_found = 0
        if allowed_usernames is not None:
            selection_not_found = len(set(allowed_usernames) - seen_private_usernames)
        private_users = sorted(per_user, key=lambda u: (-user_last[u], u))

        index_rows: list[dict[str, object]] = []
        message_total = 0
        direction_totals = {"我": 0, "客户": 0, "未知": 0}
        type_totals: dict[str, int] = {}
        for sequence, username in enumerate(private_users, start=1):
            expected_count = user_count[username]
            contact = contacts.get(username, {})
            name = display_name(
                username,
                contact.get("remark"),
                contact.get("nick_name"),
                contact.get("alias"),
            )
            stem = safe_file_stem(sequence, name, username)
            csv_name = stem + ".csv"
            html_name = stem + ".html"
            csv_path = csv_dir / csv_name
            html_path = html_dir / html_name
            merged: list[tuple[tuple[int, int, int], sqlite3.Row, dict[int, str]]] = []
            for connection, sender_names, table in per_user[username]:
                for row in connection.execute(
                    f'SELECT local_id, server_id, local_type, sort_seq, real_sender_id, '
                    f'create_time, status, message_content, compress_content FROM "{table}"'
                ):
                    key = (
                        int(row["create_time"] or 0),
                        int(row["sort_seq"] or 0),
                        int(row["local_id"] or 0),
                    )
                    merged.append((key, row, sender_names))
            merged.sort(key=lambda item: item[0])
            messages: list[dict[str, object]] = []
            own = customer = unknown_direction = 0
            first_time = last_time = ""
            with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(
                    ["时间", "方向", "发送者", "消息类型", "内容", "本地消息ID", "服务器消息ID"]
                )
                for _, row, sender_names in merged:
                    resolved_sender = sender_names.get(int(row["real_sender_id"] or 0))
                    direction = direction_for_private_chat(
                        username, resolved_sender, row["status"]
                    )
                    if direction == "我":
                        own += 1
                    elif direction == "客户":
                        customer += 1
                    else:
                        unknown_direction += 1
                    direction_totals[direction] += 1
                    content_value = row["message_content"]
                    if content_value in (None, "", b""):
                        content_value = row["compress_content"]
                    type_label, content = summarize_content(
                        row["local_type"], content_value
                    )
                    type_totals[type_label] = type_totals.get(type_label, 0) + 1
                    timestamp = _format_time(row["create_time"])
                    if not first_time:
                        first_time = timestamp
                    last_time = timestamp
                    sender_label = "我" if direction == "我" else name if direction == "客户" else "未知"
                    writer.writerow(
                        [
                            _csv_safe(timestamp),
                            direction,
                            _csv_safe(sender_label),
                            type_label,
                            _csv_safe(content),
                            str(row["local_id"] or ""),
                            str(row["server_id"] or ""),
                        ]
                    )
                    messages.append(
                        {
                            "time": timestamp,
                            "direction": direction,
                            "sender": sender_label,
                            "type": type_label,
                            "content": content,
                        }
                    )
            if len(messages) != expected_count:
                raise RuntimeError(
                    f"message count mismatch for {username}: {len(messages)}/{expected_count}"
                )
            html_path.write_text(
                _render_chat_html(name, username, messages, own, customer),
                encoding="utf-8",
            )
            message_total += len(messages)
            index_rows.append(
                {
                    "序号": sequence,
                    "客户显示名": name,
                    "备注名": str(contact.get("remark") or ""),
                    "昵称": str(contact.get("nick_name") or ""),
                    "微信号": username,
                    "微信号别名": str(contact.get("alias") or ""),
                    "消息数": len(messages),
                    "我发送": own,
                    "客户发送": customer,
                    "未知方向": unknown_direction,
                    "首条时间": first_time,
                    "末条时间": last_time,
                    "HTML文件": f"聊天记录_HTML/{html_name}",
                    "CSV文件": f"聊天记录_CSV/{csv_name}",
                }
            )
    finally:
        for connection in connections:
            connection.close()

    summary = {
        "private_conversations": len(index_rows),
        "private_messages": message_total,
        "direction_totals": direction_totals,
        "type_totals": type_totals,
        "excluded_conversations": excluded,
        "excluded_messages": excluded_messages,
        "screened_out_conversations": screened_out_conversations,
        "screened_out_messages": screened_out_messages,
        "selection_not_found": selection_not_found,
        "index_rows": index_rows,
    }
    (output_dir / "客户索引数据.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "导出摘要.json").write_text(
        json.dumps({key: value for key, value in summary.items() if key != "index_rows"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _render_chat_html(
    name: str,
    username: str,
    messages: list[dict[str, object]],
    own_count: int,
    customer_count: int,
) -> str:
    cards = []
    for message in messages:
        direction = str(message["direction"])
        css_class = "mine" if direction == "我" else "theirs" if direction == "客户" else "unknown"
        cards.append(
            '<article class="message %s"><div class="meta">%s · %s · %s</div>'
            '<div class="bubble">%s</div></article>'
            % (
                css_class,
                html.escape(str(message["time"])),
                html.escape(str(message["sender"])),
                html.escape(str(message["type"])),
                html.escape(str(message["content"])).replace("\n", "<br>"),
            )
        )
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - 微信聊天记录</title><style>
body{{margin:0;background:#f4f6f8;color:#202124;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}
header{{position:sticky;top:0;z-index:2;background:#17324d;color:#fff;padding:20px max(20px,calc((100% - 900px)/2));box-shadow:0 2px 8px #0002}}
h1{{font-size:22px;margin:0 0 4px}}.sub{{opacity:.8;font-size:13px}}main{{max-width:900px;margin:0 auto;padding:24px 18px 50px}}
.message{{margin:14px 0;display:flex;flex-direction:column;align-items:flex-start}}.message.mine{{align-items:flex-end}}.meta{{font-size:12px;color:#6b7280;margin:0 8px 5px}}
.bubble{{max-width:78%;background:#fff;border:1px solid #e3e7eb;border-radius:14px;padding:10px 13px;white-space:normal;overflow-wrap:anywhere;box-shadow:0 1px 2px #0000000d}}
.mine .bubble{{background:#dff4d1;border-color:#c7e7b5}}.unknown .bubble{{background:#fff7d6}}footer{{text-align:center;color:#8a939d;font-size:12px;padding:24px}}
@media print{{header{{position:static}}body{{background:#fff}}.bubble{{box-shadow:none}}}}
</style></head><body><header><h1>{title}</h1><div class="sub">微信号：{username} · 共 {total} 条 · 我发送 {own} 条 · 客户发送 {customer} 条</div></header>
<main>{cards}</main><footer>由本地微信数据库整理生成 · 内容未上传</footer></body></html>""".format(
        title=html.escape(name),
        username=html.escape(username),
        total=len(messages),
        own=own_count,
        customer=customer_count,
        cards="\n".join(cards),
    )

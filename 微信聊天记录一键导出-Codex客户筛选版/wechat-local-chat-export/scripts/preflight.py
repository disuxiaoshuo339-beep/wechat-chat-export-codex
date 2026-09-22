from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wechat_export.discovery import (  # noqa: E402
    default_search_roots,
    discover_accounts,
    get_file_version,
)
from wechat_export.key_scan import enumerate_authorized_weixin_processes  # noqa: E402


def _zstd_available() -> bool:
    try:
        from compression import zstd as _  # noqa: F401

        return True
    except ImportError:
        return importlib.util.find_spec("zstandard") is not None


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only WeChat 4.x export preflight")
    parser.add_argument("--root", action="append", type=Path, default=[])
    args = parser.parse_args()

    missing: list[str] = []
    if os.name != "nt":
        missing.append("Windows")
    if importlib.util.find_spec("Cryptodome") is None:
        missing.append("pycryptodomex")
    if not _zstd_available():
        missing.append("zstandard-or-python-3.14")

    try:
        processes = enumerate_authorized_weixin_processes() if os.name == "nt" else []
    except OSError:
        processes = []
    version = get_file_version(processes[0].path) if processes else ""
    roots = args.root or default_search_roots()
    accounts = discover_accounts(roots, version, len(processes))
    payload = {
        "status": "ready" if accounts and not missing else "needs_attention",
        "platform": sys.platform,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "weixin_process_count": len(processes),
        "weixin_version": version,
        "missing_dependencies": missing,
        "accounts": [
            {
                "account_id": item.account_id,
                "db_storage": str(item.db_storage),
                "core_files_ok": item.core_files_ok,
                "has_contact_db": item.has_contact_db,
                "has_session_db": item.has_session_db,
                "has_message_db": item.has_message_db,
            }
            for item in accounts
        ],
        "authorization_required": True,
        "next_action": "Ask the user to confirm one exact account_id before memory or chat access.",
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if accounts and not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())

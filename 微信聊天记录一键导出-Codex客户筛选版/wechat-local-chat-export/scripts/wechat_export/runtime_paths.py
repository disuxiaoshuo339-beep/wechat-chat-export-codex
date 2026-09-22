from __future__ import annotations

import os
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[3]


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def validate_runtime_directory(path: Path, source_db: Path | None = None) -> Path:
    """Keep private runtime data outside source checkouts and the tool package."""
    resolved = path.expanduser().resolve()
    if _inside(resolved, TOOL_ROOT):
        raise ValueError("运行数据必须保存在工具目录之外，请使用默认本地输出位置。")
    if any((ancestor / ".git").exists() for ancestor in (resolved, *resolved.parents)):
        raise ValueError("运行数据不得写入 Git 仓库，请选择仓库之外的本机目录。")
    if source_db is not None:
        account_root = source_db.resolve().parent
        if _inside(resolved, account_root) or _inside(account_root, resolved):
            raise ValueError("输出位置不得与微信源账号目录重叠。")
    return resolved


def default_output_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return validate_runtime_directory(base / "WeChatChatExport" / "runs")

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AccountCandidate:
    account_id: str
    db_storage: Path
    weixin_version: str = ""
    has_contact_db: bool = False
    has_session_db: bool = False
    has_message_db: bool = False
    process_count: int = 0

    @property
    def core_files_ok(self) -> bool:
        return self.has_contact_db and self.has_session_db and self.has_message_db


def default_search_roots() -> list[Path]:
    profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    candidates = [
        profile / "Documents" / "WeChat Files",
        profile / "Documents" / "xwechat_files",
        profile / "Documents",
        Path(r"C:\WeChat Files"),
        Path(r"D:\WeChat Files"),
    ]
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _bounded_db_storage_candidates(root: Path) -> Iterable[Path]:
    if root.name.casefold() == "db_storage" and root.is_dir():
        yield root
    direct = root / "db_storage"
    if direct.is_dir():
        yield direct
    if not root.is_dir():
        return
    for candidate in root.glob("*/db_storage"):
        if candidate.is_dir():
            yield candidate
    for candidate in root.glob("xwechat_files/*/db_storage"):
        if candidate.is_dir():
            yield candidate


def discover_accounts(
    roots: Iterable[Path], weixin_version: str = "", process_count: int = 0
) -> list[AccountCandidate]:
    found: dict[Path, AccountCandidate] = {}
    for root in roots:
        for db_storage in _bounded_db_storage_candidates(Path(root).resolve()):
            resolved = db_storage.resolve()
            if resolved in found:
                continue
            message_dir = resolved / "message"
            found[resolved] = AccountCandidate(
                account_id=resolved.parent.name,
                db_storage=resolved,
                weixin_version=weixin_version,
                has_contact_db=(resolved / "contact" / "contact.db").is_file(),
                has_session_db=(resolved / "session" / "session.db").is_file(),
                has_message_db=any(message_dir.glob("message_*.db"))
                if message_dir.is_dir()
                else False,
                process_count=process_count,
            )
    return sorted(found.values(), key=lambda item: (item.account_id, str(item.db_storage)))


def authorize_account(
    candidates: Iterable[AccountCandidate], account_id: str
) -> AccountCandidate:
    matches = [item for item in candidates if item.account_id == account_id]
    if not matches:
        raise ValueError("authorized account was not explicitly discovered")
    if len(matches) != 1:
        raise ValueError("authorized account identifier is not unique")
    return matches[0]


class _VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


def get_file_version(path: str) -> str:
    if os.name != "nt":
        return ""
    version = ctypes.WinDLL("version", use_last_error=True)
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ""
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return ""
    pointer = ctypes.c_void_p()
    length = wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return ""
    info = ctypes.cast(pointer, ctypes.POINTER(_VS_FIXEDFILEINFO)).contents
    return ".".join(
        str(value)
        for value in (
            info.dwFileVersionMS >> 16,
            info.dwFileVersionMS & 0xFFFF,
            info.dwFileVersionLS >> 16,
            info.dwFileVersionLS & 0xFFFF,
        )
    )

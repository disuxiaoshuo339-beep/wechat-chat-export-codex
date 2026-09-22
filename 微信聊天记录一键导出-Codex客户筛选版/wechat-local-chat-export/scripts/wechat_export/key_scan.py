from __future__ import annotations

import ctypes
import logging
import os
import re
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Callable, Iterable, Iterator


LOGGER = logging.getLogger(__name__)
_CANDIDATE_RE = re.compile(rb"[xX]'([0-9a-fA-F]{96}|[0-9a-fA-F]{64})'")
_WIDE_CANDIDATE_RE = re.compile(
    rb"[xX]\x00'\x00((?:[0-9a-fA-F]\x00){96}|(?:[0-9a-fA-F]\x00){64})'\x00"
)
_UNWRAPPED_ASCII_RE = re.compile(
    rb"(?<![0-9a-fA-F])([0-9a-fA-F]{96}|[0-9a-fA-F]{64})(?![0-9a-fA-F])"
)
_UNWRAPPED_WIDE_RE = re.compile(
    rb"(?<![0-9a-fA-F]\x00)((?:[0-9a-fA-F]\x00){96}|(?:[0-9a-fA-F]\x00){64})(?![0-9a-fA-F]\x00)"
)
# 按可执行文件名匹配，不锁死安装路径。
# 避免将安装路径绑定到某一台机器，支持用户自定义微信安装位置。
# 仍然只认主进程 Weixin.exe，排除 WeChatAppEx.exe 等子进程。
_AUTHORIZED_EXE_NAME = "weixin.exe"

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    path: str


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def extract_candidates(blob: bytes) -> list[bytes]:
    found: list[bytes] = []
    seen: set[bytes] = set()
    for match in _CANDIDATE_RE.finditer(blob):
        candidate = bytes.fromhex(match.group(1).decode("ascii"))
        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    for match in _WIDE_CANDIDATE_RE.finditer(blob):
        hex_bytes = match.group(1).replace(b"\x00", b"")
        candidate = bytes.fromhex(hex_bytes.decode("ascii"))
        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    for match in _UNWRAPPED_ASCII_RE.finditer(blob):
        candidate = bytes.fromhex(match.group(1).decode("ascii"))
        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    for match in _UNWRAPPED_WIDE_RE.finditer(blob):
        hex_bytes = match.group(1).replace(b"\x00", b"")
        candidate = bytes.fromhex(hex_bytes.decode("ascii"))
        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    LOGGER.info("candidate_count=%d", len(found))
    return found


def is_authorized_process(path: str) -> bool:
    if not path:
        return False
    return PureWindowsPath(path).name.casefold() == _AUTHORIZED_EXE_NAME


def find_valid_candidate(
    candidates: Iterable[bytes],
    first_pages: Iterable[bytes],
    validator: Callable[[bytes, bytes], bool],
) -> bytes | None:
    pages = tuple(first_pages)
    for candidate in candidates:
        if any(validator(page, candidate) for page in pages):
            return candidate
    return None


def find_valid_key_near_markers(
    blob: bytes,
    first_pages: Iterable[bytes],
    validator: Callable[[bytes, bytes], bool],
    radius: int = 4096,
) -> bytes | None:
    if radius < 32:
        raise ValueError("radius must be at least 32 bytes")
    tested: set[bytes] = set()
    for page in first_pages:
        marker = page[:16]
        position = blob.find(marker)
        while position >= 0:
            start = max(0, position - radius)
            end = min(len(blob) - 32, position + len(marker) + radius)
            for offset in range(start, end + 1):
                candidate = blob[offset : offset + 32]
                if candidate in tested:
                    continue
                tested.add(candidate)
                if validator(page, candidate):
                    return candidate
            position = blob.find(marker, position + 1)
    return None


def _kernel32():
    if os.name != "nt":
        raise OSError("Windows is required")
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _query_process_path(handle: int) -> str | None:
    kernel32 = _kernel32()
    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
    return buffer.value if ok else None


def enumerate_authorized_weixin_processes() -> list[ProcessInfo]:
    kernel32 = _kernel32()
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    capacity = 4096
    pids = (wintypes.DWORD * capacity)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    result: list[ProcessInfo] = []
    for pid in pids[: needed.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        try:
            path = _query_process_path(handle)
            if path and is_authorized_process(path):
                result.append(ProcessInfo(pid=int(pid), path=path))
        finally:
            kernel32.CloseHandle(handle)
    return result


def iter_readable_regions(handle: int) -> Iterator[tuple[int, int]]:
    kernel32 = _kernel32()
    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    max_address = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8 - 1)) - 1
    while address < max_address:
        queried = kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
        )
        if not queried:
            break
        base = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize)
        if mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
            yield base, size
        next_address = base + max(size, 1)
        if next_address <= address:
            break
        address = next_address


def scan_process(pid: int, chunk_size: int = 4 * 1024 * 1024) -> Iterator[bytes]:
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    seen: set[bytes] = set()
    regions = 0
    try:
        for base, size in iter_readable_regions(handle):
            regions += 1
            offset = 0
            carry = b""
            while offset < size:
                requested = min(chunk_size, size - offset)
                buffer = ctypes.create_string_buffer(requested)
                read = ctypes.c_size_t()
                ok = kernel32.ReadProcessMemory(
                    handle,
                    ctypes.c_void_p(base + offset),
                    buffer,
                    requested,
                    ctypes.byref(read),
                )
                if ok and read.value:
                    data = carry + buffer.raw[: read.value]
                    for candidate in extract_candidates(data):
                        if candidate not in seen:
                            seen.add(candidate)
                            yield candidate
                    carry = data[-110:]
                else:
                    carry = b""
                offset += requested
    finally:
        kernel32.CloseHandle(handle)
        LOGGER.info("pid=%d regions=%d unique_candidates=%d", pid, regions, len(seen))

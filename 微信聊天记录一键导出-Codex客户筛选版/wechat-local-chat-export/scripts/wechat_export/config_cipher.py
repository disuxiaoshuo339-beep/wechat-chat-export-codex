from __future__ import annotations

import hashlib
import ctypes
import os
import re
import struct
from pathlib import Path
from typing import Callable, Hashable, Iterable

from .key_scan import (
    PROCESS_QUERY_INFORMATION,
    PROCESS_VM_READ,
    ProcessInfo,
    enumerate_authorized_weixin_processes,
    iter_readable_regions,
)
from .sqlcipher import validate_key


CONFIG_CIPHER_NAME = b"com.Tencent.WCDB.Config.Cipher"
CONFIG_XOR_MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b"
    "450048844c2448488944254048584c24"
)
HEX_LITERAL_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")


def _zero_secret(secret: bytearray) -> None:
    for index in range(len(secret)):
        secret[index] = 0


def decode_config_blob(blob: bytes) -> list[bytearray]:
    decoded = bytes(
        value ^ CONFIG_XOR_MASK[index % len(CONFIG_XOR_MASK)]
        for index, value in enumerate(blob)
    )
    candidates: list[bytearray] = []
    seen: set[bytes] = set()
    for match in HEX_LITERAL_RE.finditer(decoded):
        run = match.group(1)
        starts = [0]
        if len(run) > 96:
            starts.extend(range(0, len(run) - 63, 32))
            starts.append(len(run) - 64)
        for start in dict.fromkeys(starts):
            if start + 64 > len(run):
                continue
            candidate = bytearray(bytes.fromhex(run[start : start + 64].decode("ascii")))
            digest = hashlib.sha256(candidate).digest()
            if digest in seen:
                _zero_secret(candidate)
                continue
            seen.add(digest)
            candidates.append(candidate)
    return candidates


def match_candidates_to_pages(
    candidates: Iterable[bytearray],
    pages: Iterable[tuple[Hashable, bytes]],
) -> dict[Hashable, bytearray]:
    page_list = list(pages)
    matched: dict[Hashable, bytearray] = {}
    for candidate in candidates:
        try:
            for identity, page in page_list:
                if identity not in matched and validate_key(page, candidate):
                    matched[identity] = bytearray(candidate)
        finally:
            _zero_secret(candidate)
    return matched


def _kernel32():
    if os.name != "nt":
        raise OSError("Windows is required")
    return ctypes.WinDLL("kernel32", use_last_error=True)


def extract_config_cipher_candidates_from_process(pid: int) -> list[bytearray]:
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
    )
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        def read(address: int, count: int) -> bytes | None:
            buffer = ctypes.create_string_buffer(count)
            got = ctypes.c_size_t()
            ok = kernel32.ReadProcessMemory(
                handle,
                ctypes.c_void_p(address),
                buffer,
                count,
                ctypes.byref(got),
            )
            return buffer.raw if ok and got.value == count else None

        def find_bytes(needle: bytes) -> list[int]:
            hits: list[int] = []
            for base, size in iter_readable_regions(handle):
                if not 0 < size < 0x10000000:
                    continue
                data = read(base, size)
                if data is None:
                    continue
                position = 0
                while True:
                    position = data.find(needle, position)
                    if position < 0:
                        break
                    hits.append(base + position)
                    position += 1
            return hits

        candidates: list[bytearray] = []
        seen: set[bytes] = set()
        markers = find_bytes(CONFIG_CIPHER_NAME)
        for marker in markers:
            pair = struct.pack("<Q", marker) + struct.pack(
                "<Q", len(CONFIG_CIPHER_NAME)
            )
            for qaddr in find_bytes(pair):
                node = read(qaddr - 0x10, 0x50)
                if node is None or len(node) < 0x40:
                    continue
                if struct.unpack_from("<Q", node, 0x10)[0] != marker:
                    continue
                if struct.unpack_from("<Q", node, 0x18)[0] != len(
                    CONFIG_CIPHER_NAME
                ):
                    continue
                config_pointer = struct.unpack_from("<Q", node, 0x28)[0]
                if not 0x10000 <= config_pointer < 0x800000000000:
                    continue
                obj = read(config_pointer + 0x88, 0x28)
                if obj is None or len(obj) < 0x18:
                    continue
                data_pointer = struct.unpack_from("<Q", obj, 0x8)[0]
                data_length = struct.unpack_from("<Q", obj, 0x10)[0]
                if not (
                    0 < data_length <= 1024
                    and 0x10000 <= data_pointer < 0x800000000000
                ):
                    continue
                blob = read(data_pointer, int(data_length))
                if blob is None:
                    continue
                for candidate in decode_config_blob(blob):
                    digest = hashlib.sha256(candidate).digest()
                    if digest in seen:
                        _zero_secret(candidate)
                        continue
                    seen.add(digest)
                    candidates.append(candidate)
        return candidates
    finally:
        kernel32.CloseHandle(handle)


def _load_database_pages(db_root: Path) -> list[tuple[Path, bytes]]:
    pages: list[tuple[Path, bytes]] = []
    for path in sorted(db_root.rglob("*.db")):
        try:
            if not path.is_file() or path.stat().st_size < 4096:
                continue
            with path.open("rb") as source:
                page = source.read(4096)
        except OSError:
            continue
        if len(page) == 4096:
            pages.append((path, page))
    return pages


def extract_database_keys(
    db_root: Path,
    process_provider: Callable[
        [], Iterable[ProcessInfo]
    ] = enumerate_authorized_weixin_processes,
    candidate_extractor: Callable[
        [int], list[bytearray]
    ] = extract_config_cipher_candidates_from_process,
) -> dict[Path, bytearray]:
    pages = _load_database_pages(db_root)
    matched: dict[Path, bytearray] = {}
    for process in process_provider():
        try:
            candidates = candidate_extractor(process.pid)
        except OSError:
            continue
        newly_matched = match_candidates_to_pages(candidates, pages)
        for path, secret in newly_matched.items():
            if path in matched:
                _zero_secret(secret)
            else:
                matched[path] = secret
        if len(matched) == len(pages):
            break
    return matched

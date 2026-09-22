from __future__ import annotations

import os
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

from .sqlcipher import DEFAULT, CipherParams, decrypt_page, validate_page_hmac


WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24
WAL_MAGICS = {0x377F0682, 0x377F0683}


@dataclass(frozen=True)
class WalFrame:
    page_no: int
    database_pages_after_commit: int
    encrypted_page: bytes


@dataclass(frozen=True)
class ParsedWal:
    frames: tuple[WalFrame, ...]
    final_page_count: int
    ignored_frames: int


@dataclass(frozen=True)
class WalApplyResult:
    applied_frames: int
    final_page_count: int
    ignored_frames: int


def parse_committed_frames(blob: bytes) -> ParsedWal:
    if len(blob) < WAL_HEADER_SIZE:
        raise ValueError("WAL is shorter than its header")
    magic = struct.unpack(">I", blob[:4])[0]
    if magic not in WAL_MAGICS:
        raise ValueError("unrecognized WAL magic")
    page_size = struct.unpack(">I", blob[8:12])[0]
    if page_size == 1:
        page_size = 65536
    if page_size <= 0:
        raise ValueError("invalid WAL page size")
    wal_salt = blob[16:24]
    frame_size = WAL_FRAME_HEADER_SIZE + page_size
    complete_frames = (len(blob) - WAL_HEADER_SIZE) // frame_size
    matching: list[WalFrame] = []
    for index in range(complete_frames):
        offset = WAL_HEADER_SIZE + index * frame_size
        header = blob[offset : offset + WAL_FRAME_HEADER_SIZE]
        page_no, commit_pages = struct.unpack(">II", header[:8])
        if page_no == 0:
            continue
        if header[8:16] != wal_salt:
            continue
        page_start = offset + WAL_FRAME_HEADER_SIZE
        matching.append(
            WalFrame(
                page_no=page_no,
                database_pages_after_commit=commit_pages,
                encrypted_page=blob[page_start : page_start + page_size],
            )
        )

    last_commit_index = -1
    final_page_count = 0
    for index, frame in enumerate(matching):
        if frame.database_pages_after_commit:
            last_commit_index = index
            final_page_count = frame.database_pages_after_commit
    committed = tuple(matching[: last_commit_index + 1])
    return ParsedWal(
        frames=committed,
        final_page_count=final_page_count,
        ignored_frames=complete_frames - len(committed),
    )


def apply_encrypted_wal(
    database: Path,
    wal_path: Path,
    key: bytes,
    database_salt: bytes,
    params: CipherParams = DEFAULT,
) -> WalApplyResult:
    parsed = parse_committed_frames(wal_path.read_bytes())
    if not parsed.frames:
        return WalApplyResult(
            applied_frames=0,
            final_page_count=0,
            ignored_frames=parsed.ignored_frames,
        )
    if any(len(frame.encrypted_page) != params.page_size for frame in parsed.frames):
        raise ValueError("WAL page size does not match cipher page size")

    decrypted: list[tuple[int, bytes]] = []
    for frame in parsed.frames:
        if not validate_page_hmac(
            frame.encrypted_page, key, database_salt, frame.page_no, params
        ):
            raise ValueError(f"WAL page HMAC validation failed at page {frame.page_no}")
        decrypted.append(
            (frame.page_no, decrypt_page(frame.encrypted_page, key, frame.page_no, params))
        )

    partial = database.with_name(database.name + ".walmerge.partial")
    if partial.exists():
        raise FileExistsError(f"partial WAL merge already exists: {partial}")
    shutil.copyfile(database, partial)
    with partial.open("r+b") as handle:
        for page_no, clear_page in decrypted:
            handle.seek((page_no - 1) * params.page_size)
            handle.write(clear_page)
        handle.truncate(parsed.final_page_count * params.page_size)
    os.replace(partial, database)
    return WalApplyResult(
        applied_frames=len(decrypted),
        final_page_count=parsed.final_page_count,
        ignored_frames=parsed.ignored_frames,
    )

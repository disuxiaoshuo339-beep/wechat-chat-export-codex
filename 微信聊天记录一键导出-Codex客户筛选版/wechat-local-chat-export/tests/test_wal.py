from __future__ import annotations

import hashlib
import hmac
import struct

from Cryptodome.Cipher import AES

from wechat_export.wal import apply_encrypted_wal, parse_committed_frames


PAGE_SIZE = 4096


def _encrypted_page(clear: bytes, key: bytes, salt: bytes, page_no: int) -> bytes:
    iv = bytes((page_no + index) % 256 for index in range(16))
    encrypted_start = 16 if page_no == 1 else 0
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(
        clear[encrypted_start:4016]
    )
    page = bytearray(PAGE_SIZE)
    if page_no == 1:
        page[:16] = salt
        page[16:4016] = ciphertext
    else:
        page[:4016] = ciphertext
    page[4016:4032] = iv
    hmac_salt = bytes(value ^ 0x3A for value in salt)
    hmac_key = hashlib.pbkdf2_hmac("sha512", key, hmac_salt, 2, dklen=32)
    start = 16 if page_no == 1 else 0
    signature = hmac.new(
        hmac_key,
        bytes(page[start:4032]) + struct.pack("<I", page_no),
        hashlib.sha512,
    ).digest()
    page[4032:] = signature
    return bytes(page)


def _wal(frames: list[tuple[int, int, bytes, bytes]], salt: bytes) -> bytes:
    header = bytearray(32)
    header[:4] = b"7\x7f\x06\x82"
    header[8:12] = struct.pack(">I", PAGE_SIZE)
    header[16:24] = salt
    output = bytearray(header)
    for page_no, commit_pages, frame_salt, page in frames:
        frame_header = bytearray(24)
        frame_header[:4] = struct.pack(">I", page_no)
        frame_header[4:8] = struct.pack(">I", commit_pages)
        frame_header[8:16] = frame_salt
        output.extend(frame_header)
        output.extend(page)
    return bytes(output)


def test_parser_uses_current_salt_and_stops_at_last_commit():
    salt = b"current!"
    other = b"old-salt"
    page = bytes(PAGE_SIZE)
    blob = _wal(
        [
            (2, 0, salt, page),
            (3, 3, salt, page),
            (4, 0, salt, page),
            (5, 5, other, page),
        ],
        salt,
    )

    parsed = parse_committed_frames(blob)

    assert [frame.page_no for frame in parsed.frames] == [2, 3]
    assert parsed.final_page_count == 3
    assert parsed.ignored_frames == 2


def test_apply_encrypted_wal_decrypts_committed_pages_and_truncates(tmp_path):
    key = bytes(range(32))
    database_salt = bytes(range(16, 32))
    wal_salt = b"wal-salt"
    clear_page = bytes([91]) * 4016 + bytes(80)
    encrypted = _encrypted_page(clear_page, key, database_salt, page_no=2)
    wal_path = tmp_path / "sample.db-wal"
    wal_path.write_bytes(_wal([(2, 2, wal_salt, encrypted)], wal_salt))
    database = tmp_path / "sample.db"
    database.write_bytes(bytes(PAGE_SIZE * 4))

    result = apply_encrypted_wal(database, wal_path, key, database_salt)

    merged = database.read_bytes()
    assert result.applied_frames == 1
    assert result.final_page_count == 2
    assert len(merged) == PAGE_SIZE * 2
    assert merged[PAGE_SIZE : PAGE_SIZE + 4016] == bytes([91]) * 4016
    assert merged[PAGE_SIZE + 4016 : PAGE_SIZE * 2] == bytes(80)


def test_apply_rejects_a_frame_with_invalid_page_hmac(tmp_path):
    key = bytes(range(32))
    database_salt = bytes(range(16, 32))
    wal_salt = b"wal-salt"
    invalid = bytes(PAGE_SIZE)
    wal_path = tmp_path / "sample.db-wal"
    wal_path.write_bytes(_wal([(2, 2, wal_salt, invalid)], wal_salt))
    database = tmp_path / "sample.db"
    database.write_bytes(bytes(PAGE_SIZE * 2))

    try:
        apply_encrypted_wal(database, wal_path, key, database_salt)
    except ValueError as exc:
        assert "HMAC" in str(exc)
    else:
        raise AssertionError("invalid WAL page HMAC was accepted")

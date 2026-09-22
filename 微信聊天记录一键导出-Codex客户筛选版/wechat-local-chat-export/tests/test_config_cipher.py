from __future__ import annotations

import hashlib
import hmac
import struct

from Cryptodome.Cipher import AES

from wechat_export.config_cipher import (
    CONFIG_XOR_MASK,
    decode_config_blob,
    extract_database_keys,
    match_candidates_to_pages,
)
from wechat_export.key_scan import ProcessInfo


def _make_first_page(key: bytes, salt: bytes) -> bytes:
    iv = bytes(range(32, 48))
    clear = bytearray(4096)
    clear[:16] = b"SQLite format 3\x00"
    clear[20] = 80
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(bytes(clear[16:4016]))
    hmac_salt = bytes(value ^ 0x3A for value in salt)
    hmac_key = hashlib.pbkdf2_hmac("sha512", key, hmac_salt, 2, dklen=32)
    signature = hmac.new(
        hmac_key, ciphertext + iv + struct.pack("<I", 1), hashlib.sha512
    ).digest()
    return salt + ciphertext + iv + signature


def _encode_blob(clear: bytes) -> bytes:
    return bytes(
        value ^ CONFIG_XOR_MASK[index % len(CONFIG_XOR_MASK)]
        for index, value in enumerate(clear)
    )


def test_decodes_config_cipher_blob_without_returning_text_literals():
    expected = bytes(range(32))
    clear = b"prefix x'" + expected.hex().encode("ascii") + b"' suffix"

    candidates = decode_config_blob(_encode_blob(clear))

    assert [bytes(candidate) for candidate in candidates] == [expected]


def test_matches_each_candidate_to_its_database_and_zeroes_unmatched():
    key_a = bytearray(range(32))
    key_b = bytearray(reversed(range(32)))
    unmatched = bytearray(b"u" * 32)
    pages = [
        ("a.db", _make_first_page(bytes(key_a), bytes(range(16, 32)))),
        ("b.db", _make_first_page(bytes(key_b), bytes(range(48, 64)))),
    ]

    matched = match_candidates_to_pages([unmatched, key_b, key_a], pages)

    assert set(matched) == {"a.db", "b.db"}
    assert bytes(matched["a.db"]) == bytes(range(32))
    assert bytes(matched["b.db"]) == bytes(reversed(range(32)))
    assert unmatched == bytearray(32)


def test_extract_database_keys_uses_injected_read_only_process_boundary(tmp_path):
    candidate = bytearray(range(32))
    salt = bytes(range(16, 32))
    db = tmp_path / "contact" / "contact.db"
    db.parent.mkdir()
    db.write_bytes(_make_first_page(bytes(candidate), salt))

    matched = extract_database_keys(
        tmp_path,
        process_provider=lambda: [ProcessInfo(123, r"C:\Program Files\Tencent\Weixin\Weixin.exe")],
        candidate_extractor=lambda pid: [candidate],
    )

    assert list(matched) == [db]
    assert bytes(matched[db]) == bytes(range(32))
    assert candidate == bytearray(32)

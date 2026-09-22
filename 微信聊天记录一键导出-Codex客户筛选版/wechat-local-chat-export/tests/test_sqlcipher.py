from __future__ import annotations

import hashlib
import hmac
import struct
import sqlite3

import pytest
from Cryptodome.Cipher import AES

from wechat_export.sqlcipher import decrypt_page, validate_key, verify_sqlite


@pytest.fixture
def encrypted_page_fixture():
    key = bytes(range(32))
    salt = bytes(range(16, 32))
    iv = bytes(range(32, 48))
    clear = bytearray(4096)
    clear[:16] = b"SQLite format 3\x00"
    clear[16:24] = b"fixture!"
    clear[20] = 80
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(bytes(clear[16:4016]))
    hmac_salt = bytes(value ^ 0x3A for value in salt)
    hmac_key = hashlib.pbkdf2_hmac("sha512", key, hmac_salt, 2, dklen=32)
    signature = hmac.new(hmac_key, ciphertext + iv + struct.pack("<I", 1), hashlib.sha512).digest()
    return salt + ciphertext + iv + signature, key


def test_validates_correct_key_and_rejects_wrong_key(encrypted_page_fixture):
    page, key = encrypted_page_fixture

    assert validate_key(page, key)
    assert not validate_key(page, b"x" * 32)


def test_decrypted_first_page_keeps_sqlcipher_reserved_byte_count(encrypted_page_fixture):
    page, key = encrypted_page_fixture

    clear = decrypt_page(page, key, page_no=1)

    assert clear.startswith(b"SQLite format 3\x00")
    assert len(clear) == 4096
    assert clear[20] == 80
    assert clear[-80:] == bytes(80)


def test_verify_sqlite_releases_file_for_atomic_rename(tmp_path):
    source = tmp_path / "verified.db"
    destination = tmp_path / "renamed.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE sample(value TEXT)")
    connection.close()

    result = verify_sqlite(source)
    source.replace(destination)

    assert result.ok
    assert destination.exists()

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

from Cryptodome.Cipher import AES


SQLITE_HEADER = b"SQLite format 3\x00"


@dataclass(frozen=True)
class CipherParams:
    page_size: int = 4096
    reserved_bytes: int = 80
    iv_size: int = 16
    hmac_size: int = 64
    hmac_salt_mask: int = 0x3A
    fast_kdf_iter: int = 2


@dataclass(frozen=True)
class IntegrityResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class DecryptResult:
    destination: Path
    pages: int
    integrity: IntegrityResult


DEFAULT = CipherParams()


def _raw_key(candidate: bytes) -> bytes:
    if len(candidate) == 48:
        candidate = candidate[:32]
    if len(candidate) != 32:
        raise ValueError("raw SQLCipher key must be 32 or 48 bytes")
    return candidate


def _hmac_key(key: bytes, salt: bytes, params: CipherParams) -> bytes:
    hmac_salt = bytes(value ^ params.hmac_salt_mask for value in salt)
    return hashlib.pbkdf2_hmac(
        "sha512", _raw_key(key), hmac_salt, params.fast_kdf_iter, dklen=32
    )


def _hmac_input(page: bytes, page_no: int, params: CipherParams) -> bytes:
    authenticated_end = params.page_size - params.reserved_bytes + params.iv_size
    start = 16 if page_no == 1 else 0
    return page[start:authenticated_end] + struct.pack("<I", page_no)


def validate_key(
    first_page: bytes, key: bytes, params: CipherParams = DEFAULT
) -> bool:
    if len(first_page) != params.page_size:
        return False
    salt = first_page[:16]
    calculated = hmac.new(
        _hmac_key(key, salt, params),
        _hmac_input(first_page, 1, params),
        hashlib.sha512,
    ).digest()
    expected_start = params.page_size - params.hmac_size
    return hmac.compare_digest(calculated, first_page[expected_start:])


def validate_page_hmac(
    page: bytes, key: bytes, salt: bytes, page_no: int, params: CipherParams = DEFAULT
) -> bool:
    calculated = hmac.new(
        _hmac_key(key, salt, params),
        _hmac_input(page, page_no, params),
        hashlib.sha512,
    ).digest()
    return hmac.compare_digest(calculated, page[-params.hmac_size :])


def decrypt_page(
    page: bytes, key: bytes, page_no: int, params: CipherParams = DEFAULT
) -> bytes:
    if len(page) != params.page_size:
        raise ValueError("encrypted page has unexpected size")
    encrypted_start = 16 if page_no == 1 else 0
    encrypted_end = params.page_size - params.reserved_bytes
    iv_start = encrypted_end
    iv = page[iv_start : iv_start + params.iv_size]
    ciphertext = page[encrypted_start:encrypted_end]
    plaintext = AES.new(_raw_key(key), AES.MODE_CBC, iv).decrypt(ciphertext)
    output = bytearray(params.page_size)
    if page_no == 1:
        output[:16] = SQLITE_HEADER
        output[16 : 16 + len(plaintext)] = plaintext
        output[20] = params.reserved_bytes
    else:
        output[: len(plaintext)] = plaintext
    return bytes(output)


def verify_sqlite(path: Path) -> IntegrityResult:
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
        detail = str(row[0]) if row else "no quick_check result"
        return IntegrityResult(ok=detail == "ok", detail=detail)
    except sqlite3.Error as exc:
        return IntegrityResult(ok=False, detail=f"{type(exc).__name__}: {exc}")


def decrypt_database(
    source: Path, destination: Path, key: bytes, params: CipherParams = DEFAULT
) -> DecryptResult:
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    partial = destination.with_name(destination.name + ".partial")
    if partial.exists():
        raise FileExistsError(f"partial destination already exists: {partial}")
    size = source.stat().st_size
    if size == 0 or size % params.page_size:
        raise ValueError("database size is not a positive page multiple")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as encrypted, partial.open("xb") as clear:
        first_page = encrypted.read(params.page_size)
        salt = first_page[:16]
        if not validate_key(first_page, key, params):
            raise ValueError("key does not validate against first page")
        clear.write(decrypt_page(first_page, key, 1, params))
        page_no = 1
        while True:
            page = encrypted.read(params.page_size)
            if not page:
                break
            page_no += 1
            if not validate_page_hmac(page, key, salt, page_no, params):
                raise ValueError(f"page HMAC validation failed at page {page_no}")
            clear.write(decrypt_page(page, key, page_no, params))
    integrity = verify_sqlite(partial)
    if not integrity.ok:
        raise ValueError(f"SQLite integrity validation failed: {integrity.detail}")
    os.replace(partial, destination)
    return DecryptResult(destination=destination, pages=page_no, integrity=integrity)

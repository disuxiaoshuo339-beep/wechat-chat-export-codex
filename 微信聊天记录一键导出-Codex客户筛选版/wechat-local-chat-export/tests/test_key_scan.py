from __future__ import annotations

import logging

from wechat_export.key_scan import (
    extract_candidates,
    find_valid_candidate,
    find_valid_key_near_markers,
    is_authorized_process,
)


def test_extracts_64_and_96_hex_candidates_without_logging_values(caplog):
    blob = b"noise x'" + b"a" * 64 + b"' more x'" + b"b" * 96 + b"'"

    with caplog.at_level(logging.INFO):
        result = extract_candidates(blob)

    assert [len(item) for item in result] == [32, 48]
    assert "aaaa" not in caplog.text
    assert "bbbb" not in caplog.text


def test_extracts_utf16le_raw_key_expression():
    expression = ("x'" + "c" * 96 + "'").encode("utf-16le")

    result = extract_candidates(b"prefix" + expression + b"suffix")

    assert result == [bytes.fromhex("c" * 96)]


def test_extracts_unwrapped_hex_candidate_with_boundaries():
    expression = b"-" + b"d" * 64 + b":"

    result = extract_candidates(expression)

    assert result == [bytes.fromhex("d" * 64)]


def test_only_accepts_authorized_weixin_executable():
    assert is_authorized_process(r"C:\Program Files\Tencent\Weixin\Weixin.exe")
    assert not is_authorized_process(r"C:\Program Files\Tencent\Weixin\WeChatAppEx.exe")
    assert not is_authorized_process(r"C:\Windows\notepad.exe")


def test_returns_only_candidate_that_validates_against_a_database_page():
    expected = b"k" * 32
    candidates = [b"x" * 32, expected, b"y" * 32]

    result = find_valid_candidate(candidates, [b"page"], lambda page, key: key == expected)

    assert result == expected


def test_finds_raw_key_near_database_salt_marker():
    marker = b"s" * 16
    page = marker + b"page"
    expected = bytes(range(32))
    blob = b"noise" * 20 + marker + b"padding" + expected + b"tail"

    result = find_valid_key_near_markers(
        blob,
        [page],
        lambda candidate_page, key: candidate_page == page and key == expected,
        radius=64,
    )

    assert result == expected

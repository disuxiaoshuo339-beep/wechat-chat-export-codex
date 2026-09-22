from __future__ import annotations

# 用 messages.py 自带的兼容层，而不是直接 import compression.zstd —
# 后者只有 Python 3.14+ 才有，3.11-3.13 上会让整个测试模块收集失败。
from wechat_export.messages import zstd

from wechat_export.messages import (
    decode_message_content,
    direction_for_private_chat,
    message_type_parts,
    summarize_content,
)


def test_message_type_parts_splits_packed_app_subtype():
    assert message_type_parts(0x2100000031) == (49, 33)
    assert message_type_parts(1) == (1, 0)


def test_decode_message_content_supports_zstd():
    payload = zstd.compress("客户说：好的".encode("utf-8"))

    assert decode_message_content(payload) == "客户说：好的"


def test_decode_message_content_recovers_container_text():
    payload = b"\x28\xb5\x2f\xfd\x00\x00\x00\x00\x00\x00" + "Hello 客户".encode() + b"\x01\x00padding"

    assert decode_message_content(payload) == "Hello 客户"


def test_private_direction_uses_resolved_sender_then_status_fallback():
    assert direction_for_private_chat("wxid_customer", "wxid_customer", 3) == "客户"
    assert direction_for_private_chat("wxid_customer", "wxid_self", 2) == "我"
    assert direction_for_private_chat("wxid_customer", None, 4) == "客户"


def test_structured_message_summary_keeps_useful_fields():
    xml = "<msg><appmsg><title>报价单</title><des>请查收</des><url>https://example.test/x</url></appmsg></msg>"

    label, summary = summarize_content(0x500000031, xml)

    assert label == "链接/卡片"
    assert "报价单" in summary
    assert "请查收" in summary
    assert "https://example.test/x" in summary


def test_missing_media_content_gets_an_explicit_placeholder():
    assert summarize_content(3, None) == ("图片", "[图片]")

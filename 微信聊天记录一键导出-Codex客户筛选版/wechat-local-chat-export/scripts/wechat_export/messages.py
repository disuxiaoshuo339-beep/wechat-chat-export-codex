from __future__ import annotations

import re
import xml.etree.ElementTree as ET

try:
    from compression import zstd
except ImportError:  # Python 3.10-3.13 portability path
    import zstandard as _zstandard

    class _CompatZstd:
        ZstdError = _zstandard.ZstdError

        @staticmethod
        def compress(payload: bytes) -> bytes:
            return _zstandard.ZstdCompressor().compress(payload)

        @staticmethod
        def decompress(payload: bytes) -> bytes:
            return _zstandard.ZstdDecompressor().decompress(payload)

    zstd = _CompatZstd()


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

BASE_TYPE_LABELS = {
    1: "文本",
    3: "图片",
    34: "语音",
    42: "名片",
    43: "视频",
    47: "动画表情",
    48: "位置",
    49: "链接/卡片",
    50: "通话",
    66: "企业微信消息",
    10000: "系统提示",
}

APP_SUBTYPE_LABELS = {
    1: "应用消息",
    4: "视频链接",
    5: "链接/卡片",
    6: "文件",
    8: "应用消息",
    19: "合并转发",
    24: "笔记",
    33: "小程序",
    36: "小程序",
    50: "视频号",
    51: "视频号",
    57: "引用回复",
    62: "视频号",
    63: "视频号直播",
    87: "群公告",
    2000: "转账",
    2001: "红包",
}


def message_type_parts(local_type: int | None) -> tuple[int, int]:
    value = int(local_type or 0)
    return value & 0xFFFFFFFF, value >> 32


def _clean_decoded(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip("\x00\ufeff \t\n")
    return text


def _container_text(content: bytes) -> str | None:
    offsets = [10] + [value for value in range(min(16, len(content))) if value != 10]
    for offset in offsets:
        chunk = content[offset:]
        if b"\x01\x00" in chunk:
            chunk = chunk.split(b"\x01\x00", 1)[0]
        try:
            text = _clean_decoded(chunk.decode("utf-8"))
        except UnicodeDecodeError:
            continue
        if not text:
            continue
        printable = sum(character.isprintable() or character in "\n\t" for character in text)
        if printable / len(text) >= 0.85:
            return text
    return None


def decode_message_content(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean_decoded(value)
    if isinstance(value, memoryview):
        value = value.tobytes()
    if not isinstance(value, (bytes, bytearray)):
        return _clean_decoded(str(value))
    content = bytes(value)
    if not content:
        return ""
    if content.startswith(ZSTD_MAGIC):
        try:
            return _clean_decoded(zstd.decompress(content).decode("utf-8"))
        except (zstd.ZstdError, UnicodeDecodeError):
            recovered = _container_text(content)
            if recovered:
                return recovered
    try:
        return _clean_decoded(content.decode("utf-8"))
    except UnicodeDecodeError:
        return _container_text(content) or ""


def direction_for_private_chat(
    talker: str, resolved_sender: str | None, status: int | None
) -> str:
    if resolved_sender:
        return "客户" if resolved_sender == talker else "我"
    if status in (3, 4):
        return "客户"
    if status == 2:
        return "我"
    return "未知"


def _xml_values(text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    wanted = (
        "title",
        "des",
        "filename",
        "displayname",
        "sourcedisplayname",
        "appname",
        "url",
        "content",
    )
    values: list[str] = []
    seen: set[str] = set()
    for tag in wanted:
        for node in root.iter(tag):
            value = _clean_decoded(node.text or "")
            if value and value not in seen:
                seen.add(value)
                values.append(value)
    return values


def summarize_content(local_type: int | None, value: object) -> tuple[str, str]:
    base_type, subtype = message_type_parts(local_type)
    label = (
        APP_SUBTYPE_LABELS.get(subtype, BASE_TYPE_LABELS[49])
        if base_type == 49
        else BASE_TYPE_LABELS.get(base_type, f"其他({int(local_type or 0)})")
    )
    text = decode_message_content(value)
    if base_type == 49 and text.lstrip().startswith("<"):
        values = _xml_values(text)
        if values:
            text = " | ".join(values)
    elif base_type == 48 and text.lstrip().startswith("<"):
        labels = re.findall(r'(?:label|poiname)="([^"]+)"', text)
        if labels:
            text = " | ".join(dict.fromkeys(labels))
    if not text:
        text = f"[{label}]"
    return label, text

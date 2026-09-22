from __future__ import annotations

from wechat_export.export import classify_conversation, display_name, safe_file_stem


def test_conversation_classifier_excludes_only_explicit_non_customer_accounts():
    assert classify_conversation("room@chatroom") == "group"
    assert classify_conversation("gh_example") == "public"
    assert classify_conversation("filehelper") == "system"
    assert classify_conversation("customer@openim") == "private"
    assert classify_conversation("wxid_customer") == "private"


def test_display_name_prefers_remark_then_nickname_then_alias():
    assert display_name("wxid_x", "客户备注", "昵称", "alias") == "客户备注"
    assert display_name("wxid_x", "", "昵称", "alias") == "昵称"
    assert display_name("wxid_x", None, "", "alias") == "alias"


def test_safe_file_stem_removes_windows_reserved_characters_and_is_stable():
    stem = safe_file_stem(12, '张三:采购/华东*?"<>|', "wxid_customer")

    assert stem.startswith("0012_张三_采购_华东_")
    assert not any(character in stem for character in '<>:"/\\|?*')
    assert len(stem) <= 90

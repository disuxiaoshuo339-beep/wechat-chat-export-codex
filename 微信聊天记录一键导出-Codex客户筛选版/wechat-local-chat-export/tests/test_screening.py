from __future__ import annotations

import pytest

from wechat_export.screening import guess_category, read_selection, write_screening_csv


def test_guess_category_openim_is_customer():
    assert guess_category(None, "某企业微信联系人", None, "wxid_abc@openim") == "疑似客户"


def test_guess_category_coatings_keyword_is_customer():
    assert guess_category("华东涂料采购", None, None, "wxid_a") == "疑似客户"
    assert guess_category(None, "苏州化工科技", None, "wxid_b") == "疑似客户"


def test_guess_category_phone_number_remark_is_customer():
    assert guess_category("13812345678", None, None, "wxid_c") == "疑似客户"
    assert guess_category("+86 13812345678", None, None, "wxid_d") == "疑似客户"


def test_guess_category_industry_keyword_wins_over_form():
    # 带行业词的公司-人名形态走关键词分支，直接算客户
    assert guess_category("华东化工-张三", None, None, "wxid_e") == "疑似客户"
    assert guess_category("上海贸易/李四", None, None, "wxid_f") == "疑似客户"


def test_guess_category_bare_company_person_form_is_undecided():
    # 没有行业词、只是「XX-YY」形态的，是弱信号，只能判待定，不得自动预填 Y
    assert guess_category("鼎盛-张三", None, None, "wxid_e2") == "待定"
    assert guess_category("宏远机械 李四", None, None, "wxid_f2") == "待定"


def test_guess_category_strong_private_wins_over_company_person_form():
    # 回归：亲属称谓 + 分隔符（「老公 张伟」）曾被形态规则误判为疑似客户并预填 Y
    assert guess_category("老公 张伟", None, None, "wxid_e3") == "私人"
    assert guess_category("妈妈-王芳", None, None, "wxid_e4") == "私人"
    assert guess_category("大姐 小敏", None, None, "wxid_e5") == "私人"


def test_guess_category_strong_private_keyword_is_private():
    assert guess_category("老公", None, None, "wxid_g") == "私人"
    assert guess_category(None, "我媳妇", None, "wxid_h") == "私人"


def test_guess_category_short_weak_private_keyword_is_private():
    assert guess_category("大姐", None, None, "wxid_i") == "私人"
    # 弱私人词命中但字段过长（>5）不算命中
    assert guess_category("大姐大姐大姐大姐", None, None, "wxid_j") == "待定"


def test_guess_category_falls_back_to_undecided():
    assert guess_category("阿强", "阿强", None, "wxid_k") == "待定"
    assert guess_category(None, None, None, "wxid_l") == "待定"


def test_write_screening_csv_prefills_and_counts(tmp_path):
    rows = [
        {
            "序号": 1, "显示名": "华东涂料", "备注名": "华东涂料", "昵称": "老王",
            "微信号": "wxid_a", "消息数": 10, "首条时间": "2024-01-01 00:00:00",
            "末条时间": "2024-02-01 00:00:00", "自动判定": "疑似客户",
        },
        {
            "序号": 2, "显示名": "老公", "备注名": "老公", "昵称": "老公",
            "微信号": "wxid_b", "消息数": 5, "首条时间": "2024-01-01 00:00:00",
            "末条时间": "2024-02-01 00:00:00", "自动判定": "私人",
        },
        {
            "序号": 3, "显示名": "阿强", "备注名": "阿强", "昵称": "阿强",
            "微信号": "wxid_c", "消息数": 3, "首条时间": "2024-01-01 00:00:00",
            "末条时间": "2024-02-01 00:00:00", "自动判定": "待定",
        },
    ]
    csv_path = tmp_path / "会话清单.csv"
    counts = write_screening_csv(rows, csv_path)
    assert counts == {
        "total": 3,
        "auto_customer": 1,
        "auto_private": 1,
        "auto_undecided": 1,
    }
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "疑似客户" in content and "私人" in content and "待定" in content


def test_read_selection_returns_only_rows_marked_y(tmp_path):
    csv_path = tmp_path / "会话清单.csv"
    csv_path.write_text(
        "序号,显示名,备注名,昵称,微信号,消息数,首条时间,末条时间,自动判定,是否客户\n"
        "1,华东涂料,华东涂料,老王,wxid_a,10,2024-01-01,2024-02-01,疑似客户,Y\n"
        "2,老公,老公,老公,wxid_b,5,2024-01-01,2024-02-01,私人,\n"
        "3,阿强,阿强,阿强,wxid_c,3,2024-01-01,2024-02-01,待定,?\n",
        encoding="utf-8-sig",
    )
    assert read_selection(csv_path) == {"wxid_a"}


def test_read_selection_raises_when_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_selection(tmp_path / "不存在.csv")


def test_read_selection_raises_when_nothing_selected(tmp_path):
    csv_path = tmp_path / "会话清单.csv"
    csv_path.write_text(
        "序号,显示名,备注名,昵称,微信号,消息数,首条时间,末条时间,自动判定,是否客户\n"
        "1,老公,老公,老公,wxid_b,5,2024-01-01,2024-02-01,私人,\n"
        "2,阿强,阿强,阿强,wxid_c,3,2024-01-01,2024-02-01,待定,?\n",
        encoding="utf-8-sig",
    )
    with pytest.raises(RuntimeError):
        read_selection(csv_path)


def test_read_selection_reads_gbk_saved_csv(tmp_path):
    # 中文版 Excel 的「CSV（逗号分隔）」另存为写的是 GBK，必须能读回
    csv_path = tmp_path / "会话清单.csv"
    csv_path.write_bytes(
        (
            "序号,显示名,备注名,昵称,微信号,消息数,首条时间,末条时间,自动判定,是否客户\n"
            "1,华东涂料,华东涂料,老王,wxid_a,10,2024-01-01,2024-02-01,疑似客户,Y\n"
            "2,老妈,老妈,老妈,wxid_b,5,2024-01-01,2024-02-01,私人,\n"
        ).encode("gbk")
    )
    assert read_selection(csv_path) == {"wxid_a"}


def test_read_selection_accepts_chinese_yes_marker(tmp_path):
    csv_path = tmp_path / "会话清单.csv"
    csv_path.write_text(
        "序号,显示名,备注名,昵称,微信号,消息数,首条时间,末条时间,自动判定,是否客户\n"
        "1,华东涂料,华东涂料,老王,wxid_a,10,2024-01-01,2024-02-01,疑似客户,是\n"
        "2,阿强,阿强,阿强,wxid_c,3,2024-01-01,2024-02-01,待定,?\n",
        encoding="utf-8-sig",
    )
    assert read_selection(csv_path) == {"wxid_a"}

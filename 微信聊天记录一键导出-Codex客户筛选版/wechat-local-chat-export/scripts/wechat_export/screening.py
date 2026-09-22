from __future__ import annotations

import csv
import re
from pathlib import Path


CUSTOMER_KEYWORDS = [
    "涂料", "油漆", "涂装", "化工", "化学", "树脂", "乳液", "助剂", "色浆", "颜料",
    "钛白", "填料", "分散剂", "消泡剂", "流平剂", "增稠剂", "固化剂", "稀释剂",
    "溶剂", "粉末", "水性", "油性", "环氧", "聚氨酯", "丙烯酸", "醇酸", "氟碳",
    "防腐", "防锈", "木器", "工业漆", "建筑漆", "汽车漆", "卷材", "胶粘", "油墨",
    "材料", "新材", "科技", "实业", "集团", "有限公司", "供应链", "商贸", "贸易",
    "采购", "销售", "经理", "工程师", "业务", "厂", "公司", "UV",
]

STRONG_PRIVATE_KEYWORDS = [
    "爸", "妈", "爹", "娘", "老公", "老婆", "媳妇", "爷爷", "奶奶", "外公", "外婆",
    "儿子", "女儿", "宝宝", "岳父", "岳母", "公公", "婆婆",
]

WEAK_PRIVATE_KEYWORDS = [
    "哥", "姐", "弟", "妹", "叔", "姨", "舅", "姑", "同学", "舍友", "室友", "房东",
    "老友", "发小",
]

SCREENING_HEADERS = [
    "序号", "显示名", "备注名", "昵称", "微信号", "消息数", "首条时间", "末条时间",
    "自动判定", "是否客户",
]

_SELECTED_VALUES = {"Y", "YES", "是", "1", "TRUE", "T", "√"}

_COMPANY_PERSON_SEPARATORS = "-_—（(/ "

_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


def _norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def guess_category(
    remark: object, nickname: object, alias: object, username: object
) -> str:
    remark_s = _norm(remark)
    nickname_s = _norm(nickname)
    alias_s = _norm(alias)
    username_s = _norm(username)

    if username_s.endswith("@openim"):
        return "疑似客户"

    if (
        _contains_any(remark_s, CUSTOMER_KEYWORDS)
        or _contains_any(nickname_s, CUSTOMER_KEYWORDS)
        or _contains_any(alias_s, CUSTOMER_KEYWORDS)
    ):
        return "疑似客户"

    remark_no_space = re.sub(r"\s+", "", remark_s)
    if remark_no_space.startswith("+86"):
        remark_no_space = remark_no_space[3:]
    if _PHONE_PATTERN.match(remark_no_space):
        return "疑似客户"

    # 私人判定必须排在「公司-人名形态」这条弱启发式之前：
    # 「老公 张伟」「妈妈 王芳」都带分隔符，若先跑形态规则会被预填 Y，
    # 把私人会话推进导出范围。宁可把客户判成待定，也不能把亲属判成客户。
    if _contains_any(remark_s, STRONG_PRIVATE_KEYWORDS) or _contains_any(
        nickname_s, STRONG_PRIVATE_KEYWORDS
    ):
        return "私人"

    remark_no_space_len = len(re.sub(r"\s+", "", remark_s))
    nickname_no_space_len = len(re.sub(r"\s+", "", nickname_s))
    if (
        remark_no_space_len <= 5
        and remark_no_space_len > 0
        and _contains_any(remark_s, WEAK_PRIVATE_KEYWORDS)
    ) or (
        nickname_no_space_len <= 5
        and nickname_no_space_len > 0
        and _contains_any(nickname_s, WEAK_PRIVATE_KEYWORDS)
    ):
        return "私人"

    # 「公司-人名」形态只是弱信号，判成待定（预填 ?）交人工定夺，不自动预填 Y。
    if any(separator in remark_s for separator in _COMPANY_PERSON_SEPARATORS):
        stripped = remark_s
        for separator in _COMPANY_PERSON_SEPARATORS:
            stripped = stripped.replace(separator, "")
        if len(stripped) >= 4:
            return "待定"

    return "待定"


def _csv_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def write_screening_csv(rows: list[dict], path: Path) -> dict[str, int]:
    counts = {"total": 0, "auto_customer": 0, "auto_private": 0, "auto_undecided": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(SCREENING_HEADERS)
        for row in rows:
            auto = row.get("自动判定", "待定")
            if auto == "疑似客户":
                prefill = "Y"
                counts["auto_customer"] += 1
            elif auto == "私人":
                prefill = ""
                counts["auto_private"] += 1
            else:
                prefill = "?"
                counts["auto_undecided"] += 1
            counts["total"] += 1
            writer.writerow(
                [
                    _csv_safe(row.get("序号", "")),
                    _csv_safe(row.get("显示名", "")),
                    _csv_safe(row.get("备注名", "")),
                    _csv_safe(row.get("昵称", "")),
                    _csv_safe(row.get("微信号", "")),
                    _csv_safe(row.get("消息数", "")),
                    _csv_safe(row.get("首条时间", "")),
                    _csv_safe(row.get("末条时间", "")),
                    _csv_safe(auto),
                    _csv_safe(prefill),
                ]
            )
    return counts


def read_selection(path: Path) -> set[str]:
    if not path.is_file():
        raise FileNotFoundError(
            f"找不到会话清单文件：{path}；请先运行 list_conversations.py 生成清单"
        )
    # 中文版 Excel 的「CSV（逗号分隔）」另存为默认写 GBK，不是 UTF-8。
    # 同事十有八九是用 Excel 改完直接保存，所以必须能读回 GBK。
    text = ""
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gbk", "cp936"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError as error:
            last_error = error
    else:
        raise RuntimeError(
            f"会话清单文件编码无法识别（已尝试 UTF-8 与 GBK）：{path}；"
            f"请在 Excel 里另存为「CSV UTF-8（逗号分隔）」后重试（{last_error}）"
        )

    selected: set[str] = set()
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        decision = (row.get("是否客户") or "").strip().upper()
        if decision in _SELECTED_VALUES:
            username = (row.get("微信号") or "").strip()
            if username:
                selected.add(username)
    if not selected:
        raise RuntimeError(
            "会话清单里没有任何一行被标记为客户：请在『是否客户』列填 Y 后重跑"
        )
    return selected

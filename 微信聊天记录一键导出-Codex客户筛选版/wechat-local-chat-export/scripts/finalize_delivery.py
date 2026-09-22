from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wechat_export.runtime_paths import validate_runtime_directory  # noqa: E402

from wechat_export.reconcile import validate_archive_members  # noqa: E402


def _csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return max(sum(1 for _ in csv.reader(stream)) - 1, 0)


def _write_state(run_root: Path, payload: dict[str, object]) -> None:
    (run_root / "run-state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_state(run_root: Path) -> dict[str, object]:
    state_path = run_root / "run-state.json"
    if state_path.is_file():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def _purge_workspace(run_root: Path) -> list[str]:
    purged: list[str] = []
    run_root_resolved = run_root.resolve()
    for name in ("source_copy", "private"):
        target = (run_root / name).resolve()
        try:
            is_inside = target == run_root_resolved or run_root_resolved in target.parents
        except (OSError, ValueError):
            is_inside = False
        if not is_inside:
            continue
        if target.exists():
            shutil.rmtree(target)
            purged.append(name)
    return purged


def finalize(run_root: Path, purge_workspace: bool = False) -> dict[str, object]:
    run_root = validate_runtime_directory(run_root)
    delivery = run_root / "delivery"
    source = json.loads((delivery / "客户索引数据.json").read_text(encoding="utf-8"))
    rows = source["index_rows"]
    html_files = sorted((delivery / "聊天记录_HTML").glob("*.html"))
    csv_files = sorted((delivery / "聊天记录_CSV").glob("*.csv"))

    xlsx_path = delivery / "客户聊天索引.xlsx"
    csv_index_path = delivery / "客户聊天索引.csv"
    if xlsx_path.is_file():
        index_path = xlsx_path
    elif csv_index_path.is_file():
        index_path = csv_index_path
    else:
        raise FileNotFoundError("客户聊天索引.xlsx 或 客户聊天索引.csv 均不存在")

    if len(rows) != len(html_files) or len(rows) != len(csv_files):
        raise RuntimeError("conversation/file counts do not match")
    by_name = {path.relative_to(delivery).as_posix(): path for path in csv_files}
    for row in rows:
        csv_path = by_name.get(str(row["CSV文件"]))
        if csv_path is None or _csv_rows(csv_path) != int(row["消息数"]):
            raise RuntimeError(f"CSV message count mismatch: {row['CSV文件']}")
    directions = source["direction_totals"]
    if int(source["private_messages"]) != sum(int(directions[key]) for key in ("我", "客户", "未知")):
        raise RuntimeError("direction totals do not reconcile")
    readme = delivery / "README.txt"
    readme.write_text(
        "微信客户一对一聊天记录\n\n"
        "本包只包含人工勾选确认的客户会话；已排除群聊、公众号、系统账号以及全部未勾选的私人会话。\n"
        "全部内容在本机整理，未上传。\n\n"
        f"{index_path.name}：汇总与客户索引。\n"
        "聊天记录_HTML：适合浏览。\n"
        "聊天记录_CSV：适合检索和二次处理。\n"
        "导出摘要.json：数量摘要。\n",
        encoding="utf-8-sig",
    )
    allowed = [index_path, delivery / "导出摘要.json", readme, *html_files, *csv_files]
    archive = run_root / "微信客户聊天记录_交付.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in allowed:
            zf.write(path, path.relative_to(delivery).as_posix())
    with zipfile.ZipFile(archive) as zf:
        members = zf.namelist()
        check = validate_archive_members(members)
        if not check.ok:
            raise RuntimeError(f"forbidden archive members: {check.forbidden}")
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failed: {bad}")

    purged: list[str] = []
    if purge_workspace:
        purged = _purge_workspace(run_root)

    result = {
        "status": "complete",
        "archive": str(archive),
        "private_conversations": len(rows),
        "private_messages": int(source["private_messages"]),
        "files": len(allowed),
        "purged": purged,
    }
    (run_root / "final-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    state = _read_state(run_root)
    state["status"] = "complete"
    state["archive"] = str(archive)
    _write_state(run_root, state)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile and package delivery-only WeChat exports")
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--purge-workspace", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            finalize(validate_runtime_directory(args.run_root), purge_workspace=args.purge_workspace),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

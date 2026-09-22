from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wechat_export.runtime_paths import validate_runtime_directory  # noqa: E402

from wechat_export.export import export_private_chats  # noqa: E402
from wechat_export.screening import read_selection  # noqa: E402


def _write_state(run_root: Path, payload: dict[str, object]) -> None:
    (run_root / "run-state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_state(run_root: Path) -> dict[str, object]:
    state_path = run_root / "run-state.json"
    if state_path.is_file():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def run_export(run_root: Path, selection: Path) -> dict[str, object]:
    run_root = validate_runtime_directory(run_root)
    decrypted = run_root / "private" / "decrypted"
    if not decrypted.is_dir():
        raise RuntimeError(
            "找不到解密后的数据目录：请先运行 prepare_snapshot.py 完成快照与解密"
        )
    if not selection.is_file():
        raise FileNotFoundError(
            f"找不到会话清单文件：{selection}；请先运行 list_conversations.py 生成清单并人工勾选"
        )
    delivery = run_root / "delivery"
    if delivery.exists():
        raise FileExistsError(
            f"交付目录已存在：{delivery}；请先删除该目录或新建一个 run_root 后重试"
        )

    selected = read_selection(selection)
    summary = export_private_chats(decrypted, delivery, allowed_usernames=selected)

    state = _read_state(run_root)
    state.update(
        {
            "status": "needs_index",
            "delivery": str(delivery),
            "index_json": str(delivery / "客户索引数据.json"),
            "next_action": "运行 build_index.py 生成客户聊天索引，再运行 finalize_delivery.py 打包交付",
        }
    )
    phases = list(state.get("phases", []))
    phases.append(
        {
            "phase": "export",
            "status": "ok",
            "selected_conversations": len(selected),
            "private_conversations": summary["private_conversations"],
            "private_messages": summary["private_messages"],
            "screened_out_conversations": summary["screened_out_conversations"],
            "screened_out_messages": summary["screened_out_messages"],
            "selection_not_found": summary["selection_not_found"],
        }
    )
    state["phases"] = phases
    _write_state(run_root, state)

    return {
        "status": state["status"],
        "run_root": str(run_root),
        "delivery": str(delivery),
        "selected_conversations": len(selected),
        "private_conversations": summary["private_conversations"],
        "private_messages": summary["private_messages"],
        "screened_out_conversations": summary["screened_out_conversations"],
        "screened_out_messages": summary["screened_out_messages"],
        "selection_not_found": summary["selection_not_found"],
        "next_action": state["next_action"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export only the manually confirmed customer conversations "
        "(stage two: run after list_conversations.py and manual CSV review)"
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()

    run_root = validate_runtime_directory(args.run_root)
    selection = (args.selection or (run_root / "会话清单.csv")).resolve()
    try:
        result = run_export(run_root, selection)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        state = _read_state(run_root)
        state["status"] = "failed"
        state["error_type"] = type(exc).__name__
        state["error"] = str(exc)
        _write_state(run_root, state)
        print(
            json.dumps(
                {
                    "status": "failed",
                    "run_root": str(run_root),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

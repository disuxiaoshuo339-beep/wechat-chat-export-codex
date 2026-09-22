from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wechat_export.runtime_paths import validate_runtime_directory  # noqa: E402

from wechat_export.export import scan_private_conversations  # noqa: E402
from wechat_export.screening import write_screening_csv  # noqa: E402


def _write_state(run_root: Path, payload: dict[str, object]) -> None:
    (run_root / "run-state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_state(run_root: Path) -> dict[str, object]:
    state_path = run_root / "run-state.json"
    if state_path.is_file():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def list_conversations(run_root: Path) -> dict[str, object]:
    run_root = validate_runtime_directory(run_root)
    decrypted = run_root / "private" / "decrypted"
    if not decrypted.is_dir():
        raise RuntimeError(
            "找不到解密后的数据目录：请先运行 prepare_snapshot.py 完成快照与解密"
        )
    rows = scan_private_conversations(decrypted)
    screening_csv = run_root / "会话清单.csv"
    counts = write_screening_csv(rows, screening_csv)

    state = _read_state(run_root)
    state.update(
        {
            "status": "awaiting_selection",
            "screening_csv": str(screening_csv),
            "next_action": (
                "请人工打开会话清单.csv，在『是否客户』列确认（Y=导出），"
                "保存后再运行 run_export.py"
            ),
        }
    )
    phases = list(state.get("phases", []))
    phases.append({"phase": "screening", "status": "ok", **counts})
    state["phases"] = phases
    _write_state(run_root, state)

    return {
        "status": state["status"],
        "screening_csv": str(screening_csv),
        "total": counts["total"],
        "auto_customer": counts["auto_customer"],
        "auto_private": counts["auto_private"],
        "auto_undecided": counts["auto_undecided"],
        "next_action": state["next_action"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan decrypted private conversations (metadata only, no message content) "
        "and write a screening CSV for manual review"
    )
    parser.add_argument("--run-root", required=True, type=Path)
    args = parser.parse_args()

    run_root = validate_runtime_directory(args.run_root)
    try:
        result = list_conversations(run_root)
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

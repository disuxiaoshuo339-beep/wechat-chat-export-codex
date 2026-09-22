from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RunRequest:
    account_id: str | None
    output_root: Path


@dataclass(frozen=True)
class RunResult:
    status: str
    xlsx_created: bool
    phases: tuple[dict[str, object], ...]


class ExportAdapters(Protocol):
    def snapshot(self, request: RunRequest) -> dict[str, object]: ...
    def read_and_validate_keys(self, request: RunRequest) -> dict[str, object]: ...
    def decrypt(self, request: RunRequest) -> dict[str, object]: ...
    def export(self, request: RunRequest) -> dict[str, object]: ...
    def build_xlsx(self, request: RunRequest) -> bool: ...
    def reconcile(self, request: RunRequest) -> dict[str, object]: ...
    def package(self, request: RunRequest) -> dict[str, object]: ...


def sanitized_phase_record(
    phase: str,
    status: str,
    counts: dict[str, int | bool] | None = None,
    error_type: str = "",
) -> dict[str, object]:
    safe_counts = {
        str(key): value
        for key, value in (counts or {}).items()
        if isinstance(value, (int, bool))
    }
    return {
        "phase": phase,
        "status": status,
        "counts": safe_counts,
        "error_type": error_type,
    }


def _counts(payload: dict[str, Any]) -> dict[str, int | bool]:
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, (int, bool))
    }


def run_export(request: RunRequest, adapters: ExportAdapters) -> RunResult:
    phases: list[dict[str, object]] = []
    if not request.account_id:
        phases.append(sanitized_phase_record("authorization", "required"))
        return RunResult("needs_authorization", False, tuple(phases))

    snapshot = adapters.snapshot(request)
    phases.append(sanitized_phase_record("snapshot", "ok", _counts(snapshot)))

    keys = adapters.read_and_validate_keys(request)
    key_ok = bool(keys.get("ok"))
    phases.append(
        sanitized_phase_record("keys", "ok" if key_ok else "failed", _counts(keys))
    )
    if not key_ok:
        return RunResult("failed", False, tuple(phases))

    decrypted = adapters.decrypt(request)
    phases.append(sanitized_phase_record("decrypt", "ok", _counts(decrypted)))
    exported = adapters.export(request)
    phases.append(sanitized_phase_record("export", "ok", _counts(exported)))

    xlsx_created = bool(adapters.build_xlsx(request))
    phases.append(
        sanitized_phase_record("xlsx", "ok" if xlsx_created else "unavailable")
    )
    reconciled = adapters.reconcile(request)
    reconcile_ok = bool(reconciled.get("ok"))
    phases.append(
        sanitized_phase_record(
            "reconcile", "ok" if reconcile_ok else "failed", _counts(reconciled)
        )
    )
    if not reconcile_ok:
        return RunResult("failed", xlsx_created, tuple(phases))

    packaged = adapters.package(request)
    package_ok = bool(packaged.get("ok"))
    phases.append(
        sanitized_phase_record(
            "package", "ok" if package_ok else "failed", _counts(packaged)
        )
    )
    if not package_ok:
        return RunResult("failed", xlsx_created, tuple(phases))
    return RunResult("complete" if xlsx_created else "partial", xlsx_created, tuple(phases))

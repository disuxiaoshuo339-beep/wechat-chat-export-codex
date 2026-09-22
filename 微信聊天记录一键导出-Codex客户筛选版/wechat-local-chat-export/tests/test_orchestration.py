from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wechat_export.orchestration import RunRequest, run_export, sanitized_phase_record


@dataclass
class SpyAdapters:
    xlsx_available: bool = True
    key_coverage_ok: bool = True
    memory_reads: int = 0

    def snapshot(self, request):
        return {"files": 10}

    def read_and_validate_keys(self, request):
        self.memory_reads += 1
        return {"ok": self.key_coverage_ok, "validated": 3, "required": 3}

    def decrypt(self, request):
        return {"verified": 3}

    def export(self, request):
        return {"conversations": 2, "messages": 5}

    def build_xlsx(self, request):
        return self.xlsx_available

    def reconcile(self, request):
        return {"ok": True}

    def package(self, request):
        return {"ok": True}


def test_runner_stops_before_memory_read_without_authorization(tmp_path):
    spy = SpyAdapters()

    result = run_export(RunRequest(account_id=None, output_root=tmp_path), spy)

    assert result.status == "needs_authorization"
    assert spy.memory_reads == 0


def test_runner_reports_partial_when_xlsx_runtime_is_unavailable(tmp_path):
    spy = SpyAdapters(xlsx_available=False)

    result = run_export(
        RunRequest(account_id="wxid_fixture_ab12", output_root=tmp_path), spy
    )

    assert result.status == "partial"
    assert result.xlsx_created is False


def test_runner_fails_closed_when_core_key_coverage_is_incomplete(tmp_path):
    spy = SpyAdapters(key_coverage_ok=False)

    result = run_export(
        RunRequest(account_id="wxid_fixture_ab12", output_root=tmp_path), spy
    )

    assert result.status == "failed"
    assert "keys" in [record["phase"] for record in result.phases]


def test_phase_records_accept_counts_but_not_secrets_or_content():
    record = sanitized_phase_record(
        "export", "ok", counts={"messages": 5}, error_type=""
    )

    assert record == {
        "phase": "export",
        "status": "ok",
        "counts": {"messages": 5},
        "error_type": "",
    }

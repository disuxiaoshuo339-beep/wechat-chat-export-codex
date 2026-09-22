from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExportConfig:
    account_id: str
    source_db: Path
    work_root: Path

    @classmethod
    def for_authorized_account(cls, source_db: Path, work_root: Path) -> "ExportConfig":
        source = source_db.resolve()
        account_dir = source.parent
        return cls(account_id=account_dir.name, source_db=source, work_root=work_root.resolve())


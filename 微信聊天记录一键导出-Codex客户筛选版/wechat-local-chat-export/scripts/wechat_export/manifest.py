from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import ExportConfig


@dataclass(frozen=True)
class ManifestRow:
    relative_path: str
    size_bytes: int
    modified_utc: str
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_source(config: ExportConfig, candidate: Path) -> Path:
    resolved = candidate.resolve()
    if resolved != config.source_db:
        raise ValueError("source is outside the authorized account")
    if resolved.name != "db_storage" or not resolved.is_dir():
        raise ValueError("authorized account db_storage directory is missing")
    return resolved


def copy_with_manifest(source: Path, destination: Path) -> list[ManifestRow]:
    source = source.resolve()
    destination = destination.resolve()
    rows: list[ManifestRow] = []
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        relative = source_file.relative_to(source)
        target = destination / relative
        source_hash = _sha256(source_file)
        if target.exists():
            if _sha256(target) != source_hash:
                raise FileExistsError(f"destination has different content: {relative.as_posix()}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
        stat = source_file.stat()
        rows.append(
            ManifestRow(
                relative_path=relative.as_posix(),
                size_bytes=stat.st_size,
                modified_utc=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                sha256=source_hash,
            )
        )
    return rows

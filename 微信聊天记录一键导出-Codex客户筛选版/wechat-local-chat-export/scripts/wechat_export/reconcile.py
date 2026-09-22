from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CountResult:
    ok: bool
    source: int
    accounted: int


@dataclass(frozen=True)
class ArchiveResult:
    ok: bool
    forbidden: tuple[str, ...]


def reconcile_counts(
    source: int, exported: int, excluded: int, review: int
) -> CountResult:
    accounted = exported + excluded + review
    return CountResult(ok=source == accounted, source=source, accounted=accounted)


def validate_archive_members(members: list[str]) -> ArchiveResult:
    forbidden_suffixes = (".db", ".db-wal", ".db-shm", ".dmp")
    forbidden_names = {
        "keys.json",
        "会话清单.csv",
        "客户索引数据.json",
        "run-state.json",
        "source-manifest.csv",
        "final-result.json",
    }
    forbidden = tuple(
        member
        for member in members
        if member.lower().endswith(forbidden_suffixes)
        or member.rsplit("/", 1)[-1].lower() in forbidden_names
        or "/private/" in "/" + member.lower()
        or "/source_copy/" in "/" + member.lower()
        or "/logs/" in "/" + member.lower()
    )
    return ArchiveResult(ok=not forbidden, forbidden=forbidden)

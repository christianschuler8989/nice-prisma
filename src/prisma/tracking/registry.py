"""The corpus registry: one entry per canonical document, updated in place
by every pipeline stage from dedup onward.

File format is JSON Lines (one `DocEntry` per line) so it stays diffable and
so update is `load -> mutate in memory -> save`, which is fine at the scale
of a systematic review corpus (hundreds to low tens of thousands of
records, never unbounded).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DocEntry:
    """One canonical document, tracked across ingest -> ... -> eligibility."""

    doc_id: str
    doi: str = ""
    title: str = ""
    year: str = ""
    sources: list[str] = field(default_factory=list)
    # {"decision": "include"|"exclude"|"maybe", "fired_exclusion": [...], "missing_groups": [...]}
    screening: dict[str, Any] | None = None
    # {"status": "not_sought"|"retrieved"|"not_retrieved", "pdf": str|None}
    retrieval: dict[str, Any] | None = None
    # {"decision": "include"|"exclude", "reason": str|None}
    eligibility: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocEntry:
        return cls(**data)


class Registry:
    """A mutable collection of `DocEntry`, keyed by `doc_id`."""

    def __init__(self, entries: dict[str, DocEntry] | None = None) -> None:
        self._entries: dict[str, DocEntry] = entries or {}

    @classmethod
    def load(cls, path: str | Path) -> Registry:
        path = Path(path)
        entries: dict[str, DocEntry] = {}
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    entry = DocEntry.from_dict(json.loads(line))
                    entries[entry.doc_id] = entry
        return cls(entries)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for doc_id in sorted(self._entries):
                handle.write(json.dumps(self._entries[doc_id].to_dict(), ensure_ascii=False) + "\n")

    def upsert(self, entry: DocEntry) -> None:
        existing = self._entries.get(entry.doc_id)
        if existing is None:
            self._entries[entry.doc_id] = entry
            return
        # Merge rather than overwrite: a later stage (e.g. screening) must
        # not clobber fields an earlier stage (e.g. dedup) already set.
        merged = existing.to_dict()
        for key, value in entry.to_dict().items():
            if value not in (None, "", [], {}):
                merged[key] = value
        self._entries[entry.doc_id] = DocEntry.from_dict(merged)

    def get(self, doc_id: str) -> DocEntry | None:
        return self._entries.get(doc_id)

    def values(self) -> list[DocEntry]:
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries.values())


def compute_prisma_counts(registry: Registry, dedup_meta: dict[str, Any]):
    """Aggregate a `Registry` (plus the dedup stage's raw counts) into a
    `PRISMACounts`. Pure aggregation over tracked state, no regex/CSV
    scraping: every number here was written by the stage that produced it.
    """
    from prisma.reporting.prisma_flow import PRISMACounts

    entries = registry.values()

    screened = [e for e in entries if e.screening is not None]
    excluded_ta = sum(1 for e in screened if e.screening["decision"] == "exclude")

    sought = [e for e in entries if e.retrieval is not None and e.retrieval["status"] != "not_sought"]
    retrieved = [e for e in sought if e.retrieval["status"] == "retrieved"]
    not_retrieved = [e for e in sought if e.retrieval["status"] == "not_retrieved"]

    assessed = [e for e in retrieved if e.eligibility is not None]
    excluded_full_text: dict[str, int] = {}
    included = 0
    for e in assessed:
        decision = e.eligibility.get("decision")
        if decision == "exclude":
            reason = e.eligibility.get("reason") or "unspecified"
            excluded_full_text[reason] = excluded_full_text.get(reason, 0) + 1
        elif decision == "include":
            included += 1

    return PRISMACounts(
        identified_per_source=dedup_meta.get("identified_per_source", {}),
        deduplicated=dedup_meta.get("deduplicated"),
        duplicates_removed=dedup_meta.get("duplicates_removed"),
        screened_title_abstract=len(screened) or None,
        excluded_title_abstract=excluded_ta or None,
        sought_for_retrieval=len(sought) or None,
        not_retrieved=len(not_retrieved) or None,
        assessed_full_text=len(retrieved) or None,
        excluded_full_text=excluded_full_text,
        included=included if assessed else None,
    )

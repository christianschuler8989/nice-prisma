"""Full-text eligibility: the one genuinely human step in this pipeline.

PRISMA's "included" / "excluded (with reason)" call at the full-text stage
is a judgment call, not something to automate. What was missing before
wasn't the human judgment itself, it was any structured place to *record*
it. This module generates a review template from the registry (one row per
retrieved PDF) and, once filled in by a person, folds the decisions back
into the registry so `prisma counts` can tally them automatically.
"""
from __future__ import annotations

import csv
from pathlib import Path

from prisma.tracking.registry import DocEntry, Registry

VALID_DECISIONS = {"include", "exclude"}


def write_template(registry: Registry, output_path: str | Path) -> int:
    """Write a CSV template for every retrieved-but-not-yet-assessed doc.

    Returns the number of rows written.
    """
    rows = [
        e
        for e in registry.values()
        if e.retrieval is not None and e.retrieval.get("status") == "retrieved" and e.eligibility is None
    ]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["doc_id", "title", "pdf", "decision", "reason"])
        writer.writeheader()
        for e in rows:
            writer.writerow(
                {
                    "doc_id": e.doc_id,
                    "title": e.title,
                    "pdf": e.retrieval.get("pdf", ""),
                    "decision": "",
                    "reason": "",
                }
            )
    return len(rows)


def apply_template(registry: Registry, filled_path: str | Path) -> tuple[int, list[str]]:
    """Read a filled-in template back and update the registry.

    Returns `(rows_applied, doc_ids_left_blank)`. Rows with an empty
    `decision` are skipped (left for a later pass) rather than guessed at.
    """
    applied = 0
    left_blank: list[str] = []
    with open(filled_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            decision = (row.get("decision") or "").strip().lower()
            doc_id = row["doc_id"]
            if not decision:
                left_blank.append(doc_id)
                continue
            if decision not in VALID_DECISIONS:
                raise ValueError(
                    f"doc_id {doc_id}: decision must be one of {sorted(VALID_DECISIONS)}, got {decision!r}"
                )
            reason = (row.get("reason") or "").strip()
            if decision == "exclude" and not reason:
                raise ValueError(f"doc_id {doc_id}: excluded rows must have a reason")
            registry.upsert(DocEntry(doc_id=doc_id, eligibility={"decision": decision, "reason": reason or None}))
            applied += 1
    return applied, left_blank

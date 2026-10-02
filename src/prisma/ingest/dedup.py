"""Cross-source deduplication for RIS corpora.

Strategy:
  1. Exact DOI match (primary key after normalization). In practice most of
     these are already caught before this even runs, since `identity.py`
     derives `doc_id` from the DOI at ingest time.
  2. Fuzzy title match (Levenshtein ratio via rapidfuzz, default >= 92).

Each unique record is tagged with its source label for provenance. Beyond
the unique set and the human-readable audit trail, this stage is where the
corpus-wide `doc_id` identity crosswalk and tracking registry are seeded:
every raw record (unique or duplicate) is resolved to a canonical `doc_id`,
and that resolution is what lets screening, retrieval, and eligibility
join back to the same document later without re-matching titles/DOIs again.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from prisma.ingest.identity import ensure_doc_id
from prisma.ingest.ris_io import (
    Record,
    get_all_fields,
    get_field,
    normalize_doi,
    normalize_title,
    parse_ris,
    write_ris,
)
from prisma.tracking.registry import DocEntry, Registry

DEFAULT_FUZZY_THRESHOLD = 92


@dataclass
class DedupResult:
    """Outcome of a deduplication run."""

    unique: list[tuple[str, Record, str]] = field(default_factory=list)  # (db, record, doc_id)
    duplicates: list[dict] = field(default_factory=list)
    crosswalk: list[dict] = field(default_factory=list)  # {alias_doc_id, canonical_doc_id, reason}
    source_overlap: dict[str, set[str]] = field(default_factory=dict)
    identified_per_source: dict[str, int] = field(default_factory=dict)
    raw_total: int = 0
    fuzzy_threshold: int = DEFAULT_FUZZY_THRESHOLD


def _record_to_csv_row(record: Record, source_tag: str, doc_id: str) -> dict[str, str]:
    title = get_field(record, "TI") or get_field(record, "T1")
    doi = normalize_doi(get_field(record, "DO"))
    year = get_field(record, "PY") or get_field(record, "Y1")
    journal = get_field(record, "JO") or get_field(record, "T2") or get_field(record, "JF")
    return {
        "doc_id": doc_id,
        "doi": doi,
        "title": title,
        "year": year[:4] if year else "",
        "journal": journal,
        "authors": "; ".join(get_all_fields(record, "AU")),
        "keywords": "; ".join(get_all_fields(record, "KW")),
        "abstract": get_field(record, "AB")[:500],
        "source": source_tag,
    }


def deduplicate(
    sources: dict[str, str | Path],
    fuzzy_threshold: int = DEFAULT_FUZZY_THRESHOLD,
) -> DedupResult:
    """Deduplicate a set of RIS files keyed by source label.

    Args:
        sources: mapping `{source_label: ris_filepath}`. Convention:
                 prefix labels with the database (e.g. `scopus-A`, `openalex-B`)
                 to enable cross-database overlap statistics.
        fuzzy_threshold: minimum rapidfuzz ratio to treat two titles as the
                         same record. 92 is conservative; tune via tests.

    Returns:
        DedupResult with unique records (each tagged with its resolved
        `doc_id`), a duplicate audit trail, and an identity crosswalk
        mapping every duplicate's `doc_id` to the canonical one it was
        merged into.
    """
    identified_per_source: dict[str, int] = {}
    all_records: list[tuple[str, str, Record, str]] = []  # (db, label, record, doc_id)
    for label, filepath in sources.items():
        path = Path(filepath)
        if not path.exists():
            continue
        db = label.split("-", 1)[0]
        count = 0
        for rec in parse_ris(path):
            rec, doc_id = ensure_doc_id(rec)
            all_records.append((db, label, rec, doc_id))
            count += 1
        identified_per_source[label] = count

    seen_dois: dict[str, tuple[str, str]] = {}  # doi -> (db, doc_id)
    seen_titles: dict[str, tuple[str, str]] = {}  # title_norm -> (db, doc_id)
    unique: list[tuple[str, Record, str]] = []
    duplicates: list[dict] = []
    crosswalk: list[dict] = []
    overlap: dict[str, set[str]] = defaultdict(set)

    for db, label, record, doc_id in all_records:
        doi = normalize_doi(get_field(record, "DO"))
        title_raw = get_field(record, "TI") or get_field(record, "T1")
        title_norm = normalize_title(title_raw)
        is_dup = False
        reason = ""
        dup_of_db = ""
        dup_of_doc_id = ""

        if doi and doi in seen_dois:
            is_dup, reason = True, "DOI match"
            dup_of_db, dup_of_doc_id = seen_dois[doi]
            overlap[doi].add(db)
        elif title_norm:
            for seen_t, (seen_db, seen_doc_id) in seen_titles.items():
                ratio = fuzz.ratio(title_norm, seen_t)
                if ratio >= fuzzy_threshold:
                    is_dup, reason = True, f"fuzzy title ({ratio:.0f}%)"
                    dup_of_db, dup_of_doc_id = seen_db, seen_doc_id
                    overlap[title_norm].add(db)
                    break

        if is_dup:
            duplicates.append(
                {
                    "source": label,
                    "title": title_raw[:120],
                    "doi": doi,
                    "reason": reason,
                    "duplicate_of": dup_of_db,
                }
            )
            if doc_id != dup_of_doc_id:
                crosswalk.append(
                    {"alias_doc_id": doc_id, "canonical_doc_id": dup_of_doc_id, "reason": reason, "source": label}
                )
        else:
            unique.append((db, record, doc_id))
            if doi:
                seen_dois[doi] = (db, doc_id)
                overlap[doi].add(db)
            if title_norm:
                seen_titles[title_norm] = (db, doc_id)
                overlap[title_norm].add(db)

    return DedupResult(
        unique=unique,
        duplicates=duplicates,
        crosswalk=crosswalk,
        source_overlap=dict(overlap),
        identified_per_source=identified_per_source,
        raw_total=len(all_records),
        fuzzy_threshold=fuzzy_threshold,
    )


def build_registry(result: DedupResult) -> Registry:
    """Seed a `Registry` with one `DocEntry` per canonical (unique) document."""
    canonical_sources: dict[str, set[str]] = defaultdict(set)
    for db, _record, doc_id in result.unique:
        canonical_sources[doc_id].add(db)

    registry = Registry()
    for _db, record, doc_id in result.unique:
        registry.upsert(
            DocEntry(
                doc_id=doc_id,
                doi=normalize_doi(get_field(record, "DO")),
                title=get_field(record, "TI") or get_field(record, "T1"),
                year=(get_field(record, "PY") or get_field(record, "Y1"))[:4],
                sources=sorted(canonical_sources[doc_id]),
            )
        )
    return registry


def write_outputs(result: DedupResult, output_dir: str | Path, basename: str = "corpus") -> None:
    """Write the deduplicated corpus (RIS + CSV), an audit report, and the
    structured tracking artifacts (`dedup-meta.json`, `registry.jsonl`,
    `identity-crosswalk.csv`) that every later stage builds on.
    """
    import csv

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ris_path = output_dir / f"{basename}-deduplicated.ris"
    write_ris([(db, record) for db, record, _doc_id in result.unique], ris_path)

    csv_path = output_dir / f"{basename}-deduplicated.csv"
    fieldnames = ["doc_id", "doi", "title", "year", "journal", "authors", "keywords", "abstract", "source"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for source_tag, record, doc_id in result.unique:
            writer.writerow(_record_to_csv_row(record, source_tag or "", doc_id))

    report_path = output_dir / f"{basename}-dedup-report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Deduplication Report\n\n")
        f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"**Fuzzy threshold**: {result.fuzzy_threshold}% (Levenshtein ratio)\n\n")
        f.write("## Results\n\n")
        f.write(f"- Total raw records: {result.raw_total}\n")
        f.write(f"- Duplicates removed: {len(result.duplicates)}\n")
        f.write(f"- Unique records: {len(result.unique)}\n\n")
        if result.duplicates:
            f.write("## Duplicates Detail (first 50)\n\n")
            f.write("| # | Source | Dup of | Reason | Title |\n")
            f.write("|---|--------|--------|--------|-------|\n")
            for i, dup in enumerate(result.duplicates[:50], 1):
                title = dup["title"].replace("|", "\\|")
                f.write(f"| {i} | {dup['source']} | {dup['duplicate_of']} | {dup['reason']} | {title} |\n")

    meta_path = output_dir / f"{basename}-dedup-meta.json"
    meta = {
        "identified_per_source": result.identified_per_source,
        "raw_total": result.raw_total,
        "duplicates_removed": len(result.duplicates),
        "deduplicated": len(result.unique),
        "fuzzy_threshold": result.fuzzy_threshold,
        "generated_at": datetime.now().isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    crosswalk_path = output_dir / f"{basename}-identity-crosswalk.csv"
    with open(crosswalk_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["alias_doc_id", "canonical_doc_id", "reason", "source"])
        writer.writeheader()
        writer.writerows(result.crosswalk)

    registry = build_registry(result)
    registry.save(output_dir / f"{basename}-registry.jsonl")

"""Link retrieved PDFs back to registry `doc_id`s.

Extraction and quality scoring (`prisma extract`, `prisma quality`) key
their output purely by PDF filename, with no link to the record that PDF
was retrieved for. To close that gap without requiring OCR/metadata
sniffing, this module adopts one convention: a PDF's filename should start
with its `doc_id` (`doc-<hash>.pdf`, or `doc-<hash>__any-readable-suffix.pdf`).
`prisma ingest dedup` and `prisma screen` both surface `doc_id` in their CSV
output specifically so it's easy to rename retrieved PDFs this way.

For the cases where renaming isn't practical, an explicit manifest
(`doc_id,pdf` CSV) can be passed instead of relying on the filename
convention.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from prisma.ingest.identity import doc_id_from_filename
from prisma.tracking.registry import DocEntry, Registry


@dataclass
class RetrievalLinkResult:
    matched: list[tuple[str, Path]]  # (doc_id, pdf_path)
    unmatched_pdfs: list[Path]  # pdfs that matched no known doc_id
    not_retrieved: list[str]  # doc_ids that were sought but have no matching pdf
    not_sought: list[str]  # doc_ids excluded at screening, never sought
    not_sought_pdfs: list[Path]  # pdfs present for a doc_id that was excluded at screening


def _excluded_at_screening(entry: DocEntry) -> bool:
    return entry.screening is not None and entry.screening.get("decision") == "exclude"


def load_manifest(path: str | Path) -> dict[str, str]:
    """Read a `doc_id,pdf` CSV mapping (filename relative to the pdfs dir)."""
    mapping: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mapping[row["doc_id"]] = row["pdf"]
    return mapping


def link_retrieval(
    registry: Registry,
    pdfs_dir: str | Path,
    manifest: dict[str, str] | None = None,
) -> RetrievalLinkResult:
    """Match PDFs in `pdfs_dir` to registry doc_ids and update the registry.

    A doc_id that was excluded at screening is marked "not_sought". Every
    other doc_id is sought: those matched to a PDF (via the manifest, or by
    filename prefix otherwise) become "retrieved", the rest "not_retrieved".
    PDFs that match no known doc_id, and PDFs that belong to a doc_id excluded
    at screening, are reported separately rather than silently ignored.
    """
    pdfs_dir = Path(pdfs_dir)
    pdfs = sorted(pdfs_dir.rglob("*.pdf"))

    manifest = manifest or {}
    doc_id_to_pdf: dict[str, Path] = {}
    unmatched_pdfs: list[Path] = []
    not_sought_pdfs: list[Path] = []

    manifest_by_name = {name: doc_id for doc_id, name in manifest.items()}

    for pdf in pdfs:
        doc_id = manifest_by_name.get(pdf.name) or doc_id_from_filename(pdf.name)
        entry = registry.get(doc_id)
        if entry is None:
            unmatched_pdfs.append(pdf)
        elif _excluded_at_screening(entry):
            not_sought_pdfs.append(pdf)
        else:
            doc_id_to_pdf[doc_id] = pdf

    matched: list[tuple[str, Path]] = []
    not_retrieved: list[str] = []
    not_sought: list[str] = []
    for entry in registry.values():
        pdf = doc_id_to_pdf.get(entry.doc_id)
        if _excluded_at_screening(entry):
            status = "not_sought"
            not_sought.append(entry.doc_id)
        elif pdf is not None:
            status = "retrieved"
            matched.append((entry.doc_id, pdf))
        else:
            status = "not_retrieved"
            not_retrieved.append(entry.doc_id)
        registry.upsert(
            DocEntry(doc_id=entry.doc_id, retrieval={"status": status, "pdf": str(pdf) if pdf else None})
        )

    return RetrievalLinkResult(
        matched=matched,
        unmatched_pdfs=unmatched_pdfs,
        not_retrieved=not_retrieved,
        not_sought=not_sought,
        not_sought_pdfs=not_sought_pdfs,
    )

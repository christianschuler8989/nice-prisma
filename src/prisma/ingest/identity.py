"""Stable document identity across the whole PRISMA workflow.

The original tool had no notion of a "document" that persists across
stages: ingest wrote bare RIS records, screening keyed rows by DOI-or-index,
and extraction/quality keyed rows by PDF filename with no link back to the
record that PDF was retrieved for. That made it impossible to join
screening decisions to full-text decisions to quality scores, which is
exactly what's needed to derive PRISMA counts automatically.

This module assigns every record a `doc_id`: a short, deterministic,
content-derived id (DOI when available, otherwise normalized title + year)
stored in the record's RIS `ID` tag. Two records ingested from different
sources with the same DOI get the same `doc_id` before deduplication even
runs. This is not a replacement for dedup.py's fuzzy-title pass (two
records for the same paper can still disagree enough to hash differently),
but it removes the whole class of "same DOI, different identity" bugs for
free, and gives every later stage (screening, retrieval, eligibility,
quality) one stable key to join on.
"""
from __future__ import annotations

import hashlib

from prisma.ingest.ris_io import Record, get_field, normalize_doi, normalize_title

ID_TAG = "ID"


def compute_doc_id(doi: str, title: str, year: str) -> str:
    """Derive a stable id from a DOI, or failing that, title + year.

    DOI is preferred because it's an external, unambiguous identifier.
    Falling back to normalized title + year is a best effort for records
    that lack a DOI (common for preprints, dissertations, some conference
    proceedings): it's not guaranteed unique, but it's stable across runs.
    """
    doi_norm = normalize_doi(doi or "")
    if doi_norm:
        basis = f"doi:{doi_norm}"
    else:
        basis = f"title:{normalize_title(title or '')}|{(year or '').strip()[:4]}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"doc-{digest}"


def doc_id_from_filename(name: str) -> str:
    """Recover the `doc_id` from a PDF filename following the
    `<doc_id>.pdf` / `<doc_id>__<readable-suffix>.pdf` convention.

    Returns the filename stem unchanged if it doesn't look like a
    `doc-<hash>` id; callers decide whether that's a match worth trusting.
    """
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem.split("__", 1)[0]


def ensure_doc_id(record: Record) -> tuple[Record, str]:
    """Return `(record, doc_id)`, injecting an `ID` tag if none is present.

    Records that already carry an `ID` tag (e.g. re-parsed output of this
    same tool, or an export from another reference manager that sets its
    own accession number) keep that id untouched: identity, once assigned,
    should not silently change underneath a review that's already in
    progress.
    """
    existing = get_field(record, ID_TAG)
    if existing:
        return record, existing

    doi = get_field(record, "DO")
    title = get_field(record, "TI") or get_field(record, "T1")
    year = get_field(record, "PY") or get_field(record, "Y1")
    doc_id = compute_doc_id(doi, title, year)
    return [*record, (ID_TAG, doc_id)], doc_id

"""Cross-stage document tracking: identity, registry, and PRISMA counts.

Every other package in this tool (ingest, screening, extraction, quality)
produces its own file per stage. This package is the join layer: it keeps
one registry entry per canonical `doc_id` and lets each stage update that
entry in place, so PRISMA counts can be computed by aggregation instead of
by re-parsing CSV/Markdown output after the fact.
"""
from prisma.tracking.registry import DocEntry, Registry

__all__ = ["DocEntry", "Registry"]

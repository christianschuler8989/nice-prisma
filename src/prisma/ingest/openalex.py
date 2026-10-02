"""OpenAlex API client for corpus building.

OpenAlex is open access, no API key required. A polite email is recommended
via the `mailto` parameter (and the User-Agent header) to be moved into the
polite pool (faster + more reliable rate limits). See
https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication.

Every search is treated as an immutable research artifact: when `cache_dir`
is given, each page is appended to a JSON Lines file as soon as it is
fetched, and a metadata sidecar records the query spec, filters, select
fields, cursor, and retrieval timestamps. A rerun with the same `query_id`
resumes from the stored cursor instead of re-fetching, and a completed query
is served straight from the cache. This matters because OpenAlex search
results can change as records are added, merged, or reindexed, so the raw
response captured at retrieval time is the reproducible record of what the
review actually screened.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from prisma import __version__
from prisma.ingest.identity import compute_doc_id
from prisma.ingest.ris_io import normalize_doi

OPENALEX_WORKS = "https://api.openalex.org/works"

# Largest page size this client will request. nice-prisma never asks a
# service for more than the value the service recommends.
MAX_PER_PAGE = 100

# Version of the on-disk cache layout. Since format 2, `fetched` and `cursor`
# in meta.json describe what is stored in records.jsonl (records stored, and
# the cursor of the next page that has not been requested yet).
CACHE_FORMAT = 2

# A good default for screening tables: enough to build the corpus and
# convert to RIS without pulling every nested field OpenAlex can return.
DEFAULT_SELECT = (
    "id,doi,title,publication_year,publication_date,type,language,"
    "authorships,primary_location,open_access,abstract_inverted_index,"
    "cited_by_count,referenced_works_count,keywords"
)

# OpenAlex work `type` -> RIS `TY` tag. Falls back to "GEN" (generic) for
# anything unmapped, rather than mislabelling everything as a journal
# article.
_TYPE_TO_RIS = {
    "article": "JOUR",
    "review": "JOUR",
    "letter": "JOUR",
    "editorial": "JOUR",
    "erratum": "JOUR",
    "preprint": "UNPB",
    "book": "BOOK",
    "book-chapter": "CHAP",
    "monograph": "BOOK",
    "reference-entry": "CHAP",
    "dissertation": "THES",
    "report": "RPRT",
    "dataset": "DATA",
    "paratext": "GEN",
    "supplementary-materials": "GEN",
    "peer-review": "GEN",
    "standard": "STAND",
    "grant": "GEN",
    "other": "GEN",
}

logger = logging.getLogger(__name__)


class OpenAlexError(RuntimeError):
    """Raised when an OpenAlex request fails after all retries."""


def make_session(mailto: str, api_key: str | None = None) -> requests.Session:
    """Build a session with retry/backoff and polite-pool identification.

    A single connection pool (`pool_maxsize=1`) keeps requests sequential by
    construction: this client is not meant to be used concurrently from
    multiple threads.
    """
    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=1, pool_maxsize=1)
    session.mount("https://", adapter)

    headers = {
        "User-Agent": f"nice-prisma/{__version__} (mailto:{mailto})",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    session.headers.update(headers)
    return session


def _validate_filters(filters: dict[str, str]) -> None:
    for key, value in filters.items():
        or_values = str(value).split("|")
        if len(or_values) > 100:
            raise ValueError(
                f"filter {key!r} has {len(or_values)} OR-separated values; "
                "OpenAlex allows at most 100 per filter"
            )


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "query"


def _canonical_query_id(
    query: str,
    filters: dict[str, str] | None,
    select: str | None,
    per_page: int,
) -> str:
    """Derive a stable, filesystem-safe id from the query shape.

    Used as the default cache key so that re-running the same search reuses
    the same cache directory, while a materially different search (a
    different filter, a different select) gets its own directory instead of
    silently mixing pages from two different queries.
    """
    canonical = json.dumps(
        {"query": query, "filters": filters or {}, "select": select, "per_page": per_page},
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
    return f"{_slugify(query)}_{digest}"


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _load_meta(meta_path: Path) -> dict[str, Any] | None:
    if not meta_path.exists():
        return None
    with meta_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_meta(meta_path: Path, meta: dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with meta_path.open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, sort_keys=True)


def openalex_search(
    query: str,
    *,
    mailto: str,
    per_page: int = 100,
    max_records: int | None = None,
    filters: dict[str, str] | None = None,
    select: str | None = DEFAULT_SELECT,
    api_key: str | None = None,
    request_pause: float = 0.25,
    cache_dir: str | Path | None = None,
    query_id: str | None = None,
    force: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield works matching `query` from OpenAlex, page by page.

    Args:
        query: full-text search expression (passed to `search`).
        mailto: contact email; required for the polite pool and sent both
            as a query parameter and in the User-Agent header.
        per_page: 1..100 (`MAX_PER_PAGE`); larger values are refused.
        max_records: stop after this many records (None = all).
        filters: OpenAlex filters, e.g. `{"from_publication_date": "2015-01-01"}`.
            OR-values within one filter (`"article|preprint"`) are capped
            at 100 per OpenAlex's documented limit.
        select: comma-separated response fields; `None` returns full
            records. Defaults to a screening-oriented field set.
        api_key: optional OpenAlex API key (premium tier), sent as a bearer
            token. Not required for standard access.
        request_pause: base seconds to sleep between pages, plus jitter, so
            repeated scheduled runs do not synchronize.
        cache_dir: when given, every fetched page is appended to
            `<cache_dir>/<query_id>/records.jsonl` immediately, and a
            `meta.json` sidecar records the query spec and cursor. Stored
            records are always served first. A completed query never hits
            the network, and an unfinished one (interrupted, or stopped by
            `max_records`) continues with the first page it does not hold.
        query_id: cache key; derived from the query/filters/select/per_page
            when omitted, so identical searches share a cache directory.
        force: ignore an existing cache and re-fetch from scratch.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if not mailto.strip():
        raise ValueError("mailto must not be empty")
    if not 1 <= per_page <= MAX_PER_PAGE:
        raise ValueError(f"per_page must be between 1 and {MAX_PER_PAGE}")
    if filters:
        _validate_filters(filters)

    cache_path: Path | None = None
    records_path: Path | None = None
    meta_path: Path | None = None
    meta: dict[str, Any] | None = None
    cached = 0  # records handed out from the cache before any request is sent

    if cache_dir is not None:
        resolved_id = query_id or _canonical_query_id(query, filters, select, per_page)
        cache_path = Path(cache_dir) / resolved_id
        records_path = cache_path / "records.jsonl"
        meta_path = cache_path / "meta.json"
        meta = None if force else _load_meta(meta_path)

        if force and records_path.exists():
            records_path.unlink()

        if meta is not None:
            stored = _count_jsonl(records_path)
            complete = meta.get("status") == "complete"

            # Refuse an unusable entry before the first record is handed out.
            if not complete and meta.get("cache_format") != CACHE_FORMAT:
                # Entries from before format 2 do not record where the next
                # page starts, so they can be read but not continued.
                if stored and (max_records is None or max_records > stored):
                    raise OpenAlexError(
                        f"cache entry {resolved_id!r} was written by an older version and "
                        f"cannot be resumed. It holds {stored} records. Rerun with --max "
                        f"{stored} or less to use them, or with --force to fetch the "
                        "search again."
                    )
                if not stored:
                    meta.update({"cache_format": CACHE_FORMAT, "cursor": "*", "fetched": 0})
            elif not complete and stored != meta["fetched"]:
                raise OpenAlexError(
                    f"cache entry {resolved_id!r} is inconsistent ({stored} records stored, "
                    f"{meta['fetched']} expected). Rerun with --force to fetch the search again."
                )

            # Whatever is already stored is served first, so a repeated or
            # resumed search never requests a page it already holds.
            logger.info("Serving %d cached records for query_id=%s", stored, resolved_id)
            for cached, record in enumerate(_read_jsonl(records_path), start=1):
                yield record
                if max_records is not None and cached >= max_records:
                    return
            if complete:
                return
        else:
            meta = {
                "query_id": resolved_id,
                "query": query,
                "filters": filters or {},
                "select": select,
                "per_page": per_page,
                "script_version": __version__,
                "cache_format": CACHE_FORMAT,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "cursor": "*",
                "fetched": 0,
                "status": "in_progress",
            }
            _write_meta(meta_path, meta)

    cursor = meta["cursor"] if meta else "*"
    yielded = cached

    session = make_session(mailto, api_key=api_key)
    params: dict[str, str | int] = {
        "search": query,
        "per_page": per_page,
        "mailto": mailto,
    }
    if filters:
        params["filter"] = ",".join(f"{k}:{v}" for k, v in filters.items())
    if select:
        params["select"] = select

    manual_429_retries = 0
    max_manual_429_retries = 5

    try:
        while cursor:
            params["cursor"] = cursor
            response = session.get(OPENALEX_WORKS, params=params, timeout=(10, 60))

            if response.status_code == 429:
                manual_429_retries += 1
                if manual_429_retries > max_manual_429_retries:
                    raise OpenAlexError(
                        f"OpenAlex kept returning 429 after {max_manual_429_retries} "
                        "manual retries (transport-level retries already exhausted)"
                    )
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 10.0
                logger.warning("Rate limited; sleeping for %.1f seconds", delay)
                time.sleep(delay)
                continue
            manual_429_retries = 0

            response.raise_for_status()
            payload = response.json()

            logger.info(
                "OpenAlex request: cost=%s remaining=%s total_results=%s",
                response.headers.get("X-RateLimit-Credits-Used"),
                response.headers.get("X-RateLimit-Remaining"),
                payload.get("meta", {}).get("count"),
            )

            results = payload.get("results", [])
            next_cursor = payload.get("meta", {}).get("next_cursor") if results else None

            # The cache state describes what is stored on disk. It is
            # written before any record of this page is handed out, so it
            # stays correct when `max_records` stops the search mid-page.
            if meta_path is not None:
                if results:
                    _append_jsonl(records_path, results)
                meta["fetched"] += len(results)
                meta["cursor"] = next_cursor or ""
                meta["status"] = "complete" if not next_cursor else "in_progress"
                meta["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_meta(meta_path, meta)

            for work in results:
                yield work
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return

            cursor = next_cursor
            if not cursor:
                break

            time.sleep(request_pause + random.uniform(0, 0.15))
    finally:
        session.close()


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """OpenAlex stores abstracts as an inverted index for licensing reasons.

    Defensive against malformed data: non-list position values and
    non-integer positions for a word are skipped rather than raising, since
    an absent/broken abstract here just means OpenAlex didn't provide a
    clean one for this record, not that the whole ingest should fail.
    """
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        if not isinstance(idxs, list):
            continue
        for i in idxs:
            if isinstance(i, int):
                positions.append((i, word))
    positions.sort()
    return " ".join(word for _, word in positions)


def work_to_ris(work: dict[str, Any]) -> str:
    """Convert one OpenAlex work to a RIS record."""
    title = (work.get("title") or "").replace("\n", " ").strip()
    year = str(work.get("publication_year") or "")
    full_date = work.get("publication_date") or ""
    doi = normalize_doi(work.get("doi") or "")
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    primary = work.get("primary_location") or {}
    src = primary.get("source") or {}
    journal = src.get("display_name") or ""
    ris_type = _TYPE_TO_RIS.get(work.get("type") or "", "GEN")
    doc_id = compute_doc_id(doi, title, year)

    lines = [f"TY  - {ris_type}", f"ID  - {doc_id}", f"TI  - {title}"]
    for au in work.get("authorships", [])[:50]:
        name = (au.get("author") or {}).get("display_name")
        if name:
            lines.append(f"AU  - {name}")
    if year:
        lines.append(f"PY  - {year}")
    if full_date:
        lines.append(f"DA  - {full_date}")
    if journal:
        lines.append(f"JO  - {journal}")
    if doi:
        lines.append(f"DO  - {doi}")
    for kw in (work.get("keywords") or [])[:20]:
        kw_text = kw.get("display_name") if isinstance(kw, dict) else str(kw)
        if kw_text:
            lines.append(f"KW  - {kw_text}")
    if abstract:
        lines.append(f"AB  - {abstract}")
    openalex_id = work.get("id")
    if openalex_id:
        lines.append(f"N1  - openalex:{openalex_id}")
    lines.append("ER  - ")
    lines.append("")
    return "\n".join(lines)

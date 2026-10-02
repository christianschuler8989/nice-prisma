"""Cache behaviour of the OpenAlex client. No test here contacts OpenAlex:
`make_session` is replaced by a fake that serves canned pages and records
which cursors were requested.
"""
import json

import pytest

from prisma.ingest import openalex
from prisma.ingest.openalex import OpenAlexError, openalex_search

WORKS = [{"id": f"W{i}", "title": f"Title {i}"} for i in range(1, 6)]

PAGES = {
    "*": {"results": WORKS[:3], "meta": {"next_cursor": "c2", "count": 5}},
    "c2": {"results": WORKS[3:], "meta": {"next_cursor": "c3", "count": 5}},
    "c3": {"results": [], "meta": {"next_cursor": None, "count": 5}},
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.requested_cursors = []

    def get(self, _url, params, timeout):
        self.requested_cursors.append(params["cursor"])
        return FakeResponse(PAGES[params["cursor"]])

    def close(self):
        return None


@pytest.fixture
def session(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(openalex, "make_session", lambda mailto, api_key=None: fake)
    monkeypatch.setattr(openalex.time, "sleep", lambda _seconds: None)
    return fake


def _search(cache_dir, **kwargs):
    return list(
        openalex_search("some query", mailto="test@example.com", per_page=3, cache_dir=cache_dir, **kwargs)
    )


def _ids(works):
    return [w["id"] for w in works]


def test_search_cut_short_by_max_is_served_from_cache_on_repeat(tmp_path, session):
    first = _search(tmp_path, max_records=2)
    second = _search(tmp_path, max_records=2)

    assert _ids(first) == ["W1", "W2"]
    assert _ids(second) == ["W1", "W2"]
    assert session.requested_cursors == ["*"]


def test_unfinished_search_continues_with_the_first_missing_page(tmp_path, session):
    _search(tmp_path, max_records=2)
    everything = _search(tmp_path)

    assert _ids(everything) == ["W1", "W2", "W3", "W4", "W5"]
    assert session.requested_cursors == ["*", "c2", "c3"]

    again = _search(tmp_path)
    assert _ids(again) == ["W1", "W2", "W3", "W4", "W5"]
    assert session.requested_cursors == ["*", "c2", "c3"]


def test_cache_holds_every_fetched_record_exactly_once(tmp_path, session):
    _search(tmp_path, max_records=2)
    _search(tmp_path, max_records=4)
    _search(tmp_path)

    (entry,) = tmp_path.iterdir()
    lines = (entry / "records.jsonl").read_text(encoding="utf-8").splitlines()
    meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))

    assert _ids(json.loads(line) for line in lines) == ["W1", "W2", "W3", "W4", "W5"]
    assert meta["fetched"] == 5
    assert meta["status"] == "complete"


def _write_legacy_entry(cache_dir):
    """An unfinished entry as written before cache format 2 (no `cache_format`,
    cursor pointing at the page that is already stored)."""
    entry = cache_dir / "legacy"
    entry.mkdir()
    with (entry / "records.jsonl").open("w", encoding="utf-8") as handle:
        for work in WORKS[:3]:
            handle.write(json.dumps(work) + "\n")
    meta = {"query_id": "legacy", "cursor": "*", "fetched": 2, "status": "in_progress"}
    (entry / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_legacy_entry_is_served_when_it_holds_enough_records(tmp_path, session):
    _write_legacy_entry(tmp_path)

    works = _search(tmp_path, query_id="legacy", max_records=3)

    assert _ids(works) == ["W1", "W2", "W3"]
    assert session.requested_cursors == []


def test_legacy_entry_refuses_to_resume(tmp_path, session):
    _write_legacy_entry(tmp_path)

    with pytest.raises(OpenAlexError, match="cannot be resumed"):
        _search(tmp_path, query_id="legacy", max_records=5)
    assert session.requested_cursors == []


def test_force_fetches_again(tmp_path, session):
    _write_legacy_entry(tmp_path)

    works = _search(tmp_path, query_id="legacy", force=True)

    assert _ids(works) == ["W1", "W2", "W3", "W4", "W5"]
    assert session.requested_cursors == ["*", "c2", "c3"]


def test_page_size_above_recommendation_is_refused(tmp_path):
    with pytest.raises(ValueError, match="per_page"):
        list(openalex_search("some query", mailto="test@example.com", per_page=101, cache_dir=tmp_path))

import pytest

from prisma.ingest.identity import compute_doc_id, doc_id_from_filename
from prisma.tracking.eligibility import apply_template, write_template
from prisma.tracking.registry import DocEntry, Registry, compute_prisma_counts
from prisma.tracking.retrieval import link_retrieval

DEDUP_META = {
    "identified_per_source": {"openalex-a": 3, "openalex-b": 2},
    "duplicates_removed": 1,
    "deduplicated": 4,
}


def _registry() -> Registry:
    registry = Registry()
    decisions = {"doc-a": "include", "doc-b": "maybe", "doc-c": "exclude", "doc-d": "include"}
    for doc_id, decision in decisions.items():
        registry.upsert(DocEntry(doc_id=doc_id, title=f"Title {doc_id}", screening={"decision": decision}))
    return registry


def _pdfs_dir(tmp_path, names):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    for name in names:
        (pdfs / name).write_bytes(b"%PDF-1.4")
    return pdfs


def test_doc_id_is_stable_across_doi_spellings():
    plain = compute_doc_id("10.1234/abc", "Some title", "2020")
    url = compute_doc_id("https://doi.org/10.1234/ABC", "Another title", "1999")
    assert plain == url
    assert plain.startswith("doc-")


def test_doc_id_from_filename():
    assert doc_id_from_filename("doc-0123456789ab.pdf") == "doc-0123456789ab"
    assert doc_id_from_filename("doc-0123456789ab__hassani2016.pdf") == "doc-0123456789ab"


def test_retrieval_does_not_seek_records_excluded_at_screening(tmp_path):
    registry = _registry()
    pdfs = _pdfs_dir(tmp_path, ["doc-a.pdf", "doc-b__readable-name.pdf", "doc-c.pdf", "stray.pdf"])

    result = link_retrieval(registry, pdfs)

    assert sorted(doc_id for doc_id, _pdf in result.matched) == ["doc-a", "doc-b"]
    assert result.not_retrieved == ["doc-d"]
    assert result.not_sought == ["doc-c"]
    assert [p.name for p in result.not_sought_pdfs] == ["doc-c.pdf"]
    assert [p.name for p in result.unmatched_pdfs] == ["stray.pdf"]
    assert registry.get("doc-c").retrieval == {"status": "not_sought", "pdf": None}
    assert registry.get("doc-d").retrieval == {"status": "not_retrieved", "pdf": None}


def test_retrieval_uses_the_manifest_for_unconventional_names(tmp_path):
    registry = _registry()
    pdfs = _pdfs_dir(tmp_path, ["hassani2016.pdf"])

    result = link_retrieval(registry, pdfs, manifest={"doc-d": "hassani2016.pdf"})

    assert [doc_id for doc_id, _pdf in result.matched] == ["doc-d"]
    assert result.unmatched_pdfs == []


def test_counts_follow_the_registry(tmp_path):
    registry = _registry()
    pdfs = _pdfs_dir(tmp_path, ["doc-a.pdf", "doc-b.pdf"])
    link_retrieval(registry, pdfs)

    sheet = tmp_path / "review.csv"
    assert write_template(registry, sheet) == 2
    sheet.write_text(
        "doc_id,title,pdf,decision,reason\n"
        "doc-a,Title doc-a,doc-a.pdf,include,\n"
        "doc-b,Title doc-b,doc-b.pdf,exclude,Off-topic on full read\n",
        encoding="utf-8",
    )
    applied, left_blank = apply_template(registry, sheet)
    assert (applied, left_blank) == (2, [])

    counts = compute_prisma_counts(registry, DEDUP_META)

    assert counts.identified_per_source == {"openalex-a": 3, "openalex-b": 2}
    assert counts.deduplicated == 4
    assert counts.duplicates_removed == 1
    assert counts.screened_title_abstract == 4
    assert counts.excluded_title_abstract == 1
    assert counts.sought_for_retrieval == 3
    assert counts.not_retrieved == 1
    assert counts.assessed_full_text == 2
    assert counts.excluded_full_text == {"Off-topic on full read": 1}
    assert counts.included == 1


def test_registry_survives_a_save_and_load_round_trip(tmp_path):
    registry = _registry()
    path = tmp_path / "registry.jsonl"

    registry.save(path)
    loaded = Registry.load(path)

    assert len(loaded) == 4
    assert loaded.get("doc-b").screening == {"decision": "maybe"}


def test_exclusion_without_a_reason_is_rejected(tmp_path):
    registry = _registry()
    sheet = tmp_path / "review.csv"
    sheet.write_text("doc_id,title,pdf,decision,reason\ndoc-a,Title,doc-a.pdf,exclude,\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must have a reason"):
        apply_template(registry, sheet)

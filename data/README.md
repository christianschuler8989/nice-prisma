# data/

Default location for everything a nice-prisma run downloads or produces.
The whole directory is covered by `.gitignore`. Only this README is tracked.

No command hardcodes these paths. Every CLI command takes explicit `--out` /
`--in` arguments, so the layout below is a convention, followed by the
Quickstart in the top-level `README.md`.

## Layout

```
data/
├── README.md                    this file (the only tracked file)
├── library/                     shared across all surveys and iterations
│   └── openalex/
│       └── <query_id>/          one directory per distinct search
│           ├── records.jsonl    raw OpenAlex works, appended page by page
│           └── meta.json        query spec, cursor, status, timestamps
└── surveys/
    └── <survey>/                one directory per survey
        ├── ingest/              one RIS file per query
        ├── merge/               output of `prisma ingest dedup`
        ├── screening/           output of `prisma screen`
        ├── pdfs/                retrieved full texts
        ├── eligibility/         full-text review sheets (filled in by a human)
        ├── extraction/          output of `prisma extract`
        ├── quality/             output of `prisma quality`
        └── report/              counts JSON and PRISMA flow diagram
```

## library/

Content that was fetched from an external service. It is kept once and reused
by every survey, so the same search is never sent to a service twice.

`library/openalex/` is the cache directory of `prisma ingest openalex`
(pass `--cache-dir data/library/openalex`). The `<query_id>` is derived from
the query text, filters, selected fields and page size, so two surveys that
run the same search share one cache entry.

## surveys/&lt;survey&gt;/merge/

| File | Content |
|---|---|
| `corpus-deduplicated.ris` | Unique records, each with its `doc_id` in the RIS `ID` tag |
| `corpus-deduplicated.csv` | Same records as a table, first column `doc_id` |
| `corpus-dedup-report.md` | Human-readable duplicate audit trail |
| `corpus-dedup-meta.json` | Records identified per source, duplicates removed, unique total |
| `corpus-identity-crosswalk.csv` | `doc_id` of every removed duplicate mapped to its canonical `doc_id` |
| `corpus-registry.jsonl` | Tracking registry, one line per canonical document, updated by screening, retrieval and eligibility |

## surveys/&lt;survey&gt;/pdfs/

A PDF is linked to its record through its file name. Name it `<doc_id>.pdf`
or `<doc_id>__<any-readable-suffix>.pdf`, for example
`doc-5c47f5bf144b__hassani2016.pdf`. PDFs that cannot be renamed can be listed
in a `doc_id,pdf` manifest CSV passed to `prisma tracking retrieval --manifest`.

## Size

OpenAlex cache entries are about 0.5 MB per 100 records. PDFs dominate disk
usage (the 33 PDFs of the Kurdish test set take about 210 MB).

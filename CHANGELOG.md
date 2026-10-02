# Changelog

All notable changes to `nice-prisma` are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

nice-prisma is a fork of `proportione-prisma` 0.1.0. The history of the original project is kept at the end of this file.

## [Unreleased]

## [0.2.0] (2026-10-02)

First version of nice-prisma. Outputs and workflows are not compatible with `proportione-prisma` 0.1.0 (new `doc_id` columns, new files written by `prisma ingest dedup`, counts derived from the registry).

### Added

- `prisma.ingest.openalex`: retry with exponential backoff, `Retry-After` handling, sequential requests with jittered pauses, contact email in query and User-Agent.
- `prisma.ingest.openalex`: raw page cache (`records.jsonl` + `meta.json` per query, `--cache-dir`, `--no-cache`, `--query-id`, `--force`). Stored records are always served first, and an unfinished search (interrupted, or stopped by `--max`) continues with the first page it does not hold.
- `prisma.ingest.identity`: deterministic `doc_id` per record (DOI-based, title + year as fallback), stored in the RIS `ID` tag and written to every CSV.
- `prisma ingest dedup`: `<basename>-dedup-meta.json`, `<basename>-identity-crosswalk.csv` and `<basename>-registry.jsonl` next to the existing outputs.
- `prisma.tracking`: document registry shared by all stages, PDF-to-record linking by file name or manifest, full-text eligibility sheets, PRISMA counts derived from the registry.
- CLI: `prisma tracking retrieval | eligibility-template | eligibility-apply | counts`, `prisma screen --registry`, `doc_id` column in `prisma extract` and `prisma quality`.
- `data/` as default in-repository location for working data, ignored by git, layout documented in `data/README.md`.
- `examples/kurdish/`: screening rules, extraction taxonomy and counts of the Kurdish dialectology / Kurdish NLP example survey, with `examples/README.md`.
- Roadmap, design principles and known limitations in `README.md`.
- Tests for the OpenAlex cache (without network access), document identity and `prisma.tracking`.

### Changed

- Distribution renamed from `proportione-prisma` to `nice-prisma`. The import package and the CLI command stay `prisma`.
- OpenAlex page size is capped at 100 (was 200).
- User-Agent is `nice-prisma/<version>`.
- `prisma ingest openalex` writes to `<out>.part` and renames it on success, so a failed search leaves an existing RIS file untouched.
- `prisma tracking retrieval` marks records excluded at screening as `not_sought`. They no longer count as sought for retrieval or as not retrieved.
- README, CONTRIBUTING, CITATION, methodology notes and the Streamlit demo describe nice-prisma and credit the original project.

### Removed

- Signal-KPI example files (`examples/*signal_kpi*`, `examples/prisma_counts_demo.json`, `docs/taxonomy/signal-kpi.md`).

## Upstream history (`proportione-prisma`)

Entries below describe the original project at <https://github.com/Proportione/prisma>.

### Unreleased upstream at the time of the fork

- `prisma.stats`: reviewer-proof correlation/robustness helpers. Includes `fisher_ci`, `correlation_table` (Pearson + Fisher-z CI + Spearman, overall and per stratum), `partial_correlation`, `bootstrap_ci` (small-cell fragility), `missingness_compare` (selection-bias check via Mann-Whitney), and `mixed_model_icc` (random-intercept clustering + ICC; optional `statsmodels` extra). New `prisma correlate` CLI command. Adds `scipy` as a core dependency and a `[stats]` optional extra. Extracted while hardening the statistical rigour of the 20-60-20 AI-permitted-assessment study (Cuervo, 2026, Universidade de Aveiro).
- Pub1-Fusion (Cuervo & Marques, 2026, *From search queries to strategic decisions: a hybrid systematic and bibliometric review of digital signals in business forecasting*) submitted to International Journal of Information Management. Citation slot reserved for the next release once the editorial decision lands.

### 0.1.0 (2026-04-29)

- Initial public release.
- `prisma.ingest`: OpenAlex search, Unpaywall PDF discovery, RIS I/O, cross-source deduplication (DOI matching plus rapidfuzz title-author similarity).
- `prisma.screening`: two-tier rule engine (hard exclusion + multi-group inclusion), YAML-defined, full audit log.
- `prisma.extraction`: PyMuPDF text extraction, section detection, taxonomy-driven field extraction.
- `prisma.quality`: MMAT 2018 quantitative-descriptive heuristic scoring (Q1–Q5, High/Medium/Low).
- `prisma.reporting`: PRISMA 2020 flow diagram from `PRISMACounts` dataclass.
- `prisma.bibliometrics`: VOSviewer `.net` loader, Louvain communities, co-occurrence matrix.
- `prisma.viz`: matplotlib config with the Proportione brand palette.
- Streamlit demo (`streamlit_app/`) walking through the full pipeline.
- CLI (`prisma`) covering ingest / screen / extract / quality / report.
- Zenodo archive with DOI [`10.5281/zenodo.19883809`](https://doi.org/10.5281/zenodo.19883809).
- Cited in: Pub3-v2 (Cuervo & Marques, 2026, ibero-american bibliometric mapping, under review at CIDEMA II McGraw Hill).

# nice-prisma

**A service-friendly Python toolkit for PRISMA-based literature surveys.**

[![CI](https://github.com/christianschuler8989/nice-prisma/actions/workflows/ci.yml/badge.svg)](https://github.com/christianschuler8989/nice-prisma/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

nice-prisma supports the automatable parts of a PRISMA 2020 literature survey. It ingests records from OpenAlex, deduplicates across queries, screens titles and abstracts with traceable YAML rule sets, tracks every document across all stages, extracts structured fields from full texts, scores quality with MMAT 2018, and renders the PRISMA 2020 flow diagram from tracked counts.

nice-prisma is developed and maintained by Christian Schuler and is under active development (see [Roadmap](#roadmap)). It builds on an earlier open-source toolkit, which is credited under [Origin and credit](#origin-and-credit).

## What "nice" means

Every service this tool talks to is run by someone else, often for free. nice-prisma treats that as a hard design constraint.

- **Stay within recommended values.** If a service recommends a page size of 100, the tool refuses to ask for more. The same holds for documented limits such as 100 OR-values per OpenAlex filter.
- **Identify yourself.** Every request carries a contact email (`--mailto`) and a `nice-prisma/<version>` User-Agent.
- **One request at a time.** Requests are sequential, with a pause and random jitter between pages.
- **Back off when asked.** `Retry-After` headers are honoured, and retries on 429 and 5xx responses use exponential backoff with a hard upper bound.
- **Never fetch the same thing twice.** Every fetched page is written to a local cache right away. A repeated search is served from that cache, and an unfinished one continues with the first page it does not hold yet.

New code that touches the network has to follow the same rules (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Install

nice-prisma is installed from source. It is not published on PyPI.

```bash
git clone https://github.com/christianschuler8989/nice-prisma.git
cd nice-prisma
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # CLI + library
pip install -e ".[streamlit]"    # + Streamlit demo
pip install -e ".[dev]"          # + pytest, ruff, mypy
```

Python 3.10+. The import package and the CLI command are both called `prisma`.

## Quickstart

The walkthrough below runs the Kurdish example survey that ships in [`examples/kurdish/`](examples/README.md). It combines two OpenAlex queries, "Kurdish dialectology" and "Kurdish natural language processing". All output goes to `data/`, which is ignored by git (see [Data layout](#data-layout)).

```bash
S=data/surveys/kurdish
REG=$S/merge/corpus-registry.jsonl

# 1. Ingest. One RIS file per query, raw OpenAlex pages cached in the shared library.
prisma ingest openalex \
  --query "Kurdish dialectology" \
  --max 50 \
  --mailto you@example.com \
  --cache-dir data/library/openalex \
  --out $S/ingest/dialectology.ris

prisma ingest openalex \
  --query "Kurdish natural language processing nlp" \
  --max 50 \
  --mailto you@example.com \
  --cache-dir data/library/openalex \
  --out $S/ingest/nlp.ris

# 2. Merge and deduplicate. This seeds the tracking registry.
prisma ingest dedup \
  -s openalex-dialectology=$S/ingest/dialectology.ris \
  -s openalex-nlp=$S/ingest/nlp.ris \
  --out $S/merge

# 3. Screen titles and abstracts, record the decisions in the registry.
prisma screen \
  --in $S/merge/corpus-deduplicated.ris \
  --rules examples/kurdish/screening_rules.yaml \
  --out $S/screening \
  --registry $REG

# 4. Retrieval. Collect the PDFs by hand into $S/pdfs, named <doc_id>__<anything>.pdf,
#    then link them to their records.
mkdir -p $S/pdfs
prisma tracking retrieval --registry $REG --pdfs $S/pdfs

# 5. Full-text eligibility. A human fills in `decision` and `reason` in the sheet.
prisma tracking eligibility-template --registry $REG --out $S/eligibility/review.csv
prisma tracking eligibility-apply --registry $REG --in $S/eligibility/review.csv

# 6. Extract structured fields and score quality (MMAT 2018).
prisma extract \
  --pdfs $S/pdfs \
  --taxonomy examples/kurdish/extraction_taxonomy.yaml \
  --out $S/extraction/extracted.csv
prisma quality --pdfs $S/pdfs --out $S/quality/mmat.csv

# 7. Derive the counts from the registry and render the PRISMA 2020 flow diagram.
prisma tracking counts \
  --dedup-meta $S/merge/corpus-dedup-meta.json \
  --registry $REG \
  --out $S/report/prisma-counts.json
prisma report --counts $S/report/prisma-counts.json --out $S/report/prisma-flow.png
```

To try the reporting step alone, without touching any service, render the shipped counts of an earlier test run.

```bash
prisma report --counts examples/kurdish/prisma_counts.json --out data/surveys/kurdish/report/prisma-flow.png
```

The Streamlit demo shows screening, extraction, quality scoring and bibliometrics interactively.

```bash
streamlit run streamlit_app/Home.py
```

## Document tracking

Every record receives a `doc_id` at ingest time (`doc-<hash>`, derived from the DOI, or from normalised title and year if there is no DOI). The `doc_id` travels in the RIS `ID` tag and appears as a column in every CSV the tool writes.

`prisma ingest dedup` seeds a registry (`corpus-registry.jsonl`) with one entry per unique document. Screening, retrieval and eligibility each write their result onto that entry. Records excluded at screening are not sought for retrieval, records marked `include` or `maybe` are. `prisma tracking counts` aggregates the registry into the numbers of the PRISMA flow diagram, so no count is typed in by hand.

## Data layout

```
data/
├── library/openalex/<query_id>/     raw OpenAlex pages, shared across surveys
└── surveys/<survey>/
    ├── ingest/  merge/  screening/  pdfs/
    └── eligibility/  extraction/  quality/  report/
```

Details, including the files each stage writes, are in [`data/README.md`](data/README.md). The layout is a convention. Every command takes explicit paths, so the data can live anywhere.

## What's in the box

| Module | What it does |
|---|---|
| `prisma.ingest` | Polite OpenAlex search with page cache and resume, RIS I/O, `doc_id` identity, cross-source dedup (DOI + rapidfuzz), Unpaywall lookup |
| `prisma.tracking` | Registry of all documents, PDF-to-record linking, full-text eligibility sheets, PRISMA counts |
| `prisma.screening` | Two-tier rule engine (hard exclusion + multi-group inclusion), YAML-defined, full audit log |
| `prisma.extraction` | PyMuPDF text extraction, section detection, taxonomy-driven field extraction |
| `prisma.quality` | MMAT 2018 quantitative-descriptive heuristic scoring (Q1 to Q5, High/Medium/Low) |
| `prisma.reporting` | PRISMA 2020 flow diagram from a `PRISMACounts` dataclass |
| `prisma.bibliometrics` | VOSviewer `.net` loader, Louvain communities, co-occurrence matrix |
| `prisma.stats` | Correlation tables with confidence intervals, partial correlation, bootstrap, mixed-model ICC |
| `prisma.viz` | Matplotlib style configuration |

## Repository layout

| Path | Content |
|---|---|
| `src/prisma/` | The Python package (modules listed above) and the CLI (`cli.py`) |
| `examples/` | Configuration of the example surveys, see [`examples/README.md`](examples/README.md) |
| `data/` | Local working data, ignored by git, see [`data/README.md`](data/README.md) |
| `docs/` | Methodology background (`methodology.md`) |
| `streamlit_app/` | Streamlit demo (`Home.py` and one page per stage) |
| `tests/` | pytest suite |
| `CHANGELOG.md` | Changes in nice-prisma, followed by the upstream history |
| `CONTRIBUTING.md` | Setup, checks before a pull request, rules for network code |
| `CITATION.cff` | Citation metadata, including the reference to the original toolkit |

## Roadmap

### Next

- Rebuild the Unpaywall helpers so that they follow the rules above.
- Replace the inherited colour theme and move Streamlit uploads into `data/`.

### Publication tracking across steps and iterations

A publication that shows up in any query of any survey is recorded once and stays known. Metadata that was already downloaded (for example from OpenAlex) and full texts that were already collected are kept and reused. Nothing that is already available locally gets downloaded again. This goes beyond the current per-survey registry and per-query cache, and it requires a shared record store with defined data structures, schemas and naming conventions. It is the foundation for everything below.

### Streamlined, repeatable surveys

With persistent tracking in place, a survey becomes a described process that can be re-run and extended. A new iteration of a survey (new queries, updated rules, a later point in time) only processes what is new and keeps all earlier decisions.

### Automatic collection of full texts

Automatic download of PDFs for the publications that passed screening, limited to legal open-access sources and following the same rules as every other network access in this tool.

### Annotation platform for human review

A low-friction interface for the qualitative review of the collected literature. Human reviewers read, annotate and decide, and their decisions flow back into the tracked records.

## Known limitations

- The helpers in `prisma.ingest.unpaywall` predate this fork. They do not yet follow the rules above and are not wired into the CLI.
- MMAT scores and extracted fields are heuristics based on pattern matching. They support a human reviewer and do not replace one.

## Methodology references

- **PRISMA 2020.** Page, M.J. et al. (2021). *BMJ* 372:n71. https://doi.org/10.1136/bmj.n71
- **MMAT 2018.** Hong, Q.N. et al. (2018). *Education for Information* 34:285-291. https://doi.org/10.3233/EFI-180221
- **Case Survey Method.** Larsson, R. (1993). *Academy of Management Journal* 36(6):1515-1546.
- **Bibliometric methods.** Donthu, N. et al. (2021). *Journal of Business Research* 133:285-296.

More detail in [`docs/methodology.md`](docs/methodology.md).

## Origin and credit

nice-prisma started as a fork of [PRISMA](https://github.com/Proportione/prisma) (`proportione-prisma` 0.1.0, DOI [10.5281/zenodo.19883809](https://doi.org/10.5281/zenodo.19883809)), written by Javier Cuervo and Rui Pedro Figueiredo Marques and released by Proportione, LDA under the MIT licence. The screening engine, the extraction, quality, reporting, bibliometrics and statistics modules and the Streamlit demo come from that project. Thank you for making it available.

nice-prisma changes the ingestion client, adds document identity and tracking, replaces the examples, and follows its own roadmap. It is an independent project, maintained by Christian Schuler. The original authors are not responsible for it and have not endorsed it.

## How to cite

Citation metadata is in [`CITATION.cff`](CITATION.cff). If you use the parts inherited from the original toolkit, please cite the original software as well.

## Trademark / endorsement notice

This toolkit helps authors comply with the **PRISMA 2020 reporting standard**. It is not affiliated with, endorsed by, or sponsored by the PRISMA Statement Group or the EQUATOR Network. Users remain responsible for following the official PRISMA 2020 checklist when reporting.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT, see [LICENSE](LICENSE). Copyright © 2026 Christian Schuler, and © 2026 Proportione, LDA for the parts inherited from the original toolkit.

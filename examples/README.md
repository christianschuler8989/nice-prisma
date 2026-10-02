# Examples

Each subdirectory holds the configuration of one example survey. Only small,
hand-written configuration files live here. Everything a run produces goes to
`data/` (see [`data/README.md`](../data/README.md)).

| Path | Content |
|---|---|
| `kurdish/screening_rules.yaml` | Title-abstract screening rules (`prisma screen --rules`) |
| `kurdish/extraction_taxonomy.yaml` | Full-text extraction taxonomy (`prisma extract --taxonomy`) |
| `kurdish/prisma_counts.json` | Counts of a small test run on 2026-09-23, usable as input for `prisma report --counts` without running the pipeline |

## The Kurdish example survey

A small two-query survey on Kurdish dialectology and Kurdish natural language
processing. Both queries go to OpenAlex with `--max 50`, which keeps the load
on the service at one request per query.

| Source label | OpenAlex query |
|---|---|
| `openalex-dialectology` | `Kurdish dialectology` |
| `openalex-nlp` | `Kurdish natural language processing nlp` |

The screening rules exclude Aramaic studies and include records that mention
a Kurdish variety and an NLP topic. The extraction taxonomy codes four fields
per PDF (`dialect_variety`, `nlp_task`, `resource_type`, `script_orthography`).

The complete command sequence is the Quickstart in the top-level
[`README.md`](../README.md).

## Adding your own survey

Copy `kurdish/` to `examples/<your-survey>/`, edit the patterns, and use
`data/surveys/<your-survey>/` as the output location. The engines do not
care about the specific labels. Whatever matches a pattern becomes the value.

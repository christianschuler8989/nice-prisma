# Contributing

Thanks for considering a contribution.

## Setup

```bash
git clone https://github.com/christianschuler8989/nice-prisma.git
cd nice-prisma
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,streamlit]"
```

## Before opening a PR

```bash
pytest -q
ruff check src/ tests/
```

## Rules for code that talks to a service

These rules are the reason this project exists. A change that breaks one of
them will not be merged.

- Never exceed a value the service recommends or documents (page sizes,
  request rates, batch sizes). Reject larger values with a clear error.
- Send requests one at a time, with a pause between them.
- Identify the client with a contact email and the `nice-prisma/<version>`
  User-Agent.
- Honour `Retry-After`, back off exponentially, and give up after a bounded
  number of retries.
- Write every response to the local cache before using it, and check the
  cache before sending a request. Content that is already available locally
  is never downloaded again.
- Tests never contact a live service.

## Rules for working data

- Everything a run downloads or produces goes to `data/` (layout in
  `data/README.md`) and stays out of git.
- No PDFs and no bulk corpora in the repository.
- A new kind of output gets a place in the layout and a line in
  `data/README.md` in the same change.

## What tends to get merged

- Bug fixes with a regression test.
- New or improved example surveys in `examples/<survey>/`.
- Documentation.

## What tends to get pushed back

- Heavy dependencies for niche features.
- Domain-specific logic baked into `src/prisma/`. Prefer a YAML rule set or
  taxonomy in `examples/` so that every domain stays first-class.
- Changes that break the CLI surface without a note in `CHANGELOG.md`.

## Reporting issues

Please include the following.

- `prisma --version` output
- A minimal failing example (RIS snippet, YAML rules, or PDF if non-confidential)
- The expected and the actual behaviour

# dod

Scrapes war.gov's daily DoD contract-award announcements and publishes them to
[`abigailhaddad/dod-daily-contracts`](https://huggingface.co/datasets/abigailhaddad/dod-daily-contracts)
on HuggingFace. One row per contract award (not per day) -- `date`, `agency`,
`company`, `place`, `text`, `link`, `article_title`, `row_index`. Covers the
full archive, July 2014 through present.

`company`/`place` are a best-effort extraction (see `fields.py`), not
scraped fact -- ~95% match rate, `None` rather than a guess when not
confidently found (dataset card has the details on when/why).

war.gov 403s plain HTTP clients (Akamai), so `scrape.py` drives a real,
non-headless Chrome via Playwright instead of requests/curl.

A handful of individual days (fewer than ten, out of ~3,000) are missing:
war.gov's own server errors on those specific articles, or has taken them
down entirely (404). Nothing to fix on this end.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# .env: HF_TOKEN=...

python3 scrape.py                    # most recent, back 2 years
python3 scrape.py --days-back 90
python3 scrape.py --max-articles 5 --dry-run
```

Resumable (`data/seen_articles.json`, `data/next_shard.txt`); pushes to HF in
shards of 500 rows as it goes.

## Website

[dod-daily-contracts.doj-voting-section.workers.dev](https://dod-daily-contracts.doj-voting-section.workers.dev)
-- a searchable/filterable table (agency, year, full-text search) built the
same way as `hhs-dab` and `usajobs_historical`: one Parquet file, no backend,
queried client-side via DuckDB-WASM.

```bash
python3 build_web_data.py   # flattens the HF dataset into web/data/contracts.parquet
npx wrangler deploy         # redeploy after rebuilding
```

`build_web_data.py` also normalizes the `agency` column for the filter
dropdown (the raw column carries 12 years of hand-typed variants --
"MISSLE", "DEFNSE", "LOGISITICS" -- collapsed to ~28 canonical labels); the
published dataset itself is untouched.

## company/place extraction

`fields.py` holds the regex that splits each award paragraph's opening
"Company, City, State, was awarded..." clause -- imported by
`build_web_data.py` (site) and `enrich_company_place.py` (publishes it to
the HF dataset itself). To add it to new shards after a normal scrape, or
recompute everything after changing `fields.py`:

```bash
python3 enrich_company_place.py            # adds company/place to any shard missing them
python3 enrich_company_place.py --force    # recompute for every shard (e.g. after a regex fix)
python3 enrich_company_place.py --dry-run  # report match rates, push nothing
```

One commit for the whole run, not one per shard -- HF rate-limits commits
(128/hour) well below the shard count.

## Tests

```bash
pip install -r requirements-test.txt
python3 build_web_data.py   # tests/test_company_consistency.py reads its output
pytest tests/
```

`tests/test_fields.py` is unit tests for `extract_company_place` -- one per
real edge case that broke it (small-business asterisks, "D.C." followed by
punctuation, CORRECTION/UPDATE preambles, multi-awardee lists). 
`tests/test_company_consistency.py` checks the extraction against the real
dataset: a company-field search can never match more rows than a plain text
search for the same term (company is derived from text), and shouldn't
under-match by much for a company that rarely appears as a non-first name
in a multi-awardee list (Palantir, Lockheed Martin, Boeing, ...).

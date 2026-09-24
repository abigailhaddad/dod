# dod

Scrapes war.gov's daily DoD contract-award announcements and publishes them to
[`abigailhaddad/dod-daily-contracts`](https://huggingface.co/datasets/abigailhaddad/dod-daily-contracts)
on HuggingFace. One row per contract award (not per day) -- `date`, `agency`,
`text`, `link`, `article_title`, `row_index`. Covers the full archive,
July 2014 through present.

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

# DoD Daily Contracts: handoff

## What this is

A scraper for the Defense Department's daily contract announcements (war.gov/News/Contracts), a Hugging Face dataset with one row per award, and a small website on top.

- Code: https://github.com/abigailhaddad/dod
- Data: https://huggingface.co/datasets/abigailhaddad/dod-daily-contracts (columns and known limits are on the dataset card)
- Site: https://dod-daily-contracts.abigailhaddad.com

## What runs on its own

`.github/workflows/daily.yml` is the only workflow. It runs the tests, scrapes new announcements, fills in company and place, rebuilds the site's data file and deploys the site to Cloudflare. The schedule is at the top of the file, and you can also start it from the Actions tab.

## Secrets and variables

Settings > Secrets and variables > Actions.

- `HF_TOKEN` (secret): write access to the dataset.
- `CLOUDFLARE_API_TOKEN` (secret): deploys the site.
- `CLOUDFLARE_ACCOUNT_ID` (variable, not a secret): your Cloudflare account id.

## If you take it over

- Find every place that names the current owner: `grep -rn abigailhaddad . --exclude-dir=.git --exclude-dir=data`
- `config.py` holds the dataset id (`REPO_ID`, or set `HF_DATASET_REPO`). `wrangler.jsonc` (Worker name, custom domain) and `web/index.html` (links, credit line) can't read it, so edit those by hand. `README.md` has links too.
- You don't need to create the dataset first. The scraper creates it if it's missing and rewrites the dataset card from `CARD_TEMPLATE` in `scrape.py` on every run, so edits made on Hugging Face get overwritten.
- The daily run only looks back 10 days. To fill an empty dataset, run `python3 scrape.py` on your machine once (it goes back 2 years by default; see the README).

## When it breaks

- Look at the Actions tab, "Daily scrape and deploy". A red run usually means `health.py` found a problem: the log has `[health] PROBLEM:` lines, and what was scraped before that is already saved. The rules are in `health.py`.
- The likeliest cause is war.gov changing its page layout. The scraper reads `div.body` in each article.
- war.gov refuses plain HTTP clients, so the scraper drives a real Chrome window. The workflow runs it under `xvfb-run`.
- A missed day fixes itself within 10 days. For a longer gap, run `python3 scrape.py --days-back 60` locally.

## Where to look

- The dataset is 3 files, `data/shard-00000.parquet` to `00002`, 20,000 rows each (`SHARD_SIZE` in `scrape.py`). If it ever fragments into many small files, `scripts/compact_shards.py` merges them. It's a dry run unless you pass `--upload`.
- Company and place come from `fields.py`. After changing it, run `python3 enrich_company_place.py --force`.
- `dedupe.py` skips articles war.gov re-posts under a new URL.
- Tests: `pytest tests/` (see the README).

No LLM, so there are no model costs.

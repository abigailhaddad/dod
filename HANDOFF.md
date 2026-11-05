# DoD Daily Contracts: Operator Guide

For whoever runs this next. It assumes you can read a log, not that you write Python.

## What it does

Every day at 21:00 UTC (about 4–5 pm Eastern, after war.gov posts), a GitHub Action:

1. Scrapes the last 10 days of the Department of Defense's contract announcements at war.gov/News/Contracts and adds any it hasn't seen to a Hugging Face dataset, one row per contract award.
2. Fills in the `company` and `place` columns for the new rows.
3. Rebuilds the website's data file from the dataset.
4. Deploys the website to Cloudflare.

You can also start it by hand from the repo's Actions tab ("Daily scrape and deploy", Run workflow). It times out after 30 minutes.

## Where things live

| What | Where |
|---|---|
| The data | `abigailhaddad/dod-daily-contracts` on Hugging Face |
| The dataset card (the README shown on Hugging Face) | `CARD_TEMPLATE` in `scrape.py`. The scraper rewrites the card on every run, so editing it on Hugging Face doesn't stick. |
| The website | `web/`, deployed as a Cloudflare Worker named `dod-daily-contracts` |
| The schedule and deploy steps | `.github/workflows/daily.yml` |
| Run history | The repo's Actions tab |

## Secrets

Set these under repo Settings > Secrets and variables > Actions.

| Secret | Used for |
|---|---|
| `HF_TOKEN` | Reading and writing the Hugging Face dataset. Needs write access to it. |
| `CLOUDFLARE_API_TOKEN` | Deploying the website. |

The Cloudflare account ID is not a secret here. It is typed into `daily.yml` as `CLOUDFLARE_ACCOUNT_ID`, and you need to replace it with yours.

## Changing owners: everything to edit

| File | What to change |
|---|---|
| `config.py` | `REPO_ID`, the Hugging Face dataset id. Every script reads it from here. Setting an `HF_DATASET_REPO` environment variable (or a line in `.env`) overrides it without editing code. |
| `.github/workflows/daily.yml` | `CLOUDFLARE_ACCOUNT_ID`. |
| `wrangler.jsonc` | The Worker `name` and the custom domain in `routes` (`dod-daily-contracts.abigailhaddad.com`). The domain has to be on your Cloudflare account. |
| `web/index.html` | The GitHub links on lines 36–37 and 93, the Hugging Face link on line 92, and the "Built by" credit on line 94. |
| `web/site.css` | Nothing needed. Line 6 is a comment that mentions another site. |
| `README.md` | The dataset and site links near the top. |

`wrangler.jsonc` and the files in `web/` can't read `config.py`, so they have to be edited by hand.

The dataset card in `CARD_TEMPLATE` has no owner names in it, but check it for anything you want to word differently.

## How it keeps track of what it has seen

GitHub's runner starts with an empty folder each day. When there's no local record, `scrape.py` reads the links already in the Hugging Face dataset and skips those articles. It then continues the newest shard until it holds 500 rows, and starts a new one after that. So the dataset is the source of truth. The local `data/` folder is for people running it on their own machine, and git ignores it.

Because each run looks back 10 days and skips what's already there, a missed day fixes itself within 10 days. For a longer gap, run it by hand with a bigger window, for example `python3 scrape.py --days-back 60`.

War.gov sometimes re-posts an existing article under a new URL. `dedupe.py` catches those by comparing the text with recent rows, and the log says "SKIP ... (re-post)".

## What can go wrong

**War.gov changes its page layout.** The scraper reads award paragraphs from the `div.body` element of each article. If that changes, each article fails with "no paragraphs found in div.body", is logged as `[article] FAILED`, and is skipped. From reading the code, the run then still finishes with "Done. 0 new articles scraped", so the Action can show green while adding nothing. Open the scrape step's log if the site's data looks stale. I haven't tested that failure.

**War.gov blocks the scraper.** It returns 403 to plain HTTP clients, which is why the scraper drives a real, non-headless Chrome window through Playwright, and why the workflow installs Xvfb (a virtual display) and runs `xvfb-run`. If the block gets tighter, the listing step logs `[list] page 1 FAILED` five times and stops.

**Missing days.** Fewer than ten days out of about 3,000 are missing because war.gov's server errors on those articles or has removed them. Nothing to fix.

**Hugging Face commit limits.** Hugging Face allows about 128 commits an hour. The scraper pushes one commit per shard, and `enrich_company_place.py` makes one commit per run. A full backfill can hit the limit. Wait an hour and re-run.

**Company and place are guesses.** They're extracted by a pattern match in `fields.py` and are left empty when it isn't confident. After changing `fields.py`, run `python3 enrich_company_place.py --force` to recompute every shard.

## Running it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
# put HF_TOKEN=... in a file named .env

python3 scrape.py --days-back 10 --dry-run   # scrape and shard locally, push nothing
```

`--dry-run` skips the Hugging Face upload. Check `scrape.py --help` and the README before running without it.

## Tests

```bash
pip install -r requirements-test.txt
python3 build_web_data.py   # reads the dataset from Hugging Face; writes web/data/contracts.parquet
pytest tests/
```

`tests/test_company_consistency.py` compares the extraction against `web/data/contracts.parquet`, so rebuild that file first if it's old. The CI workflow doesn't run the tests, so a regex change in `fields.py` isn't checked automatically.

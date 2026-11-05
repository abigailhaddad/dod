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

The Cloudflare account ID is not a secret. `daily.yml` reads it from a repository *variable* named `CLOUDFLARE_ACCOUNT_ID` (Settings > Secrets and variables > Actions > Variables tab). Add it with your own account ID before the first run, or the deploy step fails.

## Changing owners: everything to edit

| File | What to change |
|---|---|
| `config.py` | `REPO_ID`, the Hugging Face dataset id. Every script reads it from here. Setting an `HF_DATASET_REPO` environment variable (or a line in `.env`) overrides it without editing code. |
| Repo variable | Add `CLOUDFLARE_ACCOUNT_ID` with your Cloudflare account ID. No file edit needed. |
| `wrangler.jsonc` | The Worker `name` and the custom domain in `routes` (`dod-daily-contracts.abigailhaddad.com`). The domain has to be on your Cloudflare account. |
| `web/index.html` | The GitHub links on lines 36–37 and 93, the Hugging Face link on line 92, and the "Built by" credit on line 94. |
| `web/site.css` | Nothing needed. Line 6 is a comment that mentions another site. |
| `README.md` | The dataset and site links near the top. |

`wrangler.jsonc` and the files in `web/` can't read `config.py`, so they have to be edited by hand.

The dataset card in `CARD_TEMPLATE` has no owner names in it, but check it for anything you want to word differently.

## How it keeps track of what it has seen

GitHub's runner starts with an empty folder each day. When there's no local record, `scrape.py` reads the links already in the Hugging Face dataset and skips those articles. It then continues the newest shard until it holds 20,000 rows (`SHARD_SIZE` in `scrape.py`), and starts a new one after that. So the dataset is the source of truth. The local `data/` folder is for people running it on their own machine, and git ignores it.

Because each run looks back 10 days and skips what's already there, a missed day fixes itself within 10 days. For a longer gap, run it by hand with a bigger window, for example `python3 scrape.py --days-back 60`.

War.gov sometimes re-posts an existing article under a new URL. `dedupe.py` catches those by comparing the text with recent rows, and the log says "SKIP ... (re-post)". "Recent" means rows whose article date is within 45 days of the newest article date we hold (`RECENT_DAYS` in `scrape.py`). It reads the newest shard and the two before it, so a shard rollover doesn't shrink the window.

## What can go wrong

**War.gov changes its page layout, or stops posting.** The scraper reads award paragraphs from the `div.body` element of each article. If that changes, new articles fail with "no paragraphs found in div.body" and are logged as `[article] FAILED`. The run now ends with `[health] PROBLEM: ...` lines and exits non-zero, so the Action goes red and the build and deploy steps don't run. Whatever was scraped before the problem is already saved. The rule (in `health.py`) fails the run when:

- the listing failed after 5 attempts, or the first listing page had no articles;
- the newest listed article is more than 7 days old (outside the 2025 shutdown, announcements were never more than 6 days apart; during a long pause like that one, the job will go red every day until war.gov posts again);
- the dates can't be read from the article links;
- articles failed to parse and at least as many failed as succeeded. A single bad article among several good ones, or war.gov's own "currently unavailable" error, doesn't fail the run.

A quiet day, where everything listed was already in the dataset, passes. I tested this logic with stubbed listings and articles, not against the live site.

**War.gov blocks the scraper.** It returns 403 to plain HTTP clients, which is why the scraper drives a real, non-headless Chrome window through Playwright, and why the workflow installs Xvfb (a virtual display) and runs `xvfb-run`. If the block gets tighter, the listing step logs `[list] page 1 FAILED` five times and stops.

**Missing days.** Fewer than ten days out of about 3,000 are missing because war.gov's server errors on those articles or has removed them. Nothing to fix.

**Hugging Face commit limits.** Hugging Face allows about 128 commits an hour. The scraper pushes one commit per shard it writes, and `enrich_company_place.py` makes one commit per run. With 20,000-row shards a normal run pushes one file, the newest shard, which is re-sent in full each day. A full backfill from scratch can still hit the limit. Wait an hour and re-run.

**Shard size, and the one-time compaction.** Each shard file costs two web requests to read, so the dataset used to open slowly: it was 87 files of 500 rows. The code now writes 20,000-row shards. The live dataset keeps its 87 small files until you run `scripts/compact_shards.py` once. It rewrites them into 3 files (shard-00000 to shard-00002), checks that every row, column and type came through unchanged and in the same order, and then makes one Hugging Face commit that adds the 3 and deletes the 84 others. It's a dry run unless you pass `--upload`.

Run it when the daily workflow isn't running (the schedule is 21:00 UTC), with `HF_TOKEN` set:

```bash
python3 scripts/compact_shards.py            # dry run: reads HF, writes ./compacted, verifies, uploads nothing
python3 scripts/compact_shards.py --upload   # same, then one commit to the dataset
```

The commit is pinned to the version it read, so if something else pushes in the meantime it fails and changes nothing; run it again. Until the compaction has run, a scrape continues the old layout: it finds the newest small shard, fills it to 20,000 rows and then goes on from there, which makes one very uneven file. So run the compaction before, or soon after, you merge this. Anything that lists shards by name (`build_web_data.py`, `enrich_company_place.py`, and any outside page that hardcodes `data/shard-NNNNN.parquet` URLs) needs no change, but hardcoded URLs break once the 84 files are deleted.

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

`tests/test_company_consistency.py` compares the extraction against `web/data/contracts.parquet`, so rebuild that file first if it's old. The CI workflow runs `pytest tests/` before it scrapes. In CI, `test_company_consistency.py` skips itself, because `web/data/contracts.parquet` isn't built yet. Run it by hand after changing `fields.py`.

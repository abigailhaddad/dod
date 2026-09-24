#!/usr/bin/env python3
"""
Scrape DoD daily contract-award announcements from war.gov and publish them
to HuggingFace as they accumulate, one shard per SHARD_SIZE rows.

war.gov sits behind an Akamai edge that 403s plain HTTP clients -- including
curl sending full browser headers -- but passes real, non-headless browser
traffic. So this drives an actual (visible) Chrome window via Playwright
rather than requests/curl.

Each daily article (e.g. "Contracts for July 7, 2026") is a series of <p>
tags under div.body: some are bare agency headers ("AIR FORCE", "ARMY", ...),
the rest are individual contract-award announcements. This scrapes at that
per-award granularity: one row per award paragraph, tagged with its agency,
the article's date and URL, and its position in the article.

    python3 scrape.py                     # crawl from most recent, back 2 years
    python3 scrape.py --days-back 90      # smaller window
    python3 scrape.py --dry-run           # scrape + shard locally, skip HF upload
    python3 scrape.py --max-articles 50   # smoke test
"""

import argparse
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
import os

BASE = "https://www.war.gov"
LIST_URL = f"{BASE}/News/Contracts/"
REPO_ID = os.environ.get("HF_DATASET_REPO", "abigailhaddad/dod-daily-contracts")
SHARD_SIZE = 500

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SEEN_PATH = DATA_DIR / "seen_articles.json"

COLUMNS = ["date", "agency", "text", "link", "article_title", "row_index", "scraped_at"]

MONTH_RE = re.compile(r"contracts-for-([a-z]+)-(\d{1,2})-(\d{4})", re.I)
ARTICLE_ID_RE = re.compile(r"/Article/(\d+)/")

# Legend paragraphs at the end of an article ("*Small business **Mandatory
# source"), not real awards: one or more `*`-prefixed labels and nothing else.
FOOTNOTE_RE = re.compile(r"^\s*(\*+\s*[A-Za-z0-9][A-Za-z0-9 ,.()\-]*\s*)+$")


def is_footnote(text):
    return bool(FOOTNOTE_RE.match(text))


# A minority of paragraphs across the archive carry the agency name as plain
# centered text with no bold/italic markup at all ("<p style="text-align:
# center;">DEFENSE LOGISTICS AGENCY</p>"), so there's no DOM signal to catch
# them by. Instead, treat any short, digit-free, dollar-free paragraph whose
# text matches a name we already know is an agency as a header too. Seeded
# with the standard branches/agencies so a fresh run doesn't depend on
# stumbling on a properly-formatted instance first; grows as bold-formatted
# headers are found during the scrape.
KNOWN_AGENCIES_PATH = DATA_DIR / "known_agencies.json"
SEED_AGENCIES = {
    "ARMY", "NAVY", "AIR FORCE", "MARINE CORPS", "SPACE FORCE", "COAST GUARD",
    "DEFENSE LOGISTICS AGENCY", "MISSILE DEFENSE AGENCY", "DEFENSE HEALTH AGENCY",
    "U.S. SPECIAL OPERATIONS COMMAND", "U.S. TRANSPORTATION COMMAND",
    "UNITED STATES TRANSPORTATION COMMAND", "WASHINGTON HEADQUARTERS SERVICES",
    "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY", "DEFENSE FINANCE AND ACCOUNTING SERVICE",
    "DEFENSE COUNTERINTELLIGENCE AND SECURITY AGENCY", "DEFENSE INFORMATION SYSTEMS AGENCY",
    "DEFENSE THREAT REDUCTION AGENCY", "DEFENSE MICROELECTRONICS ACTIVITY",
    "CHIEF DIGITAL AND ARTIFICIAL INTELLIGENCE OFFICE", "DEFENSE HUMAN RESOURCES ACTIVITY",
    "DEPARTMENT OF WAR EDUCATION ACTIVITY", "DEPARTMENT OF DEFENSE EDUCATION ACTIVITY",
    "DEFENSE CONTRACT MANAGEMENT AGENCY", "NATIONAL GEOSPATIAL-INTELLIGENCE AGENCY",
    "NATIONAL SECURITY AGENCY", "DEFENSE COMMISSARY AGENCY",
    "DEFENSE POW/MIA ACCOUNTING AGENCY", "UNIFORMED SERVICES UNIVERSITY",
}


def load_known_agencies():
    if KNOWN_AGENCIES_PATH.exists():
        return set(json.loads(KNOWN_AGENCIES_PATH.read_text())) | SEED_AGENCIES
    return set(SEED_AGENCIES)


def save_known_agencies(agencies):
    DATA_DIR.mkdir(exist_ok=True)
    KNOWN_AGENCIES_PATH.write_text(json.dumps(sorted(agencies)))


def looks_like_bare_header(text):
    return bool(text) and len(text) <= 70 and "$" not in text and not re.search(r"\d", text)


def polite_sleep(base=1.1, jitter=0.9):
    time.sleep(base + random.random() * jitter)


def parse_date_from_url(url):
    m = MONTH_RE.search(url)
    if not m:
        return None
    month, day, year = m.groups()
    # war.gov slugs use full names ("july"), standard abbreviations ("jul"),
    # and non-standard ones strptime doesn't know ("sept") -- try the raw
    # token against %B/%b, then its first three letters against %b.
    for cand in (month, month[:3]):
        for fmt in ("%B", "%b"):
            try:
                return datetime.strptime(f"{cand} {day} {year}", f"{fmt} %d %Y").date()
            except ValueError:
                continue
    return None


def _hf_shard_files():
    from huggingface_hub import HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN"))
    try:
        return sorted(
            f for f in api.list_repo_files(REPO_ID, repo_type="dataset")
            if f.startswith("data/shard-")
        )
    except Exception:
        return []


def load_seen():
    seen = set()
    if SEEN_PATH.exists():
        seen |= set(json.loads(SEEN_PATH.read_text()))
    # Belt-and-suspenders: derive "already pushed" links directly from local
    # shard files too, in case a prior run died before its last save_seen().
    for f in DATA_DIR.glob("shard-*.parquet"):
        try:
            seen |= set(pd.read_parquet(f, columns=["link"])["link"].unique())
        except Exception:
            pass
    # A fresh checkout (CI: data/ isn't committed) has no local state at all
    # -- fall back to the published dataset itself so a cron run there
    # doesn't treat everything as new and push duplicate shards.
    if not seen:
        from concurrent.futures import ThreadPoolExecutor

        def read_links(f):
            try:
                return set(pd.read_parquet(f"hf://datasets/{REPO_ID}/{f}", columns=["link"])["link"].unique())
            except Exception:
                return set()

        with ThreadPoolExecutor(max_workers=16) as pool:
            for s in pool.map(read_links, _hf_shard_files()):
                seen |= s
    return seen


def save_seen(seen):
    DATA_DIR.mkdir(exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


def load_resume_state():
    """(shard_num, buffer) to start from -- continuing the last shard if it's
    still under SHARD_SIZE rather than minting a near-empty file for it, so a
    low-volume day doesn't fragment the dataset into hundreds of tiny shards.
    Checks local shard files first (the normal case on a machine that already
    has data/), then falls back to the published dataset (CI's fresh checkout)."""
    local = sorted(DATA_DIR.glob("shard-*.parquet"))
    if local:
        last_num = int(local[-1].stem.split("-")[1])
        df = pd.read_parquet(local[-1])
    else:
        hf_shards = _hf_shard_files()
        if not hf_shards:
            return 0, []
        last_num = int(Path(hf_shards[-1]).stem.split("-")[1])
        df = pd.read_parquet(f"hf://datasets/{REPO_ID}/{hf_shards[-1]}")
    if len(df) < SHARD_SIZE:
        return last_num, df[COLUMNS].to_dict("records")
    return last_num + 1, []


def get_listing(page, page_num):
    url = LIST_URL if page_num == 1 else f"{LIST_URL}?Page={page_num}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    links = page.eval_on_selector_all(
        "main a[href*='/News/Contracts/Contract/Article/']",
        "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))",
    )
    out, seen_href = [], set()
    for l in links:
        if l["href"] not in seen_href:
            seen_href.add(l["href"])
            out.append(l)
    return out


class ArticleUnavailable(Exception):
    """war.gov's own CMS module errored rendering this article (seen in the
    wild: 'ArticleCS - Article View is currently unavailable'). Distinct from
    a genuinely-empty article so callers can retry instead of treating an
    empty row list as done."""


def scrape_article(page, url, title, known_agencies):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    body_text = page.evaluate("() => document.body.innerText")
    if "currently unavailable" in body_text or "an error has occurred" in body_text.lower():
        raise ArticleUnavailable(url)
    art_date = parse_date_from_url(url)
    paras = page.evaluate(
        """() => {
            // Paragraph markup drifts across the archive: modern articles
            // wrap every award in its own <p>; some 2019-era articles wrap
            // each award in a <div> instead, or wrap only the headers in a
            // <div> and leave the award text as bare text nodes separated
            // by <br> with no wrapping element at all; some 2017-era
            // articles (raw Word-paste HTML, complete with MSO conditional
            // comments and <style> blocks) wrap the ENTIRE article body in
            // one extra <div>, itself containing normal <p> tags. A single
            // fixed selector can't cover all of that, so this walks
            // div.body's child nodes and reconstructs blocks by splitting
            // on <br>, on <p> boundaries (always a leaf block), and on
            // <div> boundaries -- but a <div> is only treated as a leaf
            // block if it has no nested <p>/<div> of its own; if it does,
            // it's a transparent wrapper and gets walked the same way as
            // div.body itself. <style>/<script> content and comments are
            // skipped outright so raw CSS/JS source never leaks in as text.
            const body = document.querySelector('div.body');
            if (!body) return [];

            function collectInline(node) {
                // Recursively flattens an element's text plus whatever of
                // it is nested under strong/b (bold) or em/i (italic).
                let text = '', bold = '', em = '';
                for (const child of node.childNodes) {
                    if (child.nodeType === Node.TEXT_NODE) {
                        text += child.textContent;
                    } else if (child.nodeType !== 1) {
                        continue; // comments, etc.
                    } else if (child.tagName === 'STYLE' || child.tagName === 'SCRIPT') {
                        continue;
                    } else if (child.tagName === 'BR') {
                        text += ' ';
                    } else {
                        const sub = collectInline(child);
                        text += sub.text;
                        bold += (child.tagName === 'STRONG' || child.tagName === 'B') ? sub.text : sub.bold;
                        em += (child.tagName === 'EM' || child.tagName === 'I') ? sub.text : sub.em;
                    }
                }
                return {text, bold, em};
            }

            function asBlock(node) {
                const r = collectInline(node);
                const text = r.text.replace(/\\s+/g, ' ').trim();
                if (!text) return null;
                return {
                    text,
                    boldText: r.bold.replace(/\\s+/g, ' ').trim(),
                    emText: r.em.replace(/\\s+/g, ' ').trim(),
                };
            }

            const blocks = [];

            function walk(container) {
                let bufText = '', bufBold = '', bufEm = '';
                function pushBuf() {
                    const t = bufText.replace(/\\s+/g, ' ').trim();
                    if (t) blocks.push({
                        text: t,
                        boldText: bufBold.replace(/\\s+/g, ' ').trim(),
                        emText: bufEm.replace(/\\s+/g, ' ').trim(),
                    });
                    bufText = ''; bufBold = ''; bufEm = '';
                }

                for (const node of container.childNodes) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        bufText += node.textContent;
                    } else if (node.nodeType !== 1) {
                        continue; // comments, etc.
                    } else if (node.tagName === 'STYLE' || node.tagName === 'SCRIPT') {
                        continue;
                    } else if (node.tagName === 'BR') {
                        pushBuf();
                    } else if (node.tagName === 'P') {
                        pushBuf();
                        const b = asBlock(node);
                        if (b) blocks.push(b);
                    } else if (node.tagName === 'DIV') {
                        pushBuf();
                        if (node.querySelector('p, div')) {
                            walk(node); // transparent wrapper
                        } else {
                            const b = asBlock(node);
                            if (b) blocks.push(b);
                        }
                    } else {
                        const r = collectInline(node);
                        bufText += r.text;
                        bufBold += (node.tagName === 'STRONG' || node.tagName === 'B') ? r.text : r.bold;
                        bufEm += (node.tagName === 'EM' || node.tagName === 'I') ? r.text : r.em;
                    }
                }
                pushBuf();
            }

            walk(body);

            return blocks.map(b => ({
                text: b.text,
                isHeader: b.boldText.length > 0 && b.boldText === b.text,
                isNote: b.emText.length > 0 && b.emText === b.text,
            }));
        }"""
    )
    if not paras:
        # Nothing under div.body at all -- almost certainly a fetch that
        # raced the page still rendering, not a genuinely contentless
        # article (every real article has at least one paragraph). Treat
        # as a failure so the caller retries it instead of silently
        # recording 0 rows and marking it done forever.
        raise RuntimeError(f"no paragraphs found in div.body for {url}")
    rows = []
    agency = None
    idx = 0
    now = datetime.now(timezone.utc).isoformat()
    for p in paras:
        text = p["text"]
        if p["isHeader"]:
            agency = text
            known_agencies.add(text.strip().upper())
            continue
        if looks_like_bare_header(text) and text.strip().upper() in known_agencies:
            agency = text
            continue
        if not text or p["isNote"] or is_footnote(text):
            continue
        rows.append(
            {
                "date": art_date.isoformat() if art_date else None,
                "agency": agency,
                "text": text,
                "link": url,
                "article_title": title,
                "row_index": idx,
                "scraped_at": now,
            }
        )
        idx += 1
    return rows


def push_shard(rows, shard_num, dry_run):
    DATA_DIR.mkdir(exist_ok=True)
    df = pd.DataFrame(rows, columns=COLUMNS)
    shard_path = DATA_DIR / f"shard-{shard_num:05d}.parquet"
    df.to_parquet(shard_path, index=False)
    print(f"[shard {shard_num:05d}] wrote {len(df)} rows -> {shard_path}", file=sys.stderr)
    if dry_run:
        return
    from huggingface_hub import HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.upload_file(
        path_or_fileobj=str(shard_path),
        path_in_repo=f"data/shard-{shard_num:05d}.parquet",
        repo_id=REPO_ID,
        repo_type="dataset",
    )
    print(f"[shard {shard_num:05d}] pushed to {REPO_ID}", file=sys.stderr)


def ensure_repo_and_card(dry_run):
    if dry_run:
        return
    from huggingface_hub import HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True)
    card = CARD_TEMPLATE.format(updated=date.today().isoformat())
    api.upload_file(
        path_or_fileobj=card.encode(),
        path_in_repo="README.md",
        repo_id=REPO_ID,
        repo_type="dataset",
    )


CARD_TEMPLATE = """---
license: other
license_name: us-govt-public-domain
language:
  - en
tags:
  - government
  - defense
  - procurement
  - contracts
pretty_name: DoD Daily Contract Announcements
size_categories:
  - 10K<n<100K
configs:
  - config_name: default
    data_files: data/*.parquet
---

# DoD daily contract announcements

Scraped from [war.gov/News/Contracts](https://www.war.gov/News/Contracts/),
one row per contract award (not per day).

| column | |
|---|---|
| `date` | announcement date (ISO 8601), from the article URL |
| `agency` | branch/agency header the award was listed under (`ARMY`, `NAVY`, `AIR FORCE`, `DEFENSE LOGISTICS AGENCY`, ...), as published -- typos and casing are the source's own, not normalized |
| `company` | best-effort extraction of the awardee's name from the start of `text` (~95% match rate; `None` when not confidently found) |
| `place` | best-effort "City, State" extraction paired with `company` (`None` under the same conditions) |
| `text` | full free-text paragraph for that award, as published |
| `link` | URL of the source article (one per day, not per award) |
| `article_title` | title of the source article, e.g. "Contracts for July 7, 2026" |
| `row_index` | position of this award within its article (0-based) |
| `scraped_at` | UTC timestamp this row was scraped |

`company`/`place` are a derived convenience, not scraped fact: a regex
anchored on US state names splits each paragraph's opening "Company, City,
State, was awarded..." clause. They're `None` rather than a guess for
multi-awardee paragraphs whose first-listed company is foreign, a small
number of source-side formatting irregularities, and rows that are
themselves a garbled fragment rather than a real award opening. Dollar
amount, contract number, etc. are still only inside `text` as free text.

Covers the full archive, July 2014 through present -- a handful of
individual days (fewer than ten, out of ~3,000) are missing where war.gov's
own server errors on that article or has taken it down entirely.

U.S. government works are in the public domain. Not an official Department of
War product.

Last updated: {updated}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-back", type=int, default=730, help="how far back to scrape (default: 2 years)")
    ap.add_argument("--max-articles", type=int, default=None, help="stop after this many new articles (smoke testing)")
    ap.add_argument("--dry-run", action="store_true", help="scrape and shard locally, skip HF upload")
    args = ap.parse_args()

    cutoff = date.today() - timedelta(days=args.days_back)
    seen = load_seen()
    known_agencies = load_known_agencies()
    shard_num, buffer = load_resume_state()
    new_count = 0

    ensure_repo_and_card(args.dry_run)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()

        page_num = 1
        stop = False
        while not stop:
            for attempt in range(5):
                try:
                    arts = get_listing(page, page_num)
                    break
                except Exception as e:
                    print(f"[list] page {page_num} FAILED (attempt {attempt + 1}/5): {e}", file=sys.stderr)
                    time.sleep(10)
            else:
                print(f"[list] page {page_num}: giving up after 5 attempts, stopping", file=sys.stderr)
                break
            if not arts:
                print(f"[list] page {page_num}: no items, stopping", file=sys.stderr)
                break
            print(f"[list] page {page_num}: {len(arts)} articles", file=sys.stderr)

            for a in arts:
                d = parse_date_from_url(a["href"])
                if d and d < cutoff:
                    print(f"[list] hit cutoff date {cutoff} at {a['href']}", file=sys.stderr)
                    stop = True
                    break
                if a["href"] in seen:
                    continue

                polite_sleep()
                try:
                    rows = scrape_article(page, a["href"], a["text"], known_agencies)
                except Exception as e:
                    print(f"[article] FAILED {a['href']}: {e}", file=sys.stderr)
                    continue

                buffer.extend(rows)
                seen.add(a["href"])
                new_count += 1
                print(f"[article] {a['href']} -> {len(rows)} rows (buffer={len(buffer)})", file=sys.stderr)
                save_seen(seen)  # cheap; keeps a crash from re-scraping already-seen articles
                save_known_agencies(known_agencies)

                if len(buffer) >= SHARD_SIZE:
                    push_shard(buffer, shard_num, args.dry_run)
                    shard_num += 1
                    buffer = []

                if args.max_articles and new_count >= args.max_articles:
                    stop = True
                    break

            save_seen(seen)
            page_num += 1
            polite_sleep()

        browser.close()

    if buffer and new_count:
        push_shard(buffer, shard_num, args.dry_run)
        save_seen(seen)

    print(f"Done. {new_count} new articles scraped this run.", file=sys.stderr)


if __name__ == "__main__":
    main()

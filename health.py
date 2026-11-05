"""Decide whether a scrape run should fail loudly.

scrape.py used to end every run with "Done. N new articles scraped", even when
war.gov's page layout had changed and every article failed to parse, so the
GitHub Action showed green while adding nothing. `problems()` turns the run's
counts into a list of reasons to fail. An empty list means the run was fine,
including a quiet day with nothing new.

The thresholds come from the dataset itself (July 2014 to September 2026):
announcements are never more than 6 days apart except during the 2025
government shutdown, so a newest-listed article more than STALE_DAYS old
means war.gov stopped posting or the listing stopped showing new items.
"""

from dataclasses import dataclass
from datetime import date

STALE_DAYS = 7


@dataclass
class RunStats:
    listing_gave_up: bool = False      # a listing page failed all 5 attempts
    page1_count: int = 0               # articles on the first listing page
    newest_listed: date | None = None  # newest date parsed from page-1 URLs
    ok: int = 0                        # new articles scraped, plus re-posts skipped
    parse_failures: int = 0            # articles that raised, other than ArticleUnavailable
    unavailable: int = 0               # war.gov's own "currently unavailable" error


def problems(stats, today=None):
    today = today or date.today()
    out = []
    if stats.listing_gave_up:
        out.append("the article listing failed after 5 attempts, so some articles were never checked")
    if stats.page1_count == 0:
        out.append("the first listing page had no articles (layout change or block?)")
    elif stats.newest_listed is None:
        out.append("could not read a date from any article URL on the first listing page")
    elif (today - stats.newest_listed).days > STALE_DAYS:
        out.append(
            f"the newest listed article is from {stats.newest_listed}, "
            f"more than {STALE_DAYS} days ago"
        )
    if stats.parse_failures and stats.parse_failures >= stats.ok:
        out.append(
            f"{stats.parse_failures} article(s) failed to parse and only {stats.ok} succeeded "
            "(war.gov's page layout may have changed)"
        )
    return out

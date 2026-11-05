"""The run-health rule: loud on broken runs, quiet on quiet days."""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from health import STALE_DAYS, RunStats, problems

TODAY = date(2026, 11, 5)  # a Thursday


def stats(**kw):
    base = dict(page1_count=20, newest_listed=TODAY, ok=1)
    base.update(kw)
    return RunStats(**base)


def test_normal_day_with_new_article_is_quiet():
    assert problems(stats(ok=1), TODAY) == []


def test_quiet_day_everything_already_seen_is_quiet():
    # Listing loaded, newest article is yesterday's and already in the dataset:
    # nothing attempted, nothing failed.
    assert problems(stats(ok=0, newest_listed=TODAY - timedelta(days=1)), TODAY) == []


def test_weekend_and_holiday_gaps_are_quiet():
    # The longest gap between announcements outside the 2025 shutdown is 6 days.
    assert problems(stats(ok=0, newest_listed=TODAY - timedelta(days=6)), TODAY) == []
    assert problems(stats(ok=0, newest_listed=TODAY - timedelta(days=STALE_DAYS)), TODAY) == []


def test_stale_listing_is_loud():
    out = problems(stats(ok=0, newest_listed=TODAY - timedelta(days=STALE_DAYS + 1)), TODAY)
    assert len(out) == 1 and "days ago" in out[0]


def test_layout_change_every_article_fails_is_loud():
    out = problems(stats(ok=0, parse_failures=3), TODAY)
    assert len(out) == 1 and "failed to parse" in out[0]


def test_one_new_article_fails_to_parse_is_loud():
    assert problems(stats(ok=0, parse_failures=1), TODAY)


def test_one_bad_article_among_many_good_is_quiet():
    assert problems(stats(ok=8, parse_failures=1), TODAY) == []


def test_unavailable_articles_alone_are_quiet():
    # war.gov's own server error on an article; known, persistent, not our bug.
    assert problems(stats(ok=0, unavailable=2), TODAY) == []


def test_empty_first_listing_page_is_loud():
    out = problems(RunStats(page1_count=0), TODAY)
    assert any("no articles" in o for o in out)


def test_listing_gave_up_is_loud():
    assert problems(stats(listing_gave_up=True), TODAY)


def test_unreadable_dates_are_loud():
    out = problems(stats(newest_listed=None), TODAY)
    assert any("could not read a date" in o for o in out)

"""scrape.main() exits non-zero on a broken run and returns on a quiet one.
Playwright, Hugging Face and the filesystem state are all stubbed; no network."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrape


class FakeBrowser:
    def new_page(self):
        return object()

    def close(self):
        pass


class FakePW:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    class chromium:
        @staticmethod
        def launch(headless=False):
            return FakeBrowser()


def url(d):
    return f"https://www.war.gov/News/Contracts/Contract/Article/1/contracts-for-{d.strftime('%b-%-d-%Y').lower()}/"


@pytest.fixture
def run(monkeypatch):
    def _run(listing, seen=(), article=None):
        monkeypatch.setattr(sys, "argv", ["scrape.py", "--days-back", "10", "--dry-run"])
        monkeypatch.setattr(scrape, "sync_playwright", lambda: FakePW())
        monkeypatch.setattr(scrape, "load_seen", lambda: set(seen))
        monkeypatch.setattr(scrape, "load_known_agencies", lambda: set())
        monkeypatch.setattr(scrape, "load_resume_state", lambda: (0, []))
        monkeypatch.setattr(scrape, "load_recent_keys", lambda b, n: set())
        monkeypatch.setattr(scrape, "ensure_repo_and_card", lambda dry: None)
        monkeypatch.setattr(scrape, "save_seen", lambda s: None)
        monkeypatch.setattr(scrape, "save_known_agencies", lambda a: None)
        monkeypatch.setattr(scrape, "push_shard", lambda *a, **k: None)
        monkeypatch.setattr(scrape, "polite_sleep", lambda *a, **k: None)
        pages = {1: listing}
        monkeypatch.setattr(scrape, "get_listing", lambda page, n: pages.get(n, []))
        if article:
            monkeypatch.setattr(scrape, "scrape_article", article)
        scrape.main()

    return _run


def today_listing():
    t = date.today()
    return [{"href": url(t), "text": "Contracts"}]


def test_all_seen_quiet_day_returns_normally(run):
    listing = today_listing()
    run(listing, seen={listing[0]["href"]})  # nothing new, no exception


def test_unparseable_new_article_exits_nonzero(run):
    def boom(*a, **k):
        raise RuntimeError("no paragraphs found in div.body")

    with pytest.raises(SystemExit) as e:
        run(today_listing(), article=boom)
    assert e.value.code == 1


def test_empty_first_listing_page_exits_nonzero(run):
    with pytest.raises(SystemExit) as e:
        run([])
    assert e.value.code == 1


def test_new_article_with_rows_returns_normally(run):
    row = {"text": "ACME, Austin, Texas, was awarded $1 contract."}
    run(today_listing(), article=lambda *a, **k: [row])

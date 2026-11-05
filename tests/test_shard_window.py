"""Shard size, resuming the newest shard, and the dedupe window. No network."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrape
from dedupe import is_repost, row_key


def test_shard_size_is_large_enough_for_a_few_files():
    assert scrape.SHARD_SIZE >= 10_000


def pairs(*items):
    return list(items)


def test_window_is_relative_to_newest_article_date_not_today():
    keys = scrape.recent_row_keys(
        [("2020-01-10", "old award"), ("2020-03-01", "mid award"), ("2020-03-20", "new award")], days=30
    )
    assert row_key("new award") in keys and row_key("mid award") in keys
    assert row_key("old award") not in keys


def test_window_keeps_rows_exactly_at_the_cutoff():
    keys = scrape.recent_row_keys([("2026-01-01", "edge"), ("2026-01-31", "newest")], days=30)
    assert row_key("edge") in keys


def test_window_keeps_undated_rows():
    keys = scrape.recent_row_keys([(None, "undated"), ("2026-01-31", "newest"), ("2025-01-01", "ancient")], days=30)
    assert row_key("undated") in keys
    assert row_key("ancient") not in keys


def test_window_with_no_dates_keeps_everything():
    assert scrape.recent_row_keys([(None, "a"), (None, "b")]) == {row_key("a"), row_key("b")}


def test_window_empty():
    assert scrape.recent_row_keys([]) == set()


def shard(path, dates_texts):
    pd.DataFrame(
        {
            "date": [d for d, _ in dates_texts],
            "agency": "ARMY",
            "text": [t for _, t in dates_texts],
            "link": [f"https://x/{i}" for i in range(len(dates_texts))],
            "article_title": "Contracts",
            "row_index": range(len(dates_texts)),
            "scraped_at": "2026-01-01T00:00:00+00:00",
        }
    ).to_parquet(path, index=False)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "DATA_DIR", tmp_path)
    return tmp_path


def test_recent_keys_read_the_buffer_and_the_shards_before_it(data_dir):
    shard(data_dir / "shard-00000.parquet", [("2025-01-01", "very old"), ("2026-01-05", "january 5 award")])
    shard(data_dir / "shard-00001.parquet", [("2026-01-20", "january 20 award")])
    buffer = [{"date": "2026-01-30", "text": "january 30 award"}]
    keys = scrape.load_recent_keys(buffer, 2)
    assert {row_key("january 5 award"), row_key("january 20 award"), row_key("january 30 award")} <= keys
    assert row_key("very old") not in keys


def test_a_repost_of_a_recent_day_is_caught_when_the_buffer_is_nearly_empty(data_dir):
    # Right after a rollover the buffer holds one row; the rest of the
    # recent days are in the previous shard.
    prev = [("2026-01-28", f"award number {i} to company {i}") for i in range(10)]
    shard(data_dir / "shard-00000.parquet", prev)
    buffer = [{"date": "2026-01-29", "text": "award number 99"}]
    keys = scrape.load_recent_keys(buffer, 1)
    repost = [{"text": t} for _, t in prev]
    assert is_repost(repost, keys)


def test_missing_shard_files_are_skipped(data_dir, monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(pd, "read_parquet", boom)
    assert scrape.load_recent_keys([{"date": "2026-01-01", "text": "x"}], 3) == {row_key("x")}


def test_resume_continues_the_newest_shard_while_under_size(data_dir, monkeypatch):
    monkeypatch.setattr(scrape, "SHARD_SIZE", 5)
    shard(data_dir / "shard-00000.parquet", [("2026-01-01", f"a{i}") for i in range(5)])
    shard(data_dir / "shard-00001.parquet", [("2026-01-02", f"b{i}") for i in range(3)])
    num, buf = scrape.load_resume_state()
    assert num == 1 and len(buf) == 3
    assert list(buf[0]) == scrape.COLUMNS


def test_resume_starts_a_new_shard_when_the_newest_is_full(data_dir, monkeypatch):
    monkeypatch.setattr(scrape, "SHARD_SIZE", 5)
    shard(data_dir / "shard-00000.parquet", [("2026-01-01", f"a{i}") for i in range(5)])
    assert scrape.load_resume_state() == (1, [])

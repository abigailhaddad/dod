"""scripts/compact_shards.py: planning, verification and commit contents. No network."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import compact_shards as cs


def rows(n, start=0):
    return pd.DataFrame(
        {
            "date": [f"2026-01-{(i % 28) + 1:02d}" for i in range(start, start + n)],
            "agency": ["ARMY"] * n,
            "text": [f"Company {i}, City, State, was awarded ${i}." for i in range(start, start + n)],
            "link": [f"https://x/{i // 3}" for i in range(start, start + n)],
            "article_title": ["Contracts"] * n,
            "row_index": [i % 3 for i in range(start, start + n)],
            "scraped_at": ["2026-01-01T00:00:00+00:00"] * n,
            "company": [f"Company {i}" for i in range(start, start + n)],
            "place": ["City, State"] * n,
        }
    )


def test_plan_slices_in_order_and_names_contiguously():
    df = rows(25)
    out = cs.plan(df, 10)
    assert [n for n, _ in out] == ["shard-00000.parquet", "shard-00001.parquet", "shard-00002.parquet"]
    assert [len(f) for _, f in out] == [10, 10, 5]
    assert pd.concat([f for _, f in out], ignore_index=True).equals(df)


def test_plan_one_shard_when_under_size():
    assert [len(f) for _, f in cs.plan(rows(7), 10)] == [7]


def test_verify_passes_on_a_faithful_split():
    df = rows(25)
    assert cs.verify(df, cs.plan(df, 10), 10) == []


def test_verify_catches_a_dropped_row():
    df = rows(25)
    new = cs.plan(df.drop(index=7).reset_index(drop=True), 10)
    problems = cs.verify(df, new, 10)
    assert any("row count" in p for p in problems)


def test_verify_catches_reordered_rows():
    df = rows(25)
    swapped = df.copy()
    swapped.iloc[[3, 4]] = swapped.iloc[[4, 3]].values
    problems = cs.verify(df, cs.plan(swapped, 10), 10)
    assert any("different order" in p or "differ" in p for p in problems)


def test_verify_catches_a_changed_value():
    df = rows(25)
    changed = df.copy()
    changed.loc[12, "text"] = "something else"
    assert cs.verify(df, cs.plan(changed, 10), 10)


def test_verify_catches_a_lost_column():
    df = rows(25)
    problems = cs.verify(df, cs.plan(df.drop(columns=["company"]), 10), 10)
    assert any("columns differ" in p for p in problems)


def test_verify_catches_duplicate_keys():
    df = rows(25)
    dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    problems = cs.verify(dup, cs.plan(dup, 10), 10)
    assert any("duplicate" in p for p in problems)


def test_verify_catches_wrong_sizes_and_names():
    df = rows(25)
    frames = cs.plan(df, 10)
    assert any("sizes" in p for p in cs.verify(df, frames, 12))
    renamed = [("shard-00003.parquet", frames[0][1])] + frames[1:]
    assert any("contiguous" in p for p in cs.verify(df, renamed, 10))


def test_commit_adds_new_shards_and_deletes_only_old_ones_not_reused():
    old = [f"shard-{i:05d}.parquet" for i in range(87)]
    new = [f"shard-{i:05d}.parquet" for i in range(3)]
    add, delete = cs.commit_changes(old, new)
    assert add == [f"data/{n}" for n in new]
    assert len(delete) == 84
    assert "data/shard-00000.parquet" not in delete
    assert "data/shard-00003.parquet" in delete and "data/shard-00086.parquet" in delete


def test_round_trip_through_parquet_files(tmp_path):
    df = rows(25)
    for name, frame in cs.plan(df, 10):
        frame.to_parquet(tmp_path / name, index=False)
    reread = [(p.name, pd.read_parquet(p)) for p in sorted(tmp_path.glob("shard-*.parquet"))]
    assert cs.verify(df, reread, 10) == []

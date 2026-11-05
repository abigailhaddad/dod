#!/usr/bin/env python3
"""Rewrite the dataset's many small shards into a few large ones.

    python3 scripts/compact_shards.py                       # read HF, write ./compacted, verify (no upload)
    python3 scripts/compact_shards.py --src some/dir        # read local shard-*.parquet files instead
    python3 scripts/compact_shards.py --upload              # verify, then ONE HF commit: add new, delete old

Default is a dry run: nothing is written to Hugging Face. Reading the
dataset from HF is read-only. --upload refuses to run unless every
verification passes, and its commit is pinned to the revision that was read,
so it fails instead of overwriting a push that landed in between.
Do not run it while the daily workflow is running.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import REPO_ID  # noqa: E402
from scrape import SHARD_SIZE  # noqa: E402

KEY = ["link", "row_index"]


def shard_name(n):
    return f"shard-{n:05d}.parquet"


def plan(df, shard_size):
    """Slice df, in its current row order, into frames of `shard_size` rows
    (the last one smaller). Returns [(file_name, frame)]."""
    return [
        (shard_name(i), df.iloc[start : start + shard_size].reset_index(drop=True))
        for i, start in enumerate(range(0, len(df), shard_size))
    ]


def verify(old, new_frames, shard_size):
    """Problems (empty list = all good). `old` is the original rows in shard
    order; `new_frames` is [(file_name, frame)] as read back from disk."""
    problems = []
    new = pd.concat([f for _, f in new_frames], ignore_index=True) if new_frames else old.iloc[0:0]
    old = old.reset_index(drop=True)
    if len(new) != len(old):
        problems.append(f"row count differs: old {len(old)}, new {len(new)}")
    same_columns = list(new.columns) == list(old.columns)
    if not same_columns:
        problems.append(f"columns differ: old {list(old.columns)}, new {list(new.columns)}")
    else:
        if (new.dtypes.astype(str) != old.dtypes.astype(str)).any():
            problems.append("column types differ")
        if len(new) == len(old) and not new.equals(old):
            problems.append("rows differ, or are in a different order")
    if old.duplicated(KEY).any():
        problems.append(f"{int(old.duplicated(KEY).sum())} duplicate (link, row_index) keys in the old shards")
    if same_columns:
        if new.duplicated(KEY).any():
            problems.append(f"{int(new.duplicated(KEY).sum())} duplicate (link, row_index) keys in the new shards")
        if set(map(tuple, old[KEY].astype(str).values)) != set(map(tuple, new[KEY].astype(str).values)):
            problems.append("the set of (link, row_index) keys differs")
    names = [n for n, _ in new_frames]
    if names != [shard_name(i) for i in range(len(names))]:
        problems.append(f"shard names are not contiguous from 0: {names[:3]}...")
    sizes = [len(f) for _, f in new_frames]
    if any(s > shard_size for s in sizes) or any(s != shard_size for s in sizes[:-1]):
        problems.append(f"shard sizes are not {shard_size} except the last: {sizes}")
    return problems


def commit_changes(old_names, new_names):
    """(paths to add or overwrite, paths to delete) as repo paths."""
    add = [f"data/{n}" for n in new_names]
    delete = [f"data/{n}" for n in old_names if n not in set(new_names)]
    return add, delete


def read_local(src):
    files = sorted(Path(src).glob("shard-*.parquet"))
    if not files:
        sys.exit(f"no shard-*.parquet files in {src}")
    return [f.name for f in files], pd.concat([pd.read_parquet(f) for f in files], ignore_index=True), None


def read_hf():
    from concurrent.futures import ThreadPoolExecutor

    from huggingface_hub import HfApi

    api = HfApi()
    sha = api.dataset_info(REPO_ID).sha
    names = sorted(
        f.split("/", 1)[1]
        for f in api.list_repo_files(REPO_ID, repo_type="dataset", revision=sha)
        if f.startswith("data/shard-")
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = list(
            pool.map(lambda n: pd.read_parquet(f"hf://datasets/{REPO_ID}@{sha}/data/{n}"), names)
        )
    return names, pd.concat(frames, ignore_index=True), sha


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", help="folder of shard-*.parquet to read instead of the HF dataset")
    ap.add_argument("--out", default="compacted", help="where to write the new shards (default ./compacted)")
    ap.add_argument("--shard-size", type=int, default=SHARD_SIZE)
    ap.add_argument("--upload", action="store_true", help="after verifying, make one HF commit (adds new shards, deletes old ones)")
    args = ap.parse_args()

    old_names, old, sha = (read_local(args.src) if args.src else read_hf())
    print(f"read {len(old):,} rows from {len(old_names)} shards", file=sys.stderr)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    new_names = []
    for name, frame in plan(old, args.shard_size):
        frame.to_parquet(out / name, index=False)
        new_names.append(name)
    # Verify the files as written, not the frames in memory.
    reread = [(n, pd.read_parquet(out / n)) for n in new_names]
    problems = verify(old, reread, args.shard_size)
    for n, f in reread:
        print(f"  {n}: {len(f):,} rows, {(out / n).stat().st_size / 1e6:.1f} MB", file=sys.stderr)
    if problems:
        for p in problems:
            print(f"VERIFY FAILED: {p}", file=sys.stderr)
        sys.exit(1)
    print(f"verified: {len(old):,} rows identical, same order, same columns and types, no duplicate keys", file=sys.stderr)

    add, delete = commit_changes(old_names, new_names)
    print(f"commit would add/overwrite {len(add)} files and delete {len(delete)}", file=sys.stderr)
    if not args.upload:
        print("dry run: nothing uploaded (add --upload to commit)", file=sys.stderr)
        return
    if args.src or sha is None:
        sys.exit("--upload only works when reading from HF (no --src), so the commit is pinned to the revision it read")

    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

    ops = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=str(out / p.split("/", 1)[1])) for p in add]
    ops += [CommitOperationDelete(path_in_repo=p) for p in delete]
    HfApi().create_commit(
        repo_id=REPO_ID,
        repo_type="dataset",
        operations=ops,
        commit_message=f"Compact {len(old_names)} shards into {len(new_names)} ({args.shard_size} rows each)",
        parent_commit=sha,
    )
    print("committed", file=sys.stderr)


if __name__ == "__main__":
    main()

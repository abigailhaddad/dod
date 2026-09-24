#!/usr/bin/env python3
"""
Add `company` and `place` columns (see fields.py) to every published shard
that doesn't already have them -- both the one-time backfill of the shards
that predate this feature, and any new shards scrape.py produces later.
Idempotent: safe to re-run any time, e.g. after every scrape.py run.

    python3 enrich_company_place.py
    python3 enrich_company_place.py --dry-run   # report only, don't push
"""

import argparse
import os
import sys

import pandas as pd
from dotenv import load_dotenv

from fields import extract_company_place

load_dotenv()

REPO_ID = os.environ.get("HF_DATASET_REPO", "abigailhaddad/dod-daily-contracts")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                     help="recompute even for shards that already have company/place (e.g. after a fields.py fix)")
    args = ap.parse_args()

    from concurrent.futures import ThreadPoolExecutor

    from huggingface_hub import CommitOperationAdd, HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN"))
    shard_files = sorted(
        f for f in api.list_repo_files(REPO_ID, repo_type="dataset")
        if f.startswith("data/shard-")
    )
    print(f"{len(shard_files)} shards on {REPO_ID}", file=sys.stderr)

    def process(f):
        df = pd.read_parquet(f"hf://datasets/{REPO_ID}/{f}")
        if "company" in df.columns and "place" in df.columns and not args.force:
            return None
        company, place = zip(*df["text"].map(extract_company_place)) if len(df) else ((), ())
        df["company"] = company
        df["place"] = place
        return f, df

    # Reading each shard is a separate HTTP round-trip, network-bound not
    # CPU-bound, so a thread pool helps despite the GIL. The commit itself
    # stays a single batched call below either way.
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(process, shard_files))

    ops = []
    for result in results:
        if result is None:
            continue
        f, df = result
        matched = df["company"].notna().sum()
        print(f"{f}: {matched}/{len(df)} matched", file=sys.stderr)
        if not args.dry_run:
            local = f"/tmp/{os.path.basename(f)}"
            df.to_parquet(local, index=False)
            ops.append(CommitOperationAdd(path_in_repo=f, path_or_fileobj=local))

    print(f"{'would update' if args.dry_run else 'updating'} {len(ops) if not args.dry_run else '?'} / {len(shard_files)} shards", file=sys.stderr)
    if ops:
        api.create_commit(
            repo_id=REPO_ID, repo_type="dataset", operations=ops,
            commit_message=f"Add company/place to {len(ops)} shards",
        )
        for op in ops:
            os.remove(op.path_or_fileobj)
    print(f"done: {len(ops)} shards updated in one commit" if not args.dry_run else "dry run complete", file=sys.stderr)


if __name__ == "__main__":
    main()

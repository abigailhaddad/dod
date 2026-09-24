#!/usr/bin/env python3
"""
Flatten the published HF dataset into one Parquet for the static site to
query client-side via DuckDB-WASM -- same pattern as usajobs_historical /
hhs-dab: no backend, the browser fetches this file once and runs SQL
against it in memory.

    python3 build_web_data.py

Writes web/data/contracts.parquet.
"""

import re
import sys
from pathlib import Path

import pandas as pd

REPO_ID = "abigailhaddad/dod-daily-contracts"
OUT_PATH = Path(__file__).resolve().parent / "web" / "data" / "contracts.parquet"

# The raw `agency` column carries the source's own inconsistencies verbatim
# (typos, mixed case, abbreviations) -- fine for the dataset, useless as a
# filter dropdown with 66 near-duplicate entries, most of them a single
# occurrence of a hand-typed misspelling ("MISSLE", "DEFNSE", "LOGISITICS")
# accumulated over 12 years of daily press releases. Exhaustively mapping
# every distinct value actually observed to one of ~24 canonical labels,
# rather than fuzzy-matching, since this is a closed list, not a moving
# target -- the raw value is untouched in the published dataset, this
# normalization is web-only. Genuinely distinct historical agencies (e.g.
# Defense Security Service before its 2019 merger into DCSA, or JIEDDO's
# own renames) are kept apart rather than folded into their successor.
AGENCY_CANON = {
    "DEFENSE LOGISITICS AGENCY": "DEFENSE LOGISTICS AGENCY",
    "DEFENSE LOGISTIC AGENCY": "DEFENSE LOGISTICS AGENCY",
    "CONTRACTS DEFENSE LOGISTICS AGENCY": "DEFENSE LOGISTICS AGENCY",
    "MISSLE DEFENSE AGENCY": "MISSILE DEFENSE AGENCY",
    "MISSILE DEFNSE AGENCY": "MISSILE DEFENSE AGENCY",
    "TRANSCOM": "U.S. TRANSPORTATION COMMAND",
    "TRANSPORTATION COMMAND": "U.S. TRANSPORTATION COMMAND",
    "U.S TRANSPORTATION COMMAND": "U.S. TRANSPORTATION COMMAND",
    "UNITED STATES TRANSPORTATION COMMAND": "U.S. TRANSPORTATION COMMAND",
    "DEFENSE ADVANCE RESEARCH PROJECTS AGENCY": "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY",
    "DEFENSE ADVANCED RESEARCH AGENCY": "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY",
    "DEFENSE ADVANCED RESEARCH PROJECT AGENCY": "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY",
    "DARPA": "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY",
    "SPECIAL OPERATIONS COMMAND": "U.S. SPECIAL OPERATIONS COMMAND",
    "SPECIAL OPERATIONS COMMMAND": "U.S. SPECIAL OPERATIONS COMMAND",
    "U.S. SPECIAL COMMAND": "U.S. SPECIAL OPERATIONS COMMAND",
    "U.S.SPECIAL OPERATIONS COMMAND": "U.S. SPECIAL OPERATIONS COMMAND",
    "U.S SPECIAL OPERATIONS COMMAND": "U.S. SPECIAL OPERATIONS COMMAND",
    "U.S. SPECIAL OPERATONS COMMAND": "U.S. SPECIAL OPERATIONS COMMAND",
    "WASHINGTON HEADQUARTERS SERVICE": "WASHINGTON HEADQUARTERS SERVICES",
    "WASHINGTON HEADQUARTERS AGENCY": "WASHINGTON HEADQUARTERS SERVICES",
    "DEFENSE INFORMATIONS SYSTEMS AGENCY": "DEFENSE INFORMATION SYSTEMS AGENCY",
    "DEFENSE INFORMATION SYSTEM AGENCY": "DEFENSE INFORMATION SYSTEMS AGENCY",
    "DEFESE INFORMATION SYSTEMS AGENCY": "DEFENSE INFORMATION SYSTEMS AGENCY",
    "DEFENSE FINANCE AND ACCOUNTING SERVICES": "DEFENSE FINANCE AND ACCOUNTING SERVICE",
    "DEFENSE FINANCE ACCOUNTING SERVICES": "DEFENSE FINANCE AND ACCOUNTING SERVICE",
    "DEFENSE FINANCE ACCOUNTING SERVICE": "DEFENSE FINANCE AND ACCOUNTING SERVICE",
    "DEFENSE FINANCING ACCOUNTING SERVICES": "DEFENSE FINANCE AND ACCOUNTING SERVICE",
    "DEFENSE INTELLIGENCY AGENCY": "DEFENSE INTELLIGENCE AGENCY",
    "DEFNSE COUNTERINTELLIGENCE AND SECURITY AGENCY": "DEFENSE COUNTERINTELLIGENCE AND SECURITY AGENCY",
    "DEFENSE COUNTERINTELLIGENCE SECURITY AGENCY": "DEFENSE COUNTERINTELLIGENCE AND SECURITY AGENCY",
    "DEFENSE HUMAN RESOURCE ACTIVITY": "DEFENSE HUMAN RESOURCES ACTIVITY",
    "DEFENSE HUMAN RESOURCES ACTIVITIES": "DEFENSE HUMAN RESOURCES ACTIVITY",
    "DEFENSE CONTRACT MANGEMENT AGENCY": "DEFENSE CONTRACT MANAGEMENT AGENCY",
    "DEPARTMENT OF DEFENSE EDUCATION ACTIVITY": "DEPARTMENT OF WAR EDUCATION ACTIVITY",
    "CONTRACTS ARMY": "ARMY",
    "CONTRACTS NAVY": "NAVY",
    "CONTRACTS AIR FORCE": "AIR FORCE",
    "CONTRACTS": None,
    "JOINT IMPROVISED-THREAT DEFEAT AGENCY": "JOINT IMPROVISED-THREAT DEFEAT ORGANIZATION",
    "JOINT IMPROVISED THREAT DEFEAT ORGANIZATION": "JOINT IMPROVISED-THREAT DEFEAT ORGANIZATION",
    "DEFENSE LOGISTCS AGENCY": "DEFENSE LOGISTICS AGENCY",
    "DEFENSE ADVANCED RESEEARCH PROJECTS AGENCY": "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY",
    "CHIEF DIGITAL AND ARTIFICAL INTELLIGENCE OFFICE": "CHIEF DIGITAL AND ARTIFICIAL INTELLIGENCE OFFICE",
    "SOCOM": "U.S. SPECIAL OPERATIONS COMMAND",
    "USTRANSCOM": "U.S. TRANSPORTATION COMMAND",
    "DCSA": "DEFENSE COUNTERINTELLIGENCE AND SECURITY AGENCY",
}


def normalize_agency(a):
    if not a or not isinstance(a, str):
        return None
    up = re.sub(r"\s+", " ", a).strip().upper()
    return AGENCY_CANON.get(up, up)


def main():
    from huggingface_hub import HfApi

    print(f"Loading {REPO_ID} from HuggingFace...", file=sys.stderr)
    api = HfApi()
    shard_files = sorted(
        f for f in api.list_repo_files(REPO_ID, repo_type="dataset")
        if f.startswith("data/shard-")
    )
    dfs = [pd.read_parquet(f"hf://datasets/{REPO_ID}/{f}") for f in shard_files]
    df = pd.concat(dfs, ignore_index=True)
    print(f"{len(df):,} rows loaded from {len(shard_files)} shards", file=sys.stderr)

    df["agency"] = df["agency"].apply(normalize_agency)
    df["year"] = pd.to_datetime(df["date"], errors="coerce").dt.year
    df["id"] = range(len(df))

    df = df[["id", "date", "year", "agency", "text", "link", "article_title"]]
    df = df.sort_values("date", ascending=False, na_position="last").reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1_000_000
    print(f"wrote {len(df):,} rows -> {OUT_PATH} ({size_mb:.1f} MB)", file=sys.stderr)


if __name__ == "__main__":
    main()

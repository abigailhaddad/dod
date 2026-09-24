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


# Every award paragraph opens "<Company>, <City>, <State>, was/is awarded...";
# a US state name reliably anchors where the company name ends and the place
# begins, since a company name almost never contains one verbatim. Full
# names only (not two-letter codes) because that's what war.gov actually
# writes ("Salt Lake City, Utah", not "Salt Lake City, UT").
US_PLACES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
    "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah",
    "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin",
    "Wyoming", "D.C.", "Puerto Rico", "Guam", "American Samoa",
    "U.S. Virgin Islands", "Virgin Islands",
    "Commonwealth of the Northern Mariana Islands",
    "Northern Mariana Islands",
]
US_PLACES.sort(key=len, reverse=True)  # longest first so "Virgin Islands" doesn't shadow "U.S. Virgin Islands"
_PLACE_ALT = "|".join(re.escape(p) for p in US_PLACES)

# Company: lazy up to 80 chars, so a two-part name ("Lockheed Martin Corp.,
# Lockheed Martin Aeronautics Co.") still resolves but a match can't run away
# into unrelated boilerplate. `,\s*\**\s*` between company and city absorbs
# the small-business asterisk marker ("Inc.,* City" or "Inc., * City").
_COMPANY_PLACE_RE = re.compile(
    r"^(?P<company>.{2,80}?),\s*\**\s*"
    r"(?P<city>[A-Z][A-Za-z.'\-]+(?:[ \-][A-Z][A-Za-z.'\-]+){0,4}),\s*"
    r"(?P<place>" + _PLACE_ALT + r")\b"
)
# Text that can only occur past the opening clause, in the contract's own
# boilerplate -- if the lazy company match had to swallow this to find a
# state name, it found the WRONG state name (usually the contracting
# activity's location, not the awardee's) and should be rejected outright
# rather than published as a wrong company.
_RED_FLAGS_RE = re.compile(
    r"obligated|contracting activity|fiscal 20|solicited|is the contracting"
    r"|percent\)|task order|announced",
    re.I,
)


def extract_company_place(text):
    """Best-effort split of an award paragraph's opening "Company, City,
    State" clause. Returns (None, None) rather than a guess when a state
    name isn't found in the first ~80 characters, a CORRECTION/UPDATE
    preamble was swallowed, or a red-flag phrase suggests the match landed
    on the contracting activity instead of the awardee. ~95% match rate;
    known misses include multi-awardee paragraphs whose first-listed company
    is foreign (no US state to anchor on) and the rare source-side error
    (war.gov itself has, at least once, put a real company in the wrong
    state) -- not something this function can or should second-guess.
    """
    m = _COMPANY_PLACE_RE.match(text)
    if not m:
        return None, None
    company = m.group("company").strip()
    if re.match(r"^(CORRECTION|UPDATE)\b", company) and len(company) > 30:
        return None, None
    if _RED_FLAGS_RE.search(company) or len(company) >= 79:
        return None, None
    return company, f"{m.group('city').strip()}, {m.group('place').strip()}"


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
    company, place = zip(*df["text"].map(extract_company_place)) if len(df) else ((), ())
    df["company"] = company
    df["place"] = place

    df = df[["id", "date", "year", "agency", "company", "place", "text", "link", "article_title"]]
    df = df.sort_values("date", ascending=False, na_position="last").reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1_000_000
    print(f"wrote {len(df):,} rows -> {OUT_PATH} ({size_mb:.1f} MB)", file=sys.stderr)


if __name__ == "__main__":
    main()

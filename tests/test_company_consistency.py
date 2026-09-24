"""
Sanity checks on the company/place extraction against the real dataset.

`company` is extracted FROM `text`, so a company-field search can never
match more rows than a plain text search for the same term -- these two
counts are NOT expected to be equal, though: `company` only ever captures
the first-listed awardee in a multi-awardee IDIQ paragraph, so a company
that appears often in shared-award lists (Lockheed, Boeing, Raytheon...)
will show real, expected daylight between the two counts. What should
never happen is company_hits > text_hits (a value not grounded in its own
row's text) or a big drop in company_hits / text_hits for a company that
rarely appears as a non-first name in those lists (Palantir) -- either one
means a regex change broke something.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_PATH = Path(__file__).resolve().parent.parent / "web" / "data" / "contracts.parquet"

pytestmark = pytest.mark.skipif(
    not DATA_PATH.exists(),
    reason="web/data/contracts.parquet not built -- run build_web_data.py first",
)


@pytest.fixture(scope="module")
def df():
    return pd.read_parquet(DATA_PATH)


def _counts(df, term):
    text_hits = df["text"].str.contains(term, case=False, na=False).sum()
    company_hits = df["company"].str.contains(term, case=False, na=False).sum()
    return text_hits, company_hits


@pytest.mark.parametrize("term", [
    "Palantir", "Lockheed Martin", "Boeing", "Raytheon", "Northrop Grumman",
    "General Dynamics", "L3Harris",
])
def test_company_hits_never_exceed_text_hits(df, term):
    text_hits, company_hits = _counts(df, term)
    assert company_hits <= text_hits, (
        f"'{term}': company field matched {company_hits} rows but only "
        f"{text_hits} rows even mention it in text -- extraction is "
        f"producing values not grounded in their own row's text"
    )


@pytest.mark.parametrize("term", [
    "Palantir", "Lockheed Martin", "Boeing", "Raytheon", "Northrop Grumman",
    "General Dynamics", "L3Harris",
])
def test_company_recall_stays_high(df, term):
    text_hits, company_hits = _counts(df, term)
    assert text_hits > 0, f"expected at least one '{term}' mention in the dataset"
    recall = company_hits / text_hits
    # Observed recall for all seven ranges 86-93%; 80% leaves headroom for
    # noise (Palantir is a small-count term) without being toothless.
    assert recall >= 0.80, (
        f"'{term}': company field found {company_hits}/{text_hits} "
        f"({recall:.0%}) of text mentions -- expected at least 80%"
    )


def test_overall_match_rate_stays_high(df):
    matched = df["company"].notna().sum()
    rate = matched / len(df)
    assert rate >= 0.90, f"overall company match rate dropped to {rate:.1%} ({matched}/{len(df)})"

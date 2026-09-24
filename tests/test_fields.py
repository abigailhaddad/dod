"""Unit tests for fields.extract_company_place, one per bug found while
building it against real award text (see build_web_data.py's git history
for the actual rows each of these is drawn from)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fields import extract_company_place


def test_basic():
    text = "L3Harris Technologies Inc., Salt Lake City, Utah, is awarded an $876,440,942 cost-plus contract for..."
    assert extract_company_place(text) == ("L3Harris Technologies Inc.", "Salt Lake City, Utah")


def test_small_business_asterisk_no_space():
    text = "Massa Products Corp.,* Hingham, Massachusetts, is awarded a $61,819,998 firm-fixed-price contract..."
    assert extract_company_place(text) == ("Massa Products Corp.", "Hingham, Massachusetts")


def test_small_business_asterisk_with_space():
    text = "Chitra Productions LLC, * Norfolk, Virginia (N39430-21-D-2310); SV Synergies LLC..."
    assert extract_company_place(text) == ("Chitra Productions LLC", "Norfolk, Virginia")


def test_two_part_company_name():
    text = "The Boeing Co., Boeing Defense Space and Security, St. Louis, Missouri, is awarded..."
    assert extract_company_place(text) == (
        "The Boeing Co., Boeing Defense Space and Security", "St. Louis, Missouri"
    )


def test_dc_followed_by_comma():
    # \b fails here: "D.C." ends in a period (non-word char) immediately
    # followed by a comma (also non-word), so a word-boundary anchor never
    # fires right where the match needs to end.
    text = "Palantir, Washington, D.C., was awarded a $91,176,844 firm-fixed-price contract..."
    assert extract_company_place(text) == ("Palantir", "Washington, D.C.")


def test_district_of_columbia_full_name():
    text = "Palantir Technologies Inc., Washington, District of Columbia, is being awarded $11,750,000..."
    assert extract_company_place(text) == ("Palantir Technologies Inc.", "Washington, District of Columbia")


def test_correction_narrative_preamble_rejected():
    # "announced" is a red-flag word -- once the "CORRECTION: " tag is
    # stripped, this still reads as a narrative describing the original
    # announcement, not a company name, and gets rejected.
    text = ("CORRECTION: The contract announced Dec. 6, 2021, to FOAMTEC International LLC, "
            "Woodway, Texas (FA8529-22-C-0001), for domestic capacity extension...")
    assert extract_company_place(text) == (None, None)


def test_update_tag_stripped_from_simple_case():
    # A plain "UPDATE: Company, City, State" -- about half of all UPDATE:
    # rows look like this, structurally identical to the base case once the
    # tag itself is stripped.
    text = "UPDATE: Dentsply North America LLC, Charlotte, North Carolina (SPE2DF-26-D-0020, $49,500,000) has been added..."
    assert extract_company_place(text) == ("Dentsply North America LLC", "Charlotte, North Carolina")


def test_red_flag_boilerplate_rejected():
    # A garbled fragment (the real award text got split elsewhere); without
    # the red-flag check this would extract "Army Contracting Command" as
    # if it were the awardee.
    text = "of $13,388,146 were obligated at the time of the award. Army Contracting Command, Ft. Belvoir, Virginia is the contracting activity (W91QV1-15-C-0122)."
    assert extract_company_place(text) == (None, None)


def test_multi_awardee_only_captures_first():
    text = ("Booz Allen Hamilton Inc., McLean, Virginia (M95494-20-D-4001); Calibre Systems Inc., "
            "Alexandria, Virginia (M95494-20-D-4002); Corps Solutions...")
    assert extract_company_place(text) == ("Booz Allen Hamilton Inc.", "McLean, Virginia")


def test_foreign_first_awardee_yields_no_match():
    # No US state appears before the 80-char cap, since the first company's
    # own place is foreign -- known limitation, documented behavior.
    text = ("Aecom International Inc., Neu-Isenburg, Germany (W912GB-24-D-0038); "
            "Atkins-UC JV, Alexandria, Virginia...")
    assert extract_company_place(text) == (None, None)


def test_no_match_returns_none():
    assert extract_company_place("There are no contracts to announce today.") == (None, None)


def test_empty_and_none_input():
    assert extract_company_place("") == (None, None)
    assert extract_company_place(None) == (None, None)

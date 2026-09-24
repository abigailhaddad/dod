"""
Derived-field extraction shared between scrape.py (computed at scrape time
for new rows) and the one-time backfill for already-published rows.

Every award paragraph opens "<Company>, <City>, <State>, was/is awarded...";
a full US state name reliably anchors where the company name ends and the
place begins, since a real company name essentially never contains one
verbatim. Full names only (not two-letter codes), because that's what
war.gov actually writes ("Salt Lake City, Utah", not "Salt Lake City, UT").
"""

import re

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
    "Wyoming", "D.C.", "District of Columbia", "Puerto Rico", "Guam",
    "American Samoa", "U.S. Virgin Islands", "Virgin Islands",
    "Commonwealth of the Northern Mariana Islands",
    "Northern Mariana Islands",
]
US_PLACES.sort(key=len, reverse=True)  # longest first so "Virgin Islands" doesn't shadow "U.S. Virgin Islands"
_PLACE_ALT = "|".join(re.escape(p) for p in US_PLACES)

# Company: lazy up to 80 chars, so a two-part name ("Lockheed Martin Corp.,
# Lockheed Martin Aeronautics Co.") still resolves but a match can't run away
# into unrelated boilerplate. `,\s*\**\s*` between company and city absorbs
# the small-business asterisk marker ("Inc.,* City" or "Inc., * City"). The
# place ends on a lookahead for whitespace/punctuation/end-of-string rather
# than \b: \b needs a word/non-word transition, which "D.C." followed
# immediately by a comma ("Washington, D.C., was awarded...") never gets --
# both the trailing period and the comma are non-word characters, so \b
# silently fails to match right where it matters most.
_COMPANY_PLACE_RE = re.compile(
    r"^(?P<company>.{2,80}?),\s*\**\s*"
    r"(?P<city>[A-Z][A-Za-z.'\-]+(?:[ \-][A-Z][A-Za-z.'\-]+){0,4}),\s*"
    r"(?P<place>" + _PLACE_ALT + r")(?=[\s,.)]|$)"
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
    name isn't found in the first ~80 characters, or a red-flag phrase
    suggests the match landed on the contracting activity instead of the
    awardee. ~95% match rate; known misses include multi-awardee paragraphs
    whose first-listed company is foreign or missing a comma before its
    city (no US state to anchor on at all, or not where expected), and the
    rare source-side error (war.gov itself has, at least once, put a real
    company in the wrong state) -- not something this function can or
    should second-guess.

    A leading "CORRECTION:"/"UPDATE:" tag is stripped before the checks
    below run, not treated as disqualifying on its own: about half of
    "UPDATE:" rows are a plain "UPDATE: Company, City, State" naming one
    added awardee, structurally identical to the base case once the tag is
    off. The other half -- "CORRECTION: The contract announced Dec. 6,
    2021, to FOAMTEC..." -- describe the original announcement first, and
    are caught by the same red-flag/length checks that would catch a lazy
    match that swallowed any other boilerplate, since "announced" is
    already one of the flagged words.
    """
    if not text or not isinstance(text, str):
        return None, None
    m = _COMPANY_PLACE_RE.match(text)
    if not m:
        return None, None
    company = re.sub(r"^(CORRECTION|UPDATE):\s*", "", m.group("company").strip())
    if _RED_FLAGS_RE.search(company) or len(company) >= 79:
        return None, None
    return company, f"{m.group('city').strip()}, {m.group('place').strip()}"

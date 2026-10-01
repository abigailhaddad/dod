"""dedupe.is_repost, drawn from the real Sept. 28/29, 2026 war.gov re-post."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dedupe import is_repost, row_key


def rows(*texts):
    return [{"text": t} for t in texts]


def test_exact_copy_is_repost():
    known = {row_key(t) for t in ["A Corp., Ohio, was awarded $1.", "B Inc., Texas, was awarded $2."]}
    assert is_repost(rows("A Corp., Ohio, was awarded $1.", "B Inc., Texas, was awarded $2."), known)


def test_whitespace_and_case_variants_still_match():
    known = {row_key("Raytheon, Tucson, Arizona, was awarded a $57,8")}
    assert is_repost(rows("Raytheon,  Tucson, Arizona,\nwas awarded a $57,8"), known)


def test_mostly_copied_with_a_few_new_rows_is_repost():
    # real case: 52 of 68 rows matched exactly, the other 16 differed only in spacing
    known = {row_key(f"row {i}") for i in range(52)}
    assert is_repost(rows(*[f"row {i}" for i in range(52)], *[f"new {i}" for i in range(16)]), known)


def test_a_few_repeated_awards_is_not_repost():
    # legit overlap between different days tops out around 30%
    known = {row_key(f"row {i}") for i in range(3)}
    assert not is_repost(rows(*[f"row {i}" for i in range(3)], *[f"new {i}" for i in range(7)]), known)


def test_empty_article_is_not_repost():
    assert not is_repost([], {"x"})

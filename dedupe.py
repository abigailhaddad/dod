"""Detect war.gov re-posting an existing day's article under a new URL.

Seen in the wild: article 4614322, titled "Contracts for Sept. 28, 2026",
was a copy of the Sept. 29 article (4614270) -- 68 rows, every one already
published -- so Sept. 28 showed 138 rows instead of 70. We key on article URL,
so a re-post looks new. Across the whole 2014-2026 archive this was the only
pair of articles sharing more than 30% of their rows (it shared 100%; the next
highest was 30%, from legitimately repeated awards), so 50% separates them.
"""

import re

REPOST_THRESHOLD = 0.5


def row_key(text):
    """Whitespace/punctuation/case-insensitive key; re-posts differ in spacing."""
    return re.sub(r"\W+", "", text.lower())


def is_repost(rows, known_keys, threshold=REPOST_THRESHOLD):
    """True if at least `threshold` of the article's rows already exist in
    `known_keys` (row_keys of recently published articles)."""
    if not rows:
        return False
    hits = sum(1 for r in rows if row_key(r["text"]) in known_keys)
    return hits / len(rows) >= threshold

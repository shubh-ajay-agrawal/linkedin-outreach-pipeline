"""
title_filter.py
Filters enriched leads by job title.
KEEP leads with target titles, DROP leads with exclusion titles.
If title is missing/blank, KEEP the lead (benefit of the doubt).
"""


# Keywords that indicate a decision-maker we want to reach
KEEP_KEYWORDS = [
    "founder", "co-founder", "cofounder",
    "ceo", "chief executive",
    "cro", "chief revenue",
    "head of sales", "head of growth", "head of revenue", "head of marketing",
    "vp sales", "vp of sales", "vp growth", "vp of growth",
    "vice president sales", "vice president growth",
    "director of sales", "director of growth", "director of revenue",
    "account executive", "ae",
    "demand gen", "demand generation",
    "revenue", "gtm", "go-to-market",
    "sales lead", "growth lead",
    "owner",
]

# Keywords that indicate someone we should skip
DROP_KEYWORDS = [
    "student", "intern", "internship",
    "freelance", "freelancer",
    "job seeker", "looking for", "open to work",
    "assistant", "coordinator",
    "entry level", "junior",
]


def filter_leads(leads: list[dict]) -> tuple[list[dict], int]:
    """
    Filter a list of enriched lead dicts by job title.

    Args:
        leads: list of dicts, each must have a 'title' key (can be None/blank).

    Returns:
        (kept_leads, dropped_count)
    """
    kept = []
    dropped = 0

    for lead in leads:
        title = (lead.get("title") or "").strip().lower()

        # Missing or blank title — keep (benefit of the doubt)
        if not title:
            kept.append(lead)
            continue

        # Check DROP keywords first — if matched, skip this lead
        if any(kw in title for kw in DROP_KEYWORDS):
            dropped += 1
            continue

        # Check KEEP keywords — if matched, keep
        if any(kw in title for kw in KEEP_KEYWORDS):
            kept.append(lead)
            continue

        # Title present but matches neither list — drop
        dropped += 1

    return kept, dropped

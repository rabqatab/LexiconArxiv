"""A1(a) — `type` distribution INSIDE the CS keep-set (non-stub + keep-topic).

Wave 4c removed cross-domain non-article junk (books/peer-reviews/editorials that
were mis-fielded P2/P3 injections) by demoting the whole non-CS slice. What
remains: non-article works that ARE on-topic (CS/Math/etc.) but still aren't
papers — e.g. an editorial in a CS journal, a book chapter in Language &
Linguistics. This measures how many, by type, so we can decide a keep/demote
policy for the keep-set itself.

`type` is an indexed keyword field (Wave 4c 2026-07-06), so every count is an
exact indexed count over 6.2M points without a scroll timeout.

Usage: uv run python scripts/analytics/count_type_in_keepset.py
"""
import json

from qdrant_client import models

from src.core.snapshot.topic_gate import KEEP_FIELDS, KEEP_SUBFIELDS
from src.core.storage import QdrantStorage

FIELD_KEY = "primary_topic.field.display_name"
SUBFIELD_KEY = "primary_topic.subfield.display_name"
_STUB = models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))

# OpenAlex work types. "article"/"preprint" are real papers; the rest are the
# candidates a paper-search corpus arguably shouldn't surface as first-class.
PAPER_TYPES = ["article", "preprint"]
NONPAPER_TYPES = [
    "book-chapter", "book", "dataset", "dissertation", "paratext", "editorial",
    "letter", "erratum", "peer-review", "review", "report", "standard", "grant",
    "retraction", "other", "reference-entry", "libguides", "supplementary-materials",
]

# keep-set = non-stub AND (field in KEEP_FIELDS OR subfield in KEEP_SUBFIELDS)
KEEP_SET_MUST = [models.Filter(should=[
    models.FieldCondition(key=FIELD_KEY, match=models.MatchAny(any=sorted(KEEP_FIELDS))),
    models.FieldCondition(key=SUBFIELD_KEY, match=models.MatchAny(any=sorted(KEEP_SUBFIELDS))),
])]


def count(s, must=None, must_not=None):
    return s.client.count(s.collection_name, exact=True,
                          count_filter=models.Filter(must=must, must_not=must_not)).count


def main():
    s = QdrantStorage()
    out = {}
    out["keep_set_total"] = count(s, must=KEEP_SET_MUST, must_not=[_STUB])

    def type_count(t):
        return count(s, must=KEEP_SET_MUST + [
            models.FieldCondition(key="type", match=models.MatchValue(value=t))], must_not=[_STUB])

    out["paper_types"] = {t: type_count(t) for t in PAPER_TYPES}
    nonpaper = {t: type_count(t) for t in NONPAPER_TYPES}
    out["nonpaper_types"] = dict(sorted(nonpaper.items(), key=lambda kv: -kv[1]))
    out["nonpaper_total"] = sum(nonpaper.values())

    # no-type (unclassified) inside keep-set
    out["no_type"] = count(s, must=KEEP_SET_MUST,
                           must_not=[_STUB, models.IsEmptyCondition(is_empty=models.PayloadField(key="type"))]) \
        if False else count(s, must=KEEP_SET_MUST + [
            models.IsEmptyCondition(is_empty=models.PayloadField(key="type"))], must_not=[_STUB])

    accounted = sum(out["paper_types"].values()) + out["nonpaper_total"] + out["no_type"]
    out["other_types_uncounted"] = out["keep_set_total"] - accounted
    out["nonpaper_share_pct"] = round(100 * out["nonpaper_total"] / max(out["keep_set_total"], 1), 3)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

"""Wave 4c corpus gates at the P2/P3 boundary: topic gate + type gate.

Topic gate (docs/plans/2026-07-06-corpus-cs-cleanup.md §2): a work enters (or is
promoted within) the real-paper corpus only if its OpenAlex primary_topic
field is in KEEP_FIELDS, or its subfield is in KEEP_SUBFIELDS. Works with no
primary_topic at all are rejected — they are almost entirely cross-domain
injections even OpenAlex couldn't classify.

Type gate (A1(a), 2026-07-17): even on-topic works are kept OUT of the real
corpus when their OpenAlex `type` is a clear non-paper (a `book` whose abstract
is a table of contents, an `editorial`, a `peer-review` thread). article /
preprint / review(surveys) / book-chapter / dissertation / report / dataset /
letter — and works with NO type (mostly crawler papers OpenAlex never typed) —
all PASS. Only the DROP_TYPES below are gated. Mirror of the demotion applied by
scripts/analytics/demote_types_in_keepset.py.
"""

KEEP_FIELDS = {
    "Computer Science",
    "Mathematics",
    "Decision Sciences",     # statistics, OR, operational
    "Neuroscience",          # brain-inspired models, cog sci
    "Psychology",            # cognitive psychology, psycholinguistics
}

KEEP_SUBFIELDS = {
    "Language and Linguistics",  # from Arts and Humanities field
}


def is_keep_topic(primary_topic) -> bool:
    """True if a work/payload ``primary_topic`` dict passes the Wave 4c gate.

    Accepts the OpenAlex work shape and the stored payload shape (identical):
    ``{"field": {"display_name": ...}, "subfield": {"display_name": ...}}``.
    None / missing / malformed → False.
    """
    if not isinstance(primary_topic, dict):
        return False
    field = ((primary_topic.get("field") or {}).get("display_name") or "").strip()
    if field in KEEP_FIELDS:
        return True
    subfield = ((primary_topic.get("subfield") or {}).get("display_name") or "").strip()
    return subfield in KEEP_SUBFIELDS


# Clear non-paper OpenAlex work types (user decision 2026-07-17, "junk only").
# review(surveys), book-chapter, dissertation, report, dataset, letter are NOT
# here — they are legitimate research artifacts and stay in the corpus.
DROP_TYPES = {
    "book", "paratext", "other", "editorial", "reference-entry",
    "erratum", "standard", "retraction", "peer-review",
}


def is_keep_type(work) -> bool:
    """False only if the work's OpenAlex ``type`` is a clear non-paper.

    Missing / empty type PASSES (True) — untyped works are mostly crawler papers
    OpenAlex never classified, and must not be gated out.
    """
    if not isinstance(work, dict):
        return True
    return (work.get("type") or "").strip() not in DROP_TYPES

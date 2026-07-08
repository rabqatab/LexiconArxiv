"""Wave 4c topic gate: keep only AI/NLP-adjacent works at the P2/P3 boundary.

Policy (docs/plans/2026-07-06-corpus-cs-cleanup.md §2): a work enters (or is
promoted within) the real-paper corpus only if its OpenAlex primary_topic
field is in KEEP_FIELDS, or its subfield is in KEEP_SUBFIELDS. Works with no
primary_topic at all are rejected — they are almost entirely cross-domain
injections even OpenAlex couldn't classify.
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

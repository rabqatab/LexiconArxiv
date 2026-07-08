"""Wave 4c Task 1.1 — exact keep/delete counts with the production topic gate.

Uses the keyword indices on primary_topic.{field,subfield}.display_name
(2026-07-08) so every count is an indexed exact count, not a sample.

Usage: uv run python scripts/analytics/count_by_topic.py
"""
import json

from qdrant_client import models

from src.core.snapshot.topic_gate import KEEP_FIELDS, KEEP_SUBFIELDS
from src.core.storage import QdrantStorage

FIELD_KEY = "primary_topic.field.display_name"
SUBFIELD_KEY = "primary_topic.subfield.display_name"

_STUB = models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))

DELETE_FIELDS_OF_INTEREST = [
    "Medicine", "Engineering", "Biochemistry, Genetics and Molecular Biology",
    "Physics and Astronomy", "Social Sciences", "Environmental Science",
    "Business, Management and Accounting", "Materials Science", "Chemistry",
    "Economics, Econometrics and Finance", "Earth and Planetary Sciences",
    "Immunology and Microbiology", "Agricultural and Biological Sciences",
    "Health Professions", "Arts and Humanities", "Nursing", "Chemical Engineering",
    "Pharmacology, Toxicology and Pharmaceutics", "Dentistry", "Veterinary",
    "Energy",
]

YEAR_BUCKETS = [(None, 2009), (2010, 2014), (2015, 2019), (2020, 2024), (2025, 2026)]


def count(s, must=None, must_not=None):
    return s.client.count(s.collection_name, exact=True,
                          count_filter=models.Filter(must=must, must_not=must_not)).count


def delete_filter_conditions():
    """The exact Phase 3 delete filter.

    non-stub AND NOT(keep-field) AND NOT(keep-subfield) AND P2/P3-provenance
    only. Crawler-fetched papers (fetched_at set — tier venues, incremental
    runs) are protected regardless of topic: 2026-07-08 Phase 1 sampling
    showed the 66K non-injected candidates are ICLR/NeurIPS/ACL papers that
    OpenAlex mis-fields or never classified.
    """
    return dict(
        must=[models.Filter(should=[
            models.FieldCondition(key="injected_from_snapshot", match=models.MatchValue(value=True)),
            models.FieldCondition(key="promoted_from_stub", match=models.MatchValue(value=True)),
        ])],
        must_not=[
            _STUB,
            models.FieldCondition(key=FIELD_KEY, match=models.MatchAny(any=sorted(KEEP_FIELDS))),
            models.FieldCondition(key=SUBFIELD_KEY, match=models.MatchAny(any=sorted(KEEP_SUBFIELDS))),
        ])


def main():
    s = QdrantStorage()
    out = {}
    out["total_points"] = count(s)
    out["non_stub_total"] = count(s, must_not=[_STUB])

    # KEEP breakdown
    keep = {}
    for f in sorted(KEEP_FIELDS):
        keep[f] = count(s, must=[models.FieldCondition(key=FIELD_KEY, match=models.MatchValue(value=f))],
                        must_not=[_STUB])
    for sf in sorted(KEEP_SUBFIELDS):
        keep[f"subfield:{sf} (outside keep-fields)"] = count(
            s,
            must=[models.FieldCondition(key=SUBFIELD_KEY, match=models.MatchValue(value=sf))],
            must_not=[_STUB, models.FieldCondition(key=FIELD_KEY, match=models.MatchAny(any=sorted(KEEP_FIELDS)))],
        )
    out["keep_breakdown"] = keep
    out["keep_total"] = count(
        s,
        must_not=[_STUB],
        must=[models.Filter(should=[
            models.FieldCondition(key=FIELD_KEY, match=models.MatchAny(any=sorted(KEEP_FIELDS))),
            models.FieldCondition(key=SUBFIELD_KEY, match=models.MatchAny(any=sorted(KEEP_SUBFIELDS))),
        ])],
    )

    # DELETE set — the Phase 3 filter, plus per-field and per-year views
    dfc = delete_filter_conditions()
    out["delete_total"] = count(s, **dfc)
    delete_fields = {}
    for f in DELETE_FIELDS_OF_INTEREST:
        delete_fields[f] = count(
            s,
            must=[models.FieldCondition(key=FIELD_KEY, match=models.MatchValue(value=f))],
            must_not=[_STUB, models.FieldCondition(key=SUBFIELD_KEY,
                                                   match=models.MatchAny(any=sorted(KEEP_SUBFIELDS)))],
        )
    out["delete_by_field"] = dict(sorted(delete_fields.items(), key=lambda kv: -kv[1]))
    out["delete_no_topic"] = count(
        s,
        must=[models.IsEmptyCondition(is_empty=models.PayloadField(key=FIELD_KEY))],
        must_not=[_STUB],
    )

    per_year = {}
    for lo, hi in YEAR_BUCKETS:
        rng = models.Range(gte=lo, lte=hi) if lo else models.Range(lte=hi)
        n = count(s, must=dfc["must"] + [models.FieldCondition(key="year", range=rng)],
                  must_not=dfc["must_not"])
        per_year[f"{lo or 'pre'}-{hi}"] = n
    per_year["no_year"] = out["delete_total"] - sum(per_year.values())
    out["delete_by_year_bucket"] = per_year

    # provenance of the delete set
    prov = {}
    for name, cond in [
        ("p3_injected", models.FieldCondition(key="injected_from_snapshot", match=models.MatchValue(value=True))),
        ("p2_promoted", models.FieldCondition(key="promoted_from_stub", match=models.MatchValue(value=True))),
    ]:
        prov[name] = count(s, must=dfc["must"] + [cond], must_not=dfc["must_not"])
    prov["other"] = out["delete_total"] - sum(prov.values())
    out["delete_by_provenance"] = prov

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

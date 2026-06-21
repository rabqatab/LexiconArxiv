# Snapshot Test Fixtures

| File | Scenarios it covers |
|---|---|
| `works/tiny.jsonl.gz` | DOI match, title match (corroborated + uncorroborated), AI-concept gap, anchor gap, empty `abstract_inverted_index`, malformed line, duplicate DOI within the same file |
| `corpus/seed_papers.json` | 10 real papers across venues with varying DOI / openalex_id / cited_by states |
| `corpus/seed_stubs.json` | 8 stubs — 2 each for identifier_type `doi`, `arxiv`, `title`, `openalex` |

Adding a scenario: append a JSON line to the source for the appropriate fixture, regenerate the `.gz`, and add a test case that asserts the expected classification.

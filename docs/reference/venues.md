# Venue Reference

This document is the single source of truth for venue classifications and identifiers.

---

## Venue Tiers

| Tier | Description | Count |
|------|-------------|-------|
| **Tier 0** | Core Corpus - Top-tier venues (mandatory collection) | 11 |
| **Tier 1** | Extended Corpus - Secondary venues (priority collection) | 14 |
| **Tier 2** | Specialized Corpus - Domain-specific venues | 3+ |

---

## Tier 0 - Core Corpus (11 venues)

### Machine Learning

| Venue | Full Name | Type | OpenAlex Source IDs |
|-------|-----------|------|---------------------|
| NeurIPS | Neural Information Processing Systems | conference | S4306420609 |
| ICML | International Conference on Machine Learning | conference | S4306419644 |
| ICLR | International Conference on Learning Representations | conference | S4306419637 |
| JMLR | Journal of Machine Learning Research | journal | S118988714 |

### Artificial Intelligence

| Venue | Full Name | Type | OpenAlex Source IDs |
|-------|-----------|------|---------------------|
| AAAI | AAAI Conference on Artificial Intelligence | conference | S4210191458 |
| IJCAI | International Joint Conference on AI | conference | S4306419999, S4363608755 |

### Natural Language Processing

| Venue | Full Name | Type | OpenAlex Source IDs |
|-------|-----------|------|---------------------|
| ACL | Annual Meeting of the ACL | conference | S4306420508, S4363608652 |
| EMNLP | Empirical Methods in NLP | conference | S4306418267, S4363608991 |

### Data Mining / Web / Information Retrieval

| Venue | Full Name | Type | OpenAlex Source IDs |
|-------|-----------|------|---------------------|
| KDD | Knowledge Discovery and Data Mining | conference | S4306420424, S4363608767 |
| WWW | The Web Conference | conference | S4363608783, S4306421067, S4363608846 |
| SIGIR | ACM SIGIR Conference | conference | S4306418959, S4363608773 |

---

## Tier 1 - Extended Corpus (14 venues)

### Natural Language Processing

| Venue | Full Name | Type | OpenAlex Source IDs |
|-------|-----------|------|---------------------|
| NAACL | North American Chapter of ACL | conference | S4306420633, S4363608774 |
| EACL | European Chapter of ACL | conference | S4306418011 |
| COLING | International Conference on Computational Linguistics | conference | S4306419219 |
| Findings | Findings of the ACL | conference | S4363605144, S4363605604 |
| TACL | Transactions of the ACL | journal | S2729999759 |
| CoNLL | Conference on Computational Natural Language Learning | conference | S4306418031 |
| LREC | Language Resources and Evaluation Conference | conference | S4306424877 |

### Information Retrieval / Data Mining

| Venue | Full Name | Type | OpenAlex Source IDs |
|-------|-----------|------|---------------------|
| WSDM | Web Search and Data Mining | conference | S4363608885 |
| CIKM | Conference on Information and Knowledge Management | conference | S4363608762 |
| ICDM | IEEE International Conference on Data Mining | conference | S4363608061, S4363608104 |
| ECIR | European Conference on Information Retrieval | conference | S4306418323 |
| RecSys | ACM Conference on Recommender Systems | conference | S4306418092 |
| TOIS | ACM Transactions on Information Systems | journal | S4394735545 |

### Artificial Intelligence

| Venue | Full Name | Type | OpenAlex Source IDs |
|-------|-----------|------|---------------------|
| ESWA | Expert Systems with Applications | journal | S13144211 |

---

## Tier 2 - Specialized Corpus

### Legal AI (3 venues)

| Venue | Full Name | Type | OpenAlex Source IDs | Notes |
|-------|-----------|------|---------------------|-------|
| AILaw | Artificial Intelligence and Law | journal | S96609033 | Primary Legal AI journal |
| ICAIL | International Conference on AI and Law | conference | S4306419144 | Limited OpenAlex coverage |
| JURIX | International Conference on Legal Knowledge Systems | conference | S4306419638 | Limited OpenAlex coverage |

### ACL Workshops (90+ venues)

Workshop papers are dynamically collected from ACL Anthology XML files. Examples:

| Workshop | Description | Est. Papers/Year |
|----------|-------------|------------------|
| BioNLP | Biomedical NLP | ~80 |
| Clinical NLP | Clinical text processing | ~60 |
| ArgMining | Argument Mining | ~20 |
| SemEval | Semantic Evaluation | ~150 |
| BlackboxNLP | Analyzing Neural Networks | ~35 |

Workshop papers are stored with `venue_type: "workshop"` and `tier: 2`.

---

## Field Categories

| Field | Description | Venues |
|-------|-------------|--------|
| ML | Machine Learning | NeurIPS, ICML, ICLR, JMLR |
| AI | Artificial Intelligence | AAAI, IJCAI, ESWA |
| NLP | Natural Language Processing | ACL, EMNLP, NAACL, EACL, COLING, Findings, TACL, CoNLL, LREC |
| DM | Data Mining | KDD, ICDM |
| IR | Information Retrieval | SIGIR, WSDM, CIKM, ECIR, RecSys, TOIS |
| Web | Web | WWW |
| Legal | Legal AI / Computational Law | AILaw, ICAIL, JURIX |

---

## Data Sources by Venue

| Source | Primary Venues | Secondary Venues |
|--------|----------------|------------------|
| **OpenAlex** | NeurIPS, ICML, ICLR, AAAI, IJCAI, KDD, SIGIR, WWW, JMLR, ESWA, TOIS | All venues (metadata enrichment) |
| **ACL Anthology** | ACL, EMNLP, NAACL, EACL, COLING, Findings, TACL, CoNLL, LREC | 90+ workshops |
| **OpenReview** | ICLR, NeurIPS, ICML | - |
| **ACM Digital Library** | KDD, SIGIR, WWW, RecSys, CIKM, WSDM | - |
| **DBLP** | RecSys, ECIR, ICAIL, JURIX | WSDM, CIKM, ICDM |
| **AAAI OJS** | AAAI (2020-2023) | ICWSM |

---

## OpenAlex Source ID Notes

- **Alt IDs**: Some venues have multiple Source IDs in OpenAlex due to year-specific entries
- **OR Condition**: When querying, combine all IDs with OR: `primary_location.source.id:S123|S456`
- **Discovery**: Use `python -m src.cli.core_collect discover-sources --venue <name>` to find IDs

---

## Venue Type Values

| Value | Description |
|-------|-------------|
| `conference` | Main conference proceedings |
| `workshop` | Workshop papers |
| `journal` | Journal articles |
| `preprint` | Preprints (arXiv) |

---

## Domain Scope (arXiv Categories)

For on-demand retrieval of papers not in Core Corpus:

| Category | Description | Included |
|----------|-------------|----------|
| `cs.CL` | Computation and Language | Yes |
| `cs.AI` | Artificial Intelligence | Yes |
| `cs.LG` | Machine Learning | Yes |
| `cs.IR` | Information Retrieval | Yes |
| `cs.CV` | Computer Vision | No |
| `cs.RO` | Robotics | No |
| `eess.AS` | Audio and Speech | No |

---

## See Also

- [Data Collection Pipeline](../pipelines/data_collection.md)
- [CLI Reference](./cli.md)

# Data Collection Strategy

## 1. Overview

This document defines the **Venue-based Core Corpus collection** strategy and **On-demand Retrieval** implementation.

### 1.1 Collection Strategy Summary

| Type | Target | Timing | Storage |
|------|--------|--------|---------|
| **Core Corpus** | All papers from Tier 0/1/2 venues | Pre-collected | Permanent |
| **On-demand** | arXiv, OpenAlex search results | Query-time | Cache (optional persist) |

### 1.2 Multi-Source Architecture

OpenAlex alone has insufficient NLP venue coverage, requiring a multi-source strategy:

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA SOURCE STRATEGY                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐    Primary source for ML venues            │
│  │  OpenAlex   │ ─► NeurIPS, ICML, ICLR, AAAI, IJCAI        │
│  │  (~40K)     │    KDD, SIGIR, JMLR, ESWA, TOIS            │
│  └─────────────┘                                             │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐    Required for NLP venues                 │
│  │ ACL Anthol. │ ─► ACL, EMNLP, NAACL, EACL, COLING         │
│  │  (~30K)     │    Findings, CoNLL, LREC + 90+ workshops   │
│  └─────────────┘                                             │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐    Supplementary for IR/Legal venues       │
│  │    DBLP     │ ─► RecSys, ECIR, WSDM, CIKM                │
│  │  (~5K)      │    ICAIL, JURIX, ICDM                      │
│  └─────────────┘                                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Venue Classification

See [Venue Reference](../reference/venues.md) for complete venue details.

### 2.1 Tier Summary

| Tier | Count | Description | Primary Source |
|------|-------|-------------|----------------|
| Tier 0 | 11 | Core venues (NeurIPS, ICML, ACL, etc.) | OpenAlex, ACL Anthology |
| Tier 1 | 14 | Extended venues (NAACL, WSDM, etc.) | OpenAlex, ACL Anthology, DBLP |
| Tier 2 | 3+ | Specialized + 90+ workshops | DBLP, ACL Anthology |

### 2.2 Coverage Gap Analysis

| Source | Papers (2020+) | Coverage |
|--------|----------------|----------|
| OpenAlex (primary IDs) | 37,198 | Baseline |
| OpenAlex (with alt IDs) | 41,469 | +11.5% |
| ACL Anthology | 20,111 | NLP venues only |
| DBLP | ~5,000 | IR/Legal venues |

**Critical Gap**: OpenAlex has only 2,614 papers for ACL/EMNLP/NAACL/EACL/COLING/Findings, while ACL Anthology has 20,111 papers for same venues (87% gap!)

---

## 3. Data Sources

### 3.1 Source Summary

| Source | Purpose | API Limit | Priority | Target Venues |
|--------|---------|-----------|----------|---------------|
| **OpenAlex** | Core metadata + citation graph | 100K/day (API key) | P0 | ML/AI venues |
| **ACL Anthology** | NLP venue collection (XML parsing) | Bulk download | P0 | ACL, EMNLP, NAACL, etc. |
| **OpenReview** | ML conference papers | 1 req/sec | P0 | ICLR, NeurIPS, ICML |
| **ACM DL** | ACM conferences (open access) | 0.5 req/sec | P1 | KDD, SIGIR, WWW |
| **DBLP** | IR/Legal venue supplement | API | P1 | ECIR, ICAIL, JURIX |
| **AAAI OJS** | AAAI proceedings | 1 req/sec | P1 | AAAI, ICWSM |
| **arXiv** | On-demand latest preprints | 3 req/sec | P2 | All categories |
| **Semantic Scholar** | Additional metadata supplement | 100/5min (free) | P2 | Fallback |

### 3.2 Source Selection by Venue

| Venue Type | Primary Source | Supplementary |
|------------|---------------|---------------|
| ML/AI conferences (NeurIPS, ICML, ICLR, AAAI, IJCAI) | OpenAlex | - |
| NLP conferences (ACL, EMNLP, NAACL, EACL, COLING) | **ACL Anthology** | OpenAlex |
| IR conferences (SIGIR, RecSys, ECIR) | OpenAlex | DBLP |
| DM conferences (KDD, WSDM, CIKM, ICDM) | OpenAlex | DBLP |
| Legal AI (ICAIL, JURIX) | **DBLP** | OpenAlex |
| Journals (JMLR, TACL, TOIS, ESWA, AILaw) | OpenAlex | - |

### 3.3 Domain Scope (arXiv Categories)

Used for on-demand search of arXiv papers not in Core:

| Category | Description | Included |
|----------|-------------|----------|
| `cs.CL` | Computation and Language | Yes |
| `cs.AI` | Artificial Intelligence | Yes |
| `cs.LG` | Machine Learning | Yes |
| `cs.IR` | Information Retrieval | Yes |
| `cs.CV` | Computer Vision | No (excluded) |
| `cs.RO` | Robotics | No (excluded) |
| `eess.AS` | Audio and Speech | No (excluded) |

### 3.4 Source-Specific API Details

#### ACL Anthology

| Aspect | Details |
|--------|---------|
| **Data Format** | XML files on GitHub |
| **API Endpoint** | `https://api.github.com/repos/acl-org/acl-anthology/git/trees/master?recursive=1` |
| **File Pattern** | `{year}.{venue}.xml` (e.g., `2025.acl.xml`) |
| **Pagination** | Git Trees API (no limit) - Contents API limited to 1000 files |

**Venue Prefixes:**
```python
ACL_VENUES = {
    "acl": ["acl"],           # Main ACL conference
    "emnlp": ["emnlp"],       # EMNLP
    "naacl": ["naacl"],       # NAACL
    "eacl": ["eacl"],         # EACL
    "aacl": ["aacl", "ijcnlp"],  # AACL (also under ijcnlp.xml)
    "coling": ["coling"],     # COLING
    "findings": ["findings"], # Findings (ACL, EMNLP, NAACL)
    "tacl": ["tacl"],         # TACL journal
    "conll": ["conll"],       # CoNLL
    "lrec": ["lrec"],         # LREC
}
```

#### OpenReview

| Aspect | Details |
|--------|---------|
| **API Versions** | v1 (`api.openreview.net`) for ≤2023, v2 (`api2.openreview.net`) for 2024+ |
| **Invitation Pattern** | `{venue}/{year}/Conference/-/Submission` |
| **Accepted Filter** | `content.venue` field contains acceptance type |

**Venue Patterns (v2):**
```python
OPENREVIEW_VENUES = {
    "neurips": {
        "invitation_pattern_v2": "NeurIPS.cc/{year}/Conference/-/Submission",
        "accepted_venue_patterns": ["{conf} {year} oral", "{conf} {year} spotlight", "{conf} {year} poster"],
    },
    "neurips_db": {  # Datasets & Benchmarks Track
        "invitation_pattern_v2": "NeurIPS.cc/{year}/Datasets_and_Benchmarks_Track/-/Submission",
        "invitation_pattern_v2_alt": "NeurIPS.cc/{year}/Track/Datasets_and_Benchmarks/-/Submission",  # 2023
    },
    "iclr": {
        "invitation_pattern_v2": "ICLR.cc/{year}/Conference/-/Submission",
    },
    "icml": {
        "invitation_pattern_v2": "ICML.cc/{year}/Conference/-/Submission",
    },
}
```

**Known Pattern Changes:**
- NeurIPS D&B 2023: `Track/Datasets_and_Benchmarks` → 2024: `Datasets_and_Benchmarks_Track`
- ICLR 2024+: API v2 only
- ICML 2023+: API v2 only (not available before 2023)

### 3.5 Known Issues and Fixes

| Issue | Source | Fix |
|-------|--------|-----|
| GitHub API returns max 1000 files | ACL Anthology | Use Git Trees API instead of Contents API |
| NeurIPS D&B track missing (~460 papers) | OpenReview | Added `neurips_db` venue with alt patterns |
| AACL papers under `ijcnlp.xml` | ACL Anthology | Added `["aacl", "ijcnlp"]` prefixes |
| OpenAlex 87% gap for NLP venues | OpenAlex | Use ACL Anthology as primary for NLP |
| Invitation patterns change yearly | OpenReview | Maintain `invitation_pattern_v2_alt` fallback |

See [Incremental Crawling](incremental_crawling.md) for detailed troubleshooting.

---

## 4. Core Corpus Collection (OpenAlex)

### 4.1 Venue-based Collection

```python
class CoreCorpusCollector:
    """Collect Core Corpus based on Tier 0/1 venues"""

    BASE_URL = "https://api.openalex.org/works"

    # Tier 0 venue source IDs (combined with OR condition)
    TIER_0_SOURCES = {
        "neurips": ["S4306420609"],
        "icml": ["S4306419644"],
        "aaai": ["S4210191458"],
        "acl": ["S4306420508"],
        "emnlp": ["S4306418267"],
        "sigir": ["S4306418959"],
        # ... additional IDs
    }

    async def collect_venue(self, venue: str, since_year: int = None):
        """Collect all papers from a specific venue"""

        source_ids = self.TIER_0_SOURCES.get(venue, [])
        if not source_ids:
            raise ValueError(f"Unknown venue: {venue}")

        # Combine source IDs with OR condition
        source_filter = "|".join(source_ids)

        filter_query = f"primary_location.source.id:{source_filter}"
        if since_year:
            filter_query += f",from_publication_date:{since_year}-01-01"

        params = {
            "filter": filter_query,
            "per-page": 200,
            "cursor": "*",
            "select": "id,doi,title,abstract_inverted_index,authorships,publication_year,primary_location,referenced_works,cited_by_count,type",
            **self._key_manager.get_next_params(),
        }

        total_collected = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                response = await client.get(self.BASE_URL, params=params)
                data = response.json()

                papers = [self._parse_work(w, venue) for w in data["results"]]
                await self._store_batch(papers)
                total_collected += len(papers)

                logger.info(f"[{venue}] Collected {total_collected} papers")

                next_cursor = data["meta"].get("next_cursor")
                if not next_cursor:
                    break
                params["cursor"] = next_cursor

                await asyncio.sleep(0.1)  # Rate limiting

        return total_collected

    def _parse_work(self, work: dict, venue: str) -> RawPaper:
        return RawPaper(
            source="openalex",
            source_id=work["id"],
            title=work.get("title", ""),
            abstract=self._reconstruct_abstract(work.get("abstract_inverted_index")),
            authors=[
                Author(
                    name=a["author"]["display_name"],
                    openalex_id=a["author"]["id"],
                    affiliation=a.get("institutions", [{}])[0].get("display_name")
                )
                for a in work.get("authorships", [])
            ],
            year=work.get("publication_year"),
            doi=work.get("doi"),
            venue=venue.upper(),
            tier=0 if venue in self.TIER_0_SOURCES else 1,
            is_core=True,
            citation_count=work.get("cited_by_count", 0),
            referenced_works=work.get("referenced_works", []),  # For citation graph
            raw_data=work
        )
```

### 4.2 Citation Graph Collection

```python
class CitationGraphBuilder:
    """Build citation graph between Core papers"""

    async def build_graph(self, papers: List[RawPaper]) -> CitationGraph:
        """Generate citation graph based on referenced_works"""

        graph = CitationGraph()
        core_ids = {p.source_id for p in papers}

        for paper in papers:
            # Extract only citations within Core
            for ref_id in paper.referenced_works:
                if ref_id in core_ids:
                    graph.add_edge(paper.source_id, ref_id)

        return graph

    async def expand_citations(self, paper_id: str) -> List[str]:
        """Query papers that cite a specific paper (cited_by)"""

        url = f"https://api.openalex.org/works"
        params = {
            "filter": f"cites:{paper_id}",
            "per-page": 200,
            "select": "id,title,publication_year,primary_location"
        }

        # ... collection logic
```

### 4.3 Incremental Updates

```python
class CoreCorpusUpdater:
    """Incremental updates for Core Corpus"""

    async def update_since(self, since_date: datetime):
        """Collect papers updated since last collection"""

        # Note: from_updated_date filter requires API key
        filter_query = (
            f"primary_location.source.id:{self._all_source_ids()},"
            f"from_updated_date:{since_date.strftime('%Y-%m-%d')}"
        )

        # ... collection logic (similar to collect_venue)
```

---

## 5. ACL Anthology Collection (NLP Primary Source)

ACL Anthology is used as the **primary source** for NLP venues. It contains ~87% more papers compared to OpenAlex.

### 5.0 Workshop Support (Feb 2026 Update)

ACL Anthology includes 90+ workshop venues that are dynamically collected:

| Category | Venues | Papers (2020+) | Tier |
|----------|--------|----------------|------|
| Main venues | 9 | ~20,000 | 0-1 |
| Workshops | 90+ | ~10,000 | 2 |

**Workshop Detection:**
- Workshops are XML files with year prefix (e.g., `2024.bionlp.xml`)
- Files not matching main venue prefixes are classified as workshops
- Workshop papers have `venue_type: "workshop"` in storage

**CLI Commands:**
```bash
# Collect workshops only
uv run python -m src.cli.core_collect collect-acl --workshops-only

# Collect all including workshops
uv run python -m src.cli.core_collect collect-acl --all --include-workshops
```

### 5.1 ACL Anthology Structure

**File Organization**:
```
data/xml/
├── 2023.acl.xml      # ACL 2023 main conference
├── 2023.emnlp.xml    # EMNLP 2023
├── 2023.findings.xml # Findings papers
├── 2023.bea.xml      # BEA Workshop (co-located with ACL)
├── 2023.semeval.xml  # SemEval (co-located with ACL)
└── ...               # 127 files for 2023 alone
```

**Volume Structure**:
```xml
<collection id="2023.acl">
  <volume id="long" type="proceedings">
    <meta>
      <booktitle>Proceedings of ACL 2023 (Volume 1: Long Papers)</booktitle>
      <address>Toronto, Canada</address>
      <month>July</month>
      <year>2023</year>
      <venue>acl</venue>
    </meta>
    <paper id="1">
      <title>Paper Title</title>
      <author><first>John</first><last>Doe</last></author>
      <abstract>...</abstract>
      <url>2023.acl-long.1</url>
      <doi>10.18653/v1/2023.acl-long.1</doi>
    </paper>
  </volume>
</collection>
```

### 5.2 Track Type Identification

Volume `id` attribute indicates track type:

| Volume ID | Type | Include |
|-----------|------|---------|
| `long` | Main track long papers | ✅ |
| `short` | Main track short papers | ✅ |
| `demo` | System demonstrations | ✅ |
| `industry` | Industry track | ✅ |
| `srw` | Student research workshop | ✅ |
| `tutorial` | Tutorials | ✅ |
| `main` | Workshop main track | ✅ |
| `1`, `2`, etc. | Workshop volumes | ✅ |

### 5.3 Co-location Detection

ACL Anthology does NOT store explicit co-location relationships. Co-location is determined by matching `<address>`, `<month>`, and `<year>`:

```python
# ACL 2023 event location
EVENT_LOCATIONS = {
    "acl-2023": ("Toronto, Canada", "July", "2023"),
    "emnlp-2023": ("Singapore", "December", "2023"),
    "naacl-2024": ("Mexico City, Mexico", "June", "2024"),
    "eacl-2023": ("Dubrovnik, Croatia", "May", "2023"),
}

def get_event_papers(venue: str, year: int) -> list[Paper]:
    """Get all papers co-located with a main conference."""
    target_location = EVENT_LOCATIONS[f"{venue}-{year}"]
    papers = []

    for xml_file in glob(f"data/xml/{year}.*.xml"):
        tree = parse(xml_file)
        for volume in tree.findall("volume"):
            meta = volume.find("meta")
            location = (
                meta.findtext("address"),
                meta.findtext("month"),
                meta.findtext("year")
            )
            if location == target_location:
                # This volume is co-located
                for paper in volume.findall("paper"):
                    papers.append(parse_paper(paper, volume))

    return papers
```

### 5.4 ACL 2023 Example Scope

When collecting "ACL 2023", include ALL co-located events:

| Component | Papers |
|-----------|--------|
| Main Long | 912 |
| Main Short | 165 |
| Findings | 902 |
| System Demos | 59 |
| Industry Track | 77 |
| Student Research | 35 |
| Tutorials | 7 |
| 24 Workshops | ~900+ |
| **Total** | ~3,000+ |

### 5.5 XML Parsing Implementation

```python
class ACLAnthologyCollector:
    """Direct parsing of ACL Anthology XML"""

    ANTHOLOGY_REPO = "https://github.com/acl-org/acl-anthology"

    # New file naming convention (2020+)
    TARGET_VENUES = ["acl", "emnlp", "naacl", "eacl", "coling", "findings",
                     "tacl", "conll", "lrec"]

    async def collect_event(self, venue: str, year: int) -> list[RawPaper]:
        """Collect all papers from an event including co-located workshops."""
        target_location = self._get_event_location(venue, year)
        papers = []

        for xml_file in self._list_xml_files(year):
            tree = ET.parse(xml_file)

            for volume in tree.findall("volume"):
                meta = volume.find("meta")
                location = self._extract_location(meta)

                if location == target_location:
                    volume_papers = self._parse_volume(volume, venue)
                    papers.extend(volume_papers)

        return papers

    def _parse_volume(self, volume: ET.Element, parent_venue: str) -> list[RawPaper]:
        meta = volume.find("meta")
        volume_id = volume.get("id")

        papers = []
        for paper_elem in volume.findall("paper"):
            # IMPORTANT: Use itertext() for titles with nested <fixed-case> tags
            # Example: <title><fixed-case>BERT</fixed-case>: A Model</title>
            title_elem = paper_elem.find("title")
            title = ''.join(title_elem.itertext()).strip() if title_elem else ""

            abstract_elem = paper_elem.find("abstract")
            abstract = ''.join(abstract_elem.itertext()).strip() if abstract_elem else None

            papers.append(RawPaper(
                source=SourceType.ACL_ANTHOLOGY,
                source_id=paper_elem.find("url").text,
                title=title,
                abstract=abstract,
                authors=self._parse_authors(paper_elem),
                year=int(meta.findtext("year")),
                venue=meta.findtext("venue") or parent_venue,
                venue_type="workshop" if "workshop" in booktitle.lower() else "conference",
                tier=self._get_tier(parent_venue),
                is_core=True,
                doi=paper_elem.findtext("doi"),
                # Track type from volume id
                paper_type=self._infer_paper_type(volume_id),
            ))
        return papers

    async def collect_workshops(self, since_year: int, to_year: int = None):
        """Collect all workshop papers dynamically.

        Workshops are identified as XML files not matching main venue prefixes.
        """
        all_files = await self.list_xml_files()
        workshop_files = [f for f in all_files if self._is_workshop_file(f)]
        # ... collection logic
```

---

## 6. On-demand Retrieval

### 6.1 arXiv Real-time Search

```python
class OnDemandRetriever:
    """On-demand search (at query time)"""

    async def search_arxiv(self, query: str, categories: List[str] = None) -> List[RawPaper]:
        """Search for latest papers on arXiv"""

        if categories is None:
            categories = ["cs.CL", "cs.AI", "cs.LG", "cs.IR"]

        collector = ArxivCollector()
        papers = await collector.search(
            query=query,
            categories=categories,
            limit=100
        )

        # Check Core connection status
        for paper in papers:
            paper.is_core = False
            paper.core_connections = await self._find_core_connections(paper)

        return papers

    async def _find_core_connections(self, paper: RawPaper) -> List[str]:
        """Find connection relationships with Core Corpus"""

        connections = []

        # 1. DOI matching (preprint → published version)
        if paper.doi:
            core_match = await db.find_by_doi(paper.doi)
            if core_match:
                connections.append(("published_as", core_match.id))

        # 2. Citation relationship
        for ref in paper.referenced_works:
            if await db.is_core(ref):
                connections.append(("cites_core", ref))

        # 3. Semantic similarity (optional)
        similar_core = await self._find_similar_core(paper.embedding)
        connections.extend([("similar_to", pid) for pid in similar_core])

        return connections
```

### 6.2 OpenAlex Narrow Query

```python
class OpenAlexOnDemand:
    """OpenAlex narrow query (papers outside Core)"""

    async def search(self, query: str, limit: int = 100) -> List[RawPaper]:
        """Keyword-based narrow search"""

        params = {
            "search": query,
            "filter": "type:article|preprint,from_publication_date:2023-01-01",
            "per-page": min(limit, 200),
            "select": "id,doi,title,abstract_inverted_index,authorships,publication_year,referenced_works"
        }

        response = await self.client.get(self.BASE_URL, params=params)
        data = response.json()

        papers = []
        for work in data["results"]:
            paper = self._parse_work(work)
            paper.is_core = False
            paper.core_connections = await self._find_core_connections(paper)
            papers.append(paper)

        return papers
```

---

## 7. Data Pipeline Architecture

### 7.1 Pipeline Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      Core Collection                         │
├─────────────────────────────────────────────────────────────┤
│  OpenAlex ──┬──▶ Tier 0 Venues ──▶ Core Corpus              │
│             │                                                │
│  ACL XML ───┴──▶ NLP Venues ─────▶ (merge by DOI)           │
│                                                              │
│             ┌──▶ Citation Graph                              │
│             │                                                │
│  Core ──────┼──▶ Embedding Index                             │
│             │                                                │
│             └──▶ Qdrant / PostgreSQL                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     On-demand Retrieval                      │
├─────────────────────────────────────────────────────────────┤
│  User Query ──▶ arXiv Search ──┬──▶ Core Connection Check   │
│              ──▶ OpenAlex     ──┘                           │
│                                                              │
│  Results ──▶ Core-linked: ✓ highlight                       │
│          ──▶ Not linked:  "Unverified" label                │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Collection Schedule

| Task | Schedule | Target | Description |
|------|----------|--------|-------------|
| core_initial | Once | Tier 0 + 1 | Initial full collection |
| core_incremental | Daily 6AM | Tier 0 + 1 | Incremental updates |
| acl_sync | Monthly | NLP venues | ACL Anthology sync |
| embedding_backfill | Weekly | Core | Generate missing embeddings |
| citation_refresh | Weekly | Core | Refresh citation graph |

---

## 8. DBLP Collection (IR/Legal Venues)

DBLP is used for venues with poor OpenAlex coverage, especially IR and Legal AI conferences.

### 8.1 Target Venues

| Venue | OpenAlex Papers | DBLP Papers | Use DBLP |
|-------|-----------------|-------------|----------|
| RecSys | 54 | ~300 | ✅ |
| ECIR | 15 | ~200 | ✅ |
| ICAIL | 11 | ~150 | ✅ |
| JURIX | 4 | ~100 | ✅ |
| WSDM | 210 | ~200 | Optional |
| CIKM | 662 | ~500 | Optional |

### 8.2 DBLP API Usage

```python
class DBLPCollector:
    """Collect papers via DBLP API"""

    BASE_URL = "https://dblp.org/search/publ/api"

    async def collect_venue(self, venue: str, year: int) -> list[RawPaper]:
        """Collect papers from a venue using DBLP API."""
        params = {
            "q": f"venue:{venue}: year:{year}:",
            "format": "json",
            "h": 1000,  # max results
        }

        response = await self.client.get(self.BASE_URL, params=params)
        data = response.json()

        papers = []
        for hit in data.get("result", {}).get("hits", {}).get("hit", []):
            info = hit.get("info", {})
            papers.append(RawPaper(
                source=SourceType.DBLP,
                source_id=hit.get("@id"),
                title=info.get("title"),
                authors=self._parse_authors(info),
                year=int(info.get("year")),
                venue=venue,
                venue_type="conference",
                tier=self._get_tier(venue),
                is_core=True,
                doi=info.get("doi"),
                pdf_url=info.get("ee"),
            ))

        return papers
```

### 8.3 DBLP URL Patterns

```
# Main conference volumes
/db/conf/recsys/recsys2023.html    → RecSys 2023
/db/conf/ecir/ecir2023.html        → ECIR 2023
/db/conf/icail/icail2023.html      → ICAIL 2023
/db/conf/jurix/jurix2023.html      → JURIX 2023

# API search
/search/publ/api?q=venue:RecSys:+year:2023:
```

---

## 9. Estimated Volume (Updated)

### 9.1 Core Corpus Size by Source

| Source | Venues | Papers (2020-2024) |
|--------|--------|-------------------|
| OpenAlex | ML/AI/DM venues | ~40,000 |
| ACL Anthology | NLP venues | ~20,000 |
| DBLP | IR/Legal venues | ~5,000 |
| **Total (deduplicated)** | 27 venues | **~60,000-65,000** |

### 9.2 Papers by Tier

| Tier | Venues | Papers | Primary Source |
|------|--------|--------|----------------|
| Tier 0 | 11 venues | ~45,000 | OpenAlex, ACL Anthology |
| Tier 1 | 13 venues | ~18,000 | OpenAlex, ACL Anthology, DBLP |
| Tier 2 | 3 venues | ~2,000 | DBLP, OpenAlex |
| **Total** | 27 venues | **~65,000** | - |

### 9.3 API Credit Usage

| Operation | Credits | Frequency |
|-----------|---------|-----------|
| Initial Core collection (OpenAlex) | ~500 | Once |
| ACL Anthology XML download | Free | Once |
| DBLP API calls | Free | Once |
| Daily incremental | ~100-500 | Daily |
| Citation graph refresh | ~1,000 | Weekly |
| **Monthly Total** | ~10,000 | - |

> 100,000 daily credits is sufficient.

---

## 9. Data Quality

### 9.1 Deduplication

```python
class CoreDeduplicator:
    """Core Corpus deduplication"""

    def find_duplicates(self, paper: RawPaper) -> Optional[RawPaper]:
        # 1. DOI exact match
        if paper.doi:
            match = db.find_by_doi(paper.doi)
            if match:
                return match

        # 2. Title + Year fuzzy match
        candidates = db.find_by_title_year(paper.title, paper.year)
        for c in candidates:
            if self._title_similarity(paper.title, c.title) > 0.95:
                return c

        return None
```

### 9.2 Validation Rules

| Field | Rule | Action |
|-------|------|--------|
| title | Required, len > 10 | Reject if missing |
| year | 1990 ≤ year ≤ current+1 | Warn if out of range |
| venue | Must match Tier 0/1 | Reject if unknown |
| abstract | Optional but preferred | Warn if missing |
| authors | At least 1 author | Warn if empty |

---

## 10. Monitoring

### 10.1 Collection Metrics

```python
# Prometheus metrics
core_papers_total = Gauge('core_papers_total', 'Total Core papers', ['venue', 'tier'])
collection_errors = Counter('collection_errors', 'Collection errors', ['source', 'error_type'])
api_credits_used = Counter('api_credits_used', 'OpenAlex API credits used')
core_coverage = Gauge('core_coverage', 'Core coverage by venue', ['venue'])
```

### 10.2 Alerts

| Condition | Severity | Action |
|-----------|----------|--------|
| Daily collection < 50 papers | Warning | Check API |
| Collection error rate > 5% | Critical | Investigate |
| API credits > 80% daily | Warning | Throttle |
| Venue coverage < 90% | Warning | Check source IDs |

---

## 11. Implementation Status

### 11.1 Core Modules

| Module | File | Status |
|--------|------|--------|
| Venue Configuration | `src/core/config.py` | ✅ Complete (27 venues, all Source IDs) |
| **API Constants** | `src/core/constants.py` | ✅ Complete |
| Qdrant Storage | `src/core/storage.py` | ✅ Complete |
| Checkpoint Manager | `src/core/checkpoint.py` | ✅ Complete |
| Checkpoint Mixin | `src/core/checkpoint_mixin.py` | ✅ Complete |
| Deduplication | `src/core/deduplication.py` | ✅ Complete |
| CLI | `src/cli/core_collect.py` | ✅ Complete |
| Paper Model | `src/models/paper.py` | ✅ Complete |

**Constants Module**: Centralized API URLs and environment variable helpers:
- `OPENALEX_BASE_URL`, `CROSSREF_BASE_URL`, `S2_BASE_URL`
- `get_openalex_email()`, `get_openalex_api_key()`, `get_openalex_api_keys()`, `get_crossref_email()`, `get_s2_api_key()`
- `get_qdrant_url()`, `get_qdrant_collection()`

### 11.2 Crawler Modules

| Module | File | Status |
|--------|------|--------|
| **BaseCrawler** | `src/core/crawler/base.py` | ✅ Complete |
| OpenAlex Collector | `src/core/crawler/openalex.py` | ✅ Complete |
| ACL Anthology Crawler | `src/core/crawler/acl_anthology.py` | ✅ Complete |
| DBLP Crawler | `src/core/crawler/dblp.py` | ✅ Complete (includes ACM venues) |
| OpenReview Crawler | `src/core/crawler/openreview.py` | ✅ Complete |
| AAAI OJS Crawler | `src/core/crawler/aaai_ojs.py` | ✅ Complete |

**Crawler Architecture**: All crawlers (except OpenAlex) inherit from `BaseCrawler`, which provides:
- Async context management (`__aenter__`/`__aexit__`)
- HTTP client with configurable timeout
- Checkpoint manager integration
- Deduplicator integration
- Common `client` property with error handling

### 11.3 Enrichment Modules

| Module | File | Status |
|--------|------|--------|
| **BaseEnricher** | `src/core/enrichment/base.py` | ✅ Complete |
| OpenAlex Enricher | `src/core/enrichment/openalex.py` | ✅ Complete |
| CrossRef Enricher | `src/core/enrichment/crossref.py` | ✅ Complete |
| Semantic Scholar Enricher | `src/core/enrichment/semantic_scholar.py` | ✅ Complete |
| Stub Enricher | `src/core/enrichment/stub.py` | ✅ Complete |
| PDF Reference Extractor | `src/core/enrichment/pdf.py` | ✅ Complete |

**Enrichment Architecture**: See [Enrichment Pipeline](./enrichment.md#8-enrichment-architecture) for details on `BaseEnricher`, `OpenAlexMixin`, and `CrossRefMixin`.

### 11.4 Reference Resolution Modules

| Module | File | Status |
|--------|------|--------|
| Identifier Normalizer | `src/core/resolution/normalizer.py` | ✅ Complete |
| Reference Resolver | `src/core/resolution/resolver.py` | ✅ Complete |

### 11.5 Citation Graph Modules

| Module | File | Status |
|--------|------|--------|
| Reverse Citation Index | `src/core/citation_graph/reverse_index.py` | ✅ Complete |
| Citation Graph Builder | `src/core/citation_graph/builder.py` | ✅ Complete |
| Graph Exporter | `src/core/citation_graph/exporter.py` | ✅ Complete |
| Graph Analyzer | `src/core/citation_graph/analyzer.py` | ✅ Complete |

See [Citation Graph Design](./citation_graph.md) for details.

---

## Related Documents

- [Venue Reference](../reference/venues.md)
- [CLI Reference](../reference/cli.md)
- [Quick Start Guide](../guides/quickstart.md)
- [Enrichment Pipeline](./enrichment.md)

### 11.3 CLI Commands Available

```bash
# Collect papers from a venue
uv run python -m src.cli.core_collect collect --venue neurips --since-year 2020

# Collect all Tier 0 venues
uv run python -m src.cli.core_collect collect --tier 0

# Collect all discovered venues
uv run python -m src.cli.core_collect collect --all

# Check collection status
uv run python -m src.cli.core_collect status

# Discover OpenAlex Source IDs for venues
uv run python -m src.cli.core_collect discover-sources --venue icml
uv run python -m src.cli.core_collect discover-sources --all

# List configured venues
uv run python -m src.cli.core_collect list-venues
uv run python -m src.cli.core_collect list-venues --tier 0

# Initialize Qdrant storage
uv run python -m src.cli.core_collect init-storage

# Clear checkpoint (reset progress)
uv run python -m src.cli.core_collect clear-checkpoint

# Citation graph commands
uv run python -m src.cli.core_collect citation-graph-stats
uv run python -m src.cli.core_collect build-citation-graph -o graph.json
uv run python -m src.cli.core_collect build-citation-graph -o graph.graphml --format graphml
uv run python -m src.cli.core_collect build-citation-graph -o /tmp/graph --streaming  # Low memory
uv run python -m src.cli.core_collect analyze-citation-graph --all --top-n 50
uv run python -m src.cli.core_collect analyze-citation-graph --compute-pagerank --store
uv run python -m src.cli.core_collect get-citing-papers <paper_id>
uv run python -m src.cli.core_collect export-graph-subgraph <paper_id> --hops 2 -o subgraph.json
uv run python -m src.cli.core_collect build-cited-by  # Build reverse citations for GraphRAG
```

### 11.4 Remaining Work (Application Layer)

The Data Pipeline Layer is complete. Remaining work is in the Application Layer:

| Component | File | Status |
|-----------|------|--------|
| Embedding Pipeline | `src/core/embedding.py` | ❌ Not started (using placeholder vectors) |
| FastAPI Server | `src/api/` | ❌ Not started |
| Search Service | `src/api/search.py` | ❌ Not started |
| Graph Service | `src/api/graph.py` | ❌ Not started |
| On-demand Retrieval | `src/core/ondemand/` | ❌ Not started |
| Web Frontend | `frontend/` | ❌ Not started |

**Priority Order:**
1. **Embedding Pipeline** - Generate real embeddings (SPECTER2) to enable semantic search
2. **FastAPI Server** - Basic search endpoint with hybrid BM25 + semantic
3. **Graph Service** - Citation network API, trend analysis
4. **On-demand Retrieval** - arXiv real-time search with Core connection detection
5. **Web Frontend** - Per `docs/design/ux_design.md`

### 11.5 Environment Configuration

```env
# .env file
OPENALEX_API_KEYS=key1,key2,key3      # Comma-separated for round-robin rotation
OPENALEX_EMAIL=your-email@example.com  # Fallback polite pool when all keys exhausted
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=                       # optional, for Qdrant Cloud
```

---

## 12. Coverage Gap Resolution (Updated Feb 2026)

### 12.1 Gap Analysis Results (Q1 2020 Test)

Before adding new sources, significant coverage gaps were identified:

| Venue | Collected | Official 2020 | Gap | Source Added |
|-------|-----------|---------------|-----|--------------|
| AAAI | 0 | 1,591 | 100% | AAAI OJS |
| ICLR | 21 | 687 | 97% | OpenReview |
| ICML | 9 | 1,088 | 99% | OpenReview |
| NeurIPS | 574 | 1,898 | 70% | OpenReview |
| WWW | 3 | 350+ | 99% | ACM DL |
| KDD | 26 | 338 | 92% | ACM DL |
| SIGIR | 7 | 321 | 98% | ACM DL |

**Total papers recovered: ~5,600+ papers**

### 12.2 New Data Sources (Jan 2026)

Three new sources were added to address coverage gaps:

1. **OpenReview API** (`src/core/crawler/openreview.py`)
   - Venues: ICLR (2013+), NeurIPS (2019+), ICML (2023+)
   - Features: Full abstracts, author info, reviews/decisions
   - Rate limit: 1 req/sec (unauthenticated)
   - **API Version Handling (Feb 2026 Update):**
     - API v1 (`api.openreview.net`): ICLR ≤2023, NeurIPS ≤2022
     - API v2 (`api2.openreview.net`): ICLR 2024+, NeurIPS 2023+, ICML 2023+
     - Automatic version selection based on venue and year

2. **DBLP Crawler** (`src/core/crawler/dblp.py`)
   - ACM venues: KDD, SIGIR, WWW, RecSys, CIKM, WSDM (Tier 0-1)
   - IR venues: ECIR (Tier 1)
   - Legal AI venues: ICAIL, JURIX (Tier 2)
   - Strategy: DBLP API for metadata, enrichment pipeline for abstracts
   - Rate limit: 1 req/sec
   - Note: `acm_open.py` was consolidated into `dblp.py` in v0.7.2

3. **AAAI OJS** (`src/core/crawler/aaai_ojs.py`)
   - Venues: AAAI (2020-2023), ICWSM
   - Features: Full abstracts, PDF links
   - Note: AAAI 2024+ uses OpenReview

### 12.3 Source Priority for Deduplication

When papers exist in multiple sources, priority determines which version to keep:

```python
SOURCE_PRIORITY = {
    SourceType.OPENALEX: 1,      # Best metadata
    SourceType.OPENREVIEW: 2,    # Has reviews/decisions
    SourceType.ACL: 3,           # Good for NLP
    SourceType.ACM: 4,           # Good abstracts
    SourceType.DBLP: 5,          # Basic metadata
    SourceType.AAAI: 6,          # Basic metadata
    SourceType.ARXIV: 7,
    SourceType.SEMANTIC_SCHOLAR: 8,
}
```

### 12.4 Updated Collection Commands

```bash
# Collect from all sources including new ones
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020

# Collect only new sources (skip existing)
uv run python -m src.cli.core_collect collect-all-sources \
    --skip-openalex --skip-acl --skip-dblp

# Individual new source commands
uv run python -m src.cli.core_collect collect-openreview --all
uv run python -m src.cli.core_collect collect-acm --all
uv run python -m src.cli.core_collect collect-aaai --all
```

### 12.5 Updated Corpus Size Estimates

| Source | Venues | Papers (2020-present) |
|--------|--------|----------------------|
| OpenAlex | ML/AI/DM | ~40,000 |
| ACL Anthology (main) | NLP | ~20,000 |
| ACL Anthology (workshops) | NLP workshops | ~10,000 |
| DBLP | IR/Legal | ~5,000 |
| OpenReview | ICLR/NeurIPS/ICML | ~15,000 |
| ACM DL | KDD/SIGIR/WWW | ~10,000 |
| AAAI OJS | AAAI/ICWSM | ~8,000 |
| **Total (deduplicated)** | 30+ venues + workshops | **~90,000-100,000** |

### 12.6 Unified Enrichment Pipeline (Feb 2026 Update)

Papers from various sources lack certain metadata. The unified enrichment pipeline fetches missing data from OpenAlex via DOI lookup.

**Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    Unified Enrichment Pipeline                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │   Qdrant    │───▶│   Paper     │───▶│    OpenAlex API     │ │
│  │  (papers    │    │  Enricher   │    │  /works/doi:{doi}   │ │
│  │  missing    │    │ (parallel)  │    │                     │ │
│  │  data)      │    └──────┬──────┘    └──────────┬──────────┘ │
│  └─────────────┘           │                      │             │
│                            │  refs / abstract     │             │
│                            ▼                      ▼             │
│                    ┌─────────────┐    ┌─────────────────────┐  │
│                    │ Checkpoint  │    │   Update Qdrant     │  │
│                    │ (progress)  │    │   set_payload()     │  │
│                    └─────────────┘    └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Enrichment Types:**

| Type | Source Gap | Target |
|------|-----------|--------|
| Citations | ACL, OpenReview, DBLP lack `referenced_works` | ~10,926 papers |
| Abstracts | DBLP lacks abstracts | ~1,330 papers |

**Coverage Impact (Citations):**

| Metric | Before | After |
|--------|--------|-------|
| Papers with `referenced_works` | 19% (5,929) | ~55% (16,855) |
| ACL papers enrichable | 0% | 61% (7,754) |
| OpenReview papers enrichable | 0% | 27% (3,172) |

**Coverage Impact (Abstracts):**

| Metric | Before | After |
|--------|--------|-------|
| Papers with abstracts | ~92% | ~98% |
| DBLP papers with abstracts | 0% | ~95% |

**CLI Commands:**

```bash
# Data quality dashboard
uv run python -m src.cli.core_collect data-quality
uv run python -m src.cli.core_collect data-quality --json
uv run python -m src.cli.core_collect data-quality --by-venue

# Citation enrichment
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --dry-run
uv run python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 10
uv run python -m src.cli.core_collect clear-enrich-1-checkpoint

# Abstract enrichment
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --dry-run
uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --parallel 10
uv run python -m src.cli.core_collect clear-abstract-checkpoint
```

**Implementation:**
- Module: `src/core/enrichment/openalex.py` (unified enricher with parallel support)
- Storage methods:
  - `get_papers_missing_references()`, `batch_update_referenced_works()`
  - `get_papers_missing_abstracts()`, `batch_update_abstracts()`
  - `get_data_quality_stats()`
- Checkpoints:
  - `data/core/checkpoints/citation_enrichment.json`
  - `data/core/checkpoints/abstract_enrichment.json`

**Parallel Processing:**

The enricher supports concurrent API calls via `--parallel N`:

| Configuration | Recommended `--parallel` |
|---------------|-------------------------|
| With API key | 10 |
| With email only | 5 |
| No auth | 1 (sequential) |

### 12.7 ACL Workshop Support (Feb 2026 Update)

Workshop papers are now collected dynamically from ACL Anthology:

| Year | Workshop XML Files | Est. Papers |
|------|-------------------|-------------|
| 2024 | 93 | ~2,500 |
| 2023 | ~90 | ~2,400 |
| 2022 | ~85 | ~2,200 |
| 2021 | ~80 | ~2,000 |
| 2020 | ~75 | ~1,800 |

**CLI Commands:**
```bash
# Collect workshops only
uv run python -m src.cli.core_collect collect-acl --workshops-only --since-year 2024

# Collect all sources with workshops
uv run python -m src.cli.core_collect collect-all-sources --include-workshops
```

**Storage Schema Update:**
- `venue_type` field added to Qdrant payload
- Values: `"conference"`, `"workshop"`, `"journal"`, or `null`

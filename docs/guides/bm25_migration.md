# BM25 Hybrid Search Migration Guide

This guide explains how to enable BM25 text indexing on an existing Qdrant collection for hybrid search (dense + BM25).

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Migration Steps](#migration-steps)
- [Code Changes](#code-changes)
- [Verification](#verification)
- [Rollback](#rollback)
- [Performance Considerations](#performance-considerations)

---

## Overview

### Current State (Dense Only)

```
┌─────────────────────────────────────────┐
│           Current Architecture           │
├─────────────────────────────────────────┤
│  Query: "HyDE paper"                    │
│           │                              │
│           ▼                              │
│  ┌─────────────────┐                    │
│  │  Dense Vector   │  768-dim embedding │
│  │     Search      │  (cosine)          │
│  └────────┬────────┘                    │
│           │                              │
│           ▼                              │
│     Semantic matches                     │
│     (may miss exact "HyDE" keyword)     │
└─────────────────────────────────────────┘
```

### Target State (Hybrid: Dense + BM25)

```
┌─────────────────────────────────────────────────────────┐
│                 Hybrid Architecture                      │
├─────────────────────────────────────────────────────────┤
│  Query: "HyDE paper"                                    │
│           │                                              │
│     ┌─────┴─────┐                                       │
│     ▼           ▼                                       │
│ ┌────────┐  ┌────────┐                                  │
│ │ Dense  │  │  BM25  │  Text index with IDF            │
│ │ Vector │  │ Search │  (title, abstract, keywords)    │
│ └───┬────┘  └───┬────┘                                  │
│     │           │                                       │
│     └─────┬─────┘                                       │
│           ▼                                              │
│   ┌─────────────┐                                       │
│   │ RRF Fusion  │  Reciprocal Rank Fusion              │
│   └──────┬──────┘                                       │
│          ▼                                              │
│   Best of both worlds:                                  │
│   - Semantic similarity (dense)                         │
│   - Exact keyword matching with IDF (BM25)             │
└─────────────────────────────────────────────────────────┘
```

### Why BM25 Needs Text Indexing

BM25 scoring requires:
- **Inverted index**: Maps terms → documents
- **IDF statistics**: Computed across entire corpus
- **Document lengths**: For length normalization

Without text indices, Qdrant cannot compute these statistics.

---

## Prerequisites

### 1. Qdrant Version

BM25/text indexing requires Qdrant **1.7.0+** (released Oct 2023).

Check your version:
```bash
curl http://localhost:6333 | jq '.version'
```

### 2. Backup (Recommended)

Before migration, create a snapshot:

```bash
# Create snapshot
curl -X POST "http://localhost:6333/collections/lexicon_arxiv/snapshots"

# List snapshots
curl "http://localhost:6333/collections/lexicon_arxiv/snapshots"
```

### 3. Disk Space

Text indices add ~10-20% to collection size. Ensure sufficient disk space.

---

## Migration Steps

### Step 1: Create Text Indices (Non-Blocking)

Text index creation is **non-blocking** — queries continue working during indexing.

```bash
# Create index on title field
curl -X PUT "http://localhost:6333/collections/lexicon_arxiv/index" \
  -H "Content-Type: application/json" \
  -d '{
    "field_name": "title",
    "field_schema": {
      "type": "text",
      "tokenizer": "word",
      "min_token_len": 2,
      "max_token_len": 40,
      "lowercase": true
    }
  }'

# Create index on abstract field
curl -X PUT "http://localhost:6333/collections/lexicon_arxiv/index" \
  -H "Content-Type: application/json" \
  -d '{
    "field_name": "abstract",
    "field_schema": {
      "type": "text",
      "tokenizer": "word",
      "min_token_len": 2,
      "max_token_len": 40,
      "lowercase": true
    }
  }'

# Create index on keywords field (array of strings)
curl -X PUT "http://localhost:6333/collections/lexicon_arxiv/index" \
  -H "Content-Type: application/json" \
  -d '{
    "field_name": "keywords",
    "field_schema": {
      "type": "text",
      "tokenizer": "word",
      "min_token_len": 2,
      "max_token_len": 20,
      "lowercase": true
    }
  }'
```

### Step 2: Monitor Indexing Progress

Check collection info to see indexing status:

```bash
curl "http://localhost:6333/collections/lexicon_arxiv" | jq '.result.payload_schema'
```

Wait until all text indices show `"indexed": true`.

### Step 3: Verify Indices

```bash
# Check payload schema shows text indices
curl "http://localhost:6333/collections/lexicon_arxiv" | jq '.result.payload_schema'
```

Expected output includes:
```json
{
  "title": {
    "data_type": "text",
    "params": {
      "type": "text",
      "tokenizer": "word",
      "min_token_len": 2,
      "max_token_len": 40,
      "lowercase": true
    }
  },
  "abstract": { ... },
  "keywords": { ... }
}
```

### Step 4: Test Hybrid Query

```bash
curl -X POST "http://localhost:6333/collections/lexicon_arxiv/points/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": [0.1, 0.2, ...],  
    "limit": 10,
    "with_payload": ["title", "keywords"],
    "params": {
      "quantization": null
    }
  }'
```

For hybrid search with BM25:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Prefetch, FusionQuery, Fusion

client = QdrantClient(url="http://localhost:6333")

# Hybrid search: dense + BM25 with RRF fusion
results = client.query_points(
    collection_name="lexicon_arxiv",
    prefetch=[
        # Dense vector search
        Prefetch(
            query=embedding_vector,  # Your 768-dim vector
            limit=100,
        ),
        # BM25 text search
        Prefetch(
            query="HyDE retrieval augmented",  # Text query
            using="title",  # Or create a combined field
            limit=100,
        ),
    ],
    query=FusionQuery(fusion=Fusion.RRF),  # Reciprocal Rank Fusion
    limit=20,
)
```

---

## Code Changes

### Option A: Add Text Index on Collection Creation

Update `src/core/storage.py`:

```python
from qdrant_client.models import TextIndexParams, TokenizerType

class QdrantStorage:
    def ensure_collection(self) -> bool:
        """Ensure the collection exists with text indices for BM25."""
        try:
            self.client.get_collection(self.collection_name)
            logger.info(f"Collection '{self.collection_name}' already exists")
            return False
        except (UnexpectedResponse, Exception):
            # Create collection with vectors
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=VECTOR_DIM,
                    distance=models.Distance.COSINE,
                ),
            )
            
            # Add text indices for BM25
            self._create_text_indices()
            
            logger.info(f"Created collection '{self.collection_name}' with text indices")
            return True

    def _create_text_indices(self):
        """Create text indices for BM25 hybrid search."""
        text_fields = {
            "title": TextIndexParams(
                type="text",
                tokenizer=TokenizerType.WORD,
                min_token_len=2,
                max_token_len=40,
                lowercase=True,
            ),
            "abstract": TextIndexParams(
                type="text",
                tokenizer=TokenizerType.WORD,
                min_token_len=2,
                max_token_len=40,
                lowercase=True,
            ),
            "keywords": TextIndexParams(
                type="text",
                tokenizer=TokenizerType.WORD,
                min_token_len=2,
                max_token_len=20,
                lowercase=True,
            ),
        }
        
        for field_name, schema in text_fields.items():
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=schema,
                )
                logger.info(f"Created text index on '{field_name}'")
            except Exception as e:
                logger.warning(f"Failed to create index on '{field_name}': {e}")
```

### Option B: Migration CLI Command

Add to `src/cli/core_collect.py`:

```python
@cli.command("enable-bm25")
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
def enable_bm25(dry_run: bool):
    """Enable BM25 text indexing on the collection.
    
    Creates text indices on title, abstract, and keywords fields
    for hybrid search (dense + BM25 with RRF fusion).
    
    This operation is non-blocking - queries continue working
    during index creation.
    """
    from qdrant_client.models import TextIndexParams, TokenizerType
    
    storage = QdrantStorage()
    
    text_fields = {
        "title": TextIndexParams(
            type="text",
            tokenizer=TokenizerType.WORD,
            min_token_len=2,
            max_token_len=40,
            lowercase=True,
        ),
        "abstract": TextIndexParams(
            type="text",
            tokenizer=TokenizerType.WORD,
            min_token_len=2,
            max_token_len=40,
            lowercase=True,
        ),
        "keywords": TextIndexParams(
            type="text",
            tokenizer=TokenizerType.WORD,
            min_token_len=2,
            max_token_len=20,
            lowercase=True,
        ),
    }
    
    # Check existing indices
    collection_info = storage.client.get_collection(storage.collection_name)
    existing_indices = set(collection_info.payload_schema.keys()) if collection_info.payload_schema else set()
    
    click.echo("=== BM25 Text Index Migration ===\n")
    
    for field_name, schema in text_fields.items():
        if field_name in existing_indices:
            click.echo(f"  [SKIP] {field_name}: Index already exists")
        else:
            if dry_run:
                click.echo(f"  [PLAN] {field_name}: Would create text index")
            else:
                try:
                    storage.client.create_payload_index(
                        collection_name=storage.collection_name,
                        field_name=field_name,
                        field_schema=schema,
                    )
                    click.echo(f"  [DONE] {field_name}: Text index created")
                except Exception as e:
                    click.echo(f"  [FAIL] {field_name}: {e}", err=True)
    
    if dry_run:
        click.echo("\n(Dry run - no changes made)")
    else:
        click.echo("\nText indices created. BM25 hybrid search is now available.")
        click.echo("Note: Index building happens in background. Check status with:")
        click.echo(f"  curl http://localhost:6333/collections/{storage.collection_name}")
```

---

## Verification

### 1. Check Index Status

```bash
python -c "
from src.core.storage import QdrantStorage
storage = QdrantStorage()
info = storage.client.get_collection(storage.collection_name)
print('Payload schema:')
for field, schema in (info.payload_schema or {}).items():
    print(f'  {field}: {schema}')
"
```

### 2. Test BM25 Search Quality

```python
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

# BM25-only search (text query)
results = client.query_points(
    collection_name="lexicon_arxiv",
    query="HyDE hypothetical document",
    using="title",  # Search in title field
    limit=5,
    with_payload=["title", "keywords"],
)

for r in results.points:
    print(f"Score: {r.score:.4f} - {r.payload['title']}")
```

### 3. Compare Dense vs Hybrid

```python
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
query_text = "HyDE paper"
query_vector = model.encode(query_text).tolist()

# Dense-only search
dense_results = client.search(
    collection_name="lexicon_arxiv",
    query_vector=query_vector,
    limit=5,
)
print("Dense-only results:")
for r in dense_results:
    print(f"  {r.payload['title'][:60]}...")

# Hybrid search (with BM25)
from qdrant_client.models import Prefetch, FusionQuery, Fusion

hybrid_results = client.query_points(
    collection_name="lexicon_arxiv",
    prefetch=[
        Prefetch(query=query_vector, limit=50),
        Prefetch(query=query_text, using="title", limit=50),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=5,
)
print("\nHybrid results:")
for r in hybrid_results.points:
    print(f"  {r.payload['title'][:60]}...")
```

---

## Rollback

If issues occur, remove text indices:

```bash
# Remove title index
curl -X DELETE "http://localhost:6333/collections/lexicon_arxiv/index/title"

# Remove abstract index  
curl -X DELETE "http://localhost:6333/collections/lexicon_arxiv/index/abstract"

# Remove keywords index
curl -X DELETE "http://localhost:6333/collections/lexicon_arxiv/index/keywords"
```

Or restore from snapshot:

```bash
# List snapshots
curl "http://localhost:6333/collections/lexicon_arxiv/snapshots"

# Restore (replace with actual snapshot name)
curl -X PUT "http://localhost:6333/collections/lexicon_arxiv/snapshots/lexicon_arxiv-2024-01-01-12-00-00.snapshot/recover"
```

---

## Performance Considerations

### Index Size Impact

| Field | Est. Index Size | Notes |
|-------|-----------------|-------|
| title | ~5-10 MB | Short text, high cardinality |
| abstract | ~50-100 MB | Long text, inverted index |
| keywords | ~2-5 MB | Array of short strings |

Total: ~10-20% increase in collection storage.

### Query Latency

| Search Type | Latency (P95) | Notes |
|-------------|---------------|-------|
| Dense only | ~50ms | Current baseline |
| BM25 only | ~30ms | Fast inverted index |
| Hybrid (RRF) | ~80ms | Both searches + fusion |

### Optimization Tips

1. **Limit prefetch results**: Don't fetch 1000 from each - 50-100 is usually enough
2. **Use field-specific queries**: Search `title` for exact paper names, `abstract` for concepts
3. **Consider quantization**: Reduces dense search time, more headroom for BM25

---

## Migration Checklist

- [ ] Verify Qdrant version ≥ 1.7.0
- [ ] Create collection snapshot (backup)
- [ ] Ensure sufficient disk space (+20%)
- [ ] Run text index creation commands
- [ ] Wait for indexing to complete
- [ ] Verify indices with collection info
- [ ] Test BM25 search quality
- [ ] Test hybrid search
- [ ] Update application code (if needed)
- [ ] Monitor query latency after migration

---

## See Also

- [Search Pipeline Design](../pipelines/search.md)
- [Architecture Overview](../architecture/overview.md)
- [Qdrant Text Search Documentation](https://qdrant.tech/documentation/concepts/indexing/#full-text-index)

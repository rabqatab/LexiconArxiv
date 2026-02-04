# LexiconArxiv Documentation

AI 연구 인사이트 엔진 — **Core + On-demand** 기술 문서

> Top-tier 연구를 기준점(anchor)으로 삼아 연구 트렌드·그래프·핵심 논문을 보여주는 엔진

---

## 문서 구조

### Design Documents (`design/`)

| 문서 | 설명 | 대상 독자 |
|------|------|----------|
| [PRD](./design/prd.md) | 제품 요구사항 정의서 | PM, 전체 팀 |
| [Architecture](./design/architecture.md) | 시스템 아키텍처 설계 | Backend Engineer |
| [API Specification](./design/api_specification.md) | REST API 및 MCP 인터페이스 명세 | Frontend, API Consumer |
| [Data Model](./design/data_model.md) | 데이터베이스 스키마 및 데이터 모델 | Backend Engineer |
| [Search Pipeline](./design/search_pipeline.md) | 하이브리드 검색 파이프라인 상세 설계 | Search Engineer |
| [Data Collection](./design/data_collection.md) | 다중 소스 데이터 수집 전략 | Data Engineer |
| [Citation Graph](./design/citation_graph.md) | 인용 그래프 및 GraphRAG 설계 | Search Engineer, ML Engineer |
| [UX Design](./design/ux_design.md) | 사용자 경험 및 인터페이스 설계 | Frontend, Designer |
| [Testing Strategy](./design/testing_strategy.md) | 테스트 전략 및 품질 보증 | QA, All Engineers |

### Guides (`guides/`)

| 문서 | 설명 | 대상 독자 |
|------|------|----------|
| [Quick Start](./guides/quickstart.md) | 처음부터 전체 파이프라인 실행 가이드 | All Engineers |
| [Crawling HOWTO](./guides/crawling_howto.md) | Core Corpus 크롤링 가이드 (OpenAlex, ACL, DBLP) | Data Engineer, DevOps |

---

## Quick Links

### 핵심 개념

- **Core Corpus**: Tier 0/1/2 venue (27개 main venue + 90+ workshops) 논문 사전 수집
- **On-demand**: 질의 시점에 arXiv/OpenAlex 확장 검색
- **Core 연결**: On-demand 논문의 Core 인용/유사도 관계 표시
- **연구 그래프**: 논문 간 인용 네트워크 시각화

### Venue Tiers (27 main venues + workshops)

| Tier | Field | Venues |
|------|-------|--------|
| **Tier 0** (11) | ML | NeurIPS, ICML, ICLR, JMLR |
| | AI | AAAI, IJCAI |
| | NLP | ACL, EMNLP |
| | DM/IR/Web | KDD, WWW, SIGIR |
| **Tier 1** (13) | NLP | NAACL, EACL, COLING, Findings, TACL, CoNLL, LREC |
| | IR/DM | WSDM, CIKM, ICDM, ECIR, RecSys, TOIS |
| | AI | ESWA |
| **Tier 2** (3+) | Legal AI | AILaw, ICAIL, JURIX |
| | Workshops | BioNLP, SemEval, ArgMining, and 90+ more |

### 데이터 소스

| 소스 | 용도 | 예상 논문 수 |
|------|------|-------------|
| OpenAlex | ML/AI/DM venue + 인용 그래프 | ~40K |
| ACL Anthology | NLP venue (main + workshops) | ~30K |
| OpenReview | ICLR, NeurIPS, ICML | ~15K |
| ACM Digital Library | KDD, SIGIR, WWW | ~10K |
| DBLP | IR/Legal venue 보완 | ~5K |
| AAAI OJS | AAAI, ICWSM (2020-2023) | ~8K |
| arXiv | On-demand 최신 프리프린트 | Real-time |

### 기술 스택

```
Backend:     Python 3.11+ / FastAPI / Celery
Databases:   PostgreSQL / Elasticsearch / Qdrant
ML/NLP:      sentence-transformers / spaCy
Infra:       Docker / Kubernetes
```

---

## 개발 시작하기

### Prerequisites

```bash
# Python 3.11+
python --version

# Docker & Docker Compose
docker --version
docker-compose --version
```

### Local Setup

```bash
# Clone repository
git clone https://github.com/your-org/lexiconarxiv.git
cd lexiconarxiv

# Create virtual environment (using uv)
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -e ".[dev]"

# Start infrastructure
docker-compose up -d postgres qdrant redis

# Set environment variables
cp .env.example .env
# Edit .env with your OPENALEX_EMAIL

# Initialize Qdrant collection
python -m src.cli.core_collect init-storage

# Start development server
uvicorn app.main:app --reload
```

### Core Corpus Collection (Quick Start)

```bash
# List configured venues
python -m src.cli.core_collect list-venues

# Collect from all sources (recommended)
python -m src.cli.core_collect collect-all-sources --since-year 2020

# Include workshop papers
python -m src.cli.core_collect collect-all-sources --since-year 2020 --include-workshops

# Collect from a single venue (e.g., NeurIPS from 2020)
python -m src.cli.core_collect collect --venue neurips --since-year 2020

# Collect ACL workshops only
python -m src.cli.core_collect collect-acl --workshops-only --since-year 2024

# Check collection status
python -m src.cli.core_collect status

# Discover OpenAlex Source IDs for venues
python -m src.cli.core_collect discover-sources --venue icml
```

### Running Tests

```bash
# Unit tests
pytest tests/unit -v

# Integration tests (requires Docker services)
pytest tests/integration -v -m integration

# All tests with coverage
pytest --cov=src --cov-report=html
```

---

## API 빠른 시작

### 검색 API

```bash
curl -X POST https://api.lexiconarxiv.io/v1/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "query": "instruction tuning Korean LLM",
    "options": {
      "year_from": 2023,
      "limit": 50
    }
  }'
```

### Python SDK (예정)

```python
from lexiconarxiv import Client

client = Client(api_key="your-api-key")
results = client.search("instruction tuning", year_from=2023)

for paper in results.papers:
    print(f"{paper.title} ({paper.year})")
```

---

## 프로젝트 구조

```
lexiconarxiv/
├── docs/                        # 문서 (현재 위치)
├── src/
│   ├── api/                     # FastAPI endpoints
│   ├── core/                    # Core Corpus 수집 모듈
│   │   ├── config.py            # Venue 설정 (27 venues, Source IDs)
│   │   ├── storage.py           # Qdrant 저장소
│   │   ├── checkpoint.py        # 체크포인트/재시작
│   │   ├── deduplication.py     # 교차 소스 중복 제거
│   │   ├── crawler/             # 데이터 소스 수집기
│   │   │   ├── openalex.py      # OpenAlex API 수집기
│   │   │   ├── acl_anthology.py # ACL Anthology (main + workshops)
│   │   │   ├── openreview.py    # OpenReview API v1/v2
│   │   │   ├── acm_open.py      # ACM Digital Library
│   │   │   ├── dblp.py          # DBLP Search API
│   │   │   └── aaai_ojs.py      # AAAI OJS
│   │   ├── enrichment/          # 보강 파이프라인
│   │   │   ├── openalex.py      # OpenAlex 인용/초록 보강
│   │   │   ├── semantic_scholar.py  # S2 폴백
│   │   │   └── pdf.py           # PDF 참조 추출 (GROBID)
│   │   └── resolution/          # 참조 해결 (인용 그래프)
│   │       ├── normalizer.py    # ID 정규화 (DOI, arXiv, OpenAlex)
│   │       └── resolver.py      # 내부 ID 매핑
│   ├── models/                  # 데이터 모델
│   │   └── paper.py             # RawPaper (tier, is_core, venue_type)
│   ├── cli/                     # CLI 도구
│   │   └── core_collect.py      # Core Corpus 수집 CLI
│   └── utils/                   # 유틸리티
├── tests/
├── data/
│   └── core/
│       └── checkpoints/         # 수집 체크포인트
└── scripts/
    └── crawler/                 # 수집 스크립트
```

---

## 기여하기

1. 이슈 생성 또는 기존 이슈 확인
2. Feature branch 생성: `git checkout -b feature/your-feature`
3. 변경사항 커밋: `git commit -m "Add your feature"`
4. PR 생성

### 코드 스타일

- Python: black + isort + flake8
- Type hints 필수
- Docstrings (Google style)

---

## 버전 히스토리

| 버전 | 날짜 | 주요 변경사항 |
|------|------|---------------|
| 0.1.0 | - | MVP-1: OpenAlex + arXiv 검색 |
| 0.2.0 | - | MVP-2: ACL Anthology + 임베딩 검색 |
| 0.3.0 | - | MVP-3: Saved query + API 공개 |
| 0.4.0 | Feb 2026 | Multi-source crawlers (OpenReview, ACM, AAAI) |
| 0.4.1 | Feb 2026 | ACL workshop support, OpenReview API v2 fix |

---

## 라이선스

MIT License

---

## 연락처

- GitHub Issues: [링크]
- Email: team@lexiconarxiv.io

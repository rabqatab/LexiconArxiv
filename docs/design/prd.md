# Product Requirements Document

## AI 연구 인사이트 엔진 — Core + On-demand

> **Top-tier 연구를 기준점(anchor)으로 삼아 연구 트렌드·그래프·핵심 논문을 보여주는 AI 연구 인사이트 엔진**

---

## 1. 문제 정의

AI/NLP 연구자는 다음과 같은 문제를 지속적으로 겪고 있음:

| 문제 | 영향 |
|------|------|
| 논문이 너무 많음 | **지금 중요한 연구 흐름**을 파악하기 어려움 |
| Google Scholar의 불투명한 랭킹 | 리콜은 높지만 **검색 로직을 신뢰하기 어려움** |
| 추천 시스템(Elicit 등)의 한계 | 전체 맥락 없이 개별 추천만 제공 |
| arXiv ↔ top-tier 연결 단절 | **최신 프리프린트와 검증된 연구 간 연결이 안 보임** |

---

## 2. 제품 비전

**"질문에 답해주는 AI"가 아니라**
**"Top-tier 연구를 기준으로 지금 AI 연구가 어디로 가는지를 보여주는 엔진"**

### 핵심 가치
- **Core Corpus**: Top-tier venue 논문을 기준점(anchor)으로 활용
- **연구 그래프**: 논문 간 인용/참조 관계를 시각화
- **트렌드 분석**: 연구 흐름과 Notable 논문 자동 선정
- **On-demand 확장**: 최신 arXiv와 Core의 연결 관계 표시

---

## 3. 도메인 범위

### 포함 (In-scope)
- **NLP / Language**: ACL, EMNLP, NAACL, COLING, EACL
- **ML General**: NeurIPS, ICML, ICLR
- **AI General**: AAAI, IJCAI
- **Data Mining / Web / IR**: KDD, WWW, SIGIR, WSDM, CIKM, ICDM

### 제외 (Out-of-scope)
- ❌ Computer Vision (CVPR, ICCV, ECCV)
- ❌ Robotics (ICRA, IROS)
- ❌ Speech/Audio (ICASSP, Interspeech)

---

## 4. 핵심 전략: Core + On-demand

### 4.1 Core Corpus (사전 수집)

| Tier | Venues | 설명 |
|------|--------|------|
| **Tier 0** | NeurIPS, ICML, ICLR, AAAI, IJCAI, ACL, EMNLP, KDD, WWW, SIGIR | 무조건 전체 수집 |
| **Tier 1** | NAACL, COLING, EACL, WSDM, CIKM, ICDM | 사전 수집, 우선순위 ↓ |

- **전체 수집**: 해당 venue의 모든 논문
- **인용 그래프**: `referenced_works` 기반 논문 연결
- **임베딩**: Abstract 기반 semantic 검색 지원

### 4.2 On-demand Retrieval (질의 시점)

- 유저 질의 시 arXiv / OpenAlex에 **좁은 쿼리**로 검색
- Core Corpus와 연결되는 논문만 강조 표시
- 연결이 없는 논문은 "Unverified" 라벨 표시

---

## 5. 핵심 기능

### 5.1 검색 & 발견
- 자연어 질의 → 연구 의도 해석
- Core 기반 하이브리드 검색 (BM25 + Semantic)
- On-demand 최신 논문 확장

### 5.2 연구 그래프
- Core 논문 간 인용 네트워크
- 특정 논문의 영향력 시각화
- arXiv → Core 연결 표시

### 5.3 트렌드 & Notable
- 연도별/주제별 연구 트렌드
- Notable 연구 자동 선정 (인용, venue, 최신성 기반)
- 클러스터링 기반 주제 분류

### 5.4 Export & Integration
- BibTeX / CSV / JSON export
- REST API
- 저장된 쿼리 & 알림

---

## 6. MVP 로드맵

### MVP-1: Tier 0 Core + 기본 그래프
- Tier 0 venue 전체 수집
- 기본 검색 (BM25 + semantic)
- 인용 그래프 시각화

### MVP-2: Tier 1 + On-demand 확장
- Tier 1 venue 추가
- arXiv On-demand 검색
- Core 연결 표시

### MVP-3: 트렌드 + API/Agent 연동
- 트렌드 분석 대시보드
- Notable 논문 자동 선정
- REST API 공개
- 저장된 쿼리 & 알림

---

## 7. 타깃 사용자

### Primary
- AI/NLP PhD 및 Postdoc
- 산업 연구소(Research Lab) 소속 연구원
- 리뷰/서베이 논문 작성자

### Secondary
- 대학원 신입생 (문헌 탐색 단계)
- 기술 전략/리서치 엔지니어

---

## 8. 경쟁 대비 차별점

| 항목 | Google Scholar | Semantic Scholar | Elicit | **본 제품** |
|------|---------------|-----------------|--------|------------|
| Top-tier 기준 앵커 | ✗ | △ | ✗ | **✓** |
| 연구 그래프 | ✗ | △ | ✗ | **✓** |
| Core-arXiv 연결 | ✗ | ✗ | ✗ | **✓** |
| 트렌드 시각화 | ✗ | △ | ✗ | **✓** |
| 검색 투명성 | ✗ | ✗ | ✗ | **✓** |

---

## 9. 성공 지표

### 정량 지표
| 지표 | 목표 |
|------|------|
| Core Corpus 커버리지 | Tier 0 venue 95%+ |
| 검색 latency P95 | < 2초 |
| 그래프 로딩 P95 | < 3초 |
| Core-arXiv 연결률 | > 30% |

### 정성 지표
- "연구 흐름이 보인다" 피드백
- 리뷰/서베이 작성 시 활용 여부
- Notable 선정의 유용성

---

## 10. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| Venue 논문 수집 누락 | Core 불완전 | 다중 소스 활용 (OpenAlex + ACL Anthology + DBLP) |
| 인용 그래프 불완전 | 연결 누락 | OpenAlex `referenced_works` + Crossref 보완 |
| "Scholar와 뭐가 다르냐" | 사용자 이탈 | 그래프/트렌드 UI 강조 |
| 임베딩 비용 | 운영비 증가 | Abstract 우선, 배치 처리 |

---

## 11. 관련 문서

| 문서 | 설명 |
|------|------|
| [Architecture](./architecture.md) | 시스템 아키텍처 |
| [API Specification](./api_specification.md) | API 명세 |
| [Data Model](./data_model.md) | 데이터 스키마 |
| [Search Pipeline](./search_pipeline.md) | 검색 파이프라인 |
| [Data Collection](./data_collection.md) | 데이터 수집 전략 |
| [UX Design](./ux_design.md) | UI/UX 설계 |
| [Testing Strategy](./testing_strategy.md) | 테스트 전략 |

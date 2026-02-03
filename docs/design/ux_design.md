# UX Design Document

## 1. Design Principles

### 1.1 Core Principles

1. **연구자 신뢰 우선 (Researcher Trust First)**
   - "AI가 판단"이 아니라 "AI가 수집"
   - 모든 결과에 출처와 이유를 명시
   - 숨겨진 필터링 없음

2. **투명성 (Transparency)**
   - 검색 범위가 어디까지인지 항상 표시
   - 누락 가능성을 사전에 안내
   - 랭킹 로직을 이해할 수 있도록

3. **효율성 (Efficiency)**
   - 클릭 수 최소화
   - 필터는 즉각 반응
   - 키보드 단축키 지원

4. **Core-first 접근 (Core-first Approach)**
   - Top-tier venue 논문을 기준점(anchor)으로 표시
   - On-demand 논문의 Core 연결 관계 명시
   - 연구 흐름과 트렌드를 그래프로 시각화

---

## 2. User Flows

### 2.1 Discovery Flow (문헌 조사)

```
┌─────────────────────────────────────────────────────────────────┐
│  1. 검색 입력                                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Korean LLM instruction tuning datasets                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  2. 검색 옵션 (선택적)                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Sources: [✓] OpenAlex [✓] arXiv [✓] ACL Anthology       │   │
│  │ Year: 2022 ~ 2024    Venue: [Any]    Type: [dataset]    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  3. 결과 (투명성 패널 포함)                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 📊 623 papers found (1,250 raw → 623 after dedup)       │   │
│  │ Sources: OpenAlex (450) + arXiv (580) + ACL (220)       │   │
│  │ ⚠️ Note: Google Scholar not included                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  4. 결과 목록 + 필터 패널                                       │
│  ┌──────────────────┬──────────────────────────────────────┐   │
│  │ Filters          │ Results                              │   │
│  │ ────────────     │ ─────────────────────────────────    │   │
│  │ Year             │ 1. KULLM: Korean Large Language...   │   │
│  │ [ ] 2024 (123)   │    arXiv 2023 | Method | ★ 0.92     │   │
│  │ [✓] 2023 (234)   │                                      │   │
│  │ [✓] 2022 (266)   │ 2. KoAlpaca: Korean Alpaca Model...  │   │
│  │                  │    ACL 2023 | Dataset | ★ 0.89       │   │
│  │ Venue            │                                      │   │
│  │ [ ] ACL (45)     │ 3. Korean Instruction Dataset for... │   │
│  │ [ ] EMNLP (38)   │    arXiv 2024 | Dataset | ★ 0.87     │   │
│  │ ...              │                                      │   │
│  └──────────────────┴──────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  5. Export / Save                                               │
│  [Export BibTeX] [Export CSV] [Save Query] [Copy Citations]     │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Monitoring Flow (최신 논문 추적)

```
┌─────────────────────────────────────────────────────────────────┐
│  Saved Queries                                                  │
│  ────────────────────────────────────────────────────────────── │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 🔔 RAG Evaluation                                        │   │
│  │    "RAG evaluation benchmark" | Since: 2024              │   │
│  │    📅 Daily at 9AM | 🆕 12 new papers this week          │   │
│  │    [View Results] [Edit] [Pause]                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 🔔 Korean NLP                                            │   │
│  │    "Korean language model OR 한국어 LLM"                 │   │
│  │    📅 Weekly | 🆕 45 new papers this month               │   │
│  │    [View Results] [Edit] [Pause]                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [+ Create New Saved Query]                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Specifications

### 3.1 Search Input

```
┌─────────────────────────────────────────────────────────────┐
│ 🔍 Search for papers...                                     │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ instruction tuning_                                     │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Suggestions:                                                │
│ ├─ instruction tuning (1,523 papers)                       │
│ ├─ instruction tuning dataset (342 papers)                 │
│ └─ instruction tuning evaluation (128 papers)              │
│                                                             │
│ Recent searches:                                            │
│ ├─ Korean LLM datasets                                      │
│ └─ RAG evaluation benchmark                                 │
└─────────────────────────────────────────────────────────────┘
```

**Behavior**:
- 타이핑 시 300ms debounce 후 자동완성
- Enter: 검색 실행
- Arrow keys: 제안 항목 탐색
- Esc: 제안 닫기

### 3.2 Transparency Panel

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 Search Transparency                               [Hide] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Results: 623 papers                                         │
│                                                             │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ Raw Results          After Dedup                    │    │
│ │ ████████████████░░░  ████████████░░░░░░░░           │    │
│ │ 1,250                 623 (50% unique)              │    │
│ └─────────────────────────────────────────────────────┘    │
│                                                             │
│ Sources searched:                                           │
│ ├─ ✅ OpenAlex     450 papers                               │
│ ├─ ✅ arXiv        580 papers                               │
│ └─ ✅ ACL Anthology 220 papers                              │
│                                                             │
│ Ranking: Hybrid (BM25 40% + Semantic 60%)                   │
│                                                             │
│ ⚠️ Coverage notes:                                          │
│ • Google Scholar is not included                            │
│ • Some workshops before 2018 may be missing                 │
│                                                             │
│ 🕐 Search completed in 1.2s                                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Paper Card

```
┌─────────────────────────────────────────────────────────────┐
│ KULLM: Korean Large Language Model for Instruction...      │
│ ────────────────────────────────────────────────────────── │
│                                                             │
│ 👤 Seungjun Lee, Jihyun Kim, et al. (KAIST)               │
│ 📅 2023  |  📍 arXiv preprint  |  🏷️ method               │
│                                                             │
│ We present KULLM, a Korean instruction-tuned large         │
│ language model. Our model demonstrates strong...           │
│ [Show more]                                                 │
│                                                             │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ Relevance: ████████░░ 0.92                          │    │
│ │ Matched: title, abstract                            │    │
│ │ Found in: arXiv, OpenAlex                           │    │
│ └─────────────────────────────────────────────────────┘    │
│                                                             │
│ 🔗 Versions: [arXiv v2] [EMNLP 2023 Camera-Ready]          │
│                                                             │
│ [📄 PDF] [📝 Abstract] [💾 Save] [📋 Cite]                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Filter Panel

```
┌─────────────────────────────────────┐
│ Filters                      [Clear]│
├─────────────────────────────────────┤
│                                     │
│ 📅 Year                             │
│ ┌─────────────────────────────────┐ │
│ │ 2018 ●────────────────● 2024   │ │
│ └─────────────────────────────────┘ │
│ [ ] 2024 (123)                      │
│ [✓] 2023 (234)                      │
│ [✓] 2022 (266)                      │
│                                     │
│ 📍 Venue                            │
│ [Search venues...]                  │
│ [ ] ACL (45)                        │
│ [ ] EMNLP (38)                      │
│ [ ] NAACL (22)                      │
│ [ ] NeurIPS (18)                    │
│ [Show 12 more...]                   │
│                                     │
│ 🏷️ Paper Type                       │
│ [ ] method (312)                    │
│ [✓] dataset (156)                   │
│ [✓] benchmark (89)                  │
│ [ ] survey (34)                     │
│                                     │
│ 📄 Version                          │
│ (•) All versions                    │
│ ( ) Preprints only                  │
│ ( ) Published only                  │
│                                     │
│ 🔢 Ranking                          │
│ [Relevance          ▼]              │
│                                     │
└─────────────────────────────────────┘
```

---

## 4. Responsive Design

### 4.1 Breakpoints

| Breakpoint | Width | Layout |
|------------|-------|--------|
| Mobile | < 768px | Single column, filters in modal |
| Tablet | 768-1024px | Collapsible sidebar |
| Desktop | > 1024px | Full sidebar + main content |
| Wide | > 1440px | Extra-wide result cards |

### 4.2 Mobile Layout

```
┌─────────────────────────┐
│ 🔍 Search...            │
├─────────────────────────┤
│ [🔧 Filters] [📊 Info]  │
├─────────────────────────┤
│ 623 papers found        │
├─────────────────────────┤
│ ┌─────────────────────┐ │
│ │ KULLM: Korean...    │ │
│ │ Lee et al. | 2023   │ │
│ │ ★ 0.92 | arXiv      │ │
│ └─────────────────────┘ │
│ ┌─────────────────────┐ │
│ │ KoAlpaca: Korean... │ │
│ │ Kim et al. | 2023   │ │
│ │ ★ 0.89 | ACL        │ │
│ └─────────────────────┘ │
│           ...           │
└─────────────────────────┘
```

---

## 5. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `/` | Focus search input |
| `Esc` | Close modal / Clear focus |
| `↑` `↓` | Navigate results |
| `Enter` | Open selected paper |
| `s` | Save selected paper |
| `c` | Copy citation |
| `e` | Export selected |
| `f` | Toggle filter panel |
| `t` | Toggle transparency panel |
| `?` | Show keyboard shortcuts |

---

## 6. Accessibility

### 6.1 Requirements

- WCAG 2.1 AA 준수
- Screen reader 지원 (ARIA labels)
- 키보드 네비게이션 완전 지원
- 고대비 모드 지원
- 최소 터치 타겟: 44x44px

### 6.2 ARIA Implementation

```html
<!-- Search input -->
<input
  role="searchbox"
  aria-label="Search for papers"
  aria-autocomplete="list"
  aria-controls="search-suggestions"
  aria-expanded="true"
/>

<!-- Results list -->
<ul
  role="list"
  aria-label="Search results"
  aria-live="polite"
>
  <li role="listitem" tabindex="0">
    ...
  </li>
</ul>

<!-- Transparency panel -->
<aside
  role="complementary"
  aria-label="Search transparency information"
>
  ...
</aside>
```

---

## 7. Error States

### 7.1 No Results

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                    😕 No papers found                       │
│                                                             │
│  Your search "asdfghjkl" didn't match any papers.          │
│                                                             │
│  Suggestions:                                               │
│  • Check your spelling                                      │
│  • Try more general keywords                                │
│  • Remove some filters                                      │
│                                                             │
│  Or try one of these related searches:                      │
│  • [language model]                                         │
│  • [natural language processing]                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Partial Failure

```
┌─────────────────────────────────────────────────────────────┐
│ ⚠️ Some sources were unavailable                            │
│                                                             │
│ Results from:                                               │
│ ✅ OpenAlex (450 papers)                                    │
│ ✅ ACL Anthology (220 papers)                               │
│ ❌ arXiv (temporarily unavailable)                          │
│                                                             │
│ Showing 670 papers. [Retry arXiv]                           │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Rate Limited

```
┌─────────────────────────────────────────────────────────────┐
│ 🕐 Please wait a moment                                     │
│                                                             │
│ You've made too many requests. Please wait 30 seconds       │
│ before searching again.                                     │
│                                                             │
│ [████████░░░░░░░░░░░░] 15s remaining                        │
│                                                             │
│ Tip: Save your frequent searches to avoid rate limits.      │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Loading States

### 8.1 Search Loading

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  🔍 Searching across multiple sources...                    │
│                                                             │
│  ✓ OpenAlex                                                 │
│  ◐ arXiv (fetching...)                                      │
│  ○ ACL Anthology                                            │
│  ○ Deduplicating results                                    │
│                                                             │
│  [━━━━━━━━━━━░░░░░░░░░░] 58%                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 Skeleton Loading

```
┌─────────────────────────────────────────────────────────────┐
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                │
│ ─────────────────────────────────────────────               │
│ ░░░░░░░░░░ | ░░░░ | ░░░░░░░░░                               │
│                                                             │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                    │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                         │
│                                                             │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Dark Mode

전체 인터페이스는 Light/Dark 모드 지원:

| Element | Light | Dark |
|---------|-------|------|
| Background | #FFFFFF | #1A1A1A |
| Surface | #F5F5F5 | #2D2D2D |
| Primary text | #1A1A1A | #E5E5E5 |
| Secondary text | #666666 | #A0A0A0 |
| Primary accent | #2563EB | #60A5FA |
| Success | #16A34A | #4ADE80 |
| Warning | #D97706 | #FBBF24 |
| Error | #DC2626 | #F87171 |

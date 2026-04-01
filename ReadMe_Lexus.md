# 🚗 CarSpec Crawler — Lexus 확장판
**렉서스 UX Hybrid 전 트림 사양 자동 수집 엔진 (Playwright 기반)**

> 렉서스 미국 공식 사이트의 UX Hybrid 모델 비교 페이지(Compare)에서
> 전 트림의 사양을 수집하여 RAG 지식 베이스용 표준 JSON으로 변환하는 크롤러입니다.
> KIA 버전과의 핵심 차이는 **"한 화면에 3개 트림만 표시"** 되는 제약을 배치 순회로 극복하는 구조입니다.

---

## 📌 목차

1. [프로젝트 개요 및 KIA 버전과의 차이](#-프로젝트-개요-및-kia-버전과의-차이)
2. [수집 대상 페이지 구조](#-수집-대상-페이지-구조)
3. [핵심 과제 및 해결 전략](#-핵심-과제-및-해결-전략)
4. [수집 전략 상세: 배치 순회 흐름](#-수집-전략-상세-배치-순회-흐름)
5. [기술 스택](#-기술-스택)
6. [디렉토리 구조](#-디렉토리-구조)
7. [시스템 아키텍처](#-시스템-아키텍처)
8. [설정 파일 명세 (lexus.json)](#-설정-파일-명세-lexusjson)
9. [출력 데이터 형식](#-출력-데이터-형식)
10. [설치 및 실행 방법](#-설치-및-실행-방법)
11. [구현 시 준수 사항](#-구현-시-준수-사항)
12. [트러블슈팅](#-트러블슈팅)

---

## 🎯 프로젝트 개요 및 KIA 버전과의 차이

### KIA vs Lexus 구조 비교

| 항목 | KIA | Lexus |
|---|---|---|
| 비교 페이지 URL | `/specs-compare` (단일 고정 URL) | 모델 페이지(`/models/UX-hybrid`) + `#model_compare` 앵커 |
| URL 변경 여부 | 비교 페이지 전환 시 URL 변경 | **URL 변경 없음** (React 상태로만 전환) |
| 한 화면의 트림 수 | 전체 트림 동시 표시 | **최대 3개 트림만 표시** |
| 전체 트림 수 | 모델마다 다름 | **8개** (300h ~ F SPORT Handling AWD) |
| 셀렉터 방식 | CSS class 기반 | **`data-testid` 속성 기반** (안정적) |
| 트림 선택 UI | 드롭다운 (select/option) | **체크박스** (`input[name='model_compare-select']`) + COMPARE 버튼 |
| 기호 표현 | 텍스트 (`●`, `○`, `—`) | **SVG 아이콘** (`data-testid="OptionalIcon"` 등) + 텍스트 수치 혼재 |
| 파싱 방식 | Playwright 엘리먼트 핸들 | **`page.evaluate()` JS 파싱** (stale element 방지) |

### Lexus 수집의 핵심 제약

렉서스 비교 페이지는 한 번에 **3개 열(Column)** 만 표시합니다. 트림 8개를 전부 수집하려면 배치로 나눠 순회해야 합니다.

```
[배치 1] 300h | 300h AWD | 300h Premium
[배치 2] 300h Premium AWD | 300h F SPORT Design | 300h F SPORT Design AWD
[배치 3] 300h F SPORT Handling | 300h F SPORT Handling AWD | (패딩)
```

각 배치 결과를 마스터 딕셔너리에 **upsert**(없으면 추가, 있으면 유지)하여 전 트림 데이터를 완성합니다.

---

## 🖥️ 수집 대상 페이지 구조

### 진입 경로

```
1. https://www.lexus.com/models/UX-hybrid 접속

2. 페이지 내 네비게이션 버튼 클릭으로 Compare 섹션 이동
   └─ 선택자: #arrowbutton 또는 a[href='#model_compare']
   └─ 클릭 실패 시 fallback: document.querySelector('#model_compare')?.scrollIntoView()

3. Compare Grid 대기 및 노출
   └─ wait_for_selector("[data-testid='CompareGrid']") 로 렌더링 확인

4. 트림 체크박스 선택 (배치별)
   └─ input[name='model_compare-select'] 체크박스로 최대 3개 선택
   └─ COMPARE 버튼(button[aria-label='COMPARE']) 활성화 후 클릭

5. Compare Grid에 3개 트림 데이터 렌더링
```

### 전체 트림 목록 (8개, HTML에서 확인됨)

| # | 트림명 | select_id |
|---|---|---|
| 1 | 300h | `a300h-select` |
| 2 | 300h AWD | `a300h-awd-select` |
| 3 | 300h Premium | `a300h-premium-select` |
| 4 | 300h Premium AWD | `a300h-premium-awd-select` |
| 5 | 300h F SPORT Design | `a300h-f-sport-design--select` |
| 6 | 300h F SPORT Design AWD | `a300h-f-sport-design-awd-select` |
| 7 | 300h F SPORT Handling | `a300h-f-sport-handling--select` |
| 8 | 300h F SPORT Handling AWD | `a300h-f-sport-handling-awd-select` |

### Compare 페이지 DOM 구조 (HTML 분석 완료)

```
[data-testid="CompareGrid"]
  └── [data-testid="CompareGridImpl"]
        └── [data-testid="CompareGridTabsImpl"]
              ├── [data-testid="GridHeader"]      ← 현재 표시 중인 트림명 (th, 3개)
              └── [data-testid="DataRow"] (tr)    ← 모든 데이터 행 (반복)
                    ├── <th>                      ← 사양/기능명 셀
                    │     유형 A (SPEC): 사양명 텍스트 (예: "Engine", "Displacement")
                    │     유형 B (FEATURE): 비어있음 (th 텍스트 없음)
                    └── <td data-testid="FeaturesRow"> × N  ← 트림별 값 셀
                          유형 A: 텍스트 수치 (예: "In-line 4 hybrid", "2.0L")
                          유형 B: 기능명 텍스트 (있는 트림) 또는 NotAvailableIcon
```

> **주의**: `FeaturesRow`는 독립된 행이 아니라 `DataRow(tr)` 내부 `<td>` 셀의 `data-testid` 값입니다.
> 즉, `DataRow` 하나가 사양/기능 한 항목을 나타내며, 그 안의 `td[data-testid="FeaturesRow"]`들이 트림별 값입니다.

### 카테고리 섹션 (드로어 ID 확인됨)

각 섹션은 별도 드로어로 구분되며, 클릭하면 하위 항목이 펼쳐집니다.

| 드로어 ID | 내용 |
|---|---|
| `engine-specs-compare-drawer` | 엔진 사양 |
| `chassis-specs-compare-drawer` | 섀시 |
| `drivetrain-specs-compare-drawer` | 구동계 |
| `dimensions-specs-compare-drawer` | 제원 (크기/무게) |
| `performance-specs-compare-drawer` | 성능 수치 |
| `key-features-specs-compare-drawer` | 주요 기능 |
| `exterior-features-features-compare-drawer` | 외장 기능 |
| `interior-features-features-compare-drawer` | 내장 기능 |
| `safety-features-compare-drawer` | 안전 기능 |
| `technology-features-compare-drawer` | 기술/인포테인먼트 |
| `performance-features-compare-drawer` | 성능 기능 |

### 기호 표현 방식 (HTML에서 확인됨)

렉서스 비교 페이지는 기호를 `data-testid` 아이콘과 텍스트로 혼합 표현합니다.

| data-testid | 의미 | 정규화 값 |
|---|---|---|
| `OptionalIcon` | 옵션으로 추가 가능 | `"Optional"` |
| `NotAvailableIcon` | 해당 트림 미제공 | `"Unavailable"` |
| `NotAvailablePlaceholder` | 해당 트림 미제공 (자리 표시자) | `"Unavailable"` |
| `PackageIcon` | 패키지로 추가 가능 | `"Package"` |
| (텍스트 수치, SPEC 행) | `"110 MPH"`, `"2.0L"` 등 | 원문 그대로 |
| (텍스트 있음, FEATURE 행) | 기능명 텍스트 존재 | `"Standard"` |
| (빈 셀, FEATURE 행) | 아이콘/텍스트 없음 | `"Unavailable"` |

> **FEATURE 행 셀 내부 구조**: 기능명 텍스트는 첫 번째 `<span>` 안에, 아이콘은 `<div data-testid="FeatureTags">` 안에 위치합니다.
> `NotAvailableIcon`이 있는 셀의 `innerText`는 "not availableNA"로 나타납니다.

---

## 🧩 핵심 과제 및 해결 전략

### Challenge 1 — 3개 트림 표시 제한

**→ 해결: 트림 조합 배치 순회 + upsert 병합**

```
배치 생성 규칙:
trims = [A, B, C, D, E, F, G, H]  (8개)
→ [[A,B,C], [D,E,F], [G,H,A]]    ← 마지막 배치는 패딩으로 첫 트림 재사용
```

각 배치에서 트림 선택을 변경하고 데이터를 수집한 뒤, 마스터 딕셔너리에 병합합니다.

### Challenge 2 — URL 변경 없는 SPA 네비게이션

Compare 버튼 클릭 시 URL이 바뀌지 않으므로 `page.goto()`로 직접 접근 불가.

**→ 해결: 모델 페이지 진입 후 네비게이션 버튼 클릭 또는 앵커 스크롤**

```python
page.goto("https://www.lexus.com/models/UX-hybrid")

# 1차: 페이지 내 네비게이션 버튼 클릭
nav_btn = page.wait_for_selector(
    "#arrowbutton, a[href='#model_compare']", timeout=15000
)
nav_btn.scroll_into_view_if_needed()
nav_btn.click()

# fallback: 직접 앵커로 스크롤
page.evaluate("document.querySelector('#model_compare')?.scrollIntoView()")

# CompareGrid 렌더링 대기
page.wait_for_selector("[data-testid='CompareGrid']", timeout=30000)
```

### Challenge 3 — 트림 선택 방식 (체크박스 + COMPARE 버튼)

실제 DOM 검증 결과, ControlsRow 드롭다운 방식이 아닌 **카드형 체크박스** UI로 트림을 선택합니다.

**→ 해결: 체크박스 JavaScript 클릭 → COMPARE 버튼 활성화 대기 → 클릭**

```python
# Step A: 기존 체크 해제
page.evaluate("""
    () => {
        const cbs = document.querySelectorAll(
            "input[name='model_compare-select']:checked"
        );
        cbs.forEach(cb => cb.click());
    }
""")

# Step B: 배치 트림 체크 (JavaScript로 ID 직접 클릭)
page.evaluate(f"""
    () => {{
        const cb = document.getElementById('{trim["select_id"]}');
        if (cb && !cb.checked) cb.click();
    }}
""")

# Step C: COMPARE 버튼 활성화 후 클릭
page.wait_for_selector(
    "button[aria-label='COMPARE']:not([aria-disabled='true'])", timeout=10000
)
page.click("button[aria-label='COMPARE']:not([aria-disabled='true'])")
```

### Challenge 4 — SVG 아이콘 기반 기호 처리 (JavaScript 파싱)

텍스트가 아닌 `data-testid` 아이콘으로 기호를 표현하며, Playwright 엘리먼트 핸들의 stale 문제를 방지하기 위해 JavaScript로 브라우저 내에서 직접 추출합니다.

**→ 해결: `page.evaluate()`로 전체 그리드를 JS 내에서 파싱**

```javascript
// JS 내부 cellValue 헬퍼 (SPEC 행 값 추출)
const cellValue = td => {
    if (td.querySelector('[data-testid="NotAvailableIcon"]') ||
        td.querySelector('[data-testid="NotAvailablePlaceholder"]'))
        return 'Unavailable';
    if (td.querySelector('[data-testid="OptionalIcon"]')) return 'Optional';
    if (td.querySelector('[data-testid="PackageIcon"]'))  return 'Package';
    const text = cleanText(td.innerText);
    return text || 'Unavailable';
};

// FEATURE 행: 텍스트 있으면 'Standard', 없으면 'Unavailable'
const featureValue = td => {
    if (/* NotAvailable 아이콘 */) return 'Unavailable';
    if (/* Optional 아이콘 */)     return 'Optional';
    if (/* Package 아이콘 */)      return 'Package';
    return cleanText(td.innerText) ? 'Standard' : 'Unavailable';
};
```

### Challenge 5 — 카테고리 드로어 펼침

각 카테고리(ENGINE, DIMENSIONS 등)가 드로어로 접혀 있을 수 있습니다.

**→ 해결: `aria-expanded` 속성으로 접힘 여부 확인 후 펼치기**

```python
for drawer_id in category_drawer_ids:
    btn = page.query_selector(f"#{drawer_id}-button")
    if not btn:
        continue
    aria = btn.get_attribute("aria-expanded") or ""
    if aria.lower() == "false":
        btn.scroll_into_view_if_needed()
        btn.click()
        time.sleep(0.3)
```

### Challenge 6 — 배치 간 오버레이 복귀

COMPARE 버튼 클릭 후 비교 오버레이가 열리며, 다음 배치를 위해 카드 선택 화면으로 되돌아가야 합니다.

**→ 해결: 오버레이 닫기 버튼 클릭 또는 Escape 키**

```python
# 오버레이 닫기 시도 순서:
# 1. aria-label='Close' 버튼
# 2. .overlay-component--open button.close
# 3. fallback: Escape 키
# 4. overlay 사라짐 + 체크박스 재활성화 확인
```

---

## 🔄 수집 전략 상세: 배치 순회 흐름

```
[LexusSpecScraper.scrape_model("ux-hybrid")]
         │
         ├─ 1. 모델 페이지 접속 (domcontentloaded)
         │
         ├─ 2. 쿠키 배너 닫기 (_dismiss_cookie_banner)
         │
         ├─ 3. #arrowbutton / a[href='#model_compare'] 클릭으로 Compare 섹션 이동
         │     실패 시 fallback: scrollIntoView('#model_compare')
         │
         ├─ 4. wait_for_selector("[data-testid='CompareGrid']") 대기
         │
         ├─ 5. configs에서 all_trims (8개) 읽기 → 3개씩 배치 생성
         │     [A,B,C], [D,E,F], [G,H,A(패딩)]
         │
         ├─ 6. 배치 루프 (Step A~I)
         │     for batch in batches:
         │       ├─ A: _uncheck_all() → 기존 체크 해제 (JS)
         │       ├─ B: _check_trims() → 배치 트림 체크박스 선택 (JS)
         │       ├─ C: _click_compare_button() → COMPARE 버튼 클릭
         │       ├─ D: CompareGrid/ControlsRow 렌더링 대기
         │       ├─ E: _expand_all_drawers() → 드로어 전체 펼치기 (aria-expanded 기준)
         │       ├─ F: visible_trims = intended_labels (DOM 헤더 대신 배치 레이블 직접 사용)
         │       ├─ G: _parse_grid() → JS로 DataRow 전체 파싱
         │       │     ├─ 유형 A (th 텍스트 있음): 사양명 + 텍스트 수치
         │       │     └─ 유형 B (th 비어있음): 기능명(NotAvailable 셀 제외) + 아이콘값
         │       ├─ H: master_data upsert (패딩 트림 제외, setdefault로 덮어쓰기 방지)
         │       └─ I: _close_compare_overlay() → 다음 배치를 위해 카드 뷰 복귀
         │
         └─ 7. storage/raw/lexus_ux-hybrid_raw.json 저장
```

---

## 🛠️ 기술 스택

| 분류 | 사용 기술 |
|---|---|
| 브라우저 자동화 | Playwright for Python (sync API) |
| 언어 | Python 3.10+ |
| 데이터 저장 | JSON (로컬 파일) |
| 설정 관리 | `configs/lexus.json` |
| 패키지 관리 | pip / requirements.txt |

---

## 📂 디렉토리 구조

```
CarSpec-Crawler/
│
├── main.py
├── fetch_html.py                    # --pause 옵션으로 compare HTML 수집 가능
│
├── engine/
│   ├── scraper.py                   # KIA용
│   └── lexus_scraper.py             # Lexus 전용 (배치 순회 + 아이콘 파싱)
│
├── configs/
│   ├── kia.json
│   └── lexus.json                   # 8개 트림 목록 + data-testid 셀렉터 포함
│
├── utils/
│   ├── formatter.py
│   └── alias_mapper.py
│
├── storage/
│   ├── html/
│   │   └── lexus_ux-hybrid.html     # fetch_html.py로 수집한 원본 HTML
│   └── raw/
│       └── lexus_ux-hybrid_raw.json
│
├── requirements.txt
├── ReadMe.md
└── ReadMe_Lexus.md
```

---

## 🏗️ 시스템 아키텍처

```
[main.py] --brand lexus --model ux-hybrid
    │
    └── [engine/lexus_scraper.py] LexusSpecScraper
            │
            ├── 1. 브라우저 실행 (headless/non-headless)
            ├── 2. https://www.lexus.com/models/UX-hybrid 접속 (domcontentloaded)
            ├── 3. 쿠키 배너 닫기
            ├── 4. #arrowbutton 클릭 → Compare 섹션 이동
            │     fallback: scrollIntoView('#model_compare')
            ├── 5. wait_for_selector("[data-testid='CompareGrid']")
            ├── 6. configs에서 8개 트림 → 3개씩 배치 (_make_batches)
            ├── 7. 배치별 루프
            │     ├─ _uncheck_all()          ← JS로 기존 체크 해제
            │     ├─ _check_trims()          ← JS로 배치 트림 체크박스 선택
            │     ├─ _click_compare_button() ← COMPARE 버튼 활성화 대기 후 클릭
            │     ├─ CompareGrid 렌더링 대기
            │     ├─ _expand_all_drawers()   ← aria-expanded=false 드로어 펼치기
            │     ├─ _parse_grid()           ← JS evaluate로 DataRow 전체 파싱
            │     │     ├─ 유형 A (th 있음): 사양명 + 수치 텍스트
            │     │     └─ 유형 B (th 없음): 기능명 + 아이콘값(Optional/Package/Unavailable/Standard)
            │     ├─ master_data upsert (setdefault, 패딩 트림 제외)
            │     └─ _close_compare_overlay() ← 오버레이 닫기 → 카드 뷰 복귀
            └── 8. JSON 저장 (storage/raw/lexus_ux-hybrid_raw.json)
```

---

## ⚙️ 설정 파일 명세 (lexus.json)

```json
{
  "brand": "Lexus",
  "models": {
    "ux-hybrid": {
      "url": "https://www.lexus.com/models/UX-hybrid",
      "compare_anchor": "#model_compare",
      "batch_size": 3,
      "all_trims": [
        { "label": "300h",                    "select_id": "a300h-select" },
        { "label": "300h AWD",                "select_id": "a300h-awd-select" },
        { "label": "300h Premium",            "select_id": "a300h-premium-select" },
        { "label": "300h Premium AWD",        "select_id": "a300h-premium-awd-select" },
        { "label": "300h F SPORT Design",     "select_id": "a300h-f-sport-design--select" },
        { "label": "300h F SPORT Design AWD", "select_id": "a300h-f-sport-design-awd-select" },
        { "label": "300h F SPORT Handling",   "select_id": "a300h-f-sport-handling--select" },
        { "label": "300h F SPORT Handling AWD","select_id": "a300h-f-sport-handling-awd-select" }
      ],
      "selectors": {
        "compare_section": "#model_compare",
        "controls_row": "[data-testid='ControlsRow']",
        "trim_header": "[data-testid='GridHeader']",
        "data_row": "[data-testid='DataRow']",
        "features_row": "[data-testid='FeaturesRow']",
        "optional_icon": "[data-testid='OptionalIcon']",
        "not_available_icon": "[data-testid='NotAvailableIcon']",
        "package_icon": "[data-testid='PackageIcon']"
      },
      "category_drawer_ids": [
        "engine-specs-compare-drawer",
        "chassis-specs-compare-drawer",
        "drivetrain-specs-compare-drawer",
        "dimensions-specs-compare-drawer",
        "performance-specs-compare-drawer",
        "key-features-specs-compare-drawer",
        "exterior-features-features-compare-drawer",
        "interior-features-features-compare-drawer",
        "safety-features-compare-drawer",
        "technology-features-compare-drawer",
        "performance-features-compare-drawer"
      ]
    }
  },
  "symbol_map": {
    "●": "Standard",
    "○": "Optional",
    "—": "Unavailable"
  },
  "icon_map": {
    "OptionalIcon": "Optional",
    "NotAvailableIcon": "Unavailable",
    "NotAvailablePlaceholder": "Unavailable",
    "PackageIcon": "Package"
  },
  "wait_strategy": {
    "wait_until": "domcontentloaded",
    "wait_for_selector": "[data-testid='CompareGrid']"
  }
}
```

### 설정 필드 설명

| 필드 | 설명 |
|---|---|
| `url` | 모델 페이지 URL (compare는 이 페이지 내 앵커) |
| `compare_anchor` | Compare 섹션 앵커 ID |
| `batch_size` | 한 배치의 트림 수 (렉서스는 3 고정) |
| `all_trims` | 전체 8개 트림 목록 및 select_id |
| `selectors.*` | `data-testid` 기반 셀렉터 (HTML 분석 완료) |
| `category_drawer_ids` | 펼쳐야 할 카테고리 드로어 ID 목록 |
| `icon_map` | `data-testid` 아이콘 → 정규화 값 매핑 |

---

## 📊 출력 데이터 형식

```json
{
  "brand": "Lexus",
  "model": "UX Hybrid",
  "year": 2026,
  "crawled_at": "2026-03-31T09:00:00Z",
  "source_url": "https://www.lexus.com/models/UX-hybrid",
  "trims": {
    "300h": {
      "price_msrp": "",
      "features": {
        "Compression ratio": "14.0 : 1",
        "Displacement": "2.0L",
        "Engine": "In-line 4 hybrid",
        "Net combined horsepower": "196",
        "Top track speed": "110 MPH",
        "Turning circle": "34.2 ft",
        "All-Weather Package": "Optional",
        "Premium Package": "Optional"
      }
    },
    "300h AWD": { "...": "..." },
    "300h Premium": { "...": "..." },
    "300h Premium AWD": { "...": "..." },
    "300h F SPORT Design": { "...": "..." },
    "300h F SPORT Design AWD": { "...": "..." },
    "300h F SPORT Handling": { "...": "..." },
    "300h F SPORT Handling AWD": { "...": "..." }
  }
}
```

---

## 🚀 설치 및 실행 방법

```bash
# 의존성 설치 (최초 1회)
pip install -r requirements.txt
venv\Scripts\playwright install chromium

# HTML 수동 수집 (셀렉터 검증용)
python fetch_html.py --brand lexus --model ux-hybrid --no-headless --pause

# 전 트림 자동 수집
python main.py --brand lexus --model ux-hybrid

# 디버깅 (브라우저 화면 표시)
python main.py --brand lexus --model ux-hybrid --no-headless
```

---

## 📋 구현 시 준수 사항

| 항목 | 내용 |
|---|---|
| **배치 커버리지 보장** | 8개 트림이 모두 최소 1번 포함되도록 배치 구성, 마지막 배치는 첫 트림으로 패딩 |
| **체크박스 방식 사용** | ControlsRow 드롭다운이 아닌 `input[name='model_compare-select']` 체크박스 + COMPARE 버튼 |
| **COMPARE 버튼 대기** | `aria-disabled='true'`가 해제될 때까지 대기 후 클릭 |
| **드로어 전체 펼침** | 수집 전 `aria-expanded="false"` 드로어 11개 모두 펼치기 |
| **JS 평가로 파싱** | Playwright stale element 방지를 위해 `page.evaluate()`로 JS 내에서 전체 그리드 파싱 |
| **아이콘 우선 탐지** | NotAvailableIcon/Placeholder → "Unavailable" / OptionalIcon → "Optional" / PackageIcon → "Package" / 텍스트 있음(FEATURE) → "Standard" |
| **upsert 병합** | `setdefault(feat, val)`로 이미 수집된 트림/기능은 덮어쓰지 않음 |
| **패딩 트림 중복 방지** | `intended_labels`에 없는 트림은 병합 시 무시 |
| **오버레이 닫기** | 배치 완료 후 close 버튼 또는 Escape로 오버레이 닫고 카드 뷰 복귀 확인 |
| **로깅** | 배치 번호, 트림 조합, 파싱된 행 수, 전체 소요 시간 출력 |

---

## 🔧 트러블슈팅

| 증상 | 원인 | 해결 방법 |
|---|---|---|
| `CompareGrid` 셀렉터 타임아웃 | 페이지 로딩 지연 또는 네비게이션 버튼 미발견 | `debug_compare.png` / `debug_compare.html` 저장됨 → data-testid 목록 출력으로 진단 |
| COMPARE 버튼이 활성화 안 됨 | 체크박스 선택 실패 (select_id 미일치 등) | `[WARN] Checkbox not found: #...` 로그 확인, select_id 재검증 |
| DataRow가 0개 파싱됨 | 드로어가 접혀 있어 행이 렌더링 안 됨 | `_expand_all_drawers()` 호출 로그 확인 |
| 값 셀이 모두 `"Unavailable"` | 아이콘 탐지 셀렉터 불일치 또는 FEATURE 행 기능명 추출 실패 | debug HTML로 실제 data-testid 값 재검증 |
| 특정 트림 체크박스 미작동 | F SPORT 트림의 select_id에 `--` 이중 대시 포함 | `a300h-f-sport-design--select` 형태 그대로 사용 확인 |
| 오버레이가 닫히지 않음 | close 버튼 셀렉터 불일치 | Escape 키 fallback 동작 확인, `overlay-component--open` 셀렉터 재검증 |
| 배치 중 일부 트림 누락 | 배치 패딩 로직 오류 | 완료 후 `[WARN] Missing trims:` 로그 확인, `_make_batches()` 로직 검토 |

---

> **Note**: 이 크롤러는 Lexus 미국 공식 사이트의 공개 데이터를 수집합니다.
> 사이트의 이용 약관(Terms of Service)을 준수하고, 과도한 요청으로 서버에 부담을 주지 않도록 배치 간 적절한 딜레이를 유지하십시오.

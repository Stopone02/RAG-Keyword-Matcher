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
| 기호 표현 | 텍스트 (`●`, `○`, `—`) | **SVG 아이콘** (`data-testid="OptionalIcon"` 등) + 텍스트 수치 혼재 |

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

2. 페이지 내 COMPARE 버튼 클릭 (URL은 그대로)
   └─ #model_compare 섹션으로 스크롤

3. Compare Grid 노출 (한 화면에 3개 트림)
   └─ data-testid="CompareGrid" 컨테이너 내부에 데이터 렌더링
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
              ├── [data-testid="ControlsRow"]     ← 트림 선택 드롭다운 행
              ├── [data-testid="GridHeader"]      ← 현재 표시 중인 트림명 (3개)
              ├── [data-testid="DataRow"]         ← 수치 사양 행 (반복)
              │     └── 첫 번째 셀: 사양명
              │         나머지 셀: 각 트림의 값 (텍스트 수치)
              └── [data-testid="FeaturesRow"]     ← 기능 포함 여부 행 (반복)
                    └── 첫 번째 셀: 기능명
                        나머지 셀: 아이콘 또는 텍스트
```

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

렉서스 비교 페이지는 기호를 `data-testid` 아이콘으로 표현합니다.

| data-testid | 의미 | 정규화 값 |
|---|---|---|
| `OptionalIcon` | 옵션으로 추가 가능 | `"Optional"` |
| `NotAvailableIcon` | 해당 트림 미제공 | `"Unavailable"` |
| `NotAvailablePlaceholder` | 해당 트림 미제공 (자리 표시자) | `"Unavailable"` |
| `PackageIcon` | 패키지로 추가 가능 | `"Package"` |
| (텍스트 수치) | `"110 MPH"`, `"2.0L"` 등 | 원문 그대로 |
| (텍스트 없음 + 아이콘 없음) | 기본 포함 | `"Standard"` |

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

**→ 해결: 모델 페이지 진입 후 `#model_compare` 앵커로 스크롤**

```python
page.goto("https://www.lexus.com/models/UX-hybrid")
page.wait_for_selector("[data-testid='CompareGrid']")
# CompareGrid가 뷰포트에 들어올 때까지 스크롤
page.evaluate("document.getElementById('model_compare').scrollIntoView()")
```

### Challenge 3 — 트림 선택 방식 (ControlsRow)

각 열의 드롭다운으로 트림을 변경해야 하는데, `ControlsRow` 내부의 실제 상호작용 방식(select vs 커스텀 div)은 `--pause` 모드에서 추가 검증 필요.

**→ 해결: ID 기반 클릭 우선, 실패 시 커스텀 드롭다운 방식 전환**

```python
# 방법 A: ID 직접 클릭 (a300h-select 등이 클릭 가능 요소인 경우)
page.click("#a300h-awd-select")

# 방법 B: ControlsRow 내 select/option 조작
page.select_option("[data-testid='ControlsRow'] select:nth-child(1)", label="300h AWD")
```

### Challenge 4 — SVG 아이콘 기반 기호 처리

텍스트가 아닌 `data-testid` 아이콘으로 기호를 표현합니다.

**→ 해결: `data-testid` 탐지 우선, 텍스트 폴백**

```python
def extract_cell_value(cell):
    # 1. 아이콘 data-testid 확인
    for testid, value in icon_map.items():
        if cell.query_selector(f"[data-testid='{testid}']"):
            return value
    # 2. 텍스트 수치
    text = cell.inner_text().strip()
    if text:
        return text
    # 3. 빈 셀 = Standard (기본 포함)
    return "Standard"
```

### Challenge 5 — 카테고리 드로어 펼침

각 카테고리(ENGINE, DIMENSIONS 등)가 드로어로 접혀 있을 수 있습니다.

**→ 해결: 수집 전 모든 드로어 펼치기**

```python
for drawer_id in category_drawer_ids:
    btn = page.query_selector(f"#{drawer_id}-button")
    if btn and "collapsed" in (btn.get_attribute("class") or ""):
        btn.click()
        page.wait_for_load_state("networkidle")
```

---

## 🔄 수집 전략 상세: 배치 순회 흐름

```
[LexusSpecScraper.scrape_model("ux-hybrid")]
         │
         ├─ 1. 모델 페이지 접속 → CompareGrid 대기
         │
         ├─ 2. #model_compare 섹션으로 스크롤
         │
         ├─ 3. configs에서 all_trims (8개) 읽기 → 3개씩 배치 생성
         │     [A,B,C], [D,E,F], [G,H,A(패딩)]
         │
         ├─ 4. 배치 루프
         │     for batch in batches:
         │       ├─ 각 열에 트림 선택 (ControlsRow 조작)
         │       ├─ networkidle 대기
         │       ├─ 모든 카테고리 드로어 펼치기
         │       ├─ DataRow 파싱 → { 사양명: {트림: 값} }
         │       ├─ FeaturesRow 파싱 → { 기능명: {트림: 아이콘값} }
         │       └─ master_data에 upsert
         │
         └─ 5. storage/raw/lexus_ux-hybrid_raw.json 저장
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
            ├── 1. 브라우저 실행
            ├── 2. https://www.lexus.com/models/UX-hybrid 접속
            ├── 3. wait_for_selector("[data-testid='CompareGrid']")
            ├── 4. #model_compare 스크롤
            ├── 5. configs에서 8개 트림 → 3개씩 배치
            ├── 6. 배치별 루프
            │     ├─ ControlsRow 트림 선택
            │     ├─ 드로어 전체 펼치기
            │     ├─ DataRow / FeaturesRow 파싱
            │     │     ├─ GridHeader → 현재 3개 트림명
            │     │     ├─ 첫 번째 셀 = 사양/기능명
            │     │     └─ 나머지 셀 = 아이콘 testid 또는 텍스트 수치
            │     └─ master_data upsert
            └── 7. JSON 저장
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
| **배치 커버리지 보장** | 8개 트림이 모두 최소 1번 포함되도록 배치 구성 |
| **트림 선택 후 대기** | ControlsRow 조작 후 `networkidle` 대기 필수 |
| **드로어 전체 펼침** | DataRow/FeaturesRow 수집 전 11개 드로어 모두 펼치기 |
| **아이콘 우선 탐지** | `data-testid` 아이콘 확인 → 텍스트 → "Standard" 순 |
| **upsert 병합** | 이미 수집된 트림/기능은 덮어쓰지 않음 |
| **패딩 트림 중복 방지** | 마지막 배치 패딩 트림의 데이터는 병합 시 무시 |
| **요청 간 딜레이** | 배치 간 2~3초 딜레이 |
| **로깅** | 배치 번호, 트림 조합, 수집 행 수, 소요 시간 출력 |

---

## 🔧 트러블슈팅

| 증상 | 원인 | 해결 방법 |
|---|---|---|
| `CompareGrid` 셀렉터 타임아웃 | 페이지 로딩 중 Compare 섹션이 뷰포트 밖에 있음 | `scrollIntoView()` 후 셀렉터 대기 |
| 트림 선택 후 데이터 미변경 | `select_id` 방식이 커스텀 드롭다운과 맞지 않음 | `ControlsRow` 내 실제 인터랙션 방식 추가 검증 필요 |
| DataRow가 0개 | 드로어가 접혀 있어 행이 렌더링 안 됨 | 드로어 펼치기 로직 확인 |
| 값 셀이 모두 `"Standard"` | 아이콘 탐지 로직이 잘못된 셀렉터 사용 | `icon_map`의 testid 값 재검증 |
| 특정 트림 select_id 미작동 | F SPORT 트림의 ID에 `--` 이중 대시 포함 | `#a300h-f-sport-design--select` 형태 그대로 사용 |
| 배치 중 일부 트림 누락 | 배치 패딩 로직 오류 | `set(all_trim_labels) == set(master_data.keys())` 검증 |

---

> **Note**: 이 크롤러는 Lexus 미국 공식 사이트의 공개 데이터를 수집합니다.
> 사이트의 이용 약관(Terms of Service)을 준수하고, 과도한 요청으로 서버에 부담을 주지 않도록 배치 간 적절한 딜레이를 유지하십시오.

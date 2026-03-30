# 🏎️ CarSpec Crawler
**자동차 브랜드 사양 비교 페이지 자동 수집 엔진 (Playwright 기반)**

> 자동차 브랜드의 트림별 사양 비교(Specs & Features Comparison) 페이지에서
> 정량적 수치 및 정성적 옵션 상태(기호)를 데이터 혼선 없이 수집하여
> RAG 지식 베이스용 표준 JSON으로 변환하는 크롤러 프로토타입입니다.
> **현재 지원 브랜드: KIA (미국 공식 사이트)**

---

## 📌 목차

1. [프로젝트 개요](#-프로젝트-개요)
2. [수집 대상 페이지 구조](#-수집-대상-페이지-구조)
3. [핵심 과제 및 해결 전략](#-핵심-과제-및-해결-전략)
4. [기술 스택](#-기술-스택)
5. [디렉토리 구조](#-디렉토리-구조)
6. [시스템 아키텍처](#-시스템-아키텍처)
7. [설정 파일 명세 (Brand Config)](#-설정-파일-명세-brand-config)
8. [출력 데이터 형식](#-출력-데이터-형식)
9. [설치 및 실행 방법](#-설치-및-실행-방법)
10. [다른 브랜드로 확장하는 방법](#-다른-브랜드로-확장하는-방법)
11. [구현 시 준수 사항](#-구현-시-준수-사항)
12. [트러블슈팅](#-트러블슈팅)
13. [향후 계획](#-향후-계획)

---

## 🎯 프로젝트 개요

자동차 제조사 공식 홈페이지의 **트림별 사양 비교 페이지**는 아래와 같은 특성을 가집니다.

- 하나의 모델에 대해 **여러 트림(LX, S, GT-Line, EX 등)** 이 가로축에 나열됨
- 각 트림의 **가격(Starting MSRP)** 이 헤더에 포함됨
- 사양 항목(Feature)이 세로축에 나열되고, 각 셀에 **기호(●, ○, —)** 또는 **텍스트 값**이 표시됨
- 페이지가 **동적으로 렌더링(JavaScript)** 되므로 단순 HTTP 요청으로는 수집 불가

이 엔진은 Playwright를 활용하여 브라우저를 직접 제어하고, 위 구조를 정확하게 파싱하여 브랜드·모델·트림별로 정리된 JSON 파일을 생성합니다.

---

## 🖥️ 수집 대상 페이지 구조

**KIA Soul (2025) — Features & Specs Comparison 페이지 예시**

```
URL: https://www.kia.com/us/en/soul/specs-compare
```

| 구성 요소 | 설명 |
|---|---|
| 헤더 행 | 트림명 (LX, S, GT-Line, EX) + Starting MSRP 가격 |
| 기능 행 | 각 사양 항목명 (예: Blind-Spot Collision Avoidance Assist) |
| 값 셀 | `●` (기본 제공), `○` (옵션), `—` (미제공) 또는 텍스트 값 |
| 툴팁 아이콘 | 기능명 옆에 붙는 `ⓘ` 등 불필요 문자 → 제거 처리 대상 |

### 기호(Symbol) 의미 정의

| 기호 | 의미 | 정규화 값 |
|---|---|---|
| `●` | 해당 트림에 기본 포함 | `"Standard"` |
| `○` | 옵션 패키지로 추가 가능 | `"Optional"` |
| `—` | 해당 트림에서 제공 안 됨 | `"Unavailable"` |
| 텍스트 | 수치 또는 설명 (예: `"Nappa Leather"`) | 원문 그대로 보존 |

---

## 🧩 핵심 과제 및 해결 전략

### Challenge 1 — 열(Column) 정렬 문제
가로로 나열된 여러 트림의 데이터가 한 행(Row)에 혼재되어, 특정 트림의 데이터만 정확히 추출하기 어렵습니다.

**→ 해결: Column Index Mapping 전략**
1. 페이지 상단 헤더에서 트림 목록을 스캔하여 `{ 트림명: 열 인덱스 }` 딕셔너리 생성
2. 각 데이터 행의 값 셀을 순회할 때 **셀의 위치 인덱스 = 트림 인덱스** 로 정확히 매핑

### Challenge 2 — 기호가 텍스트가 아닌 SVG/이미지인 경우
일부 사이트에서는 `●`를 텍스트가 아닌 SVG 아이콘이나 CSS 클래스로 표현합니다.

**→ 해결: 다단계 심볼 탐지 로직**
1. 셀의 `innerText` 우선 추출
2. 텍스트가 비어있으면 자식 요소의 `class` 또는 `data-icon` 속성 확인
3. 이마저도 없으면 `aria-label` 속성으로 폴백

### Challenge 3 — 동적 렌더링 및 지연 로딩
SPA(Single Page Application) 구조로 스크롤 또는 탭 전환 시 데이터가 지연 로딩될 수 있습니다.

**→ 해결: `wait_until="networkidle"` + 명시적 요소 대기**
네트워크 요청이 완전히 안정된 후 스크래핑을 시작하며, 핵심 셀렉터에 대한 `wait_for_selector()` 를 병행합니다.

---

## 🛠️ 기술 스택

| 분류 | 사용 기술 |
|---|---|
| 브라우저 자동화 | [Playwright for Python](https://playwright.dev/python/) (sync API) |
| 언어 | Python 3.10+ |
| 데이터 저장 | JSON (로컬 파일) |
| 설정 관리 | JSON Config 파일 (브랜드별 분리) |
| 패키지 관리 | pip / requirements.txt |

---

## 📂 디렉토리 구조

```
CarSpec-Crawler/
│
├── main.py                     # 실행 진입점 (브랜드·모델 지정 후 배치 실행)
│
├── engine/
│   └── scraper.py              # Column Index 기반 메인 스크래핑 엔진
│
├── configs/                    # 브랜드별 셀렉터 및 기호 매핑 설정
│   └── kia.json                # KIA 미국 사이트 설정
│
├── utils/
│   ├── formatter.py            # 기호 변환(● → Standard) 및 텍스트 정제
│   └── alias_mapper.py         # 기능명 표준화 (예: "Horsepower" → "max_power_hp")
│
├── storage/
│   └── raw/                    # 수집 결과 저장 ({brand}_{model}_raw.json)
│
├── requirements.txt
└── ReadMe.md
```

---

## 🏗️ 시스템 아키텍처

### 전체 처리 흐름

```
[main.py]
    │
    ├── config 로드 (configs/kia.json)
    │
    └── [engine/scraper.py] KiaSpecScraper
            │
            ├── 1. 브라우저 실행 (Playwright Chromium, headless)
            ├── 2. 타겟 URL 접속 + networkidle 대기
            ├── 3. Trim Indexing
            │       └── trim_header 셀렉터로 헤더 스캔
            │           → { "LX": 0, "S": 1, "GT-Line": 2, "EX": 3 }
            ├── 4. Row Scanning
            │       └── spec_row 셀렉터로 전체 행 순회
            │           ├── feature_name 셀렉터로 기능명 추출
            │           └── value_cells 셀렉터로 값 셀 목록 추출
            ├── 5. Cell Matching
            │       └── 셀 인덱스 → 트림 인덱스 매핑하여 딕셔너리 삽입
            ├── 6. [utils/formatter.py] 기호 변환 및 텍스트 정제
            └── 7. [storage/raw/] JSON 파일로 저장
```

### 모듈별 책임

| 모듈 | 책임 |
|---|---|
| `main.py` | 실행 인자 파싱, 설정 로드, 크롤러 호출, 저장 경로 지정 |
| `engine/scraper.py` | Playwright 브라우저 제어, DOM 파싱, Column Index 매핑 |
| `utils/formatter.py` | 기호→텍스트 변환, 불필요 문자 제거, 공백 정리 |
| `utils/alias_mapper.py` | 브랜드별로 다른 기능명을 표준 키로 통일 |
| `configs/*.json` | 브랜드/사이트별 CSS 셀렉터 및 기호 정의 |

---

## ⚙️ 설정 파일 명세 (Brand Config)

각 브랜드의 사이트 구조를 `configs/{brand}.json` 파일로 정의합니다.

### KIA 예시 (`configs/kia.json`)

```json
{
  "brand": "KIA",
  "models": {
    "soul": {
      "url": "https://www.kia.com/us/en/soul/specs-compare",
      "selectors": {
        "trim_header": ".spec-compare__trim-name",
        "trim_price": ".spec-compare__trim-price",
        "spec_row": ".spec-compare__row",
        "feature_name": ".spec-compare__feature-name",
        "value_cells": ".spec-compare__feature-value"
      }
    },
    "telluride": {
      "url": "https://www.kia.com/us/en/telluride/specs-compare",
      "selectors": {
        "trim_header": ".spec-compare__trim-name",
        "trim_price": ".spec-compare__trim-price",
        "spec_row": ".spec-compare__row",
        "feature_name": ".spec-compare__feature-name",
        "value_cells": ".spec-compare__feature-value"
      }
    }
  },
  "symbol_map": {
    "●": "Standard",
    "○": "Optional",
    "—": "Unavailable",
    "–": "Unavailable"
  },
  "wait_strategy": {
    "wait_until": "networkidle",
    "wait_for_selector": ".spec-compare__row"
  }
}
```

### 설정 필드 설명

| 필드 | 타입 | 설명 |
|---|---|---|
| `brand` | string | 브랜드 식별자 |
| `models.{model}.url` | string | 수집 대상 페이지 URL |
| `selectors.trim_header` | string | 트림명이 포함된 헤더 셀 CSS 셀렉터 |
| `selectors.trim_price` | string | 트림 가격 셀 CSS 셀렉터 |
| `selectors.spec_row` | string | 사양 데이터 행 CSS 셀렉터 |
| `selectors.feature_name` | string | 각 행의 기능명 셀 CSS 셀렉터 |
| `selectors.value_cells` | string | 각 행의 값 셀 CSS 셀렉터 |
| `symbol_map` | object | 기호 → 정규화 텍스트 매핑 |
| `wait_strategy` | object | 페이지 로딩 대기 전략 |

---

## 📊 출력 데이터 형식

수집 결과는 `storage/raw/{brand}_{model}_raw.json` 경로에 저장됩니다.

### 출력 JSON 구조

```json
{
  "brand": "KIA",
  "model": "Soul",
  "year": 2025,
  "crawled_at": "2025-07-15T09:30:00Z",
  "source_url": "https://www.kia.com/us/en/soul/specs-compare",
  "trims": {
    "LX": {
      "price_msrp": "$20,490",
      "features": {
        "Blind-Spot Collision-Avoidance Assist": "Optional",
        "Forward Collision-Avoidance Assist w/ Pedestrian & Cyclist Detection": "Standard",
        "Rear Cross-Traffic Collision-Avoidance Assist": "Standard",
        "Lane Departure Warning": "Standard",
        "Lane Keeping Assist": "Standard",
        "Lane Following Assist": "Standard",
        "Lane Change Assist": "Optional",
        "Navigation-Based Smart Cruise Control w/ Stop & Go Curve": "Unavailable",
        "Highway Driving Assist": "Unavailable",
        "Intelligent Speed Limit Assist": "Standard",
        "Driver Attention Warning": "Standard"
      }
    },
    "S": {
      "price_msrp": "$22,690",
      "features": {
        "Blind-Spot Collision-Avoidance Assist": "Standard",
        "Forward Collision-Avoidance Assist w/ Pedestrian & Cyclist Detection": "Standard",
        "..."  : "..."
      }
    },
    "GT-Line": { "..." : "..." },
    "EX": { "..." : "..." }
  }
}
```

---

## 🚀 설치 및 실행 방법

### 1. 사전 요구사항

- Python 3.10 이상
- pip

### 2. 의존성 설치

```bash
# 패키지 설치
pip install -r requirements.txt

# Playwright 브라우저 바이너리 설치 (최초 1회)
playwright install chromium
```

`requirements.txt` 예시:
```
playwright>=1.40.0
```

### 3. 실행

```bash
# KIA Soul 사양 수집
python main.py --brand kia --model soul

# KIA 전체 모델 수집 (configs/kia.json 에 정의된 모든 모델)
python main.py --brand kia --all

# 헤드리스 모드 비활성화 (브라우저 화면 표시, 디버깅용)
python main.py --brand kia --model soul --no-headless
```

### 4. 결과 확인

```bash
# 수집 결과 파일 확인
cat storage/raw/kia_soul_raw.json
```

---

## 🔌 다른 브랜드로 확장하는 방법

새로운 브랜드(예: Hyundai, Toyota)를 추가하려면 설정 파일 하나만 추가하면 됩니다.

1. **사이트 분석**: 브라우저 개발자 도구(F12)로 트림 헤더, 사양 행, 값 셀의 CSS 셀렉터 확인
2. **설정 파일 생성**: `configs/hyundai.json` 파일을 `configs/kia.json` 형식에 맞춰 작성
3. **기호 정의**: 해당 브랜드 사이트에서 사용하는 기호를 `symbol_map`에 정의
4. **실행**: `python main.py --brand hyundai --model tucson`

> **주의**: 셀렉터는 사이트 업데이트 시 변경될 수 있으므로 주기적으로 검증이 필요합니다.

---

## 📋 구현 시 준수 사항

코드를 작성할 때 반드시 아래 규칙을 따릅니다.

| 항목 | 내용 |
|---|---|
| **열 개수 불일치 처리** | `value_cells` 개수가 `trim_header` 개수와 다를 경우 해당 행을 스킵하고 경고 로그 출력 |
| **동적 로딩 대기** | `wait_until="networkidle"` + `wait_for_selector(spec_row)` 병행 사용 |
| **출력 자료구조** | `{ "Trim_Name": { "Feature_Name": "Value" } }` 형태의 중첩 딕셔너리 |
| **SVG 기호 대응** | 텍스트 없을 시 `class`, `data-icon`, `aria-label` 순서로 폴백 |
| **텍스트 정제** | 툴팁 아이콘(`ⓘ`), 각주 기호(`*`, `†`) 등 불필요 문자 제거 |
| **정성 데이터 보존** | 숫자가 아닌 텍스트 값(예: `"Nappa Leather"`)은 `strip()` 후 원문 유지 |
| **로깅** | 수집 진행 상황(모델명, 트림 수, 사양 행 수, 소요 시간)을 콘솔에 출력 |
| **예외 처리** | 셀렉터를 찾지 못할 경우 `TimeoutError`를 캐치하고 해당 모델 스킵 후 계속 진행 |

---

## 🔧 트러블슈팅

| 증상 | 원인 | 해결 방법 |
|---|---|---|
| 데이터 셀이 비어 있음 | 페이지 로딩 전에 스크래핑 시작 | `wait_for_selector()` 타임아웃 값 증가 |
| 트림명은 수집되나 값이 모두 `""` | 기호가 SVG로 렌더링됨 | SVG 폴백 로직 확인 (class/aria-label) |
| 특정 행의 값 개수가 트림 수와 불일치 | colspan 또는 카테고리 구분 행 | feature_name이 없는 행 필터링 로직 추가 |
| `TimeoutError` 발생 | 사이트 응답 지연 또는 셀렉터 변경 | 셀렉터 재검증, 타임아웃 값(기본 30초) 조정 |
| 가격 정보 누락 | 트림 헤더와 가격 셀이 별도 요소 | `trim_price` 셀렉터 별도 추가 확인 |

---

## 🗺️ 향후 계획

- [ ] **다중 브랜드 지원**: Hyundai, Toyota, Honda 설정 파일 추가
- [ ] **다중 모델 병렬 수집**: `asyncio` 기반 비동기 크롤러로 전환
- [ ] **변경 감지**: 이전 수집 결과와 비교하여 변경된 사양만 업데이트
- [ ] **RAG 파이프라인 연동**: 수집된 JSON을 벡터 DB(Chroma, Pinecone 등)에 자동 임베딩
- [ ] **스케줄링**: GitHub Actions를 활용한 주기적 자동 수집
- [ ] **대시보드**: 수집 현황 및 트림별 사양 비교 시각화

---

> **Note**: 이 크롤러는 KIA 미국 공식 사이트의 공개 데이터를 수집합니다.
> 사이트의 이용 약관(Terms of Service)을 준수하고, 과도한 요청으로 서버에 부담을 주지 않도록 요청 간 적절한 딜레이를 유지하십시오.

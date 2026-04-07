"""
Mercedes-Benz specs scraper (mbusa.com compare-vehicles pages).

페이지 구조:
  - JS SPA: Playwright가 렌더링 완료 후 DOM에 모든 데이터 존재
  - Sticky nav의 .compare-header-result 순서 = 비교표 컬럼 순서

  [Feature Highlights 섹션]
    section > h2.compare-body__header ("Feature Highlights")
    section > div.compare-body__container × N트림
      └── div.compare-feature-highlight × K피처
            ├── div.compare-feature-highlight__title  → 피처명
            └── div.compare-feature-highlight__description
                  └── span.compare-feature-highlight__value (복수 가능) + span.compare-feature-highlight__unit

  [Specifications 섹션]
    section > h2.compare-body__header ("Specifications")
    section > div[data-accordion]
      └── div.accordion__item × M카테고리
            ├── button[data-accordion-button] → 카테고리명
            └── div.accordion__pane
                  └── div.compare-body__group-container × S행
                        └── div.compare-body__container × N트림
                              └── div.compare-model-spec__item
                                    ├── div.compare-model-spec__title       → 스펙명
                                    └── div.compare-model-spec__description → 값

트림명:  .compare-header-result__model-link  (sticky nav, 순서 = 컬럼 순서)
가격:    .compare-header-result__starting-value

렌더링 완료 신호: .compare-model-spec__item (이 요소가 등장하면 모든 데이터 로딩 완료)
Accordion 클릭: 불필요 — 페이지 로드 후 aria-expanded="true" 상태

다중 URL 모델:
  model_config["urls"] 배열을 순서대로 수집 후 트림 단위로 병합.
"""

import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class BenzSpecScraper:

    def __init__(self, config: dict, headless: bool = True):
        self.config = config
        self.headless = headless
        self.brand = config["brand"]
        self.wait_strategy = config.get("wait_strategy", {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_model(self, model: str) -> dict | None:
        model_config = self.config["models"].get(model)
        if not model_config:
            print(f"[WARN] Model config not found: {model}")
            return None

        urls = model_config.get("urls") or [model_config["url"]]

        all_trims: dict = {}
        source_urls: list = []

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-http2"],
            )
            page = browser.new_page(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )

            for url in urls:
                print(f"\n[INFO] Navigating → {url}")
                batch = self._scrape_single_url(page, url)
                if batch is None:
                    print(f"[WARN] Skipping {url}")
                    continue

                source_urls.append(url)
                for trim_name, trim_data in batch.items():
                    if trim_name not in all_trims:
                        all_trims[trim_name] = trim_data
                        print(f"[INFO] Added trim: {trim_name}")
                    else:
                        # 같은 트림이 여러 URL에 있는 경우 빈 값 보완
                        existing = all_trims[trim_name]
                        if not existing["price_msrp"] and trim_data["price_msrp"]:
                            existing["price_msrp"] = trim_data["price_msrp"]
                        for feat, entry in trim_data["features"].items():
                            existing["features"].setdefault(feat, entry)

            browser.close()

        if not all_trims:
            return None

        print(f"\n[INFO] Total trims collected: {list(all_trims.keys())}")
        return {
            "brand": self.brand,
            "model": model.replace("-", " ").title(),
            "year": datetime.now().year,
            "crawled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_url": source_urls[0] if len(source_urls) == 1 else source_urls,
            "trims": all_trims,
        }

    # ------------------------------------------------------------------
    # Single URL
    # ------------------------------------------------------------------

    def _scrape_single_url(self, page, url: str) -> dict | None:
        try:
            wait_until = self.wait_strategy.get("wait_until", "domcontentloaded")
            page.goto(url, wait_until=wait_until, timeout=60000)
        except PlaywrightTimeoutError:
            print(f"[ERROR] Timeout loading {url}")
            return None

        self._dismiss_cookie_banner(page)

        # JS가 스펙 데이터를 DOM에 삽입할 때까지 대기
        wait_sel = self.wait_strategy.get("wait_for_selector", ".compare-model-spec__item")
        if wait_sel:
            try:
                page.wait_for_selector(wait_sel, timeout=45000, state="attached")
                print(f"[INFO] Page ready: '{wait_sel}' found")
            except PlaywrightTimeoutError:
                print(f"[WARN] '{wait_sel}' timed out — saving debug snapshot")
                page.screenshot(path="debug_compare.png", full_page=False)
                with open("debug_compare.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                return None

        # 추가 안정화 대기 (lazy-load 이미지 등이 레이아웃에 영향 주는 경우 방지)
        time.sleep(1.0)

        # 트림명 + 가격은 라이브 DOM에서 추출 (sticky nav 기준)
        trim_names = self._get_trim_names(page)
        if not trim_names:
            print(f"[ERROR] Could not read trim names from {url}")
            return None
        print(f"[INFO] Trims ({len(trim_names)}): {trim_names}")

        prices = self._get_prices(page)
        print(f"[INFO] Prices: {prices}")

        # HTML 스냅샷으로 파싱 (JS 재렌더링 영향 차단)
        html = page.content()
        print(f"[INFO] Snapshot captured: {len(html):,} chars")

        return self._parse_snapshot(page, trim_names, prices, html)

    # ------------------------------------------------------------------
    # Live DOM: 트림명 / 가격
    # ------------------------------------------------------------------

    def _get_trim_names(self, page) -> list[str]:
        try:
            return page.evaluate("""
                () => {
                    const clean = t => t.replace(/\\s+/g, ' ').trim();
                    return [...document.querySelectorAll('.compare-header-result__model-link')]
                        .map(el => clean(el.textContent))
                        .filter(Boolean);
                }
            """)
        except Exception as e:
            print(f"[WARN] _get_trim_names error: {e}")
            return []

    def _get_prices(self, page) -> list[str]:
        try:
            return page.evaluate("""
                () => {
                    const clean = t => t.replace(/\\s+/g, ' ').trim();
                    return [...document.querySelectorAll('.compare-header-result__starting-value')]
                        .map(el => clean(el.textContent))
                        .filter(Boolean);
                }
            """)
        except Exception as e:
            print(f"[WARN] _get_prices error: {e}")
            return []

    # ------------------------------------------------------------------
    # Parse snapshot (JS DOMParser)
    # ------------------------------------------------------------------

    def _parse_snapshot(
        self,
        page,
        trim_names: list[str],
        prices: list[str],
        html: str,
    ) -> dict:
        """
        HTML 스냅샷을 JS DOMParser로 파싱.
        React 재렌더링과 무관하게 수집.

        처리 순서:
          1. Feature Highlights 섹션
          2. Specifications 섹션 (accordion 카테고리별)
        """
        n_trims = len(trim_names)
        result = {name: {"price_msrp": "", "features": {}} for name in trim_names}

        # 가격 주입
        for idx, price in enumerate(prices):
            if idx < n_trims:
                result[trim_names[idx]]["price_msrp"] = price

        rows_data: list[dict] = page.evaluate(
            """
            (args) => {
                const html   = args.html;
                const nTrims = args.nTrims;

                const doc = new DOMParser().parseFromString(html, 'text/html');

                // ── 텍스트 정제 유틸 ────────────────────────────────────
                const cleanText = el => {
                    const clone = el.cloneNode(true);
                    // disclaimer marker(*, **, †, ‡ 등) 제거
                    clone.querySelectorAll('.disclaimer__marker').forEach(n => n.remove());
                    return clone.textContent.replace(/\\s+/g, ' ').trim();
                };

                const results = [];

                // ── 1. Feature Highlights 섹션 ──────────────────────────
                const headers = [...doc.querySelectorAll('h2.compare-body__header')];
                const fhHeader = headers.find(h => h.textContent.trim() === 'Feature Highlights');
                if (fhHeader) {
                    // h2의 부모 section 안의 compare-body__container = 트림별 컬럼
                    const section = fhHeader.closest('section') || fhHeader.parentElement;
                    const columns = [...section.querySelectorAll(':scope > .compare-body__container')];

                    // 피처명 목록 결정: 첫 번째 컬럼의 title 목록
                    if (columns.length > 0) {
                        const featureTitles = [...columns[0].querySelectorAll('.compare-feature-highlight__title')]
                            .map(el => el.textContent.trim());

                        featureTitles.forEach((featureName, rowIdx) => {
                            const values = columns.map(col => {
                                const highlights = col.querySelectorAll('.compare-feature-highlight');
                                const highlight = highlights[rowIdx];
                                if (!highlight) return '';
                                return cleanText(highlight.querySelector('.compare-feature-highlight__description') || highlight);
                            });
                            // 모든 값이 비어있으면 스킵
                            if (values.every(v => !v)) return;
                            results.push({
                                section: 'Feature Highlights',
                                category: 'Feature Highlights',
                                feature: featureName,
                                values: values,
                            });
                        });
                    }
                }

                // ── 2. Specifications 섹션 ──────────────────────────────
                const specHeader = headers.find(h => h.textContent.trim() === 'Specifications');
                if (specHeader) {
                    const section = specHeader.closest('section') || specHeader.parentElement;
                    const accordion = section.querySelector('[data-accordion]');
                    if (!accordion) return results;

                    for (const item of accordion.querySelectorAll('.accordion__item')) {
                        // 카테고리명
                        const catBtn = item.querySelector('button[data-accordion-button="true"]');
                        const category = catBtn ? catBtn.textContent.trim() : '';

                        // 스펙 행 순회
                        for (const row of item.querySelectorAll('.compare-body__group-container')) {
                            // placeholder 포함 모든 자식을 위치 그대로 순회해야
                            // 트림 컬럼 인덱스가 정확히 매핑됨
                            const children = [...row.children];

                            let featureName = null;
                            const values = [];

                            for (let i = 0; i < nTrims; i++) {
                                const child = children[i];
                                if (!child || child.classList.contains('compare-body__placeholder')) {
                                    values.push('');
                                    continue;
                                }
                                const specItem = child.querySelector('.compare-model-spec__item');
                                if (!specItem) { values.push(''); continue; }
                                if (!featureName) {
                                    featureName = specItem.querySelector('.compare-model-spec__title')?.textContent.trim() || null;
                                }
                                const descEl = specItem.querySelector('.compare-model-spec__description');
                                values.push(descEl ? cleanText(descEl) : '');
                            }

                            if (!featureName) continue;

                            if (values.every(v => !v)) continue;
                            results.push({
                                section: 'Specifications',
                                category: category,
                                feature: featureName,
                                values: values,
                            });
                        }
                    }
                }

                return results;
            }
            """,
            {"html": html, "nTrims": n_trims},
        )

        print(f"[DEBUG] JS extracted {len(rows_data)} rows")

        for row in rows_data:
            feature_name = row["feature"]
            category = row["category"]
            values = row["values"]

            for idx, val in enumerate(values):
                if idx < n_trims:
                    result[trim_names[idx]]["features"].setdefault(
                        feature_name,
                        {"value": val, "category": category},
                    )

        return result

    # ------------------------------------------------------------------
    # Cookie banner
    # ------------------------------------------------------------------

    def _dismiss_cookie_banner(self, page) -> None:
        for sel in [
            "button:has-text('Accept All')",
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
            "button:has-text('OK')",
        ]:
            try:
                btn = page.wait_for_selector(sel, timeout=3000)
                if btn:
                    btn.click()
                    page.wait_for_load_state("networkidle", timeout=10000)
                    print("[INFO] Cookie banner dismissed")
                    return
            except Exception:
                continue

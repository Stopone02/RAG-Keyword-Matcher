"""
Nissan specs-trims scraper.

페이지 구조:
  - Accordion 섹션(szh-accordion__item): Key Features / Pricing / Fuel Economy / ...
  - 섹션별 sticky 헤더: <p class="font-bold text-sm uppercase">카테고리명</p>
  - Key Features 행: keyfeature-carousel, id="key-features-{row}-{col}"
    → 각 셀에 트림별 피처 텍스트 (행 라벨 없음, 행 인덱스로 구분)
  - Spec 행:
      · 피처명: id="feature-row-{Name}" 을 가진 div 또는 p 요소
        - <div id="feature-row-X"> 안에 button.nissanbold 또는 p.nissanbold
        - <p id="feature-row-X" class="nissanbold"> 처럼 el 자체가 피처명
      · 값: .accordion-carousel > div > p

트림명: p.nissanbold[class*="h-full"] (sticky 트림 헤더)

파싱 전략:
  - wait_for_selector 직후, accordion 클릭 전에 page.content() 로 SSR HTML 스냅샷
  - JS DOMParser 로 스냅샷을 파싱 → React 재렌더링 완전 우회
  - accordion 클릭으로 인해 63개 이상의 피처가 사라지는 문제 해결

다중 URL 모델(예: Frontier):
  model_config["urls"] 배열을 순서대로 스크랩 후 트림 단위로 병합.
"""

from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class NissanSpecScraper:

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
                        for feat, entry in trim_data["features"].items():
                            all_trims[trim_name]["features"].setdefault(feat, entry)

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

        wait_sel = self.wait_strategy.get("wait_for_selector", ".featured-compare")
        if wait_sel:
            try:
                page.wait_for_selector(wait_sel, timeout=30000)
                print(f"[INFO] Page ready: '{wait_sel}' found")
            except PlaywrightTimeoutError:
                print(f"[WARN] '{wait_sel}' timed out — saving debug snapshot")
                page.screenshot(path="debug_compare.png", full_page=False)
                with open("debug_compare.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                return None

        # ── SSR HTML 스냅샷: accordion 클릭 전에 캡처 ────────────────────
        # React가 accordion을 재렌더링하면 피처 요소가 63개 이상 사라지므로
        # 클릭 전 SSR HTML 을 기준으로 파싱한다.
        html_snapshot = page.content()
        print(f"[INFO] HTML snapshot captured ({len(html_snapshot):,} chars)")

        # 트림명은 sticky 헤더에 항상 존재 → 라이브 DOM에서 추출
        trim_names = self._get_trim_names(page)
        if not trim_names:
            print(f"[ERROR] Could not read trim names from {url}")
            return None
        print(f"[INFO] Trims ({len(trim_names)}): {trim_names}")

        return self._parse_all_rows(page, trim_names, html_snapshot)

    # ------------------------------------------------------------------
    # Trim names (라이브 DOM)
    # ------------------------------------------------------------------

    def _get_trim_names(self, page) -> list[str]:
        try:
            names = page.evaluate("""
                () => {
                    const clean = t => t.replace(/\\s+/g, ' ').trim();
                    const els = document.querySelectorAll(
                        'p.nissanbold.h-full, p[class*="nissanbold"][class*="h-full"]'
                    );
                    const names = [];
                    for (const el of els) {
                        const t = clean(el.textContent);
                        if (t) names.push(t);
                    }
                    return names;
                }
            """)
            return names or []
        except Exception as e:
            print(f"[WARN] _get_trim_names error: {e}")
            return []

    # ------------------------------------------------------------------
    # Parse all rows (SSR HTML 스냅샷 기반)
    # ------------------------------------------------------------------

    def _parse_all_rows(self, page, trim_names: list, html: str) -> dict:
        """
        SSR HTML 스냅샷을 JS DOMParser 로 파싱.
        React 재렌더링과 무관하게 서버가 내려준 전체 피처를 수집한다.

        처리 대상:
          1. 카테고리 헤더: p.font-bold.text-sm.uppercase
          2. Key Features 행: .keyfeature-carousel
          3. Spec 행: [id^="feature-row-"] (div 또는 p)
        """
        n_trims = len(trim_names)
        result = {name: {"price_msrp": "", "features": {}} for name in trim_names}

        rows_data = page.evaluate("""
            (args) => {
                const html    = args.html;
                const nTrims  = args.nTrims;

                // ── SSR 스냅샷을 독립 Document 로 파싱 ──────────────────
                const doc = new DOMParser().parseFromString(html, 'text/html');

                const cleanText = t => t
                    .replace(/[\\u00ae\\u2122\\u2020\\u2021\\u2019]/g, '')
                    .replace(/\\s+/g, ' ')
                    .trim();

                const getTextNoSup = el => {
                    const clone = el.cloneNode(true);
                    clone.querySelectorAll('sup').forEach(s => s.remove());
                    return cleanText(clone.textContent);
                };

                const results = [];
                let currentCategory = '';
                let keyFeatureRowIdx = 0;

                // 카테고리 헤더, 스펙 행(id^=feature-row-), Key Features 행
                const allEls = doc.querySelectorAll([
                    'p.font-bold.text-sm.uppercase',
                    '[id^="feature-row-"]',
                    '.keyfeature-carousel',
                ].join(','));

                for (const el of allEls) {
                    const cls = el.className || '';

                    // ── 카테고리 헤더 ──────────────────────────────────────
                    if (el.tagName === 'P' && cls.includes('uppercase')) {
                        currentCategory = cleanText(el.textContent);
                        keyFeatureRowIdx = 0;
                        continue;
                    }

                    // ── Key Features 행 ────────────────────────────────────
                    if (cls.includes('keyfeature-carousel')) {
                        const values = [];
                        for (let col = 0; col < nTrims; col++) {
                            const cell = el.querySelector(
                                `[id="key-features-${keyFeatureRowIdx}-${col}"]`
                            );
                            if (cell) {
                                const inner = cell.querySelector('div') || cell;
                                values.push(cleanText(inner.textContent));
                            } else {
                                values.push('');
                            }
                        }
                        if (values.every(v => !v)) continue;
                        results.push({
                            type: 'key_feature',
                            feature: `Key Feature ${keyFeatureRowIdx + 1}`,
                            category: currentCategory || 'Key Features',
                            values,
                        });
                        keyFeatureRowIdx++;
                        continue;
                    }

                    // ── Spec 행 ────────────────────────────────────────────
                    if (el.id && el.id.startsWith('feature-row-')) {
                        // 피처명:
                        //   <div id="feature-row-X"> → 자식에서 .nissanbold 탐색
                        //   <p   id="feature-row-X" class="nissanbold"> → el 자체가 피처명
                        let nameEl = el.querySelector('button.nissanbold, p.nissanbold');
                        if (!nameEl && el.classList.contains('nissanbold')) {
                            nameEl = el;
                        }
                        if (!nameEl) continue;

                        const featureName = getTextNoSup(nameEl);
                        if (!featureName) continue;

                        // accordion-carousel 탐색: 최대 3단계 위 부모까지
                        let carousel = null;
                        let node = el.parentElement;
                        for (let i = 0; i < 3 && node && !carousel; i++) {
                            carousel = node.querySelector('.accordion-carousel');
                            if (!carousel) node = node.parentElement;
                        }
                        if (!carousel) continue;

                        const cells = [...carousel.querySelectorAll(':scope > div')];
                        const values = cells.slice(0, nTrims).map(cell => {
                            const p = cell.querySelector('p');
                            return p ? getTextNoSup(p) : cleanText(cell.textContent);
                        });
                        while (values.length < nTrims) values.push('');

                        results.push({
                            type: 'spec',
                            feature: featureName,
                            category: currentCategory,
                            values,
                        });
                    }
                }

                return results;
            }
        """, {"html": html, "nTrims": n_trims})

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

        # "Starting From" → price_msrp 에도 저장 (features 에는 유지)
        for trim_name in result:
            sf = result[trim_name]["features"].get("Starting From")
            if sf and sf.get("value"):
                result[trim_name]["price_msrp"] = sf["value"]

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
                    print(f"[INFO] Cookie banner dismissed")
                    return
            except Exception:
                continue

"""
Mazda Compare-Specs scraper.

페이지 구조:
  - 상단 CarCard 캐러셀: N개 트림 카드(이름+가격)가 항상 DOM에 존재
  - 비교 테이블: 한 번에 4개 트림 컬럼만 렌더링 (DOM 자체가 교체됨)
  - CarCarouselDot / 'next' 버튼으로 캐러셀 위치 이동
  - Accordion 섹션 (KEY FEATURES / EXTERIOR / INTERIOR / ENGINE & MECHANICAL / SAFETY & SECURITY):
    - 닫힘: open 속성 없음
    - 열림: open="" 속성 있음

기호 매핑:
  icon-check  → Standard
  icon-minus  → Unavailable

카테고리 형식:
  {Accordion 섹션명} / {StyledTableHeader 텍스트}
  예) INTERIOR / COMFORT & CONVENIENCE
"""

import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from utils.formatter import clean_text


class MazdaSpecScraper:

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

        url = model_config["url"]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            # 뷰포트를 충분히 크게 설정 (BoundingClientRect 감지 안정성)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})

            # --- Navigate ---
            print(f"[INFO] Navigating to {url}")
            try:
                wait_until = self.wait_strategy.get("wait_until", "domcontentloaded")
                page.goto(url, wait_until=wait_until, timeout=60000)
            except PlaywrightTimeoutError:
                print(f"[ERROR] Timeout loading {url}")
                browser.close()
                return None

            self._dismiss_cookie_banner(page)

            # --- Wait for accordion to appear ---
            wait_sel = self.wait_strategy.get(
                "wait_for_selector",
                '[class*="Accordionstyles__StyledAccordionHeader"]',
            )
            try:
                page.wait_for_selector(wait_sel, timeout=30000)
                print(f"[INFO] Page ready: accordion found")
            except PlaywrightTimeoutError:
                print(f"[WARN] Accordion not found — saving debug snapshot")
                page.screenshot(path="debug_compare.png", full_page=False)
                with open("debug_compare.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                browser.close()
                return None

            # --- 전체 트림 이름+가격 읽기 (항상 DOM에 존재) ---
            all_trims_info = self._read_all_trim_cards(page)
            if not all_trims_info:
                print(f"[ERROR] Could not read trim cards")
                browser.close()
                return None
            all_names = [t["name"] for t in all_trims_info]
            print(f"[INFO] All trims ({len(all_names)}): {all_names}")

            start_time = time.time()
            master_data: dict = {}

            # --- 캐러셀 루프: 미수집 트림이 남는 동안 반복 ---
            for attempt in range(len(all_names)):
                print(f"\n[ATTEMPT {attempt + 1}] collected={list(master_data.keys())}")

                # 섹션 펼치기
                self._expand_all_sections(page)

                # 현재 보이는 트림명 감지
                visible_names = self._get_visible_trim_names(page, all_names)
                print(f"[INFO] Visible trims: {visible_names}")

                if not visible_names:
                    print(f"[WARN] Could not detect visible trims — stopping")
                    break

                # 테이블 파싱 (새 트림이 없어도 기존 트림의 빈 값 보완 가능)
                batch_data = self._parse_table(page, visible_names)
                total_features = sum(len(v["features"]) for v in batch_data.values())
                print(f"[INFO] Parsed {total_features} features across {len(batch_data)} trims")

                for trim_name, trim_data in batch_data.items():
                    if trim_name not in master_data:
                        master_data[trim_name] = trim_data
                        print(f"[INFO] Added: {trim_name}")
                    else:
                        # 기존 트림: 빈 값이 있으면 새 값으로 보완
                        for feat, entry in trim_data["features"].items():
                            existing = master_data[trim_name]["features"].get(feat)
                            if not existing or not existing.get("value"):
                                master_data[trim_name]["features"][feat] = entry

                # 모든 트림 수집 완료 확인
                uncollected = [n for n in all_names if n not in master_data]
                if not uncollected:
                    print(f"[INFO] All trims collected!")
                    break

                # 수집됐어도 빈 값이 있는 트림 확인
                empty_value_trims = [
                    n for n in master_data
                    if any(not v.get("value") for v in master_data[n]["features"].values())
                ]
                if empty_value_trims:
                    print(f"[INFO] Trims with empty values: {empty_value_trims} — will retry")

                print(f"[INFO] Still uncollected: {uncollected} — navigating next")

                # 다음 캐러셀 위치로 이동
                moved = self._click_carousel_next(page)
                if not moved:
                    print(f"[WARN] Cannot navigate further — stopping")
                    break

                # 테이블 DOM이 실제로 바뀔 때까지 대기
                self._wait_for_table_update(page, visible_names)

            browser.close()

        elapsed = round(time.time() - start_time, 2)
        collected = list(master_data.keys())
        missing = [n for n in all_names if n not in collected]
        print(f"\n[INFO] Elapsed: {elapsed}s")
        print(f"[INFO] Collected trims: {collected}")
        if missing:
            print(f"[WARN] Missing trims: {missing}")

        if not master_data:
            return None

        # 가격 채우기
        price_map = {t["name"]: t["price"] for t in all_trims_info}
        for trim_name in master_data:
            if not master_data[trim_name].get("price_msrp"):
                master_data[trim_name]["price_msrp"] = price_map.get(trim_name, "")

        return {
            "brand": self.brand,
            "model": model.replace("-", " ").title(),
            "year": datetime.now().year,
            "crawled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_url": url,
            "trims": master_data,
        }

    # ------------------------------------------------------------------
    # Trim card reading
    # ------------------------------------------------------------------

    def _read_all_trim_cards(self, page) -> list[dict]:
        """CarCard 캐러셀에서 모든 트림 이름과 가격을 읽는다.
        'See Inventory' 버튼이 있는 카드(비교 영역)만 필터링한다."""
        try:
            trims = page.evaluate("""
                () => {
                    const clean = t => t.replace(/\\s+/g, ' ').trim();
                    const results = [];
                    const cards = document.querySelectorAll('[class*="CarCardstyles__StyledCarCard-sc"]');
                    for (const card of cards) {
                        const hasInventory = card.textContent.includes('See Inventory') ||
                                             card.textContent.includes('SEE INVENTORY');
                        if (!hasInventory) continue;

                        const headingEl = card.querySelector('[class*="StyledCarCardHeading"]');
                        const blurbEl = card.querySelector('[class*="StyledCarCardBlurb"]');
                        if (!headingEl) continue;

                        const name = clean(headingEl.textContent);
                        const blurbText = blurbEl ? clean(blurbEl.textContent) : '';
                        const priceMatch = blurbText.match(/\\$?(\\d{1,3}(?:,\\d{3})+)/);
                        const price = priceMatch ? '$' + priceMatch[1] : '';

                        results.push({ name, price });
                    }
                    return results;
                }
            """)
            return trims or []
        except Exception as e:
            print(f"[WARN] _read_all_trim_cards error: {e}")
            return []

    # ------------------------------------------------------------------
    # Carousel navigation
    # ------------------------------------------------------------------

    def _get_visible_trim_names(self, page, all_names: list) -> list:
        """현재 캐러셀 위치에서 보이는 트림명을 반환.

        감지 방법 우선순위:
        1. CSS transform (rail 및 상위 요소 탐색) → 카드 인덱스 계산
        2. scrollLeft / margin-left / left CSS 속성
        3. BoundingClientRect (RailWrapper 기준)
        4. Fallback: all_names[0:4]
        """
        try:
            result = page.evaluate("""
                (allNames) => {
                    const clean = t => t.replace(/\\s+/g, ' ').trim();
                    const CARDS_PER_PAGE = 4;

                    // 비교 영역 Rail 찾기 (See Inventory가 있는 것)
                    const allRails = document.querySelectorAll('[class*="CarCarouselRail-sc-"]');
                    let rail = null;
                    for (const r of allRails) {
                        if (r.textContent.includes('See Inventory') ||
                            r.textContent.includes('SEE INVENTORY')) {
                            rail = r; break;
                        }
                    }
                    if (!rail && allRails.length) rail = allRails[0];
                    if (!rail) return { method: 'no_rail', names: allNames.slice(0, CARDS_PER_PAGE) };

                    const cards = [...rail.querySelectorAll('[class*="CarCardstyles__StyledCarCard-sc"]')];
                    if (!cards.length) return { method: 'no_cards', names: allNames.slice(0, CARDS_PER_PAGE) };

                    const cardWidth = cards[0].offsetWidth;

                    // Method 1: rail 및 상위 요소에서 CSS transform 탐색
                    // (일부 사이트는 rail 자체가 아닌 부모/자식 요소에 transform 적용)
                    let xOffset = 0;
                    let transformFound = false;
                    const candidateEls = [rail];
                    // rail 직계 자식도 확인
                    for (const ch of rail.children) candidateEls.push(ch);
                    // rail의 상위 4단계까지 확인
                    let ancestor = rail.parentElement;
                    for (let i = 0; i < 4 && ancestor && ancestor !== document.body; i++, ancestor = ancestor.parentElement) {
                        candidateEls.push(ancestor);
                    }

                    for (const el of candidateEls) {
                        const st = window.getComputedStyle(el);
                        const transform = el.style.transform || st.transform || '';
                        if (!transform || transform === 'none') continue;
                        const t3d = transform.match(/translate3d\\(\\s*(-?[\\d.]+)px/);
                        const mat = transform.match(/matrix\\([^,]+,[^,]+,[^,]+,[^,]+,\\s*(-?[\\d.]+)/);
                        if (t3d) { xOffset = Math.abs(parseFloat(t3d[1])); transformFound = true; break; }
                        if (mat) { xOffset = Math.abs(parseFloat(mat[1])); transformFound = true; break; }
                    }

                    // Method 2: scrollLeft / margin-left / left 속성 fallback
                    if (!transformFound || xOffset === 0) {
                        xOffset = rail.scrollLeft || 0;
                    }
                    if (xOffset === 0 && cardWidth > 10) {
                        const ml = parseFloat(window.getComputedStyle(rail).marginLeft) || 0;
                        if (ml < 0) xOffset = Math.abs(ml);
                    }

                    if (cardWidth > 10) {
                        const firstIdx = xOffset > 0 ? Math.round(xOffset / cardWidth) : 0;
                        const visibleCards = cards.slice(firstIdx, firstIdx + CARDS_PER_PAGE);
                        if (visibleCards.length > 0) {
                            const names = visibleCards.map(c => {
                                const h = c.querySelector('[class*="StyledCarCardHeading"]');
                                return h ? clean(h.textContent) : '';
                            }).filter(Boolean);
                            if (names.length) return { method: 'transform', firstIdx, xOffset, cardWidth, names };
                        }
                    }

                    // Method 3: BoundingClientRect (RailWrapper 기준)
                    const wrapper = rail.closest('[class*="CarCarouselRailWrapper"]') ||
                                    rail.parentElement;
                    if (wrapper) {
                        const wr = wrapper.getBoundingClientRect();
                        const visible = cards.filter(c => {
                            const r = c.getBoundingClientRect();
                            const cx = (r.left + r.right) / 2;
                            return cx >= wr.left - 5 && cx <= wr.right + 5;
                        });
                        if (visible.length) {
                            return {
                                method: 'bounding',
                                names: visible.map(c => {
                                    const h = c.querySelector('[class*="StyledCarCardHeading"]');
                                    return h ? clean(h.textContent) : '';
                                }).filter(Boolean)
                            };
                        }
                    }

                    return { method: 'fallback', names: allNames.slice(0, CARDS_PER_PAGE) };
                }
            """, all_names)

            method = result.get("method", "?") if isinstance(result, dict) else "?"
            names = result.get("names", []) if isinstance(result, dict) else result
            print(f"[DEBUG] visible_names method={method} xOffset={result.get('xOffset', '?')} cardWidth={result.get('cardWidth', '?')} firstIdx={result.get('firstIdx', '?')}: {names}")
            return names or []
        except Exception as e:
            print(f"[WARN] _get_visible_trim_names error: {e}")
            return []

    def _click_carousel_next(self, page) -> bool:
        """trim_selector next 버튼을 클릭해 다음 위치로 이동."""
        try:
            result = page.evaluate("""
                () => {
                    const btn = document.querySelector(
                        '[data-analytics-link-component-name="trim_selector"]' +
                        '[data-analytics-link-description="next"]'
                    );
                    if (!btn) return 'not_found';
                    const style = window.getComputedStyle(btn);
                    if (btn.disabled || btn.getAttribute('aria-disabled') === 'true' ||
                        style.pointerEvents === 'none' || style.opacity === '0') {
                        return 'disabled';
                    }
                    btn.click();
                    return 'clicked';
                }
            """)
            print(f"[INFO] Carousel next: {result}")
            return result == "clicked"
        except Exception as e:
            print(f"[WARN] _click_carousel_next error: {e}")
            return False

    def _wait_for_table_update(self, page, prev_visible_names: list) -> None:
        """캐러셀 이동 후 테이블 DOM이 실제로 업데이트될 때까지 대기.
        최초 셀의 텍스트 값이 변경되거나, 최대 4초 대기 후 진행."""
        # 현재 첫 번째 텍스트 스펙 행의 첫 번째 셀 값 스냅샷
        try:
            before_val = page.evaluate("""
                () => {
                    const cell = document.querySelector(
                        '[class*="Tablestyles__StyledTableCell-sc"] p'
                    );
                    return cell ? cell.textContent.trim() : '';
                }
            """)
        except Exception:
            before_val = ""

        # 최대 4초 대기하면서 값 변경 감지
        for _ in range(8):
            time.sleep(0.5)
            try:
                after_val = page.evaluate("""
                    () => {
                        const cell = document.querySelector(
                            '[class*="Tablestyles__StyledTableCell-sc"] p'
                        );
                        return cell ? cell.textContent.trim() : '';
                    }
                """)
                if after_val != before_val:
                    print(f"[INFO] Table DOM updated ('{before_val[:20]}' → '{after_val[:20]}')")
                    time.sleep(0.5)  # 추가 안정화 대기
                    return
            except Exception:
                pass

        print(f"[INFO] Table DOM may not have changed — proceeding anyway")

    # ------------------------------------------------------------------
    # Accordion expansion
    # ------------------------------------------------------------------

    def _expand_all_sections(self, page) -> None:
        """open 속성이 없는(닫힌) 모든 Accordion 헤더를 클릭해 펼친다."""
        expanded = 0
        try:
            btns = page.query_selector_all('[class*="Accordionstyles__StyledAccordionHeader"]')
            for btn in btns:
                try:
                    is_open = btn.get_attribute("open") is not None
                    if not is_open:
                        btn.scroll_into_view_if_needed()
                        btn.click()
                        time.sleep(0.4)
                        expanded += 1
                except Exception:
                    continue
        except Exception as e:
            print(f"[WARN] _expand_all_sections error: {e}")
        if expanded:
            print(f"[INFO] Expanded {expanded} section(s)")
            time.sleep(1.0)

    # ------------------------------------------------------------------
    # Table parsing
    # ------------------------------------------------------------------

    def _parse_table(self, page, trim_names: list) -> dict:
        """현재 보이는 테이블 컬럼을 파싱한다.

        행 유형:
        1. 텍스트 스펙: 셀에 <p> 텍스트 → 값 그대로
        2. 불릿 피처: 셀에 <ul><li> → 포함 여부로 Standard/Unavailable
        3. 아이콘 스펙: 셀에 icon-check / icon-minus → Standard / Unavailable

        카테고리: '{Accordion 섹션} / {StyledTableHeader}'
        피처명:   currentSubHeader 또는 currentTableHeader
        """
        n_trims = len(trim_names)
        result = {name: {"price_msrp": "", "features": {}} for name in trim_names}

        rows_data = page.evaluate("""
            (nTrims) => {
                // <sup> 태그(각주 숫자)를 제거한 뒤 textContent 반환
                const getText = el => {
                    const clone = el.cloneNode(true);
                    clone.querySelectorAll('sup').forEach(s => s.remove());
                    return clone.textContent;
                };
                const clean = t => t
                    .replace(/\\u00ae|\\u2122|\\*|\\u2020|\\u2021|\\u2019/g, '')
                    .replace(/\\s+/g, ' ')
                    .trim();

                let currentAccordion = '';
                let currentTableHeader = '';
                let currentSubHeader = '';

                const results = [];

                // Accordion 헤더 + 테이블 헤더/서브헤더/행 모두 DOM 순서대로 순회
                const allEls = document.querySelectorAll([
                    '[class*="Accordionstyles__StyledAccordionHeader"]',
                    '[class*="Tablestyles__StyledTableHeader-sc"]',
                    '[class*="Tablestyles__StyledTableSubHeader-sc"]',
                    '[class*="Tablestyles__StyledTableRow-sc"]',
                ].join(','));

                for (const el of allEls) {
                    const cls = el.className || '';

                    // ── Accordion 섹션 헤더 ──────────────────────────────────
                    if (cls.includes('StyledAccordionHeader')) {
                        const headingEl = el.querySelector('[class*="StyledAccordionHeading"]');
                        currentAccordion = clean(getText(headingEl || el));
                        currentTableHeader = '';
                        currentSubHeader = '';
                        continue;
                    }

                    // ── 테이블 대분류 헤더 ───────────────────────────────────
                    if (cls.includes('StyledTableHeader-sc')) {
                        currentTableHeader = clean(getText(el));
                        currentSubHeader = '';
                        continue;
                    }

                    // ── 테이블 소분류/행 레이블 ─────────────────────────────
                    if (cls.includes('StyledTableSubHeader-sc')) {
                        const span = el.querySelector('span');
                        currentSubHeader = clean(getText(span || el));
                        continue;
                    }

                    // ── 데이터 행 ────────────────────────────────────────────
                    if (!cls.includes('StyledTableRow-sc')) continue;

                    const cells = [...el.querySelectorAll('[class*="Tablestyles__StyledTableCell-sc"]')];
                    if (!cells.length) continue;

                    // 카테고리: {accordion} / {tableHeader}
                    const category = currentAccordion && currentTableHeader
                        ? `${currentAccordion} / ${currentTableHeader}`
                        : (currentAccordion || currentTableHeader);

                    // 셀 유형 판별
                    const hasBullets = cells.some(c => c.querySelector('ul'));
                    const hasIcons   = cells.some(c => c.querySelector('.icon-check, .icon-minus'));

                    if (hasBullets) {
                        // ── 유형 2: 불릿 리스트 ─────────────────────────────
                        // 일부 트림은 <ul><li> 대신 <p> 태그로 단일 피처를 표시
                        // (불릿 없이 텍스트만 표시되는 케이스)
                        const allFeatures = new Set();
                        for (const cell of cells.slice(0, nTrims)) {
                            for (const li of cell.querySelectorAll('li')) {
                                const t = clean(getText(li));
                                if (t) allFeatures.add(t);
                            }
                            // <ul>이 없는 셀: <p> 텍스트를 피처로 추가
                            if (!cell.querySelector('ul')) {
                                const p = cell.querySelector('p');
                                if (p) {
                                    const t = clean(getText(p));
                                    if (t) allFeatures.add(t);
                                }
                            }
                        }
                        for (const feat of allFeatures) {
                            const values = cells.slice(0, nTrims).map(cell => {
                                const liTexts = [...cell.querySelectorAll('li')]
                                    .map(li => clean(getText(li)));
                                if (liTexts.includes(feat)) return 'Standard';
                                // <ul> 없는 셀은 <p> 텍스트와 비교
                                if (!cell.querySelector('ul')) {
                                    const p = cell.querySelector('p');
                                    if (p && clean(getText(p)) === feat) return 'Standard';
                                }
                                return 'Unavailable';
                            });
                            while (values.length < nTrims) values.push('Unavailable');
                            results.push({ feature: feat, values, category });
                        }

                    } else if (hasIcons) {
                        // ── 유형 3: 아이콘 (check/minus) ────────────────────
                        const featureName = currentSubHeader || currentTableHeader;
                        if (!featureName) continue;
                        const values = cells.slice(0, nTrims).map(cell => {
                            if (cell.querySelector('.icon-check'))  return 'Standard';
                            if (cell.querySelector('.icon-minus'))  return 'Unavailable';
                            // 텍스트가 있는 셀 (일부 트림은 텍스트로 표시될 수 있음)
                            const p = cell.querySelector('p');
                            const txt = p ? clean(getText(p)) : clean(getText(cell));
                            return txt || 'Unavailable';
                        });
                        while (values.length < nTrims) values.push('Unavailable');
                        results.push({ feature: featureName, values, category });

                    } else {
                        // ── 유형 1: 텍스트 스펙 ─────────────────────────────
                        const featureName = currentSubHeader || currentTableHeader;
                        if (!featureName) continue;
                        const values = cells.slice(0, nTrims).map(cell => {
                            const p = cell.querySelector('p');
                            return p ? clean(getText(p)) : clean(getText(cell));
                        });
                        while (values.length < nTrims) values.push('');
                        results.push({ feature: featureName, values, category });
                    }
                }
                return results;
            }
        """, n_trims)

        print(f"[DEBUG] JS extracted {len(rows_data)} rows")

        for row in rows_data:
            feature_name = row["feature"]
            values = row["values"]
            category = row["category"]
            for idx, val in enumerate(values):
                if idx < n_trims:
                    result[trim_names[idx]]["features"].setdefault(feature_name, {
                        "value": val,
                        "category": category,
                    })

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

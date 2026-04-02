"""
Lexus Compare Grid scraper.

Collects all trims by cycling through batches of 3 columns.
Uses data-testid selectors (stable across CSS class changes).
"""

import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from utils.formatter import clean_text


class LexusSpecScraper:

    def __init__(self, config: dict, headless: bool = True):
        self.config = config
        self.headless = headless
        self.brand = config["brand"]
        self.icon_map = config.get("icon_map", {})
        self.wait_strategy = config.get("wait_strategy", {})

    def scrape_model(self, model: str) -> dict | None:
        model_config = self.config["models"].get(model)
        if not model_config:
            print(f"[WARN] Model config not found: {model}")
            return None

        url = model_config["url"]
        sel = model_config.get("selectors", {})
        all_trims = model_config.get("all_trims")       # None이면 자동 감지
        batch_size = model_config.get("batch_size", 3)
        compare_anchor = model_config.get("compare_anchor", "#model_compare")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()

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

            # --- Navigate to compare section ---
            print(f"[INFO] Scrolling to compare section ...")
            try:
                nav_btn = page.wait_for_selector(
                    "#arrowbutton, a[href='#model_compare']", timeout=15000
                )
                if nav_btn:
                    nav_btn.scroll_into_view_if_needed()
                    nav_btn.click()
                    time.sleep(2)
                    print(f"[INFO] Navigated to compare section")
            except PlaywrightTimeoutError:
                page.evaluate(f"document.querySelector('{compare_anchor}')?.scrollIntoView()")
                time.sleep(2)

            # --- Wait for CompareGrid ---
            wait_sel = self.wait_strategy.get("wait_for_selector")
            if wait_sel:
                try:
                    page.wait_for_selector(wait_sel, timeout=30000)
                    print(f"[INFO] CompareGrid found")
                except PlaywrightTimeoutError:
                    print(f"[WARN] CompareGrid not found — saving debug snapshot")
                    page.screenshot(path="debug_compare.png", full_page=False)
                    with open("debug_compare.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    print(f"[DEBUG] Saved debug_compare.png and debug_compare.html")
                    # Check what data-testid values ARE present
                    testids = page.evaluate("""
                        () => [...new Set(
                            [...document.querySelectorAll('[data-testid]')]
                            .map(el => el.getAttribute('data-testid'))
                        )].sort()
                    """)
                    print(f"[DEBUG] data-testid values on page: {testids}")

            # --- Auto-detect trims if not in config ---
            if not all_trims:
                all_trims = self._detect_trims(page)
                if not all_trims:
                    print(f"[ERROR] Could not detect trims from page")
                    browser.close()
                    return None
                print(f"[INFO] Auto-detected {len(all_trims)} trims: {[t['label'] for t in all_trims]}")

            # --- Build batches ---
            batches = self._make_batches(all_trims, batch_size)
            print(f"[INFO] {len(all_trims)} trims → {len(batches)} batches of {batch_size}")

            master_data: dict = {}
            start_time = time.time()

            for batch_idx, batch in enumerate(batches):
                intended_labels = [t["label"] for t in batch]
                print(f"\n[BATCH {batch_idx + 1}/{len(batches)}] {intended_labels}")

                # Step A: Uncheck all currently checked trims
                self._uncheck_all(page)

                # Step B: Check the 3 trims in this batch
                self._check_trims(page, batch)

                # Step C: Click the now-enabled COMPARE button
                if not self._click_compare_button(page):
                    print(f"[WARN] Could not click COMPARE — skipping batch")
                    continue

                # Step D: Wait for CompareGrid to render
                try:
                    page.wait_for_selector(
                        "[data-testid='CompareGrid'], [data-testid='ControlsRow']",
                        timeout=20000,
                    )
                    print(f"[INFO] CompareGrid rendered")
                except PlaywrightTimeoutError:
                    print(f"[WARN] CompareGrid timeout — proceeding anyway")

                time.sleep(1)

                # Step E: 매 배치마다 현재 DOM의 drawer를 확장
                # (배치별로 선택된 트림에 따라 drawer 구성이 달라질 수 있음)
                self._expand_all_drawers(page)

                # Step F: 실제 DOM 컬럼 순서를 읽어 intended_labels와 순서 검증
                visible_trims = self._read_column_order(page, intended_labels)
                print(f"[INFO] Using trim columns: {visible_trims}")

                # Step G: Parse the grid
                batch_data = self._parse_grid(page, sel, visible_trims)
                total_features = sum(len(v["features"]) for v in batch_data.values())
                print(f"[INFO] Parsed {total_features} feature entries across {len(batch_data)} trims")

                # Step H: Upsert into master (skip padding trims)
                for trim_label, trim_data in batch_data.items():
                    if trim_label not in intended_labels:
                        continue
                    if trim_label not in master_data:
                        master_data[trim_label] = trim_data
                    else:
                        for feat, entry in trim_data["features"].items():
                            master_data[trim_label]["features"].setdefault(feat, entry)

                # Step I: Close the overlay to return to card selection view
                if batch_idx < len(batches) - 1:
                    self._close_compare_overlay(page)

            browser.close()

        elapsed = round(time.time() - start_time, 2)
        collected = list(master_data.keys())
        missing = [t["label"] for t in all_trims if t["label"] not in collected]
        print(f"\n[INFO] Elapsed: {elapsed}s")
        print(f"[INFO] Collected trims: {collected}")
        if missing:
            print(f"[WARN] Missing trims: {missing}")

        if not master_data:
            return None

        return {
            "brand": self.brand,
            "model": model.replace("-", " ").title(),
            "year": datetime.now().year,
            "crawled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_url": url,
            "trims": master_data,
        }

    # ------------------------------------------------------------------
    # Auto-detection
    # ------------------------------------------------------------------

    def _detect_trims(self, page) -> list:
        """페이지의 트림 선택 카드에서 label과 checkbox ID를 자동 감지."""
        try:
            trims = page.evaluate("""
                () => {
                    const clean = t => t.replace(/\\s+/g, ' ').trim();
                    const results = [];
                    for (const card of document.querySelectorAll('[data-testid="Card"]')) {
                        const h2 = card.querySelector('h2');
                        const cb = card.querySelector('input[name="model_compare-select"]');
                        if (!h2 || !cb) continue;
                        results.push({ label: clean(h2.innerText), select_id: cb.id });
                    }
                    return results;
                }
            """)
            return trims or []
        except Exception as e:
            print(f"[WARN] _detect_trims error: {e}")
            return []

    def _detect_drawer_ids(self, page) -> list:
        """페이지의 drawer 버튼 ID를 문서 순서대로 자동 감지.
        ID 패턴: {drawer_id}-drawer-button → drawer_id만 추출."""
        try:
            ids = page.evaluate("""
                () => {
                    const results = [];
                    for (const btn of document.querySelectorAll('[id$="-drawer-button"][aria-expanded]')) {
                        const drawerId = btn.id.replace(/-drawer-button$/, '');
                        results.push(drawerId);
                    }
                    return results;
                }
            """)
            return ids or []
        except Exception as e:
            print(f"[WARN] _detect_drawer_ids error: {e}")
            return []

    # ------------------------------------------------------------------
    # Batch helpers
    # ------------------------------------------------------------------

    def _make_batches(self, all_trims: list, batch_size: int) -> list:
        """Split trims into batches. Pad last batch with first trim."""
        batches = []
        for i in range(0, len(all_trims), batch_size):
            batch = list(all_trims[i:i + batch_size])
            while len(batch) < batch_size:
                batch.append(all_trims[0])
            batches.append(batch)
        return batches

    # ------------------------------------------------------------------
    # Trim checkbox selection
    # ------------------------------------------------------------------

    def _close_compare_overlay(self, page) -> None:
        """Close the compare-grid overlay and wait for card view to restore."""
        print(f"[INFO] Closing compare overlay ...")
        # Try close button first
        for close_sel in [
            "#compare-grid-overlay [aria-label='Close']",
            "#compare-grid-overlay button[aria-label='close']",
            ".overlay-component--open [data-testid='Close']",
            ".overlay-component--open button.close",
        ]:
            try:
                btn = page.query_selector(close_sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1)
                    print(f"[INFO] Overlay closed via close button")
                    break
            except Exception:
                continue
        else:
            # Fallback: Escape key
            page.keyboard.press("Escape")
            time.sleep(1)

        # Wait for overlay to disappear
        try:
            page.wait_for_selector(
                "#compare-grid-overlay.overlay-component--open",
                state="hidden",
                timeout=8000,
            )
            print(f"[INFO] Overlay hidden")
        except PlaywrightTimeoutError:
            pass

        # Wait for card checkboxes to be re-enabled
        try:
            page.wait_for_selector(
                "input[name='model_compare-select']:not([disabled])",
                timeout=8000,
            )
        except PlaywrightTimeoutError:
            pass
        time.sleep(1)

    def _uncheck_all(self, page) -> None:
        """Uncheck all currently checked trim checkboxes via JavaScript."""
        try:
            count = page.evaluate("""
                () => {
                    const cbs = document.querySelectorAll(
                        "input[name='model_compare-select']:checked"
                    );
                    cbs.forEach(cb => {
                        cb.click();
                    });
                    return cbs.length;
                }
            """)
            if count:
                print(f"[INFO] Unchecked {count} trim(s)")
            time.sleep(0.5)
        except Exception as e:
            print(f"[WARN] _uncheck_all error: {e}")

    def _check_trims(self, page, batch: list) -> None:
        """Check the checkboxes for the given batch of trims via JavaScript."""
        checked = 0
        for trim in batch:
            try:
                result = page.evaluate(f"""
                    () => {{
                        const cb = document.getElementById('{trim['select_id']}');
                        if (!cb) return 'not_found';
                        if (cb.checked) return 'already_checked';
                        cb.click();
                        return 'clicked';
                    }}
                """)
                if result in ('clicked', 'already_checked'):
                    checked += 1
                    print(f"[DEBUG] Checked: {trim['label']} ({result})")
                else:
                    print(f"[WARN] Checkbox not found: #{trim['select_id']}")
                time.sleep(0.3)
            except Exception as e:
                print(f"[WARN] _check_trims error for '{trim['label']}': {e}")
        print(f"[INFO] Checked {checked}/{len(batch)} trims")

    def _click_compare_button(self, page) -> bool:
        """Click the COMPARE button that becomes enabled after selecting trims."""
        try:
            # Wait for button to become enabled
            page.wait_for_selector(
                "button[aria-label='COMPARE']:not([aria-disabled='true'])",
                timeout=10000,
            )
            btn = page.query_selector("button[aria-label='COMPARE']:not([aria-disabled='true'])")
            if btn:
                btn.scroll_into_view_if_needed()
                btn.click()
                print(f"[INFO] COMPARE button clicked")
                time.sleep(2)
                return True
        except PlaywrightTimeoutError:
            print(f"[WARN] COMPARE button did not become enabled")
        except Exception as e:
            print(f"[WARN] _click_compare_button error: {e}")
        return False

    # ------------------------------------------------------------------
    # Drawer expansion
    # ------------------------------------------------------------------

    def _expand_all_drawers(self, page) -> None:
        """현재 DOM의 모든 drawer 버튼을 스캔해서 접힌 것을 모두 펼침.
        배치마다 호출하므로 모델/배치별로 달라지는 drawer 구성에 자동 대응."""
        expanded = 0
        try:
            btns = page.query_selector_all("[id$='-drawer-button'][aria-expanded]")
            for btn in btns:
                try:
                    aria = btn.get_attribute("aria-expanded") or ""
                    if aria.lower() == "false":
                        btn.scroll_into_view_if_needed()
                        btn.click()
                        time.sleep(0.3)
                        expanded += 1
                except Exception:
                    continue
        except Exception as e:
            print(f"[WARN] _expand_all_drawers error: {e}")
        if expanded:
            print(f"[INFO] Expanded {expanded} drawer(s)")
            time.sleep(1.5)  # 모든 드로어 애니메이션 및 lazy DOM 렌더링 완료 대기

    # ------------------------------------------------------------------
    # Grid parsing
    # ------------------------------------------------------------------

    def _read_grid_headers(self, page, selector: str) -> list[str]:
        headers = []
        try:
            for el in page.query_selector_all(selector):
                text = clean_text(el.inner_text())
                if text:
                    headers.append(text)
        except Exception as e:
            print(f"[WARN] _read_grid_headers error: {e}")
        return headers

    def _read_column_order(self, page, intended_labels: list) -> list:
        """실제 DOM의 GridHeader 순서를 읽어 컬럼 매핑 순서를 반환.
        중복 헤더(sticky + 일반)는 제거. 읽기 실패 시 intended_labels 순서 유지."""
        try:
            headers = page.evaluate("""
                () => {
                    const clean = t => t
                        .replace(/[\\u24d8\\u2139*\\u2020\\u2021\\u00b6#]/g, '')
                        .replace(/\\s+/g, ' ').trim();
                    const seen = new Set();
                    const result = [];
                    for (const el of document.querySelectorAll('[data-testid="GridHeader"]')) {
                        const text = clean(el.innerText);
                        if (text && !seen.has(text)) {
                            seen.add(text);
                            result.push(text);
                        }
                    }
                    return result;
                }
            """)
            if headers and len(headers) == len(intended_labels) and all(h in intended_labels for h in headers):
                print(f"[INFO] DOM column order: {headers}")
                return headers
            print(f"[WARN] DOM headers {headers} ≠ intended {intended_labels} — using intended order")
        except Exception as e:
            print(f"[WARN] _read_column_order error: {e}")
        return intended_labels

    def _parse_grid(self, page, sel: dict, trim_headers: list) -> dict:
        """
        JavaScript로 브라우저 내에서 직접 추출.
        Playwright 엘리먼트 핸들의 stale 문제를 완전히 우회.
        카테고리는 DOM의 모든 drawer 버튼을 직접 스캔해 aria-controls 기반으로 결정.
        """
        result = {name: {"price_msrp": "", "features": {}} for name in trim_headers}
        n_trims = len(trim_headers)

        rows_data = page.evaluate("""
            (nTrims) => {
                const cleanText = t => t
                    .replace(/[\\u24d8\\u2139*\\u2020\\u2021\\u00b6#]/g, '')
                    .replace(/\\s+/g, ' ')
                    .trim();

                const hasIcon = (td, testid) => !!td.querySelector(`[data-testid="${testid}"]`);
                const isUnavailable = td =>
                    hasIcon(td, 'NotAvailableIcon') || hasIcon(td, 'NotAvailablePlaceholder');

                const cellValue = td => {
                    if (isUnavailable(td))           return 'Unavailable';
                    if (hasIcon(td, 'OptionalIcon')) return 'Optional';
                    if (hasIcon(td, 'PackageIcon'))  return 'Optional';
                    const text = cleanText(td.innerText);
                    return text || 'Unavailable';
                };

                // DOM의 모든 drawer 버튼을 스캔해 aria-controls 기반 rowId → 카테고리 매핑
                // design-options(색상 스와치), key-features(summary)는 제외
                const SKIP_DRAWERS = new Set([
                    'design-options-swatches-compare-drawer',
                    'key-features-specs-compare-drawer',
                ]);
                const rowCategoryMap = {};
                for (const btn of document.querySelectorAll('[id$="-drawer-button"][aria-controls]')) {
                    const drawerId = btn.id.replace(/-drawer-button$/, '');
                    if (SKIP_DRAWERS.has(drawerId)) continue;
                    const label = cleanText(btn.innerText);
                    for (const ctrlId of (btn.getAttribute('aria-controls') || '').split(/\s+/)) {
                        const baseId = ctrlId.replace(/^column-\d+-/, '');
                        if (baseId && !rowCategoryMap[baseId]) rowCategoryMap[baseId] = label;
                    }
                }

                const getCategory = row => rowCategoryMap[row.id] || '';

                // FeatureTags(아이콘+라벨 영역)를 제외한 순수 기능명 텍스트 추출
                // 예) "Auto-dimming rearview mirror Available as option" → "Auto-dimming rearview mirror"
                const getFeatureName = td => {
                    const clone = td.cloneNode(true);
                    clone.querySelectorAll('[data-testid="FeatureTags"]').forEach(el => el.remove());
                    return cleanText(clone.innerText);
                };

                // 값 우선순위: Optional(2) > Standard(1) > Unavailable(0)
                // 같은 featureName이 DOM에 두 번 나타날 때(일반 drawer + Package drawer)
                // 더 높은 우선순위 값으로 머지
                const PRIORITY = { 'Optional': 2, 'Standard': 1, 'Unavailable': 0 };
                const mergeVal = (a, b) => PRIORITY[a] >= PRIORITY[b] ? a : b;

                // featureName → [values, category] 머지 맵
                const mergeMap = new Map();

                const upsert = (featureName, values, category) => {
                    if (!mergeMap.has(featureName)) {
                        mergeMap.set(featureName, { values: [...values], category });
                        return;
                    }
                    const existing = mergeMap.get(featureName);
                    for (let i = 0; i < values.length; i++) {
                        existing.values[i] = mergeVal(existing.values[i], values[i]);
                    }
                    // 카테고리는 Optional 값이 있는 쪽 우선
                    if (values.some(v => v === 'Optional') && !existing.values.some(v => v === 'Optional')) {
                        existing.category = category;
                    }
                };

                const rows = document.querySelectorAll('[data-testid="DataRow"]');

                rows.forEach(row => {
                    const rowId = row.id || '';
                    // BUILD 링크 행, 트림명 헤더 행은 제외
                    if (rowId === 'build-link' || rowId === 'trim-name') return;

                    const cells = [...row.querySelectorAll('[data-testid="FeaturesRow"]')];
                    if (!cells.length) return;

                    const category = getCategory(row);
                    const th = row.querySelector('th');
                    const thText = th ? cleanText(th.innerText) : '';

                    if (thText) {
                        // ── 유형 A: SPEC 행 ──────────────────────────────────
                        const values = cells.slice(0, nTrims).map(cellValue);
                        while (values.length < nTrims) values.push('Unavailable');
                        upsert(thText, values, category);

                    } else {
                        // ── 유형 B: FEATURE 행 ───────────────────────────────
                        let featureName = '';
                        for (const td of cells) {
                            if (isUnavailable(td)) continue;
                            const name = getFeatureName(td);
                            if (name) { featureName = name; break; }
                        }
                        if (!featureName) return;

                        const values = cells.slice(0, nTrims).map(td => {
                            if (isUnavailable(td))           return 'Unavailable';
                            if (hasIcon(td, 'OptionalIcon')) return 'Optional';
                            if (hasIcon(td, 'PackageIcon'))  return 'Optional';
                            const text = cleanText(td.innerText);
                            return text ? 'Standard' : 'Unavailable';
                        });

                        while (values.length < nTrims) values.push('Unavailable');
                        upsert(featureName, values, category);
                    }
                });

                return [...mergeMap.entries()].map(([name, {values, category}]) => [name, values, category]);
            }
        """, n_trims)

        print(f"[DEBUG] JS extracted {len(rows_data)} rows")

        for feature_name, values, category in rows_data:
            for idx, val in enumerate(values):
                if idx < n_trims:
                    result[trim_headers[idx]]["features"][feature_name] = {
                        "value": val,
                        "category": category,
                    }

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

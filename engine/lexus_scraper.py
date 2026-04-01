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
        sel = model_config["selectors"]
        all_trims = model_config["all_trims"]
        batch_size = model_config.get("batch_size", 3)
        drawer_ids = model_config.get("category_drawer_ids", [])
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

                # Step E: Expand all category drawers
                self._expand_all_drawers(page, drawer_ids)

                # Step F: 실제 DOM 컬럼 순서를 읽어 intended_labels와 순서 검증
                visible_trims = self._read_column_order(page, intended_labels)
                print(f"[INFO] Using trim columns: {visible_trims}")

                # Step G: Parse the grid
                batch_data = self._parse_grid(page, sel, visible_trims, drawer_ids)
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

    def _expand_all_drawers(self, page, drawer_ids: list) -> None:
        expanded = 0
        for drawer_id in drawer_ids:
            try:
                btn = page.query_selector(f"#{drawer_id}-drawer-button")
                if not btn:
                    continue
                aria = btn.get_attribute("aria-expanded") or ""
                if aria.lower() == "false":
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    time.sleep(0.3)
                    expanded += 1
            except Exception:
                continue
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

    def _parse_grid(self, page, sel: dict, trim_headers: list, drawer_ids: list) -> dict:
        """
        JavaScript로 브라우저 내에서 직접 추출.
        Playwright 엘리먼트 핸들의 stale 문제를 완전히 우회.
        카테고리는 각 DataRow의 DOM 조상을 올라가며 drawer ID와 매칭해 drawer 버튼 텍스트로 결정.
        """
        result = {name: {"price_msrp": "", "features": {}} for name in trim_headers}
        n_trims = len(trim_headers)

        rows_data = page.evaluate("""
            (args) => {
                const nTrims   = args.nTrims;
                const drawerIds = args.drawerIds;

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
                    if (hasIcon(td, 'PackageIcon'))  return 'Standard';
                    const text = cleanText(td.innerText);
                    return text || 'Unavailable';
                };

                // drawer 버튼들을 문서 순서대로 수집
                // 실제 버튼 ID 패턴: {drawerId}-drawer-button
                const drawerButtons = [];
                for (const drawerId of drawerIds) {
                    const btn = document.getElementById(`${drawerId}-drawer-button`);
                    if (btn) drawerButtons.push({ btn, label: cleanText(btn.innerText) });
                }
                drawerButtons.sort((a, b) =>
                    a.btn.compareDocumentPosition(b.btn) & 4 ? -1 : 1
                );

                // DataRow보다 앞에 위치한 drawer 버튼 중 가장 마지막 것이 해당 카테고리
                const getCategory = row => {
                    let label = '';
                    for (const { btn, label: l } of drawerButtons) {
                        if (btn.compareDocumentPosition(row) & 4) label = l;
                    }
                    return label;
                };

                // FeatureTags(아이콘+라벨 영역)를 제외한 순수 기능명 텍스트 추출
                // 예) "Auto-dimming rearview mirror Available as option" → "Auto-dimming rearview mirror"
                const getFeatureName = td => {
                    const clone = td.cloneNode(true);
                    clone.querySelectorAll('[data-testid="FeatureTags"]').forEach(el => el.remove());
                    return cleanText(clone.innerText);
                };

                const results = [];
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
                        // <th>에 기능명이 있고, 각 <td>에 수치/텍스트가 들어있음
                        const values = cells.slice(0, nTrims).map(cellValue);
                        while (values.length < nTrims) values.push('Unavailable');
                        results.push([thText, values, category]);

                    } else {
                        // ── 유형 B: FEATURE 행 ───────────────────────────────
                        // 기능명: FeatureTags 영역을 제거한 후의 텍스트 사용
                        //   → OptionalIcon 셀도 포함해서 탐색 (기능명이 해당 셀에 있을 수 있음)
                        //   → Unavailable 셀만 제외
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
                            if (hasIcon(td, 'PackageIcon'))  return 'Standard';
                            const text = cleanText(td.innerText);
                            return text ? 'Standard' : 'Unavailable';
                        });

                        while (values.length < nTrims) values.push('Unavailable');
                        results.push([featureName, values, category]);
                    }
                });

                return results;
            }
        """, {"nTrims": n_trims, "drawerIds": drawer_ids})

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

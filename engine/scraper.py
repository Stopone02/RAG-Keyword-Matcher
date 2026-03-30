import re
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from utils.formatter import clean_text, convert_symbol


class SpecScraper:
    """Column-index-based spec scraper for car brand comparison pages."""

    def __init__(self, config: dict, headless: bool = True):
        self.config = config
        self.headless = headless
        self.brand = config["brand"]
        self.symbol_map = config.get("symbol_map", {})
        self.wait_strategy = config.get("wait_strategy", {})

    def scrape_model(self, model: str) -> dict | None:
        model_config = self.config["models"].get(model)
        if not model_config:
            print(f"[WARN] Model config not found: {model}")
            return None

        url = model_config["url"]
        selectors = model_config["selectors"]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()

            # --- Page Load ---
            try:
                wait_until = self.wait_strategy.get("wait_until", "networkidle")
                print(f"[INFO] Navigating to {url}")
                page.goto(url, wait_until=wait_until, timeout=60000)

            except PlaywrightTimeoutError:
                print(f"[ERROR] Timeout loading page: {url} — skipping model '{model}'")
                browser.close()
                return None

            self._dismiss_cookie_banner(page)

            wait_sel = self.wait_strategy.get("wait_for_selector")
            if wait_sel:
                try:
                    page.wait_for_selector(wait_sel, timeout=30000)
                except PlaywrightTimeoutError:
                    print(f"[WARN] wait_for_selector '{wait_sel}' timed out — proceeding anyway")

            # --- DEBUG: screenshot + HTML snippet ---
            page.screenshot(path="debug_screenshot.png", full_page=False)
            html_snippet = page.content()[:3000]
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"[DEBUG] Screenshot → debug_screenshot.png")
            print(f"[DEBUG] HTML snippet:\n{html_snippet}\n")

            start_time = time.time()

            # --- Trim Header Scan ---
            trim_names = self._read_trim_names(page, selectors["trim_header"])
            trim_prices = self._read_trim_prices(page, selectors["trim_price"], len(trim_names))

            if not trim_names:
                print(f"[ERROR] No trim headers found for model '{model}' — skipping")
                browser.close()
                return None

            print(f"[INFO] Found {len(trim_names)} trims: {trim_names}")

            # --- Row Scanning ---
            trims_data = {
                name: {"price_msrp": trim_prices[i], "features": {}}
                for i, name in enumerate(trim_names)
            }

            try:
                rows = page.query_selector_all(selectors["spec_row"])
            except Exception as e:
                print(f"[ERROR] Could not query spec rows: {e}")
                browser.close()
                return None

            total_rows = 0
            skipped_rows = 0

            for row in rows:
                total_rows += 1

                feature_el = row.query_selector(selectors["feature_name"])
                if not feature_el:
                    skipped_rows += 1
                    continue

                feature_name = clean_text(feature_el.inner_text())
                if not feature_name:
                    skipped_rows += 1
                    continue

                value_els = row.query_selector_all(selectors["value_cells"])

                if len(value_els) != len(trim_names):
                    print(
                        f"[WARN] Row '{feature_name}': expected {len(trim_names)} cells,"
                        f" got {len(value_els)} — skipping row"
                    )
                    skipped_rows += 1
                    continue

                for idx, cell in enumerate(value_els):
                    raw_value = self._extract_cell_value(cell)
                    normalized = convert_symbol(raw_value, self.symbol_map)
                    trims_data[trim_names[idx]]["features"][feature_name] = normalized

            elapsed = round(time.time() - start_time, 2)
            print(
                f"[INFO] Scanned {total_rows} rows, skipped {skipped_rows},"
                f" features collected: {total_rows - skipped_rows}, elapsed: {elapsed}s"
            )

            browser.close()

        return {
            "brand": self.brand,
            "model": model.title(),
            "year": self._extract_year(url),
            "crawled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_url": url,
            "trims": trims_data,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dismiss_cookie_banner(self, page) -> None:
        """Accept cookie consent popup if present."""
        cookie_selector = self.config.get("cookie_accept_selector")
        if cookie_selector:
            selectors_to_try = [cookie_selector]
        else:
            selectors_to_try = [
                "button:has-text('Accept All')",
                "button:has-text('Accept all')",
                "button:has-text('Accept')",
                "button:has-text('I Accept')",
                "button:has-text('Agree')",
                "button:has-text('OK')",
                "[id*='accept'][id*='cookie']",
                "[class*='accept'][class*='cookie']",
            ]

        for sel in selectors_to_try:
            try:
                btn = page.wait_for_selector(sel, timeout=3000)
                if btn:
                    btn.click()
                    print(f"[INFO] Cookie banner dismissed via: {sel}")
                    page.wait_for_load_state("networkidle", timeout=10000)
                    return
            except Exception:
                continue

    def _read_trim_names(self, page, selector: str) -> list[str]:
        names = []
        try:
            for el in page.query_selector_all(selector):
                name = clean_text(el.inner_text())
                if name:
                    names.append(name)
        except Exception as e:
            print(f"[WARN] Could not read trim headers: {e}")
        return names

    def _read_trim_prices(self, page, selector: str, expected: int) -> list[str]:
        prices = []
        try:
            for el in page.query_selector_all(selector):
                prices.append(clean_text(el.inner_text()))
        except Exception as e:
            print(f"[WARN] Could not read trim prices: {e}")
        # Pad to match trim count
        while len(prices) < expected:
            prices.append("")
        return prices

    def _extract_cell_value(self, cell) -> str:
        # 1. Try innerText first
        text = cell.inner_text().strip()
        if text:
            return text

        # 2. Try child element class / data-icon attribute (SVG icon fallback)
        try:
            child = cell.query_selector("[class]")
            if child:
                icon = child.get_attribute("data-icon") or ""
                if icon:
                    return icon

                cls = (child.get_attribute("class") or "").lower()
                if any(k in cls for k in ("standard", "filled", "included", "yes")):
                    return "●"
                if any(k in cls for k in ("optional", "available", "pkg")):
                    return "○"
                if any(k in cls for k in ("unavailable", "not-available", " na", "no")):
                    return "—"
        except Exception:
            pass

        # 3. aria-label fallback
        try:
            aria = cell.get_attribute("aria-label") or ""
            if aria:
                return aria.strip()
        except Exception:
            pass

        return ""

    def _extract_year(self, url: str) -> int:
        match = re.search(r"(20\d{2})", url)
        return int(match.group(1)) if match else datetime.now().year

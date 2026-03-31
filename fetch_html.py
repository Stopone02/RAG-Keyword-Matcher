"""
Step 1: HTML Fetcher
Run this first to capture raw HTML for selector analysis.

Usage:
    python fetch_html.py --brand kia --model soul
    python fetch_html.py --brand kia --model soul --no-headless

    # Lexus (URL이 바뀌지 않는 SPA — 수동으로 Compare 화면까지 이동 후 Resume)
    python fetch_html.py --brand lexus --model ux-hybrid --no-headless --pause
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def load_config(brand: str) -> dict:
    config_path = Path("configs") / f"{brand.lower()}.json"
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 1: Fetch raw HTML for selector analysis",
    )
    parser.add_argument("--brand", required=True, help="Brand name (e.g. kia)")
    parser.add_argument("--model", required=True, help="Model name (e.g. soul)")
    parser.add_argument(
        "--no-headless", action="store_true",
        help="Show browser window",
    )
    parser.add_argument(
        "--pause", action="store_true",
        help="Pause after page load so you can manually navigate to the target view, "
             "then resume in Playwright Inspector to save HTML. "
             "Requires --no-headless.",
    )
    return parser.parse_args()


def dismiss_cookie_banner(page, config: dict) -> None:
    cookie_selector = config.get("cookie_accept_selector")
    selectors_to_try = (
        [cookie_selector] if cookie_selector
        else [
            "button:has-text('Accept All')",
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
            "button:has-text('I Accept')",
            "button:has-text('Agree')",
            "button:has-text('OK')",
        ]
    )
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


def main() -> None:
    args = parse_args()
    config = load_config(args.brand)

    model_config = config["models"].get(args.model.lower())
    if not model_config:
        print(f"[ERROR] Model '{args.model}' not found in config. "
              f"Available: {list(config['models'].keys())}")
        sys.exit(1)

    url = model_config["url"]
    wait_strategy = config.get("wait_strategy", {})

    out_dir = Path("storage") / "html"
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / f"{args.brand.lower()}_{args.model.lower()}.html"
    shot_path = out_dir / f"{args.brand.lower()}_{args.model.lower()}.png"

    print(f"[INFO] Target URL: {url}")

    if args.pause and not args.no_headless:
        print("[WARN] --pause requires --no-headless. Adding --no-headless automatically.")
        args.no_headless = True

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.no_headless)
        page = browser.new_page()

        try:
            wait_until = wait_strategy.get("wait_until", "domcontentloaded")
            page.goto(url, wait_until=wait_until, timeout=60000)
        except PlaywrightTimeoutError:
            print(f"[ERROR] Timeout loading page: {url}")
            browser.close()
            sys.exit(1)

        dismiss_cookie_banner(page, config)

        wait_sel = wait_strategy.get("wait_for_selector")
        if wait_sel:
            try:
                page.wait_for_selector(wait_sel, timeout=30000)
                print(f"[INFO] Selector '{wait_sel}' found — page ready")
            except PlaywrightTimeoutError:
                print(f"[WARN] wait_for_selector '{wait_sel}' timed out — saving anyway")

        if args.pause:
            print("\n[PAUSE] 브라우저에서 원하는 화면(Compare 등)으로 이동하세요.")
            print("        준비되면 Playwright Inspector 창에서 [Resume] 버튼을 클릭하세요.\n")
            page.pause()

        # Save full HTML
        html_content = page.content()
        html_path.write_text(html_content, encoding="utf-8")
        print(f"[INFO] HTML saved  → {html_path}  ({len(html_content):,} chars)")

        # Save screenshot
        page.screenshot(path=str(shot_path), full_page=True)
        print(f"[INFO] Screenshot  → {shot_path}")

        browser.close()

    print("\n[DONE] Share the HTML file with Claude to analyze selectors,")
    print(f"       then update configs/{args.brand.lower()}.json and run main.py")


if __name__ == "__main__":
    main()
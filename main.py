import argparse
import json
import sys
from pathlib import Path

from engine.scraper import SpecScraper


def load_config(brand: str) -> dict:
    config_path = Path("configs") / f"{brand.lower()}.json"
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_result(data: dict, brand: str, model: str) -> Path:
    output_dir = Path("storage") / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{brand.lower()}_{model.lower()}_raw.json"
    output_path = output_dir / filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Saved → {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CarSpec Crawler — Playwright-based car spec scraper",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--brand", required=True, help="Brand name (e.g. kia)")
    parser.add_argument("--model", help="Model name (e.g. soul, telluride)")
    parser.add_argument(
        "--all", dest="all_models", action="store_true",
        help="Crawl all models defined in the brand config",
    )
    parser.add_argument(
        "--no-headless", action="store_true",
        help="Show browser window (useful for debugging)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.brand)
    headless = not args.no_headless

    if args.all_models:
        models_to_crawl = list(config["models"].keys())
    elif args.model:
        model_key = args.model.lower()
        if model_key not in config["models"]:
            print(f"[ERROR] Model '{args.model}' not found in config. "
                  f"Available: {list(config['models'].keys())}")
            sys.exit(1)
        models_to_crawl = [model_key]
    else:
        print("[ERROR] Specify --model <name> or --all")
        sys.exit(1)

    scraper = SpecScraper(config, headless=headless)
    results = []

    for model in models_to_crawl:
        print(f"\n{'='*60}")
        print(f"[INFO] Starting: {config['brand']} / {model.upper()}")
        print(f"{'='*60}")

        result = scraper.scrape_model(model)
        if result:
            path = save_result(result, args.brand, model)
            results.append(str(path))
        else:
            print(f"[WARN] No data collected for model '{model}'")

    print(f"\n[DONE] Completed {len(results)}/{len(models_to_crawl)} model(s)")
    for r in results:
        print(f"  → {r}")


if __name__ == "__main__":
    main()

"""
Mercedes-Benz Key Features 수집 실행 스크립트.

사용법:
  python run_benz_features.py --model c-class
  python run_benz_features.py --model c-class --no-headless
  python run_benz_features.py --model glc --model gla   (복수 모델)
  python run_benz_features.py --all                     (config의 전체 모델)

출력:
  storage/csv/benz_features.xlsx  — 모델별 시트
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from engine.benz_features_scraper import BenzFeaturesScraper


CONFIG_PATH = Path(__file__).parent / "configs" / "benz_features.json"


def main():
    parser = argparse.ArgumentParser(description="Benz Key Features scraper")
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        metavar="MODEL",
        help="수집할 모델명 (여러 번 지정 가능). 예: --model c-class --model glc",
    )
    parser.add_argument("--all", action="store_true", help="config의 전체 모델 수집")
    parser.add_argument(
        "--no-headless", action="store_true", help="브라우저 UI 표시 (디버깅용)"
    )
    parser.add_argument(
        "--output-dir", default="storage/csv", help="Excel 저장 디렉토리 (default: storage/csv)"
    )
    parser.add_argument(
        "--output-file", default="benz_features.xlsx", help="출력 파일명 (default: benz_features.xlsx)"
    )
    args = parser.parse_args()

    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    scraper = BenzFeaturesScraper(config, headless=not args.no_headless)

    target_models: list[str]
    if args.all:
        target_models = list(config["models"].keys())
    elif args.models:
        target_models = args.models
    else:
        parser.print_help()
        print("\n[ERROR] --model 또는 --all 을 지정하세요.")
        sys.exit(1)

    print(f"[INFO] Target models: {target_models}")
    print(f"[INFO] Headless: {not args.no_headless}")
    print(f"[INFO] Output: {args.output_dir}/{args.output_file}\n")

    all_model_data = []

    for model in target_models:
        print(f"\n{'='*60}")
        print(f"  Model: {model}")
        print(f"{'='*60}")

        data = scraper.scrape_model(model)
        if data is None:
            print(f"[ERROR] No data collected for model: {model}")
            continue

        all_model_data.append(data)

        # 결과 요약
        trim_names = data["trim_names"]
        rows = data["rows"]
        print(f"\n[RESULT] {model}")
        print(f"  Trims   : {len(trim_names)}")
        print(f"  Features: {len(rows)} total rows")
        for cat in config["categories"]:
            cat_rows = [r for r in rows if r["category"] == cat]
            print(f"    {cat:15s}: {len(cat_rows)}")

    if all_model_data:
        excel_path = scraper.save_excel(
            all_model_data,
            output_dir=args.output_dir,
            filename=args.output_file,
        )
        print(f"\n[DONE] Excel saved → {excel_path}")
    else:
        print("\n[WARN] No data collected.")


if __name__ == "__main__":
    main()

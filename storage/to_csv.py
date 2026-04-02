"""
Convert raw JSON files in storage/raw/ to CSV.

Output layout:
  rows    = feature names
  columns = Brand | Model | Year | Category | Feature | Trim1 | Trim2 | ...

Usage:
    python storage/to_csv.py                          # convert all JSON files
    python storage/to_csv.py lexus_ux-hybrid_raw.json # convert specific file
"""

import csv
import json
import sys
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw"
OUT_DIR = Path(__file__).parent / "csv"


def _entry_value(entry) -> str:
    """features 값이 dict(신형) 또는 str(구형) 모두 처리."""
    if isinstance(entry, dict):
        return entry.get("value", "Unavailable") or "Unavailable"
    return entry or "Unavailable"


def _entry_category(entry) -> str:
    if isinstance(entry, dict):
        return entry.get("category", "")
    return ""


def convert(json_path: Path) -> Path:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    brand = data.get("brand", "")
    model = data.get("model", "")
    year = data.get("year", "")
    trims = data.get("trims", {})

    if not trims:
        print(f"[WARN] No trim data in {json_path.name} — skipping")
        return None

    trim_names = list(trims.keys())

    # 카테고리 첫 등장 순서 기록 + feature 수집 (수집 순서 유지)
    all_features: list[str] = []
    feature_category: dict[str, str] = {}
    cat_order: list[str] = []       # 카테고리 첫 등장 순서
    seen_feats: set[str] = set()
    seen_cats: set[str] = set()
    for trim_data in trims.values():
        for feat, entry in trim_data.get("features", {}).items():
            cat = _entry_category(entry)
            if cat and cat not in seen_cats:
                cat_order.append(cat)
                seen_cats.add(cat)
            if feat not in seen_feats:
                all_features.append(feat)
                feature_category[feat] = cat
                seen_feats.add(feat)

    # 카테고리 첫 등장 순서대로 정렬, 같은 카테고리 내에서는 수집 순서 유지
    cat_rank = {c: i for i, c in enumerate(cat_order)}
    all_features.sort(key=lambda f: cat_rank.get(feature_category.get(f, ""), len(cat_order)))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / json_path.name.replace("_raw.json", ".csv")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)

        # Header row
        writer.writerow(["Brand", "Model", "Year", "Category", "Feature"] + trim_names)

        # Data rows
        for feat in all_features:
            row = [brand, model, year, feature_category.get(feat, ""), feat]
            for trim in trim_names:
                entry = trims[trim].get("features", {}).get(feat, "Unavailable")
                row.append(_entry_value(entry))
            writer.writerow(row)

    print(f"[OK] {json_path.name} → {out_path.name}  "
          f"({len(all_features)} features × {len(trim_names)} trims)")
    return out_path


def main():
    if len(sys.argv) > 1:
        targets = [RAW_DIR / sys.argv[1]]
    else:
        targets = sorted(RAW_DIR.glob("*.json"))

    if not targets:
        print(f"[ERROR] No JSON files found in {RAW_DIR}")
        sys.exit(1)

    results = []
    for path in targets:
        if not path.exists():
            print(f"[ERROR] File not found: {path}")
            continue
        out = convert(path)
        if out:
            results.append(out)

    print(f"\n[DONE] Converted {len(results)} file(s) → {OUT_DIR}")


if __name__ == "__main__":
    main()

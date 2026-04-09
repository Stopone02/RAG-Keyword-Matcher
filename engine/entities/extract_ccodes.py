"""
configurations JSON에서 ccode + lowerLevelPackage 추출.

사용법:
  python extract_ccodes.py <input.json>

  input.json 이 없으면 stdin에서 읽음.
  예) curl ... | python extract_ccodes.py

LONE STAR 포함 트림은 제외, (ccode, lowerLevelPackage) 중복 제거.
"""

import json
import sys


EXCLUDE_KEYWORDS = ["LONE STAR"]


def extract(data: dict) -> list[dict]:
    seen = set()
    results = []

    for cfg in data.get("configurations", []):
        desc = cfg.get("descriptions", {}).get("longDescription", "")
        if any(kw in desc.upper() for kw in EXCLUDE_KEYWORDS):
            continue

        ccode = cfg.get("ccode", "")
        llp = cfg.get("lowerLevelPackage", "")
        key = (ccode, llp)
        if key in seen:
            continue
        seen.add(key)

        results.append({"ccode": ccode, "lowerLevelPackage": llp, "description": desc})

    return results


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    results = extract(data)

    print(f"{'#':<4} {'ccode':<30} {'llp':<8} description")
    print("-" * 90)
    for i, r in enumerate(results, 1):
        print(f"{i:<4} {r['ccode']:<30} {r['lowerLevelPackage']:<8} {r['description']}")

    print(f"\n총 {len(results)}개")


if __name__ == "__main__":
    main()

"""
Ram Trucks specs scraper — API 기반 (HTML 파싱 없음).

────────────────────────────────────────────────────────────
구조 개요
────────────────────────────────────────────────────────────
Phase 1  CVD API → 전체 조합 열거
  GET /hostd/api/cvd/{MYC}/{MYC}_CVD.json
    configurations[]  →  ccode, llp, filterCombinations
    filterGroups[]    →  Drive / Cab / Box / Trim 이름 매핑
  → (drive, cab, box) 그룹별 ccode 목록 구성
  → 그룹마다 최대 4개씩 묶어 API 호출 준비

Phase 2  configuration-compare API → 스펙 데이터 수집
  POST /hostd/api/configuration-compare/compare
  Body: {"stateCode":"NY","models":[{"code":..,"llpCode":..,"configuration":"standard"},...]}
  Response:
    competitors[]          → referenceId, description(트림명), prices.base
    compare{specId}        → description(스펙명), comparison{referenceId}.text(값)
    sections{key}          → groupings[] 목록
    groupings{grpId}       → description(카테고리명), compareIds[]

────────────────────────────────────────────────────────────
Config 예시 (configs/ram.json)
────────────────────────────────────────────────────────────
  "1500-dt": {
    "vehicle_code": "ram_1500_dt",
    "model_year_codes": ["CUT202620", "CUT202520"]
  }
  modelYearCode 형식: CUT{YEAR}20  (예: 2026 → CUT202620)
"""

import json
import random
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

CVD_API = "https://www.ramtrucks.com/hostd/api/cvd/{myc}/{myc}_CVD.json"
COMPARE_API = "https://www.ramtrucks.com/hostd/api/configuration-compare/compare"
STATE_CODE = "NY"


class RamSpecScraper:

    def __init__(self, config: dict, headless: bool = True):
        self.config = config
        self.headless = headless
        self.brand = config["brand"]

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def scrape_model(self, model: str) -> list[dict] | None:
        """연도별로 분리된 결과 dict 리스트를 반환합니다."""
        model_cfg = self.config["models"].get(model)
        if not model_cfg:
            print(f"[WARN] Model config not found: {model}")
            return None

        mycs = model_cfg["model_year_codes"]
        # year → {trims, source_calls}
        year_data: dict[str, dict] = {}

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = ctx.new_page()

            # 세션 워밍업 (쿠키 + 봇 감지 회피)
            self._warm_up_session(page)

            for myc in mycs:
                year = myc[3:7]
                print(f"\n{'='*60}")
                print(f"[INFO] Year {year} ({myc})")
                print(f"{'='*60}")

                year_data.setdefault(year, {"trims": {}, "source_calls": []})
                year_trims = year_data[year]["trims"]
                year_calls = year_data[year]["source_calls"]

                # Phase 1: CVD API → ccode 그룹
                allowed_trims = model_cfg.get("allowed_trims")
                excluded_trims = model_cfg.get("excluded_trims")
                groups = self._fetch_cvd_groups(page, myc, allowed_trims=allowed_trims, excluded_trims=excluded_trims)
                if not groups:
                    print(f"[WARN] No groups for {myc}")
                    continue

                total_unique = sum(len(v) for v in groups.values())
                print(f"[INFO] {total_unique} unique trims / {len(groups)} groups")
                for (drive, cab, box), trims in sorted(groups.items()):
                    print(f"       {drive} | {cab} | {box}: {[t['trim'] for t in trims]}")

                # Phase 2: 그룹당 최대 4개씩 compare API 호출
                for (drive, cab, box), trims in sorted(groups.items()):
                    for i in range(0, len(trims), 4):
                        chunk = trims[i: i + 4]
                        delay = random.uniform(2.0, 5.0)
                        print(f"\n[INFO] ({drive}|{cab}|{box}) chunk {i//4+1} - wait {delay:.1f}s")
                        time.sleep(delay)

                        batch = self._call_compare_api(page, chunk)
                        if batch is None:
                            continue

                        year_calls.append({
                            "drive": drive, "cab": cab, "box": box, "year": year,
                            "codes": [t["ccode"] for t in chunk],
                        })
                        for trim_name, trim_data in batch.items():
                            if trim_name not in year_trims:
                                year_trims[trim_name] = trim_data
                                print(f"[INFO] Added trim: {trim_name}")
                            else:
                                existing = year_trims[trim_name]
                                if not existing["price_msrp"] and trim_data["price_msrp"]:
                                    existing["price_msrp"] = trim_data["price_msrp"]
                                for feat, entry in trim_data["features"].items():
                                    existing["features"].setdefault(feat, entry)

            ctx.close()
            browser.close()

        if not year_data:
            return None

        crawled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        results = []
        for year, yd in sorted(year_data.items(), reverse=True):
            if not yd["trims"]:
                continue
            print(f"\n[INFO] Year {year}: {len(yd['trims'])} trims collected")
            results.append({
                "brand": self.brand,
                "model": model,
                "year": year,
                "crawled_at": crawled_at,
                "source_api": COMPARE_API,
                "source_calls": yd["source_calls"],
                "trims": yd["trims"],
            })

        return results if results else None

    # ──────────────────────────────────────────────────────────────────
    # Phase 1: CVD API → (drive, cab, box) 그룹별 ccode 목록
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_trim_name(name: str) -> str:
        """비교용 트림명 정규화: 특수문자 제거, 대문자, 공백 정리."""
        import re
        return re.sub(r"[^A-Z0-9 ]", "", name.upper()).strip()

    def _fetch_cvd_groups(
        self, page, myc: str,
        allowed_trims: list | None = None,
        excluded_trims: list | None = None,
    ) -> dict | None:
        api_url = CVD_API.format(myc=myc)
        print(f"[INFO] Fetching CVD: {api_url}")
        try:
            resp = page.request.get(api_url, timeout=30000)
            if not resp.ok:
                print(f"[ERROR] CVD {resp.status}")
                return None
            data = resp.json()
        except Exception as e:
            print(f"[ERROR] CVD fetch: {e}")
            return None

        filter_map = {
            fg["id"]: {f["id"]: f["description"] for f in fg["filters"]}
            for fg in data.get("filterGroups", [])
        }

        # 허용/제외 트림 정규화 집합
        allowed_set = (
            {self._normalize_trim_name(t) for t in allowed_trims}
            if allowed_trims else None
        )
        excluded_set = (
            {self._normalize_trim_name(t) for t in excluded_trims}
            if excluded_trims else None
        )

        groups: dict = {}
        seen: set = set()
        for cfg in data.get("configurations", []):
            fc = cfg.get("filterCombinations", {})
            drive = filter_map.get("filterGroup1", {}).get(fc.get("filterGroup1", {}).get("id"), "?")
            cab   = filter_map.get("filterGroup2", {}).get(fc.get("filterGroup2", {}).get("id"), "?")
            box   = filter_map.get("filterGroup4", {}).get(fc.get("filterGroup4", {}).get("id"), "?")
            trim  = filter_map.get("filterGroup5", {}).get(fc.get("filterGroup5", {}).get("id"), "Unknown")

            norm_trim = self._normalize_trim_name(trim)

            # allowed_trims 필터링 (filterGroup5 기준)
            if allowed_set and norm_trim not in allowed_set:
                continue

            # excluded_trims 필터링 (filterGroup5 기준)
            if excluded_set and norm_trim in excluded_set:
                continue

            # dedup 키: drive + longDescription の組み合わせで重複排除
            # → ProMaster のように追加グレードが別 filterGroup にある場合も全組み合わせを収集
            # → トラック系で drive(4X2/4X4)が異なるが longDescription が同一な場合も区別
            long_desc = cfg.get("descriptions", {}).get("longDescription", "")
            dedup = (drive, long_desc) if long_desc else (drive, cab, box, trim)
            if dedup in seen:
                continue
            seen.add(dedup)
            groups.setdefault((drive, cab, box), []).append(
                {"ccode": cfg["ccode"], "llp": cfg["lowerLevelPackage"], "trim": trim}
            )
        return groups

    # ──────────────────────────────────────────────────────────────────
    # Phase 2: compare API 호출 → 트림별 스펙 dict 반환
    # ──────────────────────────────────────────────────────────────────

    def _call_compare_api(self, page, chunk: list) -> dict | None:
        """
        chunk: [{"ccode": ..., "llp": ..., "trim": ...}, ...]
        returns: {trim_description: {"price_msrp": ..., "features": {...}}}
        """
        body = {
            "stateCode": STATE_CODE,
            "models": [
                {"code": t["ccode"], "llpCode": t["llp"], "configuration": "standard"}
                for t in chunk
            ],
        }
        ccodes_str = ", ".join(t["ccode"] for t in chunk)
        print(f"[INFO] Compare API → {ccodes_str}")

        try:
            resp = page.request.post(
                COMPARE_API,
                data=json.dumps(body),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=30000,
            )
        except Exception as e:
            print(f"[ERROR] Compare API request: {e}")
            return None

        if not resp.ok:
            print(f"[ERROR] Compare API status {resp.status}")
            return None

        try:
            data = resp.json()
        except Exception as e:
            print(f"[ERROR] Compare API JSON parse: {e}")
            return None

        return self._parse_compare_response(data)

    # ──────────────────────────────────────────────────────────────────
    # JSON 응답 파싱
    # ──────────────────────────────────────────────────────────────────

    def _parse_compare_response(self, data: dict) -> dict | None:
        """
        사이트 탭 기준 파싱.

        사이트 탭 구조 (equipment-categories.views):
          View 1: Powertrain   → subCategories → options (state: S/C/U)
          View 2: Packages     → subCategories → options
          View 3: Exterior     → subCategories → options
          View 4: Interior     → subCategories → options

        수치 사양 (sections.dimensions → groupings.grpSpecsAndDim → compare):
          Dimensions: Specs and Dimensions 그루핑

        가격 (sections.highlights → grpHighlightsPricing → compare):
          Pricing: Base Price, Destination Fee, Net Price

        option 가용성 판별:
          state='S' OR standard=True           → standard
          state='C'                             → optional
          state='U' + msrp>0                   → optional (선택 가능, 미선택)
          pricing.included=True + standard=False → optional (패키지/엔진 구성에 따라 포함)
          그 외                                 → not available
        """
        competitors = data.get("competitors", [])
        if not competitors:
            print("[WARN] No competitors in response")
            return None

        # referenceId → {name, price}
        ref_map: dict = {
            c["referenceId"]: {
                "name": f"{c['year']} {c.get('description', '')}".strip() if c.get("year") else c.get("description", ""),
                "price": c.get("prices", {}).get("base", 0.0),
            }
            for c in competitors
        }

        result = {
            info["name"]: {
                "price_msrp": f"${info['price']:,.0f}" if info["price"] else "",
                "features": {},
            }
            for info in ref_map.values()
            if info["name"]
        }

        ec = data.get("equipment-categories", {})
        views = ec.get("views", {})
        subcats = ec.get("subCategories", {})
        options = data.get("options", {})
        compare = data.get("compare", {})
        groupings = data.get("groupings", {})

        # ── Part 1: 사이트 탭 (View 1~4) ─────────────────────────────────
        # 수집 순서: view → 트림별 subCategory 순서(order) → 옵션 순서(order)
        # 동일 피쳐명이 이미 있으면 덮어쓰지 않음 (variation만 다른 중복 옵션 처리)
        seen_feats_by_trim: dict[str, set] = {name: set() for name in result}

        for view_id in sorted(views.keys(), key=lambda x: int(x)):
            view_data = views[view_id]
            view_name = view_data.get("description", f"View {view_id}")

            # 트림마다 subCategory 순서 → 옵션 순서대로 수집
            for ref_id, info in ref_map.items():
                if not info["name"]:
                    continue
                trim_name = info["name"]
                ref_view_data = view_data.get("models", {}).get(ref_id, {})
                sc_id_order = [str(s) for s in ref_view_data.get("subCategories", [])]
                sc_set = set(sc_id_order)

                # 이 트림 × 이 view에 해당하는 옵션 수집 후 (sc_id 순서, opt order) 정렬
                entries = []
                for opt_key, opt_data in options.items():
                    m = opt_data.get("models", {}).get(ref_id)
                    if not m:
                        continue
                    sc_id = str(m.get("subCategoryId", ""))
                    if sc_id not in sc_set:
                        continue
                    sc_rank = sc_id_order.index(sc_id)
                    opt_order = m.get("order", 9999)
                    entries.append((sc_rank, opt_order, opt_key, opt_data, m, sc_id))

                entries.sort(key=lambda x: (x[0], x[1]))

                for sc_rank, opt_order, opt_key, opt_data, m, sc_id in entries:
                    feat_name = opt_data.get("description", opt_key)
                    sc = subcats.get(sc_id, {})
                    cat = sc.get("description", view_name)
                    state = m.get("state", "")
                    is_standard = m.get("standard", False)
                    pricing = m.get("pricing", {})
                    msrp = pricing.get("msrp", 0) or 0
                    is_included = pricing.get("included", False)
                    if state == "S" or is_standard:
                        value = "standard"
                    elif state == "C" or (state == "U" and msrp > 0) or is_included:
                        value = "optional"
                    else:
                        value = "not available"

                    if feat_name not in seen_feats_by_trim[trim_name]:
                        seen_feats_by_trim[trim_name].add(feat_name)
                        result[trim_name]["features"][feat_name] = {"value": value, "category": cat}

        # ── Part 2: 모든 groupings의 스펙 텍스트/수치 값 수집 ───────────────
        # compare dict의 모든 grouping을 순회하여 누락 없이 수집.
        # - PKG-* compareId는 Views(Part 1)에서 이미 options로 처리됨 → 스킵
        # - total-price는 사이트 표시명 net-price로 alias
        # - 중복 compareId는 첫 번째 grouping 기준으로 처리 (first-wins)
        # - 같은 피처가 Part 1(options)에서 이미 수집된 경우 spec 텍스트값으로 덮어씀
        _CID_ALIAS = {"total-price": "net-price"}
        seen_cids: set = set()

        for grp_v in groupings.values():
            cat = grp_v.get("description", "")
            for cid in grp_v.get("compareIds", []):
                cid_str = str(cid)
                # PKG-* 는 View 2(Packages)에서 options로 처리됨
                if cid_str.startswith("PKG-"):
                    continue
                actual_cid = _CID_ALIAS.get(cid_str, cid_str)
                if actual_cid in seen_cids:
                    continue
                seen_cids.add(actual_cid)

                spec = compare.get(actual_cid)
                if not spec:
                    continue
                feat_name = spec.get("description", actual_cid)
                for ref_id, val_data in spec.get("comparison", {}).items():
                    info = ref_map.get(ref_id)
                    if not info or not info["name"]:
                        continue
                    trim_name = info["name"]
                    text = val_data.get("text") or ""
                    numeric = val_data.get("numeric")
                    value = self._normalize_spec_value(text, numeric)
                    if value != "not available":
                        result[trim_name]["features"][feat_name] = {"value": value, "category": cat}

        feat_counts = [len(v["features"]) for v in result.values()]
        print(f"[DEBUG] Parsed {len(result)} trims, features/trim: {feat_counts}")
        return result

    # ──────────────────────────────────────────────────────────────────
    # 값 정규화
    # ──────────────────────────────────────────────────────────────────

    _UNAVAILABLE_WORDS = {"not available", "unavailable", "n/a"}

    @staticmethod
    def _normalize_spec_value(text: str, numeric) -> str:
        """Dimensions/Pricing 수치 사양용 정규화.
        text가 있으면 그대로, 없으면 numeric을 문자열로 반환."""
        if text:
            return text
        if numeric is not None and numeric != "":
            return str(numeric)
        return "not available"

    @staticmethod
    def _normalize_value(
        text: str,
        standard: bool,
        options: list,
        feat_desc: str,
        numeric=None,
    ) -> str:
        """
        우선순위:
          1. text가 유효한 수치/문자 값 → 그대로 사용
               - "available"       → "optional"
               - "unavailable"     → "not available"
          2. text가 없거나 feature 이름과 동일 → standard/options/numeric으로 판별
               - numeric 값 존재   → str(numeric)
               - standard=True     → "standard"
               - options 있음      → "optional"
               - 그 외             → "not available"
        """
        UNAVAILABLE = {"not available", "unavailable", "n/a", "na", "not avail"}

        if text and text != feat_desc:
            t_lower = text.lower().strip()
            if t_lower == "yes":
                return "standard"
            if t_lower == "available":
                return "optional"
            if t_lower in UNAVAILABLE or t_lower == "no":
                return "not available"
            return text

        # text 없음 or text == feature 이름
        # numeric=0은 패키지 포함 여부($0=포함)를 의미 → standard/options로 판별
        if numeric is not None and numeric != "" and numeric != 0:
            return str(numeric)
        if standard:
            return "standard"
        if options:
            return "optional"
        return "not available"

    # ──────────────────────────────────────────────────────────────────
    # 세션 초기화 (쿠키 + 봇 감지 우회)
    # ──────────────────────────────────────────────────────────────────

    def _warm_up_session(self, page) -> None:
        print("[INFO] Warming up session...")
        try:
            page.goto("https://www.ramtrucks.com/", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[WARN] Warm-up failed: {e}")
            return

        # 쿠키 배너
        for sel in [
            "button:has-text('Accept All')",
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
        ]:
            try:
                btn = page.wait_for_selector(sel, timeout=3000)
                if btn:
                    btn.click()
                    print("[INFO] Cookie banner dismissed")
                    break
            except Exception:
                continue

        time.sleep(random.uniform(2.0, 4.0))
        print("[INFO] Session ready")

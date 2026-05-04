"""
동작구 24시간 운영 점포 수집 스크립트
카카오 로컬 키워드 검색 API 사용
- 상호명에 '24시' 포함된 점포 자동 수집
출력: open24_dongjak.csv (name, lat, lng, category)
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import math
import os
import time

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../backend/.env"))
API_KEY = os.environ["KAKAO_REST_API_KEY"]

# ── 동작구 격자 설정 ────────────────────────────────────────────
MIN_LAT, MAX_LAT = 37.470, 37.525
MIN_LNG, MAX_LNG = 126.905, 126.980
STEP_M   = 600
RADIUS_M = 700

LAT_M = 111_320
LNG_M = 111_320 * math.cos(math.radians(37.49))
STEP_LAT = STEP_M / LAT_M
STEP_LNG = STEP_M / LNG_M

SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
HEADERS    = {"Authorization": f"KakaoAK {API_KEY}"}

# 상호명 24시간 키워드 패턴
HOUR24_KEYWORDS = ["24시", "24시간", "24H", "24h", "이십사시", "24"]


def contains_24h(name: str) -> bool:
    return any(kw in name for kw in HOUR24_KEYWORDS)


def keyword_search(query: str, x: float, y: float, page: int = 1) -> dict:
    params = {
        "query":  query,
        "x":      x,        # 경도
        "y":      y,        # 위도
        "radius": RADIUS_M,
        "size":   15,
        "page":   page,
    }
    resp = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=10)
    if resp.status_code != 200:
        print(f"  [오류] {resp.status_code}: {resp.text[:150]}")
        return {}
    return resp.json()


# ── 격자 생성 ───────────────────────────────────────────────────
lat_pts = np.arange(MIN_LAT, MAX_LAT + STEP_LAT, STEP_LAT)
lng_pts = np.arange(MIN_LNG, MAX_LNG + STEP_LNG, STEP_LNG)
total_pts = len(lat_pts) * len(lng_pts)
print(f"격자: {len(lat_pts)} × {len(lng_pts)} = {total_pts}개 지점\n")

seen_ids: set = set()
results:  list = []

for i, lat in enumerate(lat_pts):
    for j, lng in enumerate(lng_pts):
        added = 0
        for page in range(1, 4):   # 최대 3페이지 (45건)
            data = keyword_search("24시", x=lng, y=lat, page=page)
            docs = data.get("documents", [])
            meta = data.get("meta", {})

            for doc in docs:
                pid  = doc.get("id", "")
                name = doc.get("place_name", "")

                if pid in seen_ids:
                    continue
                if not contains_24h(name):
                    continue

                seen_ids.add(pid)
                results.append({
                    "name":     name,
                    "lat":      float(doc.get("y", 0)),
                    "lng":      float(doc.get("x", 0)),
                    "category": doc.get("category_name", ""),
                    "address":  doc.get("road_address_name") or doc.get("address_name", ""),
                })
                added += 1

            if meta.get("is_end", True):
                break
            time.sleep(0.1)

        idx = i * len(lng_pts) + j + 1
        print(f"  [{idx:>3}/{total_pts}] ({lat:.4f}, {lng:.4f}) → {added}개 추가 (누적 {len(results)}개)")
        time.sleep(0.12)

# ── 저장 ────────────────────────────────────────────────────────
df = pd.DataFrame(results).drop_duplicates(subset=["name", "lat", "lng"])
out_path = os.path.join(os.path.dirname(__file__), "open24_dongjak.csv")
df.to_csv(out_path, index=False, encoding="utf-8-sig")

print(f"\n✓ 저장 완료: {out_path}")
print(f"  자동 수집: {len(df)}개\n")
if not df.empty:
    print("[카테고리별]")
    print(df["category"].value_counts().to_string())

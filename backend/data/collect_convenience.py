import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import requests
import csv
import time
import numpy as np
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("KAKAO_REST_API_KEY")

# ── 1. 관악구 경계 ────────────────────────────────────────────────
MIN_LAT, MAX_LAT = 37.440, 37.496
MIN_LNG, MAX_LNG = 126.898, 126.985

# ── 2. 격자 중심점 생성 (450m 간격) ───────────────────────────────
STEP = 0.004
lat_points = np.arange(MIN_LAT, MAX_LAT + STEP, STEP)
lng_points = np.arange(MIN_LNG, MAX_LNG + STEP, STEP)

print(f"요청 격자 수: {len(lat_points)} × {len(lng_points)} = {len(lat_points)*len(lng_points)}개")

# ── 3. 카카오 카테고리 검색 API 호출 ─────────────────────────────
def search_convenience(lat, lng, radius=500):
    url = "https://dapi.kakao.com/v2/local/search/category.json"
    headers = {"Authorization": f"KakaoAK {API_KEY}"}
    results = []

    for page in range(1, 4):
        params = {
            "category_group_code": "CS2",
            "x": lng,
            "y": lat,
            "radius": radius,
            "page": page,
            "size": 15,
        }
        res = requests.get(url, headers=headers, params=params)
        if res.status_code != 200:
            print(f"  API 오류: {res.status_code}")
            break

        data = res.json()
        docs = data.get("documents", [])
        results.extend(docs)

        if data["meta"]["is_end"]:
            break

    return results

# ── 4. 전체 격자 순회 ─────────────────────────────────────────────
all_stores = {}  # place_id 기준 중복 제거
total = len(lat_points) * len(lng_points)
count = 0

for lat in lat_points:
    for lng in lng_points:
        count += 1
        stores = search_convenience(lat, lng)
        for s in stores:
            pid = s["id"]
            if pid not in all_stores:
                all_stores[pid] = s
        time.sleep(0.1)

    print(f"  진행: {count}/{total} | 수집된 편의점: {len(all_stores)}개")

print(f"\n총 {len(all_stores)}개 편의점 수집 완료")

# ── 5. CSV 저장 ───────────────────────────────────────────────────
output_path = "convenience_gwanak.csv"
with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["name", "lat", "lng", "address", "score"])
    for s in all_stores.values():
        writer.writerow([
            s["place_name"],
            s["y"],
            s["x"],
            s.get("road_address_name") or s.get("address_name", ""),
            5,
        ])

print(f"✓ {output_path} 저장 완료")

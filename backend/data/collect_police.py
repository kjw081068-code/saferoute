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

# ── 3. 카카오 키워드 검색 API 호출 ───────────────────────────────
KEYWORDS = ["경찰서", "지구대", "파출소"]

def search_police(keyword, lat, lng, radius=1000):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {API_KEY}"}
    results = []

    for page in range(1, 4):
        params = {
            "query": keyword,
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

# ── 4. 전체 격자 × 키워드 순회 ───────────────────────────────────
all_places = {}  # place_id 기준 중복 제거
total = len(lat_points) * len(lng_points) * len(KEYWORDS)
count = 0

for lat in lat_points:
    for lng in lng_points:
        for keyword in KEYWORDS:
            count += 1
            places = search_police(keyword, lat, lng)
            for p in places:
                pid = p["id"]
                if pid not in all_places:
                    all_places[pid] = p
            time.sleep(0.1)

    print(f"  진행: {count}/{total} | 수집된 경찰서/지구대/파출소: {len(all_places)}개")

print(f"\n총 {len(all_places)}개 수집 완료")

# ── 5. 관악구 경계 내 필터링 ─────────────────────────────────────
filtered = {}
for pid, p in all_places.items():
    try:
        lat_v = float(p["y"])
        lng_v = float(p["x"])
    except (ValueError, KeyError):
        continue
    if MIN_LAT <= lat_v <= MAX_LAT and MIN_LNG <= lng_v <= MAX_LNG:
        filtered[pid] = p

print(f"관악구 경계 내 필터링 후: {len(filtered)}개")
for p in filtered.values():
    print(f"  - {p['place_name']} ({p['y']}, {p['x']})")

# ── 6. CSV 저장 ───────────────────────────────────────────────────
output_path = "police_gwanak.csv"
with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["name", "lat", "lng", "address"])
    for p in filtered.values():
        writer.writerow([
            p["place_name"],
            p["y"],
            p["x"],
            p.get("road_address_name") or p.get("address_name", ""),
        ])

print(f"✓ {output_path} 저장 완료")

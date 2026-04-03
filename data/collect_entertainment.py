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

# ── 2. 검색 키워드 목록 ───────────────────────────────────────────
KEYWORDS = ["단란주점", "룸살롱", "룸싸롱", "룸사롱", "룸바", "유흥주점", "풀살롱", "노래빠"]

# ── 유흥시설 카테고리만 허용 (일반 노래방 자동 제외) ────────────
def is_valid(store):
    category = store.get("category_name", "")
    # 카카오 카테고리에 "유흥시설" 포함된 것만 허용
    return "유흥시설" in category

# ── 3. 격자 중심점 생성 (450m 간격) ───────────────────────────────
STEP = 0.004
lat_points = np.arange(MIN_LAT, MAX_LAT + STEP, STEP)
lng_points = np.arange(MIN_LNG, MAX_LNG + STEP, STEP)

print(f"요청 격자 수: {len(lat_points)} × {len(lng_points)} = {len(lat_points)*len(lng_points)}개")

# ── 4. 카카오 키워드 검색 API 호출 ────────────────────────────────
def search_keyword(keyword, lat, lng, radius=500):
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

# ── 5. 전체 키워드 × 격자 순회 ───────────────────────────────────
all_stores = {}  # place_id 기준 중복 제거
total = len(lat_points) * len(lng_points)

for keyword in KEYWORDS:
    print(f"\n[키워드: {keyword}] 검색 시작", flush=True)
    count = 0
    for lat in lat_points:
        for lng in lng_points:
            count += 1
            stores = search_keyword(keyword, lat, lng)
            for s in stores:
                pid = s["id"]
                if pid not in all_stores and is_valid(s):
                    all_stores[pid] = s
            print(f"  [{keyword}] {count}/{total} | 수집: {len(all_stores)}개", end="\r", flush=True)
            time.sleep(0.1)

print(f"\n전체 수집 완료: {len(all_stores)}개 (중복 제거 전)")

# ── 6. 관악구 주소 기준 필터링 ───────────────────────────────────
filtered = {}
for pid, s in all_stores.items():
    address = s.get("road_address_name") or s.get("address_name", "")
    if "관악구" in address:
        filtered[pid] = s

print(f"관악구 내 유흥시설: {len(filtered)}개")

# ── 7. 결과 출력 (확인용) ─────────────────────────────────────────
print("\n[수집된 업소 목록]")
for s in filtered.values():
    print(f"  {s['place_name']} | {s.get('category_name', '')} | {s.get('road_address_name') or s.get('address_name', '')}")

# ── 8. CSV 저장 ───────────────────────────────────────────────────
output_path = "entertainment_gwanak.csv"
with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["name", "lat", "lng", "address"])
    for s in filtered.values():
        writer.writerow([
            s["place_name"],
            s["y"],
            s["x"],
            s.get("road_address_name") or s.get("address_name", ""),
        ])

print(f"\n✓ {output_path} 저장 완료")

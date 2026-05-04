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

MIN_LAT, MAX_LAT = 37.490, 37.535814
MIN_LNG, MAX_LNG = 126.916, 126.988477
STEP = 0.004

lat_points = np.arange(MIN_LAT, MAX_LAT + STEP, STEP)
lng_points = np.arange(MIN_LNG, MAX_LNG + STEP, STEP)
print(f"요청 격자 수: {len(lat_points)} × {len(lng_points)} = {len(lat_points)*len(lng_points)}개")

KEYWORDS = ["소방서", "119안전센터", "119지역대"]

def search(keyword, lat, lng, radius=1000):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {API_KEY}"}
    results = []
    for page in range(1, 4):
        params = {"query": keyword, "x": lng, "y": lat, "radius": radius, "page": page, "size": 15}
        res = requests.get(url, headers=headers, params=params)
        if res.status_code != 200:
            break
        data = res.json()
        results.extend(data.get("documents", []))
        if data["meta"]["is_end"]:
            break
    return results

all_places = {}
total = len(lat_points) * len(lng_points) * len(KEYWORDS)
count = 0

for lat in lat_points:
    for lng in lng_points:
        for keyword in KEYWORDS:
            count += 1
            for p in search(keyword, lat, lng):
                if p["id"] not in all_places:
                    all_places[p["id"]] = p
            time.sleep(0.1)
    print(f"  진행: {count}/{total} | 수집: {len(all_places)}개")

filtered = {
    pid: p for pid, p in all_places.items()
    if MIN_LAT <= float(p["y"]) <= MAX_LAT and MIN_LNG <= float(p["x"]) <= MAX_LNG
}

print(f"\n동작구 내 소방서/119안전센터: {len(filtered)}개")
for p in filtered.values():
    print(f"  - {p['place_name']} ({p['y']}, {p['x']})")

output_path = "firestation_dongjak.csv"
with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["name", "lat", "lng", "address"])
    for p in filtered.values():
        writer.writerow([p["place_name"], p["y"], p["x"],
                         p.get("road_address_name") or p.get("address_name", "")])

print(f"✓ {output_path} 저장 완료")

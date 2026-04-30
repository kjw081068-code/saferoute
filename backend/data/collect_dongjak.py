import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import requests, csv, time, numpy as np, os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
API_KEY = os.getenv("KAKAO_REST_API_KEY")

MIN_LAT, MAX_LAT = 37.490, 37.535
MIN_LNG, MAX_LNG = 126.916, 126.988
STEP = 0.004
lat_pts = np.arange(MIN_LAT, MAX_LAT + STEP, STEP)
lng_pts = np.arange(MIN_LNG, MAX_LNG + STEP, STEP)
print(f"동작구 격자: {len(lat_pts)} × {len(lng_pts)} = {len(lat_pts)*len(lng_pts)}개")

def kakao_category(lat, lng, code, radius=500):
    url = "https://dapi.kakao.com/v2/local/search/category.json"
    headers = {"Authorization": f"KakaoAK {API_KEY}"}
    results = []
    for page in range(1, 4):
        res = requests.get(url, headers=headers, params={"category_group_code": code, "x": lng, "y": lat, "radius": radius, "page": page, "size": 15})
        if res.status_code != 200: break
        data = res.json()
        results.extend(data.get("documents", []))
        if data["meta"]["is_end"]: break
    return results

def kakao_keyword(lat, lng, keyword, radius=500):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {API_KEY}"}
    results = []
    for page in range(1, 4):
        res = requests.get(url, headers=headers, params={"query": keyword, "x": lng, "y": lat, "radius": radius, "page": page, "size": 15})
        if res.status_code != 200: break
        data = res.json()
        results.extend(data.get("documents", []))
        if data["meta"]["is_end"]: break
    return results

def in_bounds(s):
    return MIN_LAT <= float(s["y"]) <= MAX_LAT and MIN_LNG <= float(s["x"]) <= MAX_LNG

def save_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "lat", "lng", "address"])
        w.writerows(rows)

# ── 편의점 (CS2) ───────────────────────────────────────
print("\n[편의점 수집 중...]")
conv = {}
total = len(lat_pts) * len(lng_pts)
cnt = 0
for lat in lat_pts:
    for lng in lng_pts:
        for s in kakao_category(lat, lng, "CS2"):
            if s["id"] not in conv: conv[s["id"]] = s
        time.sleep(0.08)
        cnt += 1
    print(f"  진행: {cnt}/{total} | 수집: {len(conv)}개")
rows = [[s["place_name"], s["y"], s["x"], s.get("road_address_name") or s.get("address_name","")] for s in conv.values() if in_bounds(s)]
save_csv("convenience_dongjak.csv", rows)
print(f"✓ convenience_dongjak.csv ({len(rows)}개)")

# ── 유흥주점 ───────────────────────────────────────────
print("\n[유흥주점 수집 중...]")
ent = {}
cnt = 0
for lat in lat_pts:
    for lng in lng_pts:
        for s in kakao_keyword(lat, lng, "유흥주점"):
            if s["id"] not in ent: ent[s["id"]] = s
        time.sleep(0.08)
        cnt += 1
    print(f"  진행: {cnt}/{total} | 수집: {len(ent)}개")
rows = [[s["place_name"], s["y"], s["x"], s.get("road_address_name") or s.get("address_name","")] for s in ent.values() if in_bounds(s)]
save_csv("entertainment_dongjak.csv", rows)
print(f"✓ entertainment_dongjak.csv ({len(rows)}개)")

# ── 경찰서/지구대/파출소 ───────────────────────────────
print("\n[경찰서/지구대/파출소 수집 중...]")
police = {}
for kw in ["경찰서", "지구대", "파출소"]:
    cnt = 0
    for lat in lat_pts:
        for lng in lng_pts:
            for s in kakao_keyword(lat, lng, kw):
                if s["id"] not in police: police[s["id"]] = s
            time.sleep(0.08)
            cnt += 1
        print(f"  [{kw}] 진행: {cnt}/{total} | 수집: {len(police)}개")
rows = [[s["place_name"], s["y"], s["x"], s.get("road_address_name") or s.get("address_name","")] for s in police.values() if in_bounds(s)]
save_csv("police_dongjak.csv", rows)
print(f"✓ police_dongjak.csv ({len(rows)}개)")

print("\n=== 동작구 데이터 수집 완료 ===")

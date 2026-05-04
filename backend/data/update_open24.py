"""
1. open24_dongjak.csv에서 좌표 없는 항목 자동 좌표 채우기
2. 프랜차이즈 + 무인 업종 동작구 전 지점 추가
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import os, time
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../backend/.env"))
API_KEY = os.environ["KAKAO_REST_API_KEY"]

CSV_PATH   = os.path.join(os.path.dirname(__file__), "open24_dongjak.csv")
SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
HEADERS    = {"Authorization": f"KakaoAK {API_KEY}"}

# 동작구 범위
MIN_LAT, MAX_LAT = 37.460, 37.535
MIN_LNG, MAX_LNG = 126.895, 126.985
DONGJAK_X = 126.9439
DONGJAK_Y = 37.4963

def in_dongjak(lat, lng):
    return MIN_LAT <= lat <= MAX_LAT and MIN_LNG <= lng <= MIN_LNG + (MAX_LNG - MIN_LNG)

def search_all(query: str, radius: int = 5000) -> list:
    """동작구 반경 내 전 지점 수집 (페이지 순회)"""
    results = []
    for page in range(1, 4):
        params = {
            "query":  query,
            "x":      DONGJAK_X,
            "y":      DONGJAK_Y,
            "radius": radius,
            "size":   15,
            "page":   page,
        }
        resp = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=10)
        if resp.status_code != 200:
            break
        data = resp.json()
        docs = data.get("documents", [])
        for d in docs:
            lat, lng = float(d["y"]), float(d["x"])
            if MIN_LAT <= lat <= MAX_LAT and MIN_LNG <= lng <= MAX_LNG:
                results.append(d)
        if data.get("meta", {}).get("is_end", True):
            break
        time.sleep(0.1)
    return results

def search_one(name: str) -> dict | None:
    """상호명 1개 검색 → 가장 가까운 결과 반환"""
    params = {
        "query":  name,
        "x":      DONGJAK_X,
        "y":      DONGJAK_Y,
        "radius": 5000,
        "size":   5,
    }
    resp = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=10)
    if resp.status_code != 200:
        return None
    docs = resp.json().get("documents", [])
    return docs[0] if docs else None

# ── 1. 좌표 없는 항목 채우기 ────────────────────────────────────
df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
missing = df[df["lat"].isna()]

print(f"=== 좌표 없는 항목 {len(missing)}개 처리 ===")
for idx, row in missing.iterrows():
    doc = search_one(row["name"])
    if doc:
        df.at[idx, "lat"]      = float(doc["y"])
        df.at[idx, "lng"]      = float(doc["x"])
        df.at[idx, "category"] = doc.get("category_name", "")
        df.at[idx, "address"]  = doc.get("road_address_name") or doc.get("address_name", "")
        print(f"  ✓ {row['name']} → ({df.at[idx,'lat']:.4f}, {df.at[idx,'lng']:.4f})")
    else:
        print(f"  ✗ {row['name']} → 검색 결과 없음")
    time.sleep(0.1)

# ── 2. 프랜차이즈 + 무인 전 지점 수집 ──────────────────────────
FRANCHISES = [
    "맥도날드",
    "KFC",
    "버거킹",
    "롯데리아",
    "서브웨이",
    "만월경",
    "싸다김밥",
    "셀프리커피",
    "무인",     # 무인 붙은 모든 업종
]

existing_names = set(df["name"].tolist())
new_rows = []

print(f"\n=== 프랜차이즈 + 무인 수집 ===")
for keyword in FRANCHISES:
    docs = search_all(keyword)
    added = 0
    for d in docs:
        name = d["place_name"]
        lat  = float(d["y"])
        lng  = float(d["x"])
        key  = f"{name}_{lat:.4f}_{lng:.4f}"
        if name in existing_names:
            continue
        existing_names.add(name)
        new_rows.append({
            "name":     name,
            "lat":      lat,
            "lng":      lng,
            "category": d.get("category_name", ""),
            "address":  d.get("road_address_name") or d.get("address_name", ""),
        })
        added += 1
    print(f"  [{keyword}] {added}개 추가")
    time.sleep(0.15)

# ── 3. 저장 ─────────────────────────────────────────────────────
if new_rows:
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

df = df.dropna(subset=["lat", "lng"])
df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")

print(f"\n✓ 저장 완료: 총 {len(df)}개")

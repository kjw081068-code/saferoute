"""
동작구 CCTV / 보안등 / 가로등 데이터 변환 스크립트

- CCTV (xlsx):   위도/경도 이미 있음 → 추출만
- 보안등 (csv):  위도/경도 이미 있음 → 추출만
- 가로등 (csv):  지번주소 → 카카오 API 좌표 변환 → 중복 제거
"""

import os
import time
import math
import requests
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KAKAO_KEY = os.getenv("KAKAO_REST_API_KEY", "")

if not KAKAO_KEY:
    dotenv_path = os.path.join(BASE_DIR, "..", ".env")
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("KAKAO_REST_API_KEY="):
                KAKAO_KEY = line.split("=", 1)[1].strip()
                break

if not KAKAO_KEY:
    raise RuntimeError(".env에서 KAKAO_REST_API_KEY를 찾을 수 없습니다.")

print(f"카카오 REST API 키 확인 완료: {KAKAO_KEY[:8]}...")


# ── 유틸: 두 좌표 간 거리(미터) ──────────────────────────────────────────────

def haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    rad = math.pi / 180
    dlat = (lat2 - lat1) * rad
    dlng = (lng2 - lng1) * rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(a)))


# ── 1. CCTV ──────────────────────────────────────────────────────────────────

print("\n[1/3] CCTV 처리 중...")

df_cctv = pd.read_excel(os.path.join(BASE_DIR, "cctv_dongjak_raw.xlsx"))
df_cctv.columns = df_cctv.columns.str.strip()

df_cctv_out = df_cctv[["위도", "경도"]].rename(columns={"위도": "lat", "경도": "lng"})
df_cctv_out = df_cctv_out.dropna(subset=["lat", "lng"])
df_cctv_out = df_cctv_out[
    df_cctv_out["lat"].between(37.4, 37.6) & df_cctv_out["lng"].between(126.8, 127.1)
].reset_index(drop=True)

out_path = os.path.join(BASE_DIR, "cctv_dongjak.csv")
df_cctv_out.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"  → {len(df_cctv_out)}건 저장: cctv_dongjak.csv")


# ── 2. 보안등 ─────────────────────────────────────────────────────────────────

print("\n[2/3] 보안등 처리 중...")

df_safe = pd.read_csv(os.path.join(BASE_DIR, "safelight_dongjak_raw.csv"), encoding="cp949")
df_safe.columns = df_safe.columns.str.strip()

df_safe_out = df_safe[["위도", "경도"]].rename(columns={"위도": "lat", "경도": "lng"})
df_safe_out = df_safe_out.dropna(subset=["lat", "lng"])
df_safe_out = df_safe_out[
    df_safe_out["lat"].between(37.4, 37.6) & df_safe_out["lng"].between(126.8, 127.1)
].reset_index(drop=True)

out_path = os.path.join(BASE_DIR, "safelight_dongjak.csv")
df_safe_out.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"  → {len(df_safe_out)}건 저장: safelight_dongjak.csv")


# ── 3. 가로등: 지번 → 좌표 변환 ──────────────────────────────────────────────

print("\n[3/3] 가로등 변환 중...")

df_sl = pd.read_csv(os.path.join(BASE_DIR, "streetlight_dongjak_raw.csv"), encoding="utf-8")
df_sl.columns = df_sl.columns.str.strip()

# 지번 기준 내부 중복 제거
before = len(df_sl)
df_sl = df_sl.drop_duplicates(subset=["지번"]).reset_index(drop=True)
print(f"  지번 중복 제거: {before}건 → {len(df_sl)}건")

# 기존 관악구 가로등 좌표 로드 (중복 비교용)
existing_coords = []
sl_raw_path = os.path.join(BASE_DIR, "streetlight_raw.csv")
if os.path.exists(sl_raw_path):
    for enc in ["utf-8", "utf-8-sig", "cp949", "euc-kr"]:
        try:
            df_existing = pd.read_csv(sl_raw_path, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    for _, row in df_existing.iterrows():
        try:
            existing_coords.append((float(row["lat"]), float(row["lng"])))
        except Exception:
            pass
    print(f"  기존 관악구 가로등: {len(existing_coords)}개 로드 완료")

DUPLICATE_RADIUS_M = 10

def is_duplicate_with_existing(lat, lng):
    for elat, elng in existing_coords:
        if haversine_m(lat, lng, elat, elng) <= DUPLICATE_RADIUS_M:
            return True
    return False


def geocode_jibun(dong: str, jibun: str) -> tuple[float, float] | None:
    query = f"서울특별시 동작구 {dong} {jibun}"
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    try:
        r = requests.get(url, headers=headers, params={"query": query}, timeout=5)
        r.raise_for_status()
        docs = r.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception:
        pass
    return None


results = []
failed = []
total = len(df_sl)

for i, row in df_sl.iterrows():
    dong = str(row["행정동"]).strip()
    jibun = str(row["지번"]).strip()

    coord = geocode_jibun(dong, jibun)

    if coord is None:
        failed.append({"행정동": dong, "지번": jibun, "사유": "API 결과 없음"})
        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"  진행: {i+1}/{total} | 성공: {len(results)} | 실패: {len(failed)}")
        time.sleep(0.1)
        continue

    lat, lng = coord

    if is_duplicate_with_existing(lat, lng):
        failed.append({"행정동": dong, "지번": jibun, "사유": "기존 데이터와 중복"})
        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"  진행: {i+1}/{total} | 성공: {len(results)} | 실패: {len(failed)}")
        time.sleep(0.1)
        continue

    results.append({"lat": lat, "lng": lng})

    if (i + 1) % 50 == 0 or (i + 1) == total:
        print(f"  진행: {i+1}/{total} | 성공: {len(results)} | 실패: {len(failed)}")

    time.sleep(0.1)

df_sl_out = pd.DataFrame(results)
out_path = os.path.join(BASE_DIR, "streetlight_dongjak.csv")
df_sl_out.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\n  → {len(df_sl_out)}건 저장: streetlight_dongjak.csv")

if failed:
    fail_path = os.path.join(BASE_DIR, "streetlight_dongjak_failed.csv")
    pd.DataFrame(failed).to_csv(fail_path, index=False, encoding="utf-8-sig")
    print(f"  → 실패/중복 {len(failed)}건: streetlight_dongjak_failed.csv")

print("\n✅ 변환 완료")

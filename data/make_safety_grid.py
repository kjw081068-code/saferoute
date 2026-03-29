`import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import pandas as pd
import numpy as np
from scipy.spatial import cKDTree

# ── 1. 데이터 로드 ────────────────────────────────────────────────
cctv = pd.read_csv("cctv_sinlim.csv", encoding="utf-8")
sl   = pd.read_csv("streetlight_sinlim.csv", encoding="utf-8")

cctv = cctv.rename(columns={"위도": "lat", "경도": "lng", "CCTV 수량": "qty"})
sl   = sl.rename(columns={"위도": "lat", "경도": "lng"})

# ── 2. 위도/경도 → 미터 변환 함수 (Equirectangular 근사) ──────────
REF_LAT = cctv["lat"].mean()          # 기준 위도
LAT_M   = 111320                       # 위도 1도 ≈ 111,320m
LNG_M   = 111320 * np.cos(np.radians(REF_LAT))  # 경도 1도 ≈ LNG_M m

def to_xy(lat, lng):
    return lng * LNG_M, lat * LAT_M

# ── 3. 신림동 경계 계산 (두 데이터셋 합집합) ─────────────────────
all_lats = pd.concat([cctv["lat"], sl["lat"]])
all_lngs = pd.concat([cctv["lng"], sl["lng"]])

min_lat, max_lat = all_lats.min(), all_lats.max()
min_lng, max_lng = all_lngs.min(), all_lngs.max()

print(f"경계 위도: {min_lat:.6f} ~ {max_lat:.6f}")
print(f"경계 경도: {min_lng:.6f} ~ {max_lng:.6f}")

# ── 4. 100m × 100m 격자 생성 ────────────────────────────────────
STEP_LAT = 100 / LAT_M   # 위도 방향 격자 간격 (도)
STEP_LNG = 100 / LNG_M   # 경도 방향 격자 간격 (도)

lat_centers = np.arange(min_lat, max_lat + STEP_LAT, STEP_LAT)
lng_centers = np.arange(min_lng, max_lng + STEP_LNG, STEP_LNG)

grid_lats, grid_lngs = np.meshgrid(lat_centers, lng_centers)
grid_lats = grid_lats.ravel()
grid_lngs = grid_lngs.ravel()

print(f"격자 수: {len(grid_lats)}개 ({len(lat_centers)} × {len(lng_centers)})")

# ── 5. KD-Tree로 반경 내 개수 집계 ──────────────────────────────
# XY 좌표(미터) 변환
gx, gy = to_xy(grid_lats, grid_lngs)
grid_xy = np.column_stack([gx, gy])

# CCTV: 반경 100m, qty 합산
cx, cy = to_xy(cctv["lat"].values, cctv["lng"].values)
cctv_xy = np.column_stack([cx, cy])
cctv_tree = cKDTree(cctv_xy)

# 격자별 반경 100m 안의 CCTV qty 합산
cctv_counts = np.zeros(len(grid_xy), dtype=float)
idx_lists = cctv_tree.query_ball_point(grid_xy, r=100)
for i, idxs in enumerate(idx_lists):
    cctv_counts[i] = cctv["qty"].iloc[idxs].sum() if idxs else 0

# 가로등: 반경 80m, 개수 집계
lx, ly = to_xy(sl["lat"].values, sl["lng"].values)
sl_xy   = np.column_stack([lx, ly])
sl_tree = cKDTree(sl_xy)

light_counts = np.array([len(idxs) for idxs in sl_tree.query_ball_point(grid_xy, r=80)],
                        dtype=float)

# ── 6. 안전점수 계산 (상대평가) ──────────────────────────────────
def minmax(arr):
    mn, mx = arr.min(), arr.max()
    if mx == mn:
        return np.zeros_like(arr, dtype=float)
    return (arr - mn) / (mx - mn)

cctv_norm  = minmax(cctv_counts)   # 0~1 정규화
light_norm = minmax(light_counts)  # 0~1 정규화

scores = cctv_norm * 60 + light_norm * 40   # 0~100점

# 순위 기반으로 정확히 하위 30% → 위험, 중위 40% → 보통, 상위 30% → 안전
n      = len(scores)
ranks  = pd.Series(scores).rank(method="first") - 1   # 0-indexed 순위
grades = np.where(ranks < n * 0.30, "위험",
         np.where(ranks < n * 0.70, "보통", "안전")).tolist()

# ── 7. 결과 저장 ─────────────────────────────────────────────────
result = pd.DataFrame({
    "위도":         grid_lats,
    "경도":         grid_lngs,
    "cctv_count":   cctv_counts.astype(int),
    "light_count":  light_counts.astype(int),
    "score":        scores.round(2),
    "grade":        grades,
})

result.to_csv("safety_grid.csv", index=False, encoding="utf-8-sig")
print("\n✓ safety_grid.csv 저장 완료")

# ── 8. 등급별 격자 수 출력 ───────────────────────────────────────
summary = result["grade"].value_counts().reindex(["안전", "보통", "위험"], fill_value=0)
total   = len(result)
print("\n[등급별 격자 수]")
for g, cnt in summary.items():
    pct = cnt / total * 100
    print(f"  {g}  : {cnt:>5}개  ({pct:.1f}%)")
print(f"  합계  : {total:>5}개")

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import pandas as pd
import numpy as np
from scipy.spatial import cKDTree

# ── 1. 데이터 로드 ────────────────────────────────────────────────
cctv = pd.read_csv("cctv_raw.csv", encoding="cp949")
sl   = pd.read_csv("streetlight_gwanak.csv", encoding="utf-8-sig")
conv = pd.read_csv("convenience_gwanak.csv", encoding="utf-8-sig")

cctv = cctv.rename(columns={"위도": "lat", "경도": "lng", "CCTV 수량": "qty"})
sl   = sl.rename(columns={"위도": "lat", "경도": "lng"})
conv = conv.rename(columns={"lat": "lat", "lng": "lng"})

conv["lat"] = conv["lat"].astype(float)
conv["lng"] = conv["lng"].astype(float)

# ── 2. 위도/경도 → 미터 변환 함수 ────────────────────────────────
REF_LAT = 37.47
LAT_M   = 111320
LNG_M   = 111320 * np.cos(np.radians(REF_LAT))

def to_xy(lat, lng):
    return lng * LNG_M, lat * LAT_M

# ── 3. 관악구 경계 ────────────────────────────────────────────────
MIN_LAT, MAX_LAT = 37.440, 37.496
MIN_LNG, MAX_LNG = 126.898, 126.985

print(f"경계 위도: {MIN_LAT} ~ {MAX_LAT}")
print(f"경계 경도: {MIN_LNG} ~ {MAX_LNG}")

# ── 4. 100m × 100m 격자 생성 ────────────────────────────────────
STEP_LAT = 100 / LAT_M
STEP_LNG = 100 / LNG_M

lat_centers = np.arange(MIN_LAT, MAX_LAT + STEP_LAT, STEP_LAT)
lng_centers = np.arange(MIN_LNG, MAX_LNG + STEP_LNG, STEP_LNG)

grid_lats, grid_lngs = np.meshgrid(lat_centers, lng_centers)
grid_lats = grid_lats.ravel()
grid_lngs = grid_lngs.ravel()

print(f"격자 수: {len(grid_lats)}개 ({len(lat_centers)} × {len(lng_centers)})")

# ── 5. KD-Tree로 반경 내 개수 집계 ──────────────────────────────
gx, gy = to_xy(grid_lats, grid_lngs)
grid_xy = np.column_stack([gx, gy])

# CCTV: 반경 100m, qty 합산, 최대 5대 캡
cx, cy = to_xy(cctv["lat"].values, cctv["lng"].values)
cctv_tree = cKDTree(np.column_stack([cx, cy]))
cctv_scores = np.zeros(len(grid_xy))
for i, idxs in enumerate(cctv_tree.query_ball_point(grid_xy, r=100)):
    raw = cctv["qty"].iloc[idxs].sum() if idxs else 0
    cctv_scores[i] = min(raw, 5) * 5  # 5점/대, 최대 25점

# 가로등: 반경 80m, 최대 4개 캡
lx, ly = to_xy(sl["lat"].values, sl["lng"].values)
sl_tree = cKDTree(np.column_stack([lx, ly]))
light_scores = np.zeros(len(grid_xy))
for i, idxs in enumerate(sl_tree.query_ball_point(grid_xy, r=80)):
    light_scores[i] = min(len(idxs), 4) * 5  # 5점/개, 최대 20점

# 편의점: 반경 100m, 최대 2개 캡
vx, vy = to_xy(conv["lat"].values, conv["lng"].values)
conv_tree = cKDTree(np.column_stack([vx, vy]))
conv_scores = np.zeros(len(grid_xy))
for i, idxs in enumerate(conv_tree.query_ball_point(grid_xy, r=100)):
    conv_scores[i] = min(len(idxs), 2) * 5  # 5점/개, 최대 10점

# ── 6. 안전점수 계산 ─────────────────────────────────────────────
# 기본 40점 + 가산점 (최대 95점)
scores = 40 + cctv_scores + light_scores + conv_scores

# 등급: 상대평가 (하위 30% → 위험, 중위 40% → 보통, 상위 30% → 안전)
n     = len(scores)
ranks = pd.Series(scores).rank(method="first") - 1  # 0-indexed 순위
grades = np.where(ranks < n * 0.30, "위험",
         np.where(ranks < n * 0.70, "보통", "안전")).tolist()

# ── 7. 결과 저장 ─────────────────────────────────────────────────
result = pd.DataFrame({
    "위도":          grid_lats,
    "경도":          grid_lngs,
    "cctv_count":    (cctv_scores / 5).astype(int),
    "light_count":   (light_scores / 5).astype(int),
    "conv_count":    (conv_scores / 5).astype(int),
    "score":         scores.round(2),
    "grade":         grades,
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
print(f"\n[점수 범위] {scores.min():.0f} ~ {scores.max():.0f}점 | 평균: {scores.mean():.1f}점")

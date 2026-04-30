import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import pandas as pd
import numpy as np
from scipy.spatial import cKDTree

# ── 1. 데이터 로드 ────────────────────────────────────────────────
cctv      = pd.read_csv("cctv_raw.csv", encoding="cp949")
sl_raw    = pd.read_csv("streetlight_raw.csv", encoding="cp949")
safelight = pd.read_csv("safelight_dongjak.csv", encoding="utf-8-sig")
conv      = pd.read_csv("convenience_dongjak.csv", encoding="utf-8-sig")
ent       = pd.read_csv("entertainment_dongjak.csv", encoding="utf-8-sig")
police    = pd.read_csv("police_dongjak.csv", encoding="utf-8-sig")

cctv.columns = [c.strip() for c in cctv.columns]
cctv = cctv.rename(columns={"위도": "lat", "경도": "lng", "CCTV 수량": "qty"})

sl_raw.columns = ['id', 'lat', 'lng']
sl = sl_raw[["lat", "lng"]].copy()

safelight["lat"] = safelight["lat"].astype(float)
safelight["lng"] = safelight["lng"].astype(float)

conv["lat"] = conv["lat"].astype(float)
conv["lng"] = conv["lng"].astype(float)
ent["lat"]  = ent["lat"].astype(float)
ent["lng"]  = ent["lng"].astype(float)
police["lat"] = police["lat"].astype(float)
police["lng"] = police["lng"].astype(float)

# ── 2. 위도/경도 → 미터 변환 함수 ────────────────────────────────
REF_LAT = 37.51
LAT_M   = 111320
LNG_M   = 111320 * np.cos(np.radians(REF_LAT))

def to_xy(lat, lng):
    return lng * LNG_M, lat * LAT_M

# ── 3. 동작구 경계 ────────────────────────────────────────────────
MIN_LAT, MAX_LAT = 37.490, 37.535
MIN_LNG, MAX_LNG = 126.916, 126.988

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

# CCTV: 반경 100m, qty 합산, 최대 4대 캡
cx, cy = to_xy(cctv["lat"].values, cctv["lng"].values)
cctv_tree = cKDTree(np.column_stack([cx, cy]))
cctv_scores = np.zeros(len(grid_xy))
for i, idxs in enumerate(cctv_tree.query_ball_point(grid_xy, r=100)):
    raw = cctv["qty"].iloc[idxs].sum() if idxs else 0
    cctv_scores[i] = min(raw, 4) * 5  # 5점/대, 최대 20점

# 가로등(대로변): 반경 80m, 최대 3개 캡, 5점/개
lx, ly = to_xy(sl["lat"].values, sl["lng"].values)
sl_tree = cKDTree(np.column_stack([lx, ly]))
light_scores = np.zeros(len(grid_xy))
for i, idxs in enumerate(sl_tree.query_ball_point(grid_xy, r=80)):
    light_scores[i] = min(len(idxs), 3) * 5  # 5점/개, 최대 15점

# 보안등(골목길): 반경 80m, 최대 3개 캡, 3점/개
sx, sy = to_xy(safelight["lat"].values, safelight["lng"].values)
safelight_tree = cKDTree(np.column_stack([sx, sy]))
safelight_scores = np.zeros(len(grid_xy))
safelight_counts = np.zeros(len(grid_xy), dtype=int)
for i, idxs in enumerate(safelight_tree.query_ball_point(grid_xy, r=80)):
    safelight_counts[i] = min(len(idxs), 3)
    safelight_scores[i] = safelight_counts[i] * 3  # 3점/개, 최대 9점

# 편의점: 반경 100m, 최대 2개 캡
vx, vy = to_xy(conv["lat"].values, conv["lng"].values)
conv_tree = cKDTree(np.column_stack([vx, vy]))
conv_scores = np.zeros(len(grid_xy))
for i, idxs in enumerate(conv_tree.query_ball_point(grid_xy, r=100)):
    conv_scores[i] = min(len(idxs), 2) * 5  # 5점/개, 최대 10점

# 유흥주점: 반경 100m, 최대 3개 캡, 감점
ex, ey = to_xy(ent["lat"].values, ent["lng"].values)
ent_tree = cKDTree(np.column_stack([ex, ey]))
ent_counts = np.zeros(len(grid_xy), dtype=int)
ent_deducts = np.zeros(len(grid_xy))
for i, idxs in enumerate(ent_tree.query_ball_point(grid_xy, r=100)):
    ent_counts[i] = min(len(idxs), 3)
    ent_deducts[i] = ent_counts[i] * 3  # 3점/개, 최대 9점 감점

# 경찰서/지구대/파출소: 반경 300m, 최대 1개 캡, 가산
px, py = to_xy(police["lat"].values, police["lng"].values)
police_tree = cKDTree(np.column_stack([px, py]))
police_counts = np.zeros(len(grid_xy), dtype=int)
for i, idxs in enumerate(police_tree.query_ball_point(grid_xy, r=300)):
    police_counts[i] = min(len(idxs), 1)

# ── 6. 안전점수 계산 ─────────────────────────────────────────────
scores = np.minimum(np.maximum(40 + cctv_scores + light_scores + safelight_scores + conv_scores + police_counts * 10 - ent_deducts, 10), 100)

# 등급: 상대평가 (하위 30% → 위험, 중위 40% → 보통, 상위 30% → 안전)
n     = len(scores)
ranks = pd.Series(scores).rank(method="first") - 1
grades = np.where(ranks < n * 0.30, "위험",
         np.where(ranks < n * 0.70, "보통", "안전")).tolist()

# ── 7. 결과 저장 ─────────────────────────────────────────────────
result = pd.DataFrame({
    "위도":           grid_lats,
    "경도":           grid_lngs,
    "cctv_count":     (cctv_scores / 5).astype(int),
    "light_count":    (light_scores / 5).astype(int),
    "safelight_count": safelight_counts,
    "conv_count":     (conv_scores / 5).astype(int),
    "ent_count":      ent_counts,
    "police_count":   police_counts,
    "score":          scores.round(2),
    "grade":          grades,
})

result.to_csv("safety_grid_dongjak.csv", index=False, encoding="utf-8-sig")
print("\n✓ safety_grid_dongjak.csv 저장 완료")

# ── 8. 등급별 격자 수 출력 ───────────────────────────────────────
summary = result["grade"].value_counts().reindex(["안전", "보통", "위험"], fill_value=0)
total   = len(result)
print("\n[등급별 격자 수]")
for g, cnt in summary.items():
    pct = cnt / total * 100
    print(f"  {g}  : {cnt:>5}개  ({pct:.1f}%)")
print(f"  합계  : {total:>5}개")
print(f"\n[점수 범위] {scores.min():.0f} ~ {scores.max():.0f}점 | 평균: {scores.mean():.1f}점")

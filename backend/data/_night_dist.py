import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import math
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from pathlib import Path

DATA_DIR = Path(__file__).parent
_REF_LAT = 37.47
_LAT_M = 111_320
_LNG_M = 111_320 * math.cos(math.radians(_REF_LAT))
LAT_MIN, LAT_MAX = 37.490, 37.535814
LNG_MIN, LNG_MAX = 126.916, 126.988477
GRID_M = 25.0

def load_tree(path, qty_col=None):
    df = pd.read_csv(path, encoding='utf-8-sig').dropna(subset=['lat','lng'])
    xs = df['lng'].values * _LNG_M
    ys = df['lat'].values * _LAT_M
    tree = cKDTree(np.column_stack([xs, ys]))
    qty = df[qty_col].values.astype(float) if qty_col else None
    return tree, qty

def _dim(count, base):
    score, mult, rem = 0.0, 1.0, float(count)
    while rem >= 0.001:
        take = min(1.0, rem)
        score += base * mult * take
        mult *= 0.5
        rem -= take
    return score

lat_step = GRID_M / _LAT_M
lng_step = GRID_M / _LNG_M
lats = np.arange(LAT_MIN + lat_step/2, LAT_MAX, lat_step)
lngs = np.arange(LNG_MIN + lng_step/2, LNG_MAX, lng_step)
grid_lat, grid_lng = np.meshgrid(lats, lngs, indexing='ij')
grid_lat = grid_lat.ravel()
grid_lng = grid_lng.ravel()

cctv_tree, cctv_qty = load_tree(DATA_DIR / 'cctv_dongjak.csv', 'qty')
safelight_tree, _   = load_tree(DATA_DIR / 'safelight_dongjak.csv')
streetlight_tree, _ = load_tree(DATA_DIR / 'streetlight_dongjak.csv')
conv_tree, _        = load_tree(DATA_DIR / 'convenience_dongjak.csv')
open24_tree, _      = load_tree(DATA_DIR / 'open24_dongjak.csv')
police_tree, _      = load_tree(DATA_DIR / 'police_dongjak.csv')
ent_tree, _         = load_tree(DATA_DIR / 'entertainment_dongjak.csv')
firestation_tree, _ = load_tree(DATA_DIR / 'firestation_dongjak.csv')

xs = grid_lng * _LNG_M
ys = grid_lat * _LAT_M
pts = np.column_stack([xs, ys])
n = len(grid_lat)
scores = np.zeros(n)

# CCTV 30m / 30~100m
near_list = cctv_tree.query_ball_point(pts, r=30.0)
far_list  = cctv_tree.query_ball_point(pts, r=100.0)
for i, (ni, fi) in enumerate(zip(near_list, far_list)):
    ni_set = set(ni); fi_only = set(fi) - ni_set
    qty_n = float(cctv_qty[list(ni_set)].sum()) if ni_set else 0.0
    qty_f = float(cctv_qty[list(fi_only)].sum()) if fi_only else 0.0
    scores[i] += (18.0 if qty_n >= 2 else 12.0 if qty_n >= 1 else 0.0) + _dim(qty_f, 6.0)

# 가로등 25m
for i, idxs in enumerate(streetlight_tree.query_ball_point(pts, r=25.0)):
    scores[i] += _dim(len(idxs), 5.5)

# 보안등 10m
for i, idxs in enumerate(safelight_tree.query_ball_point(pts, r=10.0)):
    scores[i] += _dim(len(idxs), 4.0)

# 편의점+24시 야간 150m
for i, pt in enumerate(pts):
    cnt = len(conv_tree.query_ball_point(pt, r=150.0)) + len(open24_tree.query_ball_point(pt, r=150.0))
    scores[i] += _dim(cnt, 3.5)

# 경찰서 300m
for i, idxs in enumerate(police_tree.query_ball_point(pts, r=300.0)):
    scores[i] += _dim(len(idxs), 14.0)

# 소방서 300m
for i, idxs in enumerate(firestation_tree.query_ball_point(pts, r=300.0)):
    scores[i] += min(len(idxs), 1) * 10.5

# 유흥주점 100m 감점
for i, idxs in enumerate(ent_tree.query_ball_point(pts, r=100.0)):
    scores[i] -= _dim(len(idxs), 7.5)

s_min = math.floor(scores.min() / 2) * 2
s_max = math.ceil(scores.max() / 2) * 2
bins = np.arange(s_min, s_max + 2, 2)
counts, edges = np.histogram(scores, bins=bins)

danger = int(np.sum(scores < 0))
safe   = int(np.sum(scores >= 20))
normal = n - danger - safe

print("=== 야간 점수분포 (2점 단위) ===")
print(f"총 {n:,}개 격자")
print(f"위험(S<0):   {danger:6,}개  {danger/n*100:.1f}%")
print(f"보통(0~20):  {normal:6,}개  {normal/n*100:.1f}%")
print(f"안전(S>=20): {safe:6,}개  {safe/n*100:.1f}%")
print(f"최소={scores.min():.1f}  최대={scores.max():.1f}  평균={scores.mean():.1f}  중앙={np.median(scores):.1f}")
print()
print(f"{'구간':>10}  {'개수':>7}  {'비율':>6}  등급")
print("-" * 38)
for i, cnt in enumerate(counts):
    lo, hi = edges[i], edges[i+1]
    grade = "위험" if hi <= 0 else "안전" if lo >= 20 else "보통"
    print(f"  {lo:4.0f}~{hi:4.0f}  {cnt:7,}  {cnt/n*100:5.2f}%  {grade}")

# -*- coding: utf-8 -*-
"""B안 지리마스킹 기준 주간 위험/보통/안전 비율"""
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
DANGER_THRESH = 0.0
SAFE_THRESH   = 16.0
DAYTIME_BONUS = 6.0
STORE_WEIGHT_DAY = 2.0
STORE_RATE = 0.3

def load_tree(path, qty_col=None):
    if not path.exists(): return None, None
    df = pd.read_csv(path, encoding='utf-8-sig').dropna(subset=['lat','lng'])
    xs = df['lng'].values * _LNG_M
    ys = df['lat'].values * _LAT_M
    tree = cKDTree(np.column_stack([xs, ys]))
    qty = df[qty_col].values.astype(float) if qty_col else None
    return tree, qty

def dim(count, base, rate=0.5):
    s, mult, rem = 0.0, 1.0, float(count)
    while rem >= 0.001:
        take = min(1.0, rem)
        s += base * mult * take
        mult *= (1.0 - rate)
        rem -= take
    return s

lat_step = GRID_M / _LAT_M
lng_step = GRID_M / _LNG_M
lats = np.arange(LAT_MIN + lat_step/2, LAT_MAX, lat_step)
lngs = np.arange(LNG_MIN + lng_step/2, LNG_MAX, lng_step)
grid_lat, grid_lng = np.meshgrid(lats, lngs, indexing='ij')
grid_lat = grid_lat.ravel()
grid_lng = grid_lng.ravel()

cctv_tree, cctv_qty = load_tree(DATA_DIR/'cctv_dongjak.csv', qty_col='qty')
conv_tree, _        = load_tree(DATA_DIR/'convenience_dongjak.csv')
open24_tree, _      = load_tree(DATA_DIR/'open24_dongjak.csv')
police_tree, _      = load_tree(DATA_DIR/'police_dongjak.csv')
ent_tree, _         = load_tree(DATA_DIR/'entertainment_dongjak.csv')
firestation_tree, _ = load_tree(DATA_DIR/'firestation_dongjak.csv')

pts = np.column_stack([grid_lng * _LNG_M, grid_lat * _LAT_M])
n   = len(grid_lat)
scores = np.full(n, DAYTIME_BONUS)  # 주간 활동보너스 기본 적용

if cctv_tree is not None:
    near_list = cctv_tree.query_ball_point(pts, r=30.0)
    far_list  = cctv_tree.query_ball_point(pts, r=100.0)
    for i, (ni, fi) in enumerate(zip(near_list, far_list)):
        ni_set = set(ni); fi_only = set(fi) - ni_set
        qty_n = float(cctv_qty[list(ni_set)].sum()) if ni_set else 0.0
        qty_f = float(cctv_qty[list(fi_only)].sum()) if fi_only else 0.0
        near_score = 18.0 if qty_n >= 2 else (12.0 if qty_n >= 1 else 0.0)
        scores[i] += near_score + dim(min(qty_f, 3.0), 6.0)

# 주간: 가로등·보안등 없음
for i, pt in enumerate(pts):
    cnt = 0
    if conv_tree:   cnt += len(conv_tree.query_ball_point(pt, r=150.0))
    if open24_tree: cnt += len(open24_tree.query_ball_point(pt, r=150.0))
    scores[i] += dim(cnt, STORE_WEIGHT_DAY, rate=STORE_RATE)

if police_tree is not None:
    dists, _ = police_tree.query(pts, k=1)
    mask = dists < 200.0; scores[mask] += 14.0 * (1.0 - dists[mask] / 200.0)

if firestation_tree is not None:
    dists, _ = firestation_tree.query(pts, k=1)
    mask = dists < 300.0; scores[mask] += 10.5 * (1.0 - dists[mask] / 300.0)

if ent_tree is not None:
    for i, idxs in enumerate(ent_tree.query_ball_point(pts, r=50.0)):
        scores[i] -= min(len(idxs), 2) * 7.5  # 주간 감점 배율 1.0

# B안 지리 마스킹
geo_exclude = (
    (grid_lat >= 37.519) |
    ((grid_lat >= 37.495) & (grid_lat <= 37.512) &
     (grid_lng >= 126.972) & (grid_lng <= 126.990)) |
    ((grid_lat <= 37.496) &
     (grid_lng >= 126.945) & (grid_lng <= 126.975))
)
walkable = ~geo_exclude

def print_stats(label, mask):
    s = scores[mask]
    total = len(s)
    danger = int(np.sum(s <= DANGER_THRESH))
    safe   = int(np.sum(s >= SAFE_THRESH))
    normal = total - danger - safe
    print(f'\n[{label}]  {total:,}개')
    print(f'  위험 (≤{DANGER_THRESH:g}점): {danger:6,}개  {danger/total*100:5.1f}%')
    print(f'  보통 ({DANGER_THRESH:g}~{SAFE_THRESH:g}점): {normal:6,}개  {normal/total*100:5.1f}%')
    print(f'  안전 (≥{SAFE_THRESH:g}점): {safe:6,}개  {safe/total*100:5.1f}%')
    print(f'  평균={s.mean():.1f}  중앙={np.median(s):.1f}  최소={s.min():.1f}  최대={s.max():.1f}')

print('=== 주간 점수 / B안 지리마스킹 기준 ===')
print_stats('전체 격자', np.ones(n, dtype=bool))
print_stats('B안 마스킹 후 (보행 가능 지역)', walkable)

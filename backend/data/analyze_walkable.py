# -*- coding: utf-8 -*-
"""
비보행지역 제외 후 실제 위험/보통/안전 비율 산출
방법 A: 0점 격자 제외 (인프라 없는 지역 = 비보행)
방법 B: 지리적 마스킹 (한강 수면 / 현충원 / 관악산 좌표 범위 제외)
"""
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
safelight_tree, _   = load_tree(DATA_DIR/'safelight_dongjak.csv')
streetlight_tree, _ = load_tree(DATA_DIR/'streetlight_dongjak.csv')
conv_tree, _        = load_tree(DATA_DIR/'convenience_dongjak.csv')
open24_tree, _      = load_tree(DATA_DIR/'open24_dongjak.csv')
police_tree, _      = load_tree(DATA_DIR/'police_dongjak.csv')
ent_tree, _         = load_tree(DATA_DIR/'entertainment_dongjak.csv')
firestation_tree, _ = load_tree(DATA_DIR/'firestation_dongjak.csv')

pts = np.column_stack([grid_lng * _LNG_M, grid_lat * _LAT_M])
n   = len(grid_lat)
scores = np.zeros(n)

if cctv_tree is not None:
    near_list = cctv_tree.query_ball_point(pts, r=30.0)
    far_list  = cctv_tree.query_ball_point(pts, r=100.0)
    for i, (ni, fi) in enumerate(zip(near_list, far_list)):
        ni_set = set(ni); fi_only = set(fi) - ni_set
        qty_n = float(cctv_qty[list(ni_set)].sum()) if ni_set else 0.0
        qty_f = float(cctv_qty[list(fi_only)].sum()) if fi_only else 0.0
        near_score = 18.0 if qty_n >= 2 else (12.0 if qty_n >= 1 else 0.0)
        scores[i] += near_score + dim(min(qty_f, 3.0), 6.0)

if streetlight_tree is not None:
    for i, idxs in enumerate(streetlight_tree.query_ball_point(pts, r=35.0)):
        scores[i] += min(len(idxs), 2) * 5.5

if safelight_tree is not None:
    for i, idxs in enumerate(safelight_tree.query_ball_point(pts, r=18.0)):
        scores[i] += min(len(idxs), 1) * 4.0

for i, pt in enumerate(pts):
    cnt = 0
    if conv_tree:   cnt += len(conv_tree.query_ball_point(pt, r=150.0))
    if open24_tree: cnt += len(open24_tree.query_ball_point(pt, r=150.0))
    scores[i] += dim(cnt, 3.5, rate=0.3)

if police_tree is not None:
    dists, _ = police_tree.query(pts, k=1)
    mask = dists < 200.0; scores[mask] += 14.0 * (1.0 - dists[mask] / 200.0)

if firestation_tree is not None:
    dists, _ = firestation_tree.query(pts, k=1)
    mask = dists < 300.0; scores[mask] += 10.5 * (1.0 - dists[mask] / 300.0)

if ent_tree is not None:
    for i, idxs in enumerate(ent_tree.query_ball_point(pts, r=50.0)):
        scores[i] -= min(len(idxs), 2) * 7.5 * 2.5

# ── 방법 B: 지리적 마스킹 ─────────────────────────────────
# 한강 수면: 동작구 북단, 위도 37.519 이상 구간
HANGANG_LAT = 37.519

# 국립서울현충원: 흑석동·동작동 내 대형 공원
# 실측 좌표 범위 (대략)
HYUNCHUNG_LAT_MIN = 37.495
HYUNCHUNG_LAT_MAX = 37.512
HYUNCHUNG_LNG_MIN = 126.972
HYUNCHUNG_LNG_MAX = 126.990

# 관악산 기슭: 동작구 남쪽 + 서쪽 일부 (비거주 녹지)
# 대략 lat < 37.496, lng 126.945~126.975
GWANAK_LAT_MAX = 37.496
GWANAK_LNG_MIN = 126.945
GWANAK_LNG_MAX = 126.975

geo_exclude = (
    (grid_lat >= HANGANG_LAT) |
    (
        (grid_lat >= HYUNCHUNG_LAT_MIN) & (grid_lat <= HYUNCHUNG_LAT_MAX) &
        (grid_lng >= HYUNCHUNG_LNG_MIN) & (grid_lng <= HYUNCHUNG_LNG_MAX)
    ) |
    (
        (grid_lat <= GWANAK_LAT_MAX) &
        (grid_lng >= GWANAK_LNG_MIN) & (grid_lng <= GWANAK_LNG_MAX)
    )
)

def print_stats(label, mask):
    s = scores[mask]
    total = len(s)
    danger = int(np.sum(s <= DANGER_THRESH))
    safe   = int(np.sum(s >= SAFE_THRESH))
    normal = total - danger - safe
    print(f'\n[{label}]  대상 격자: {total:,}개')
    print(f'  위험 (≤{DANGER_THRESH:g}점): {danger:6,}개  {danger/total*100:5.1f}%')
    print(f'  보통 ({DANGER_THRESH:g}~{SAFE_THRESH:g}점): {normal:6,}개  {normal/total*100:5.1f}%')
    print(f'  안전 (≥{SAFE_THRESH:g}점): {safe:6,}개  {safe/total*100:5.1f}%')
    print(f'  평균={s.mean():.1f}  중앙={np.median(s):.1f}  최소={s.min():.1f}  최대={s.max():.1f}')

print('=== 비보행지역 제외 전/후 비율 비교 ===')

# 기준: 전체
print_stats('전체 격자 (제외 없음)', np.ones(n, dtype=bool))

# 방법 A: 0점 격자 제외
walkable_a = scores > DANGER_THRESH
print_stats('방법A: 0점 격자 제외 (인프라 없는 지역)', walkable_a)

# 방법 B: 지리 마스킹
walkable_b = ~geo_exclude
excluded_b = geo_exclude.sum()
print(f'\n[방법B 마스킹 제외 수]')
hangang_cnt    = (grid_lat >= HANGANG_LAT).sum()
hyunchung_cnt  = ((grid_lat >= HYUNCHUNG_LAT_MIN) & (grid_lat <= HYUNCHUNG_LAT_MAX) &
                  (grid_lng >= HYUNCHUNG_LNG_MIN)  & (grid_lng <= HYUNCHUNG_LNG_MAX)).sum()
gwanak_cnt     = ((grid_lat <= GWANAK_LAT_MAX) &
                  (grid_lng >= GWANAK_LNG_MIN) & (grid_lng <= GWANAK_LNG_MAX)).sum()
print(f'  한강 수면(lat>=37.519):  {hangang_cnt:,}개')
print(f'  국립현충원(좌표범위):     {hyunchung_cnt:,}개')
print(f'  관악산 기슭(좌표범위):    {gwanak_cnt:,}개')
print(f'  총 제외:                  {excluded_b:,}개')
print_stats('방법B: 지리 마스킹 제외', walkable_b)

# 방법 A+B 조합
walkable_ab = walkable_a & walkable_b
print_stats('방법A+B: 0점+지리 마스킹 동시 제외', walkable_ab)

# -*- coding: utf-8 -*-
"""야간 안전 구간(16점 이상) 격자의 인프라 구성 분석"""
import math
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from pathlib import Path
from collections import Counter

DATA_DIR = Path(__file__).parent
_REF_LAT = 37.47
_LAT_M = 111_320
_LNG_M = 111_320 * math.cos(math.radians(_REF_LAT))

LAT_MIN, LAT_MAX = 37.490, 37.535814
LNG_MIN, LNG_MAX = 126.916, 126.988477
GRID_M = 25.0
SAFE_THRESH = 16.0

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
n = len(grid_lat)

score_cctv   = np.zeros(n)
score_light  = np.zeros(n)
score_safe   = np.zeros(n)
score_store  = np.zeros(n)
score_police = np.zeros(n)
score_fire   = np.zeros(n)
score_ent    = np.zeros(n)

if cctv_tree is not None:
    near_list = cctv_tree.query_ball_point(pts, r=30.0)
    far_list  = cctv_tree.query_ball_point(pts, r=100.0)
    for i, (ni, fi) in enumerate(zip(near_list, far_list)):
        ni_set = set(ni); fi_only = set(fi) - ni_set
        qty_n = float(cctv_qty[list(ni_set)].sum()) if ni_set else 0.0
        qty_f = float(cctv_qty[list(fi_only)].sum()) if fi_only else 0.0
        near_score = 18.0 if qty_n >= 2 else (12.0 if qty_n >= 1 else 0.0)
        score_cctv[i] = near_score + dim(min(qty_f, 3.0), 6.0)

if streetlight_tree is not None:
    for i, idxs in enumerate(streetlight_tree.query_ball_point(pts, r=35.0)):
        score_light[i] = min(len(idxs), 2) * 5.5

if safelight_tree is not None:
    for i, idxs in enumerate(safelight_tree.query_ball_point(pts, r=18.0)):
        score_safe[i] = min(len(idxs), 1) * 4.0

for i, pt in enumerate(pts):
    cnt = 0
    if conv_tree is not None: cnt += len(conv_tree.query_ball_point(pt, r=150.0))
    if open24_tree is not None: cnt += len(open24_tree.query_ball_point(pt, r=150.0))
    score_store[i] = dim(cnt, 3.5, rate=0.3)

if police_tree is not None:
    dists, _ = police_tree.query(pts, k=1)
    mask = dists < 200.0
    score_police[mask] = 14.0 * (1.0 - dists[mask] / 200.0)

if firestation_tree is not None:
    dists, _ = firestation_tree.query(pts, k=1)
    mask = dists < 300.0
    score_fire[mask] = 10.5 * (1.0 - dists[mask] / 300.0)

if ent_tree is not None:
    for i, idxs in enumerate(ent_tree.query_ball_point(pts, r=50.0)):
        score_ent[i] = min(len(idxs), 2) * 7.5 * 2.5

total = score_cctv + score_light + score_safe + score_store + score_police + score_fire - score_ent

safe_mask = total >= SAFE_THRESH
sm = safe_mask.sum()

print(f'=== 야간 안전 구간(>=16점) 인프라 분석 ===')
print(f'안전 격자: {sm:,}개 ({sm/n*100:.1f}%)')
print()

def has(arr, mask): return int((arr[mask] > 0).sum())
def avg_nz(arr, mask):
    sub = arr[mask]; nz = sub[sub > 0]
    return float(nz.mean()) if len(nz) > 0 else 0.0

print('=== 요소 보유 비율 (안전 구간 내) ===')
print(f'  CCTV 있음       : {has(score_cctv,safe_mask):6,}개  {has(score_cctv,safe_mask)/sm*100:5.1f}%  평균기여 {avg_nz(score_cctv,safe_mask):.1f}점')
print(f'  가로등 있음      : {has(score_light,safe_mask):6,}개  {has(score_light,safe_mask)/sm*100:5.1f}%  평균기여 {avg_nz(score_light,safe_mask):.1f}점')
print(f'  보안등 있음      : {has(score_safe,safe_mask):6,}개  {has(score_safe,safe_mask)/sm*100:5.1f}%  평균기여 {avg_nz(score_safe,safe_mask):.1f}점')
print(f'  편의점/24시 있음 : {has(score_store,safe_mask):6,}개  {has(score_store,safe_mask)/sm*100:5.1f}%  평균기여 {avg_nz(score_store,safe_mask):.1f}점')
print(f'  경찰서 반경내    : {has(score_police,safe_mask):6,}개  {has(score_police,safe_mask)/sm*100:5.1f}%  평균기여 {avg_nz(score_police,safe_mask):.1f}점')
print(f'  소방서 반경내    : {has(score_fire,safe_mask):6,}개  {has(score_fire,safe_mask)/sm*100:5.1f}%  평균기여 {avg_nz(score_fire,safe_mask):.1f}점')
print(f'  유흥 감점        : {has(score_ent,safe_mask):6,}개  {has(score_ent,safe_mask)/sm*100:5.1f}%')
print()

# 점수 구간별 조합
print('=== 점수 구간별 인프라 조합 ===')
bands = [(16,20),(20,25),(25,30),(30,40),(40,60),(60,200)]
for lo, hi in bands:
    bm = (total >= lo) & (total < hi)
    bc = bm.sum()
    if bc == 0: continue
    print(f'\n  [{lo}~{hi}점)  {bc:,}개 ({bc/n*100:.1f}%)')
    combos = Counter()
    for i in np.where(bm)[0]:
        parts = []
        if score_cctv[i]   > 0: parts.append(f'CCTV({score_cctv[i]:.0f})')
        if score_light[i]  > 0: parts.append(f'가로등({score_light[i]:.0f})')
        if score_safe[i]   > 0: parts.append(f'보안등({score_safe[i]:.0f})')
        if score_store[i]  > 0: parts.append(f'편의점({score_store[i]:.1f})')
        if score_police[i] > 0: parts.append(f'경찰({score_police[i]:.1f})')
        if score_fire[i]   > 0: parts.append(f'소방({score_fire[i]:.1f})')
        if score_ent[i]    > 0: parts.append(f'유흥감점(-{score_ent[i]:.0f})')
        combos[', '.join(parts) if parts else '???'] += 1
    for combo, cnt in combos.most_common(8):
        print(f'    {cnt:5,}개  {combo}')

# 최고점 구간 상세
print(f'\n=== 전체 분포 요약 ===')
print(f'  최대 점수: {total.max():.1f}')
print(f'  안전 평균: {total[safe_mask].mean():.1f}')
print(f'  안전 중앙값: {np.median(total[safe_mask]):.1f}')
top_bins = np.arange(16, total.max()+2, 2)
counts, edges = np.histogram(total[safe_mask], bins=top_bins)
for i, cnt in enumerate(counts):
    if cnt == 0: continue
    pct = cnt/sm*100
    bar = '#' * int(pct)
    print(f'  [{edges[i]:.0f}~{edges[i+1]:.0f}) {cnt:5,}개  {pct:5.1f}%  {bar}')

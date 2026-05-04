# -*- coding: utf-8 -*-
"""4~16점(보통) 및 16점+(안전) 구간별 인프라 상세 비율 분석"""
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

sc = np.zeros(n); sl = np.zeros(n); ss = np.zeros(n)
sst = np.zeros(n); sp = np.zeros(n); sf = np.zeros(n); se = np.zeros(n)

if cctv_tree is not None:
    near_list = cctv_tree.query_ball_point(pts, r=30.0)
    far_list  = cctv_tree.query_ball_point(pts, r=100.0)
    for i, (ni, fi) in enumerate(zip(near_list, far_list)):
        ni_set = set(ni); fi_only = set(fi) - ni_set
        qty_n = float(cctv_qty[list(ni_set)].sum()) if ni_set else 0.0
        qty_f = float(cctv_qty[list(fi_only)].sum()) if fi_only else 0.0
        near_score = 18.0 if qty_n >= 2 else (12.0 if qty_n >= 1 else 0.0)
        sc[i] = near_score + dim(min(qty_f, 3.0), 6.0)

if streetlight_tree is not None:
    for i, idxs in enumerate(streetlight_tree.query_ball_point(pts, r=35.0)):
        sl[i] = min(len(idxs), 2) * 5.5

if safelight_tree is not None:
    for i, idxs in enumerate(safelight_tree.query_ball_point(pts, r=18.0)):
        ss[i] = min(len(idxs), 1) * 4.0

for i, pt in enumerate(pts):
    cnt = 0
    if conv_tree: cnt += len(conv_tree.query_ball_point(pt, r=150.0))
    if open24_tree: cnt += len(open24_tree.query_ball_point(pt, r=150.0))
    sst[i] = dim(cnt, 3.5, rate=0.3)

if police_tree is not None:
    dists, _ = police_tree.query(pts, k=1)
    mask = dists < 200.0; sp[mask] = 14.0 * (1.0 - dists[mask] / 200.0)

if firestation_tree is not None:
    dists, _ = firestation_tree.query(pts, k=1)
    mask = dists < 300.0; sf[mask] = 10.5 * (1.0 - dists[mask] / 300.0)

if ent_tree is not None:
    for i, idxs in enumerate(ent_tree.query_ball_point(pts, r=50.0)):
        se[i] = min(len(idxs), 2) * 7.5 * 2.5

total = sc + sl + ss + sst + sp + sf - se

def band_summary(label, mask):
    bc = mask.sum()
    if bc == 0:
        print(f'\n[{label}]  0개')
        return
    pct_total = bc / n * 100

    cctv_pct  = (sc[mask]  > 0).mean() * 100
    light_pct = (sl[mask]  > 0).mean() * 100
    safe_pct  = (ss[mask]  > 0).mean() * 100
    store_pct = (sst[mask] > 0).mean() * 100
    pol_pct   = (sp[mask]  > 0).mean() * 100
    fire_pct  = (sf[mask]  > 0).mean() * 100
    ent_pct   = (se[mask]  > 0).mean() * 100

    avg_cctv  = sc[mask][sc[mask]   > 0].mean() if (sc[mask]  > 0).any() else 0
    avg_light = sl[mask][sl[mask]   > 0].mean() if (sl[mask]  > 0).any() else 0
    avg_safe  = ss[mask][ss[mask]   > 0].mean() if (ss[mask]  > 0).any() else 0
    avg_store = sst[mask][sst[mask] > 0].mean() if (sst[mask] > 0).any() else 0

    combos = Counter()
    for i in np.where(mask)[0]:
        parts = []
        if sc[i]  > 0: parts.append('CCTV')
        if sl[i]  > 0: parts.append('가로등')
        if ss[i]  > 0: parts.append('보안등')
        if sst[i] > 0: parts.append('편의점')
        if sp[i]  > 0: parts.append('경찰서')
        if sf[i]  > 0: parts.append('소방서')
        if se[i]  > 0: parts.append('유흥감점')
        combos['+'.join(parts) if parts else '없음'] += 1

    print(f'\n{"="*58}')
    print(f'[{label}]  {bc:,}개  전체의 {pct_total:.1f}%')
    print(f'{"="*58}')
    print(f'  CCTV  있음: {cctv_pct:5.1f}%  (있을때 평균 {avg_cctv:.1f}점)')
    print(f'  가로등있음: {light_pct:5.1f}%  (있을때 평균 {avg_light:.1f}점)')
    print(f'  보안등있음: {safe_pct:5.1f}%  (있을때 평균 {avg_safe:.1f}점)')
    print(f'  편의점있음: {store_pct:5.1f}%  (있을때 평균 {avg_store:.1f}점)')
    print(f'  경찰서있음: {pol_pct:5.1f}%')
    print(f'  소방서있음: {fire_pct:5.1f}%')
    print(f'  유흥감점  : {ent_pct:5.1f}%')
    print(f'  --- 인프라 조합 상위 5 ---')
    for combo, cnt in combos.most_common(5):
        print(f'  {cnt:5,}개 ({cnt/bc*100:4.1f}%)  {combo}')

bands = [
    ('4~8점   [보통 하단]',   (total >= 4)  & (total < 8)),
    ('8~12점  [보통 중단]',   (total >= 8)  & (total < 12)),
    ('12~16점 [보통 상단]',   (total >= 12) & (total < 16)),
    ('16~20점 [안전 하단]',   (total >= 16) & (total < 20)),
    ('20~30점 [안전 중단]',   (total >= 20) & (total < 30)),
    ('30점+   [안전 상단]',   (total >= 30)),
]

print('=== 야간 점수대별 인프라 수준 상세 ===')
for label, mask in bands:
    band_summary(label, mask)

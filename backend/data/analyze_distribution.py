"""
동작구 전체 안전점수 분포 분석 스크립트
- 25m 간격 격자 생성 (동작구 바운딩박스)
- 각 격자 중심점 점수 계산 (현재 실서버 로직과 동일)
- 주간/야간 두 가지 분포 출력 + 히스토그램
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

DATA_DIR = Path(__file__).parent

CCTV_PATH         = DATA_DIR / "cctv_dongjak.csv"
SAFELIGHT_PATH    = DATA_DIR / "safelight_dongjak.csv"
STREETLIGHT_PATH  = DATA_DIR / "streetlight_dongjak.csv"
CONVENIENCE_PATH  = DATA_DIR / "convenience_dongjak.csv"
OPEN24_PATH       = DATA_DIR / "open24_dongjak.csv"
POLICE_PATH       = DATA_DIR / "police_dongjak.csv"
ENTERTAINMENT_PATH= DATA_DIR / "entertainment_dongjak.csv"
FIRESTATION_PATH  = DATA_DIR / "firestation_dongjak.csv"

LAT_MIN, LAT_MAX = 37.490, 37.535814
LNG_MIN, LNG_MAX = 126.916, 126.988477
GRID_M = 25.0

_REF_LAT = 37.47
_LAT_M = 111_320
_LNG_M = 111_320 * math.cos(math.radians(_REF_LAT))

# 현재 실서버 임계값
DANGER_THRESH = 0.0
SAFE_THRESH   = 20.0

# 편의점/24시 주간 고정점수
STORE_DAY_SCORE = 10.0
STORE_CAP       = 2
STORE_WEIGHT    = 3.5


def load_tree(path: Path, qty_col: str = None):
    if not path.exists():
        print(f"  [경고] 파일 없음: {path.name}")
        return None, None
    df = pd.read_csv(path, encoding="utf-8-sig").dropna(subset=["lat", "lng"])
    xs = df["lng"].values * _LNG_M
    ys = df["lat"].values * _LAT_M
    tree = cKDTree(np.column_stack([xs, ys]))
    qty = df[qty_col].values.astype(float) if qty_col else None
    print(f"  로드: {path.name}  ({len(df):,}개)")
    return tree, qty


def build_grid():
    lat_step = GRID_M / _LAT_M
    lng_step = GRID_M / _LNG_M
    lats = np.arange(LAT_MIN + lat_step / 2, LAT_MAX, lat_step)
    lngs = np.arange(LNG_MIN + lng_step / 2, LNG_MAX, lng_step)
    grid_lat, grid_lng = np.meshgrid(lats, lngs, indexing="ij")
    return grid_lat.ravel(), grid_lng.ravel(), len(lats), len(lngs)


def _dim(count: float, base: float) -> float:
    """체감수익감소: base × (1 + 0.5 + 0.25 + ...), cap 없음."""
    score, mult, rem = 0.0, 1.0, float(count)
    while rem >= 0.001:
        take = min(1.0, rem)
        score += base * mult * take
        mult *= 0.5
        rem -= take
    return score


def batch_scores(grid_lat, grid_lng, trees, daytime: bool):
    cctv_tree, cctv_qty, safelight_tree, streetlight_tree, \
    conv_tree, open24_tree, police_tree, ent_tree, firestation_tree = trees

    xs = grid_lng * _LNG_M
    ys = grid_lat * _LAT_M
    pts = np.column_stack([xs, ys])
    n = len(grid_lat)
    scores = np.zeros(n)

    # CCTV 30m: 1개=12점, 2개 이상=18점 / 30~100m: 체감감소 base=6
    if cctv_tree is not None:
        near_list = cctv_tree.query_ball_point(pts, r=30.0)
        far_list  = cctv_tree.query_ball_point(pts, r=100.0)
        for i, (ni, fi) in enumerate(zip(near_list, far_list)):
            ni_set = set(ni)
            fi_only = set(fi) - ni_set
            qty_n = float(cctv_qty[list(ni_set)].sum()) if ni_set else 0.0
            qty_f = float(cctv_qty[list(fi_only)].sum()) if fi_only else 0.0
            if qty_n >= 2:
                near_score = 18.0
            elif qty_n >= 1:
                near_score = 12.0
            else:
                near_score = 0.0
            scores[i] += near_score + _dim(qty_f, 6.0)

    # 가로등 (반경 25m, 체감감소 base=5.5)
    if streetlight_tree is not None:
        for i, idxs in enumerate(streetlight_tree.query_ball_point(pts, r=25.0)):
            scores[i] += _dim(len(idxs), 5.5)

    # 보안등 (반경 10m, 체감감소 base=4.0)
    if safelight_tree is not None:
        for i, idxs in enumerate(safelight_tree.query_ball_point(pts, r=10.0)):
            scores[i] += _dim(len(idxs), 4.0)

    # 편의점+24시 (주간: 고정 10점 / 야간: 반경 150m, 체감감소 base=3.5)
    has_store = (conv_tree is not None) or (open24_tree is not None)
    if has_store:
        if daytime:
            scores += STORE_DAY_SCORE
        else:
            for i, pt in enumerate(pts):
                cnt = 0
                if conv_tree is not None:
                    cnt += len(conv_tree.query_ball_point(pt, r=150.0))
                if open24_tree is not None:
                    cnt += len(open24_tree.query_ball_point(pt, r=150.0))
                scores[i] += _dim(cnt, 3.5)

    # 경찰서 (반경 300m, 체감감소 base=14.0)
    if police_tree is not None:
        for i, idxs in enumerate(police_tree.query_ball_point(pts, r=300.0)):
            scores[i] += _dim(len(idxs), 14.0)

    # 소방서 (반경 300m, cap=1, 10.5점)
    if firestation_tree is not None:
        for i, idxs in enumerate(firestation_tree.query_ball_point(pts, r=300.0)):
            scores[i] += min(len(idxs), 1) * 10.5

    # 유흥주점 (반경 100m, 체감감소 base=7.5, 감점)
    if ent_tree is not None:
        for i, idxs in enumerate(ent_tree.query_ball_point(pts, r=100.0)):
            scores[i] -= _dim(len(idxs), 7.5)

    return scores


def print_hist(label: str, scores: np.ndarray):
    n = len(scores)
    danger = int(np.sum(scores < DANGER_THRESH))
    safe   = int(np.sum(scores >= SAFE_THRESH))
    normal = n - danger - safe

    print(f"\n{'='*50}")
    print(f"[{label}]  총 {n:,}개 격자")
    print(f"{'='*50}")
    print(f"  위험 (S<{DANGER_THRESH:g}):        {danger:6,}개  {danger/n*100:5.1f}%")
    print(f"  보통 ({DANGER_THRESH:g}≤S<{SAFE_THRESH:g}):   {normal:6,}개  {normal/n*100:5.1f}%")
    print(f"  안전 (S≥{SAFE_THRESH:g}):         {safe:6,}개  {safe/n*100:5.1f}%")
    print(f"  최소={scores.min():.1f}  최대={scores.max():.1f}  평균={scores.mean():.1f}  중앙={np.median(scores):.1f}")

    # 히스토그램 (2점 단위)
    s_min = math.floor(scores.min() / 2) * 2
    s_max = math.ceil(scores.max() / 2) * 2
    bins = np.arange(s_min, s_max + 2, 2)
    counts, edges = np.histogram(scores, bins=bins)
    print(f"\n  히스토그램 (2점 단위):")
    bar_max = counts.max()
    for i, cnt in enumerate(counts):
        bar = int(cnt / bar_max * 30) if bar_max > 0 else 0
        lo, hi = edges[i], edges[i+1]
        if hi <= DANGER_THRESH:
            marker = "위험"
        elif lo >= SAFE_THRESH:
            marker = "안전"
        else:
            marker = "보통"
        print(f"  [{lo:5.0f}~{hi:4.0f}) {'#'*bar:<30} {cnt:6,}개  {cnt/n*100:5.2f}%  {marker}")


def main():
    print("=== 동작구 안전점수 분포 분석 ===")
    print(f"격자 간격: {GRID_M}m  /  임계값: 위험<{DANGER_THRESH} / 보통 {DANGER_THRESH}~{SAFE_THRESH} / 안전≥{SAFE_THRESH}")

    print("\n데이터 로드 중...")
    cctv_tree, cctv_qty   = load_tree(CCTV_PATH, qty_col="qty")
    safelight_tree, _     = load_tree(SAFELIGHT_PATH)
    streetlight_tree, _   = load_tree(STREETLIGHT_PATH)
    conv_tree, _          = load_tree(CONVENIENCE_PATH)
    open24_tree, _        = load_tree(OPEN24_PATH)
    police_tree, _        = load_tree(POLICE_PATH)
    ent_tree, _           = load_tree(ENTERTAINMENT_PATH)
    firestation_tree, _   = load_tree(FIRESTATION_PATH)

    trees = (cctv_tree, cctv_qty, safelight_tree, streetlight_tree,
             conv_tree, open24_tree, police_tree, ent_tree, firestation_tree)

    print("\n격자 생성 중...")
    grid_lat, grid_lng, n_lat, n_lng = build_grid()
    print(f"  격자 크기: {n_lat} × {n_lng} = {len(grid_lat):,}개")

    print("\n점수 계산 중...")
    scores_day   = batch_scores(grid_lat, grid_lng, trees, daytime=True)
    print("  주간 완료.")
    scores_night = batch_scores(grid_lat, grid_lng, trees, daytime=False)
    print("  야간 완료.")

    print_hist("주간 (08~22시, 편의점 고정 10점)", scores_day)
    print_hist("야간 (22~08시, 편의점 실제 반경)", scores_night)

    print("\n=== 분석 완료 ===")


if __name__ == "__main__":
    main()

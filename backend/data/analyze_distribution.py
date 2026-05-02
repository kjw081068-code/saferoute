"""
동작구 전체 안전점수 분포 분석 스크립트
- 25m 간격 격자 생성 (동작구 바운딩박스)
- 각 격자 중심점 점수 계산 (체감수익감소 방식)
- 전체/내부/경계 격자 등급 분포 출력
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

# ──────────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────────
DATA_DIR = Path(__file__).parent

CCTV_PATH        = DATA_DIR / "cctv_dongjak.csv"
SAFELIGHT_PATH   = DATA_DIR / "safelight_dongjak.csv"
STREETLIGHT_PATH = DATA_DIR / "streetlight_dongjak.csv"
CONVENIENCE_PATH = DATA_DIR / "convenience_dongjak.csv"
POLICE_PATH      = DATA_DIR / "police_dongjak.csv"
ENTERTAINMENT_PATH = DATA_DIR / "entertainment_dongjak.csv"

# ──────────────────────────────────────────────
# 동작구 바운딩박스
# ──────────────────────────────────────────────
LAT_MIN, LAT_MAX = 37.490, 37.535814
LNG_MIN, LNG_MAX = 126.916, 126.988477

GRID_M = 25.0  # 격자 간격 (m)

# 서울 위경도→미터 변환 상수
_REF_LAT = 37.47
_LAT_M = 111_320
_LNG_M = 111_320 * math.cos(math.radians(_REF_LAT))

# 점수 임계값
DANGER_THRESH = 40.0
SAFE_THRESH   = 60.0

# 기본점수
BASE_SCORE = 40.0


# ──────────────────────────────────────────────
# 체감수익감소 점수
# ──────────────────────────────────────────────
def _diminishing(count: float, base: float) -> float:
    score, mult, rem = 0.0, 1.0, float(count)
    while rem >= 0.001:
        take = min(1.0, rem)
        score += base * mult * take
        mult *= 0.5
        rem -= take
    return score


# ──────────────────────────────────────────────
# KDTree 로드
# ──────────────────────────────────────────────
def load_tree_with_qty(path: Path, qty_col: str = None):
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


# ──────────────────────────────────────────────
# 격자 생성
# ──────────────────────────────────────────────
def build_grid():
    lat_step = GRID_M / _LAT_M
    lng_step = GRID_M / _LNG_M

    lats = np.arange(LAT_MIN + lat_step / 2, LAT_MAX, lat_step)
    lngs = np.arange(LNG_MIN + lng_step / 2, LNG_MAX, lng_step)

    grid_lat, grid_lng = np.meshgrid(lats, lngs, indexing="ij")
    grid_lat = grid_lat.ravel()
    grid_lng = grid_lng.ravel()

    n_lat = len(lats)
    n_lng = len(lngs)
    return grid_lat, grid_lng, n_lat, n_lng


# ──────────────────────────────────────────────
# 배치 점수 계산
# ──────────────────────────────────────────────
def batch_scores(grid_lat, grid_lng,
                 cctv_tree, cctv_qty,
                 safelight_tree,
                 streetlight_tree,
                 conv_tree,
                 police_tree,
                 ent_tree):
    xs = grid_lng * _LNG_M
    ys = grid_lat * _LAT_M
    pts = np.column_stack([xs, ys])
    n = len(grid_lat)
    scores = np.full(n, BASE_SCORE)

    # CCTV 30m cap=2×6.0 + 70m cap=2×3.5
    if cctv_tree is not None:
        near_list = cctv_tree.query_ball_point(pts, r=30.0)
        far_list  = cctv_tree.query_ball_point(pts, r=70.0)
        for i, (ni, fi) in enumerate(zip(near_list, far_list)):
            qty_n = float(cctv_qty[list(ni)].sum()) if ni else 0.0
            qty_f = float(cctv_qty[list(fi)].sum()) if fi else 0.0
            scores[i] += min(qty_n, 2) * 6.0 + min(qty_f, 2) * 3.5

    # 가로등 (반경 20m, cap=2×5.5)
    if streetlight_tree is not None:
        idxs_list = streetlight_tree.query_ball_point(pts, r=20.0)
        for i, idxs in enumerate(idxs_list):
            scores[i] += min(len(idxs), 2) * 5.5

    # 보안등 (반경 5m, cap=1×4.0)
    if safelight_tree is not None:
        idxs_list = safelight_tree.query_ball_point(pts, r=5.0)
        for i, idxs in enumerate(idxs_list):
            scores[i] += min(len(idxs), 1) * 4.0

    # 편의점 (반경 100m, cap=2×3.5)
    if conv_tree is not None:
        idxs_list = conv_tree.query_ball_point(pts, r=100.0)
        for i, idxs in enumerate(idxs_list):
            scores[i] += min(len(idxs), 2) * 3.5

    # 경찰서 (반경 200m, cap=1×14.0)
    if police_tree is not None:
        idxs_list = police_tree.query_ball_point(pts, r=200.0)
        for i, idxs in enumerate(idxs_list):
            scores[i] += min(len(idxs), 1) * 14.0

    # 유흥주점 (반경 50m, cap=2×7.5, 감점)
    if ent_tree is not None:
        idxs_list = ent_tree.query_ball_point(pts, r=50.0)
        for i, idxs in enumerate(idxs_list):
            scores[i] -= min(len(idxs), 2) * 7.5

    scores = np.maximum(scores, 10.0)
    return scores


def grade(s):
    if s < DANGER_THRESH:
        return "위험"
    if s < SAFE_THRESH:
        return "보통"
    return "안전"


def print_dist(label: str, scores: np.ndarray):
    n = len(scores)
    danger = np.sum(scores < DANGER_THRESH)
    safe   = np.sum(scores >= SAFE_THRESH)
    normal = n - danger - safe
    print(f"\n[{label}] 총 {n:,}개 격자")
    print(f"  위험 (<{DANGER_THRESH}): {danger:6,}개  {danger/n*100:5.1f}%")
    print(f"  보통 ({DANGER_THRESH}~{SAFE_THRESH}): {normal:6,}개  {normal/n*100:5.1f}%")
    print(f"  안전 (≥{SAFE_THRESH}): {safe:6,}개  {safe/n*100:5.1f}%")
    print(f"  점수 통계: 최소={scores.min():.1f}  최대={scores.max():.1f}  평균={scores.mean():.1f}  중앙={np.median(scores):.1f}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    print("=== 동작구 안전점수 분포 분석 ===")
    print(f"격자 간격: {GRID_M}m  /  바운딩박스: lat {LAT_MIN}~{LAT_MAX}, lng {LNG_MIN}~{LNG_MAX}")
    print()

    # 데이터 로드
    print("데이터 로드 중...")
    cctv_tree, cctv_qty = load_tree_with_qty(CCTV_PATH, qty_col="qty")
    safelight_tree, _   = load_tree_with_qty(SAFELIGHT_PATH)
    streetlight_tree, _ = load_tree_with_qty(STREETLIGHT_PATH)
    conv_tree, _        = load_tree_with_qty(CONVENIENCE_PATH)
    police_tree, _      = load_tree_with_qty(POLICE_PATH)
    ent_tree, _         = load_tree_with_qty(ENTERTAINMENT_PATH)

    # 격자 생성
    print("\n격자 생성 중...")
    grid_lat, grid_lng, n_lat, n_lng = build_grid()
    print(f"  격자 크기: {n_lat} × {n_lng} = {len(grid_lat):,}개")

    # 경계 마스크 (가장 바깥 1겹)
    row_idx = np.arange(len(grid_lat)) // n_lng
    col_idx = np.arange(len(grid_lat)) % n_lng
    boundary_mask = (
        (row_idx == 0) | (row_idx == n_lat - 1) |
        (col_idx == 0) | (col_idx == n_lng - 1)
    )
    interior_mask = ~boundary_mask

    n_boundary = int(boundary_mask.sum())
    n_interior = int(interior_mask.sum())
    print(f"  경계 격자: {n_boundary:,}개 ({n_boundary/len(grid_lat)*100:.1f}%)")
    print(f"  내부 격자: {n_interior:,}개 ({n_interior/len(grid_lat)*100:.1f}%)")

    # 점수 계산
    print("\n점수 계산 중 (시간이 걸릴 수 있음)...")
    scores = batch_scores(
        grid_lat, grid_lng,
        cctv_tree, cctv_qty,
        safelight_tree,
        streetlight_tree,
        conv_tree,
        police_tree,
        ent_tree,
    )
    print("  계산 완료!")

    # 결과 출력
    print_dist("전체 격자", scores)
    print_dist("내부 격자 (경계 제외)", scores[interior_mask])
    print_dist("경계 격자", scores[boundary_mask])

    print("\n=== 분석 완료 ===")
    print(f"현재 임계값: 위험<{DANGER_THRESH} / 보통 {DANGER_THRESH}~{SAFE_THRESH} / 안전≥{SAFE_THRESH}")


if __name__ == "__main__":
    main()

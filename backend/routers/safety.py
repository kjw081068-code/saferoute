import math
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from scipy.spatial import cKDTree

router = APIRouter()

# CSV_PATH = Path(__file__).parents[1] / "data" / "safety_grid.csv"          # 관악구 비활성화
CSV_PATH_DONGJAK = Path(__file__).parents[1] / "data" / "safety_grid_dongjak.csv"
# CCTV_CSV_PATH = Path(__file__).parents[1] / "data" / "cctv_raw.csv"        # 관악구 비활성화
CCTV_DONGJAK_CSV_PATH = Path(__file__).parents[1] / "data" / "cctv_dongjak.csv"
SAFELIGHT_DONGJAK_CSV_PATH = Path(__file__).parents[1] / "data" / "safelight_dongjak.csv"
# STREETLIGHT_CSV_PATH = Path(__file__).parents[1] / "data" / "streetlight_raw.csv"  # 관악구 비활성화
STREETLIGHT_DONGJAK_CSV_PATH  = Path(__file__).parents[1] / "data" / "streetlight_dongjak.csv"
# CONVENIENCE_GWANAK_CSV_PATH = Path(__file__).parents[1] / "data" / "convenience_gwanak.csv"  # 관악구 비활성화
CONVENIENCE_DONGJAK_CSV_PATH  = Path(__file__).parents[1] / "data" / "convenience_dongjak.csv"
# POLICE_GWANAK_CSV_PATH = Path(__file__).parents[1] / "data" / "police_gwanak.csv"            # 관악구 비활성화
POLICE_DONGJAK_CSV_PATH       = Path(__file__).parents[1] / "data" / "police_dongjak.csv"
# ENTERTAINMENT_GWANAK_CSV_PATH = Path(__file__).parents[1] / "data" / "entertainment_gwanak.csv"  # 관악구 비활성화
ENTERTAINMENT_DONGJAK_CSV_PATH= Path(__file__).parents[1] / "data" / "entertainment_dongjak.csv"

# 서울 기준 위경도→미터 변환 상수
_REF_LAT = 37.47
_LAT_M = 111_320
_LNG_M = 111_320 * math.cos(math.radians(_REF_LAT))

# 절대 등급 임계값
_GRADE_DANGER_THRESH = 40.0
_GRADE_SAFE_THRESH   = 60.0

# 기본 안전점수
_BASE_SCORE = 40.0

_cctv_tree: Optional[cKDTree] = None
_cctv_qty: Optional[np.ndarray] = None
_safelight_tree: Optional[cKDTree] = None
_streetlight_tree: Optional[cKDTree] = None
_convenience_tree: Optional[cKDTree] = None
_police_tree: Optional[cKDTree] = None
_entertainment_tree: Optional[cKDTree] = None


def _diminishing_score(count: float, base: float) -> float:
    """체감 수익 감소 점수: n번째 개체는 base × 0.5^(n-1), 수렴 최대 = base × 2"""
    score, mult, rem = 0.0, 1.0, float(count)
    while rem >= 0.001:
        take = min(1.0, rem)
        score += base * mult * take
        mult *= 0.5
        rem -= take
    return score


def _load_cctv() -> None:
    global _cctv_tree, _cctv_qty
    if _cctv_tree is not None:
        return
    frames = []
    # 관악구 CCTV 비활성화
    # if CCTV_CSV_PATH.exists():
    #     df1 = pd.read_csv(CCTV_CSV_PATH, encoding="cp949")
    #     df1 = df1.rename(columns={"위도": "lat", "경도": "lng", "CCTV 수량": "qty"})
    #     frames.append(df1[["lat", "lng", "qty"]])
    if CCTV_DONGJAK_CSV_PATH.exists():
        df2 = pd.read_csv(CCTV_DONGJAK_CSV_PATH, encoding="utf-8-sig")
        frames.append(df2[["lat", "lng", "qty"]])
    if not frames:
        _cctv_tree = None
        _cctv_qty = np.array([])
        return
    cctv = pd.concat(frames, ignore_index=True).dropna(subset=["lat", "lng", "qty"])
    xs = cctv["lng"].values * _LNG_M
    ys = cctv["lat"].values * _LAT_M
    _cctv_tree = cKDTree(np.column_stack([xs, ys]))
    _cctv_qty = cctv["qty"].values.astype(float)


def _cctv_score_for_coord(lat: float, lng: float) -> float:
    """30m 직접감시 cap=2 × 6.0(max 12) + 70m 경로추적 cap=2 × 3.5(max 7)."""
    _load_cctv()
    if _cctv_tree is None or len(_cctv_qty) == 0:
        return 0.0
    x, y = lng * _LNG_M, lat * _LAT_M
    idxs_near = _cctv_tree.query_ball_point([x, y], r=30.0)
    idxs_far  = _cctv_tree.query_ball_point([x, y], r=70.0)
    qty_near = float(_cctv_qty[list(idxs_near)].sum()) if idxs_near else 0.0
    qty_far  = float(_cctv_qty[list(idxs_far)].sum())  if idxs_far  else 0.0
    return min(qty_near, 2) * 6.0 + min(qty_far, 2) * 3.5


def _load_safelight() -> None:
    global _safelight_tree
    if _safelight_tree is not None:
        return
    if not SAFELIGHT_DONGJAK_CSV_PATH.exists():
        _safelight_tree = None
        return
    df = pd.read_csv(SAFELIGHT_DONGJAK_CSV_PATH, encoding="utf-8-sig").dropna(subset=["lat", "lng"])
    xs = df["lng"].values * _LNG_M
    ys = df["lat"].values * _LAT_M
    _safelight_tree = cKDTree(np.column_stack([xs, ys]))


def _safelight_score_for_coord(lat: float, lng: float, radius_m: float = 5.0) -> float:
    """반경 5m 내 보안등 cap=1 × 4.0(max 4)."""
    _load_safelight()
    if _safelight_tree is None:
        return 0.0
    idxs = _safelight_tree.query_ball_point([lng * _LNG_M, lat * _LAT_M], r=radius_m)
    return min(len(idxs), 1) * 4.0


def _load_streetlight() -> None:
    global _streetlight_tree
    if _streetlight_tree is not None:
        return
    frames = []
    # 관악구 가로등 비활성화
    # if STREETLIGHT_CSV_PATH.exists():
    #     df = pd.read_csv(STREETLIGHT_CSV_PATH, encoding="cp949").rename(columns={"위도": "lat", "경도": "lng"})
    #     frames.append(df[["lat", "lng"]])
    if STREETLIGHT_DONGJAK_CSV_PATH.exists():
        frames.append(pd.read_csv(STREETLIGHT_DONGJAK_CSV_PATH, encoding="utf-8-sig")[["lat", "lng"]])
    if not frames:
        _streetlight_tree = None
        return
    df = pd.concat(frames, ignore_index=True).dropna(subset=["lat", "lng"])
    xs, ys = df["lng"].values * _LNG_M, df["lat"].values * _LAT_M
    _streetlight_tree = cKDTree(np.column_stack([xs, ys]))


def _streetlight_score_for_coord(lat: float, lng: float, radius_m: float = 20.0) -> float:
    """반경 20m 내 가로등 cap=2 × 5.5(max 11)."""
    _load_streetlight()
    if _streetlight_tree is None:
        return 0.0
    idxs = _streetlight_tree.query_ball_point([lng * _LNG_M, lat * _LAT_M], r=radius_m)
    return min(len(idxs), 2) * 5.5


def _load_convenience() -> None:
    global _convenience_tree
    if _convenience_tree is not None:
        return
    frames = []
    # 관악구 편의점 비활성화
    # if CONVENIENCE_GWANAK_CSV_PATH.exists():
    #     frames.append(pd.read_csv(CONVENIENCE_GWANAK_CSV_PATH, encoding="utf-8-sig")[["lat", "lng"]])
    if CONVENIENCE_DONGJAK_CSV_PATH.exists():
        frames.append(pd.read_csv(CONVENIENCE_DONGJAK_CSV_PATH, encoding="utf-8-sig")[["lat", "lng"]])
    if not frames:
        _convenience_tree = None
        return
    df = pd.concat(frames, ignore_index=True).dropna(subset=["lat", "lng"])
    xs, ys = df["lng"].values * _LNG_M, df["lat"].values * _LAT_M
    _convenience_tree = cKDTree(np.column_stack([xs, ys]))


def _convenience_score_for_coord(lat: float, lng: float, radius_m: float = 100.0) -> float:
    """반경 100m 내 편의점 cap=2 × 3.5(max 7)."""
    _load_convenience()
    if _convenience_tree is None:
        return 0.0
    idxs = _convenience_tree.query_ball_point([lng * _LNG_M, lat * _LAT_M], r=radius_m)
    return min(len(idxs), 2) * 3.5


def _load_police() -> None:
    global _police_tree
    if _police_tree is not None:
        return
    frames = []
    # 관악구 경찰서 비활성화
    # if POLICE_GWANAK_CSV_PATH.exists():
    #     frames.append(pd.read_csv(POLICE_GWANAK_CSV_PATH, encoding="utf-8-sig")[["lat", "lng"]])
    if POLICE_DONGJAK_CSV_PATH.exists():
        frames.append(pd.read_csv(POLICE_DONGJAK_CSV_PATH, encoding="utf-8-sig")[["lat", "lng"]])
    if not frames:
        _police_tree = None
        return
    df = pd.concat(frames, ignore_index=True).dropna(subset=["lat", "lng"])
    xs, ys = df["lng"].values * _LNG_M, df["lat"].values * _LAT_M
    _police_tree = cKDTree(np.column_stack([xs, ys]))


def _police_score_for_coord(lat: float, lng: float, radius_m: float = 200.0) -> float:
    """반경 200m 내 경찰서 cap=1 × 14.0(max 14)."""
    _load_police()
    if _police_tree is None:
        return 0.0
    idxs = _police_tree.query_ball_point([lng * _LNG_M, lat * _LAT_M], r=radius_m)
    return min(len(idxs), 1) * 14.0


def _load_entertainment() -> None:
    global _entertainment_tree
    if _entertainment_tree is not None:
        return
    frames = []
    # 관악구 유흥주점 비활성화
    # if ENTERTAINMENT_GWANAK_CSV_PATH.exists():
    #     frames.append(pd.read_csv(ENTERTAINMENT_GWANAK_CSV_PATH, encoding="utf-8-sig")[["lat", "lng"]])
    if ENTERTAINMENT_DONGJAK_CSV_PATH.exists():
        frames.append(pd.read_csv(ENTERTAINMENT_DONGJAK_CSV_PATH, encoding="utf-8-sig")[["lat", "lng"]])
    if not frames:
        _entertainment_tree = None
        return
    df = pd.concat(frames, ignore_index=True).dropna(subset=["lat", "lng"])
    xs, ys = df["lng"].values * _LNG_M, df["lat"].values * _LAT_M
    _entertainment_tree = cKDTree(np.column_stack([xs, ys]))


def _entertainment_score_for_coord(lat: float, lng: float, radius_m: float = 50.0) -> float:
    """반경 50m 내 유흥주점 cap=2 × 7.5(max 15 감점)."""
    _load_entertainment()
    if _entertainment_tree is None:
        return 0.0
    idxs = _entertainment_tree.query_ball_point([lng * _LNG_M, lat * _LAT_M], r=radius_m)
    return min(len(idxs), 2) * 7.5


def score_to_grade_realtime(score: float) -> str:
    """고정 절대 임계값으로 점수를 등급으로 변환합니다.
    위험: <40 / 보통: 40~60 / 안전: >=60
    """
    if score < _GRADE_DANGER_THRESH:
        return "위험"
    if score < _GRADE_SAFE_THRESH:
        return "보통"
    return "안전"


class SafetyScore(BaseModel):
    lat: float
    lng: float
    score: float
    grade: str
    cctv_count: int
    light_count: int
    conv_count: int
    ent_count: int
    police_count: int


class LatLng(BaseModel):
    lat: float
    lng: float


class MapPoints(BaseModel):
    cctv: List[LatLng]
    streetlight: List[LatLng]


@router.get("/map-points", response_model=MapPoints)
def get_map_points():
    try:
        cctv_df = pd.read_csv(CCTV_DONGJAK_CSV_PATH, encoding="utf-8-sig")
        cctv_list = [LatLng(lat=row["lat"], lng=row["lng"]) for _, row in cctv_df.iterrows()]
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="cctv_dongjak.csv 파일을 찾을 수 없습니다.")
    try:
        light_df = pd.read_csv(STREETLIGHT_DONGJAK_CSV_PATH, encoding="utf-8-sig")
        light_list = [LatLng(lat=row["lat"], lng=row["lng"]) for _, row in light_df.iterrows()]
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="streetlight_dongjak.csv 파일을 찾을 수 없습니다.")
    return MapPoints(cctv=cctv_list, streetlight=light_list)


@router.get("/safety-score", response_model=SafetyScore)
def get_safety_score(
    lat: float = Query(..., description="위도"),
    lng: float = Query(..., description="경도"),
):
    """클릭 좌표에서 실시간 반경 계산으로 안전점수를 반환합니다."""
    _load_cctv()
    _load_streetlight()
    _load_safelight()
    _load_convenience()
    _load_police()
    _load_entertainment()

    x, y = lng * _LNG_M, lat * _LAT_M

    # CCTV qty 합산 (30m 직접감시 + 70m 경로추적 이중 반경)
    cctv_qty = 0.0
    cctv_qty_far = 0.0
    if _cctv_tree is not None and len(_cctv_qty) > 0:
        idxs_near = _cctv_tree.query_ball_point([x, y], r=30.0)
        idxs_far  = _cctv_tree.query_ball_point([x, y], r=70.0)
        cctv_qty     = float(_cctv_qty[list(idxs_near)].sum()) if idxs_near else 0.0
        cctv_qty_far = float(_cctv_qty[list(idxs_far)].sum())  if idxs_far  else 0.0

    # 가로등 개수
    street_count = 0
    if _streetlight_tree is not None:
        street_count = len(_streetlight_tree.query_ball_point([x, y], r=20.0))

    # 보안등 개수
    safe_count = 0
    if _safelight_tree is not None:
        safe_count = len(_safelight_tree.query_ball_point([x, y], r=5.0))

    # 편의점 개수
    conv_count = 0
    if _convenience_tree is not None:
        conv_count = len(_convenience_tree.query_ball_point([x, y], r=100.0))

    # 경찰서 개수
    police_count = 0
    if _police_tree is not None:
        police_count = len(_police_tree.query_ball_point([x, y], r=200.0))

    # 유흥주점 개수
    ent_count = 0
    if _entertainment_tree is not None:
        ent_count = len(_entertainment_tree.query_ball_point([x, y], r=50.0))

    score = max(
        _BASE_SCORE
        + min(cctv_qty, 2) * 6.0
        + min(cctv_qty_far, 2) * 3.5
        + min(street_count, 2) * 5.5
        + min(safe_count, 1) * 4.0
        + min(conv_count, 2) * 3.5
        + min(police_count, 1) * 14.0
        - min(ent_count, 2) * 7.5,
        10.0,
    )

    return SafetyScore(
        lat=lat,
        lng=lng,
        score=round(score, 1),
        grade=score_to_grade_realtime(score),
        cctv_count=round(cctv_qty),
        light_count=street_count + safe_count,
        conv_count=conv_count,
        ent_count=ent_count,
        police_count=police_count,
    )

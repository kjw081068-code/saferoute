import math
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

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
OPEN24_DONGJAK_CSV_PATH = Path(__file__).parents[1] / "data" / "open24_dongjak.csv"
FIRESTATION_DONGJAK_CSV_PATH = Path(__file__).parents[1] / "data" / "firestation_dongjak.csv"

# 서울 기준 위경도→미터 변환 상수
_REF_LAT = 37.47
_LAT_M = 111_320
_LNG_M = 111_320 * math.cos(math.radians(_REF_LAT))

# 가중합 점수 S에 대한 등급(예전 총점 40/60과 동치: S = 옛 총점 − 40)
_GRADE_SCORE_DANGER_LT = 0.0   # S < 0 → 위험 (옛 총점 < 40)
_GRADE_SCORE_SAFE_GE = 16.0    # S ≥ 16 → 안전

# 편의점·24시 점포: 야간(22~08시) base=3.5(수렴 11.67점) / 주간(08~22시) base=2.0(수렴 6.67점, 약한 상권 신호)
_TZ_SEOUL = ZoneInfo("Asia/Seoul")
_STORE_RADIUS_M = 150.0
_STORE_WEIGHT_NIGHT = 3.5   # 야간 체감 base (수렴 11.67점)
_STORE_WEIGHT_DAY   = 2.0   # 주간 체감 base (수렴 6.67점)
_STORE_RATE = 0.3

# 주간 활동성 보너스: 자연광·사람들의 자연 감시 효과
_DAYTIME_ACTIVITY_BONUS = 6.0


def store_proximity_night_window_kst(now: Optional[datetime] = None) -> bool:
    """True면 야간(20시~익일 7시 미만): 편의점·24시 점포를 실제 반경으로 반영.
    False면 주간(7시~20시 미만): 두 항목 모두 cap 만점만 적용(데이터 없으면 0).
    """
    t = now or datetime.now(_TZ_SEOUL)
    if t.tzinfo is None:
        t = t.replace(tzinfo=_TZ_SEOUL)
    else:
        t = t.astimezone(_TZ_SEOUL)
    h = t.hour
    return h >= 20 or h < 7


_cctv_tree: Optional[cKDTree] = None
_cctv_qty: Optional[np.ndarray] = None
_safelight_tree: Optional[cKDTree] = None
_streetlight_tree: Optional[cKDTree] = None
_convenience_tree: Optional[cKDTree] = None
_open24_tree: Optional[cKDTree] = None
_police_tree: Optional[cKDTree] = None
_entertainment_tree: Optional[cKDTree] = None
_firestation_tree: Optional[cKDTree] = None


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
    """30m 직접감시: 1개=12점, 2개 이상=18점 고정.
    30~100m 경로추적: base 6점, cap 3개, 체감수익감소(max 10.5점).
    """
    _load_cctv()
    if _cctv_tree is None or len(_cctv_qty) == 0:
        return 0.0
    x, y = lng * _LNG_M, lat * _LAT_M
    idxs_near = set(_cctv_tree.query_ball_point([x, y], r=30.0))
    idxs_far  = set(_cctv_tree.query_ball_point([x, y], r=100.0)) - idxs_near
    qty_near = float(_cctv_qty[list(idxs_near)].sum()) if idxs_near else 0.0
    qty_far  = float(_cctv_qty[list(idxs_far)].sum())  if idxs_far  else 0.0

    if qty_near >= 2:
        near_score = 18.0
    elif qty_near >= 1:
        near_score = 12.0
    else:
        near_score = 0.0

    far_score, mult, rem = 0.0, 1.0, min(qty_far, 3.0)
    while rem >= 0.001:
        take = min(1.0, rem)
        far_score += 6.0 * mult * take
        mult *= 0.5
        rem -= take

    return near_score + far_score


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


def _safelight_score_for_coord(lat: float, lng: float, radius_m: float = 10.0) -> float:
    """야간(22~08시)에만 반경 10m 내 보안등 cap=1 × 4.0. 주간에는 0점."""
    if not store_proximity_night_window_kst():
        return 0.0
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


def _streetlight_score_for_coord(lat: float, lng: float, radius_m: float = 30.0) -> float:
    """야간(22~08시)에만 반경 30m 내 가로등 cap=2 × 5.5. 주간에는 0점."""
    if not store_proximity_night_window_kst():
        return 0.0
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


def _load_open24() -> None:
    """24시간 영업 등 점포 CSV → KDTree (편의점과 동일 가중치 규칙용)."""
    global _open24_tree
    if _open24_tree is not None:
        return
    if not OPEN24_DONGJAK_CSV_PATH.exists():
        _open24_tree = None
        return
    df = pd.read_csv(OPEN24_DONGJAK_CSV_PATH, encoding="utf-8-sig").dropna(subset=["lat", "lng"])
    if len(df) == 0:
        _open24_tree = None
        return
    xs = df["lng"].values * _LNG_M
    ys = df["lat"].values * _LAT_M
    _open24_tree = cKDTree(np.column_stack([xs, ys]))


def _diminishing_score(count: float, base: float, rate: float = 0.5) -> float:
    """한계편익체감 점수: n번째 개체는 base × (1-rate)^(n-1), 수렴 최대 = base / rate."""
    score, mult, rem = 0.0, 1.0, float(count)
    while rem >= 0.001:
        take = min(1.0, rem)
        score += base * mult * take
        mult *= (1.0 - rate)
        rem -= take
    return score


def _combined_conv_open24_score_for_coord(lat: float, lng: float, radius_m: float = _STORE_RADIUS_M) -> float:
    """편의점 + 24시 점포를 한 레이어로 한계편익체감 적용.

    야간(22~08시): base=3.5, 수렴 11.67점 (안전 요소로 강하게 반영)
    주간(08~22시): base=2.0, 수렴 6.67점 (상권 활성화 약한 신호만 반영)
    """
    _load_convenience()
    _load_open24()
    has_any = (_convenience_tree is not None) or (_open24_tree is not None)
    if not has_any:
        return 0.0
    xy = [lng * _LNG_M, lat * _LAT_M]
    n = 0
    if _convenience_tree is not None:
        n += len(_convenience_tree.query_ball_point(xy, r=radius_m))
    if _open24_tree is not None:
        n += len(_open24_tree.query_ball_point(xy, r=radius_m))
    weight = _STORE_WEIGHT_NIGHT if store_proximity_night_window_kst() else _STORE_WEIGHT_DAY
    return _diminishing_score(n, weight, rate=_STORE_RATE)


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
    """가장 가까운 경찰서까지 거리 비례 감쇄 (0m=14점, 200m=0점)."""
    _load_police()
    if _police_tree is None:
        return 0.0
    dist, _ = _police_tree.query([lng * _LNG_M, lat * _LAT_M], k=1)
    if dist >= radius_m:
        return 0.0
    return 14.0 * (1.0 - dist / radius_m)


def _load_firestation() -> None:
    global _firestation_tree
    if _firestation_tree is not None:
        return
    if not FIRESTATION_DONGJAK_CSV_PATH.exists():
        _firestation_tree = None
        return
    df = pd.read_csv(FIRESTATION_DONGJAK_CSV_PATH, encoding="utf-8-sig").dropna(subset=["lat", "lng"])
    if len(df) == 0:
        _firestation_tree = None
        return
    xs, ys = df["lng"].values * _LNG_M, df["lat"].values * _LAT_M
    _firestation_tree = cKDTree(np.column_stack([xs, ys]))


def _firestation_score_for_coord(lat: float, lng: float, radius_m: float = 300.0) -> float:
    """가장 가까운 소방서까지 거리 비례 감쇄 (0m=10.5점, 300m=0점)."""
    _load_firestation()
    if _firestation_tree is None:
        return 0.0
    dist, _ = _firestation_tree.query([lng * _LNG_M, lat * _LAT_M], k=1)
    if dist >= radius_m:
        return 0.0
    return 10.5 * (1.0 - dist / radius_m)


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
    """반경 50m 내 유흥주점 감점. 야간에는 ×1.5 가중치 (주간 max 15점, 야간 max 22.5점)."""
    _load_entertainment()
    if _entertainment_tree is None:
        return 0.0
    idxs = _entertainment_tree.query_ball_point([lng * _LNG_M, lat * _LAT_M], r=radius_m)
    base = min(len(idxs), 2) * 7.5
    return base * 2.5 if store_proximity_night_window_kst() else base


def _daytime_activity_bonus() -> float:
    """주간(08~22시) 활동성 보너스. 야간에는 0점."""
    return 0.0 if store_proximity_night_window_kst() else _DAYTIME_ACTIVITY_BONUS


def score_to_grade_realtime(score: float) -> str:
    """가중합 점수 S를 등급으로 변환합니다.
    예전(기본 40 포함 총점 T) 기준 T<40 / 40≤T<60 / T≥60 과 동일하게,
    S = T − 40 이면 S<0 / 0≤S<20 / S≥20 입니다.
    """
    if score <= _GRADE_SCORE_DANGER_LT:
        return "위험"
    if score < _GRADE_SCORE_SAFE_GE:
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
    open24_count: int
    ent_count: int
    police_count: int
    firestation_count: int


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
    _load_open24()
    _load_police()
    _load_firestation()
    _load_entertainment()

    x, y = lng * _LNG_M, lat * _LAT_M

    # CCTV 30m 반경 수량 합(표시용; 점수는 _cctv_score_for_coord와 동일 로직)
    cctv_qty = 0.0
    if _cctv_tree is not None and len(_cctv_qty) > 0:
        idxs_near = _cctv_tree.query_ball_point([x, y], r=30.0)
        cctv_qty = float(_cctv_qty[list(idxs_near)].sum()) if idxs_near else 0.0

    # 가로등 개수
    street_count = 0
    if _streetlight_tree is not None:
        street_count = len(_streetlight_tree.query_ball_point([x, y], r=30.0))

    # 보안등 개수
    safe_count = 0
    if _safelight_tree is not None:
        safe_count = len(_safelight_tree.query_ball_point([x, y], r=10.0))

    # 편의점 개수(표시용; 점수의 야간 반경과 동일)
    conv_count = 0
    if _convenience_tree is not None:
        conv_count = len(_convenience_tree.query_ball_point([x, y], r=_STORE_RADIUS_M))

    # 24시간 점포 개수(표시용)
    open24_count = 0
    if _open24_tree is not None:
        open24_count = len(_open24_tree.query_ball_point([x, y], r=_STORE_RADIUS_M))

    # 경찰서 개수
    police_count = 0
    if _police_tree is not None:
        police_count = len(_police_tree.query_ball_point([x, y], r=200.0))

    # 소방서 개수
    firestation_count = 0
    if _firestation_tree is not None:
        firestation_count = len(_firestation_tree.query_ball_point([x, y], r=300.0))

    # 유흥주점 개수
    ent_count = 0
    if _entertainment_tree is not None:
        ent_count = len(_entertainment_tree.query_ball_point([x, y], r=50.0))

    score = (
        _daytime_activity_bonus()
        + _cctv_score_for_coord(lat, lng)
        + _streetlight_score_for_coord(lat, lng)
        + _safelight_score_for_coord(lat, lng, radius_m=18.0)
        + _combined_conv_open24_score_for_coord(lat, lng)
        + _police_score_for_coord(lat, lng)
        + _firestation_score_for_coord(lat, lng)
        - _entertainment_score_for_coord(lat, lng)
    )

    return SafetyScore(
        lat=lat,
        lng=lng,
        score=round(score, 1),
        grade=score_to_grade_realtime(score),
        cctv_count=round(cctv_qty),
        light_count=street_count + safe_count,
        conv_count=conv_count,
        open24_count=open24_count,
        ent_count=ent_count,
        police_count=police_count,
        firestation_count=firestation_count,
    )

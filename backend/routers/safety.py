import math
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from scipy.spatial import cKDTree

router = APIRouter()

CSV_PATH = Path(__file__).parents[1] / "data" / "safety_grid.csv"
CSV_PATH_DONGJAK = Path(__file__).parents[1] / "data" / "safety_grid_dongjak.csv"
CCTV_CSV_PATH = Path(__file__).parents[1] / "data" / "cctv_raw.csv"
CCTV_DONGJAK_CSV_PATH = Path(__file__).parents[1] / "data" / "cctv_dongjak.csv"
SAFELIGHT_DONGJAK_CSV_PATH = Path(__file__).parents[1] / "data" / "safelight_dongjak.csv"
STREETLIGHT_CSV_PATH = Path(__file__).parents[1] / "data" / "streetlight_raw.csv"

# 서울 기준 위경도→미터 변환 상수
_REF_LAT = 37.47
_LAT_M = 111_320
_LNG_M = 111_320 * math.cos(math.radians(_REF_LAT))

_grid_df: Optional[pd.DataFrame] = None
_cctv_tree: Optional[cKDTree] = None
_cctv_qty: Optional[np.ndarray] = None
_safelight_tree: Optional[cKDTree] = None
_grade_danger_thresh: Optional[float] = None
_grade_safe_thresh: Optional[float] = None


def _load_grid() -> pd.DataFrame:
    global _grid_df
    if _grid_df is None:
        df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
        df = df.rename(columns={"위도": "lat", "경도": "lng"})
        if CSV_PATH_DONGJAK.exists():
            df2 = pd.read_csv(CSV_PATH_DONGJAK, encoding="utf-8-sig")
            df2 = df2.rename(columns={"위도": "lat", "경도": "lng"})
            df = pd.concat([df, df2], ignore_index=True)
        # 관악구에 없는 컬럼(safelight_count 등)을 0으로 채움
        if "safelight_count" in df.columns:
            df["safelight_count"] = df["safelight_count"].fillna(0).astype(int)
        _grid_df = df
    return _grid_df


def _load_cctv() -> None:
    """CCTV 원본 CSV를 로드하고 미터 단위 KDTree를 구축합니다."""
    global _cctv_tree, _cctv_qty
    if _cctv_tree is not None:
        return

    frames = []
    if CCTV_CSV_PATH.exists():
        df1 = pd.read_csv(CCTV_CSV_PATH, encoding="cp949")
        df1 = df1.rename(columns={"위도": "lat", "경도": "lng", "CCTV 수량": "qty"})
        frames.append(df1[["lat", "lng", "qty"]])
    if CCTV_DONGJAK_CSV_PATH.exists():
        df2 = pd.read_csv(CCTV_DONGJAK_CSV_PATH, encoding="utf-8-sig")
        frames.append(df2[["lat", "lng", "qty"]])

    if not frames:
        _cctv_tree = None
        _cctv_qty = np.array([])
        return

    cctv = pd.concat(frames, ignore_index=True).dropna(subset=["lat", "lng", "qty"])
    # 위경도를 미터 단위로 변환하여 KDTree 구축
    xs = cctv["lng"].values * _LNG_M
    ys = cctv["lat"].values * _LAT_M
    _cctv_tree = cKDTree(np.column_stack([xs, ys]))
    _cctv_qty = cctv["qty"].values.astype(float)


def _cctv_score_for_coord(lat: float, lng: float) -> float:
    """이중 반경 CCTV 점수를 반환합니다.
    15m 이내: min(qty, 4) × 5  (최대 20점)
    15m 초과~30m 이내: min(qty, 4) × 2.5  (최대 10점)
    두 구역 카메라가 다를 경우 독립 합산.
    """
    _load_cctv()
    if _cctv_tree is None or len(_cctv_qty) == 0:
        return 0.0

    x = lng * _LNG_M
    y = lat * _LAT_M

    inner_idxs = set(_cctv_tree.query_ball_point([x, y], r=15.0))
    outer_idxs = set(_cctv_tree.query_ball_point([x, y], r=30.0)) - inner_idxs

    inner_qty = float(_cctv_qty[list(inner_idxs)].sum()) if inner_idxs else 0.0
    outer_qty = float(_cctv_qty[list(outer_idxs)].sum()) if outer_idxs else 0.0

    return min(inner_qty, 4.0) * 5.0 + min(outer_qty, 4.0) * 2.5


def _load_safelight() -> None:
    """보안등(동작구) CSV를 로드하고 미터 단위 KDTree를 구축합니다."""
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
    """주어진 좌표로부터 radius_m 이내 보안등 개수로 점수를 반환합니다.
    기존 계산식 동일: min(count, 3) * 3 (최대 9점)
    """
    _load_safelight()
    if _safelight_tree is None:
        return 0.0

    x = lng * _LNG_M
    y = lat * _LAT_M
    idxs = _safelight_tree.query_ball_point([x, y], r=radius_m)
    return min(len(idxs), 3) * 3.0


def _get_grade_thresholds() -> Tuple[float, float]:
    """격자 score 열의 30/70 백분위수를 절대 임계값으로 반환합니다 (1회 캐싱)."""
    global _grade_danger_thresh, _grade_safe_thresh
    if _grade_danger_thresh is None:
        df = _load_grid()
        _grade_danger_thresh = float(df["score"].quantile(0.30))
        _grade_safe_thresh = float(df["score"].quantile(0.70))
    return _grade_danger_thresh, _grade_safe_thresh


def score_to_grade_realtime(score: float) -> str:
    """절대 임계값 기반으로 점수를 등급으로 변환합니다."""
    danger_thresh, safe_thresh = _get_grade_thresholds()
    if score < danger_thresh:
        return "위험"
    if score < safe_thresh:
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
        cctv_df = pd.read_csv(CCTV_CSV_PATH, encoding="cp949")
        cctv_df = cctv_df[(cctv_df["위도"] > 37.0) & (cctv_df["위도"] < 38.0) & (cctv_df["경도"] > 126.0) & (cctv_df["경도"] < 128.0)]
        cctv_list = [LatLng(lat=row["위도"], lng=row["경도"]) for _, row in cctv_df.iterrows()]
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="cctv_raw.csv 파일을 찾을 수 없습니다.")

    try:
        light_df = pd.read_csv(STREETLIGHT_CSV_PATH, encoding="cp949")
        light_df = light_df[(light_df["위도"] > 37.0) & (light_df["위도"] < 38.0) & (light_df["경도"] > 126.0) & (light_df["경도"] < 128.0)]
        light_list = [LatLng(lat=row["위도"], lng=row["경도"]) for _, row in light_df.iterrows()]
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="streetlight_raw.csv 파일을 찾을 수 없습니다.")

    return MapPoints(cctv=cctv_list, streetlight=light_list)


@router.get("/safety-score", response_model=SafetyScore)
def get_safety_score(
    lat: float = Query(..., description="위도"),
    lng: float = Query(..., description="경도"),
):
    try:
        df = _load_grid()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="safety_grid.csv 파일을 찾을 수 없습니다.")

    idx = ((df["lat"] - lat) ** 2 + (df["lng"] - lng) ** 2).idxmin()
    row = df.loc[idx]

    return SafetyScore(
        lat=lat,
        lng=lng,
        score=round(float(row["score"]), 1),
        grade=str(row["grade"]),
        cctv_count=int(row["cctv_count"]),
        light_count=int(row["light_count"]),
        conv_count=int(row["conv_count"]),
        ent_count=int(row["ent_count"]),
        police_count=int(row.get("police_count", 0)),
    )

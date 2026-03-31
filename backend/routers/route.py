import math
import os
from typing import List

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from routers.safety import _load_grid

router = APIRouter()

TMAP_PEDESTRIAN_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
SAMPLE_INTERVAL_M = 100  # 샘플링 간격 (미터, 격자 크기와 동일)


# ── 요청/응답 모델 ───────────────────────────────────────────────────────────

class RouteRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    dest_lat: float
    dest_lng: float


class SegmentScore(BaseModel):
    lat: float
    lng: float
    score: float
    grade: str


class RouteResult(BaseModel):
    type: str                     # "safe" or "normal"
    points: List[List[float]]     # [[lat, lng], ...]
    segments: List[SegmentScore]
    avg_score: float
    grade: str
    duration: int                 # 분 단위


class RouteResponse(BaseModel):
    routes: List[RouteResult]


# ── 내부 유틸 함수 ────────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 거리를 미터 단위로 반환합니다."""
    R = 6_371_000  # 지구 반지름 (미터)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _extract_coords(kakao_route: dict) -> List[tuple]:
    """카카오 경로 한 개에서 (lat, lng) 튜플 리스트를 추출합니다.

    카카오 응답의 vertexes는 평탄 배열 [lng0, lat0, lng1, lat1, ...] 형태입니다.
    """
    coords = []
    for section in kakao_route.get("sections", []):
        for road in section.get("roads", []):
            vx = road.get("vertexes", [])
            for i in range(0, len(vx) - 1, 2):
                coords.append((vx[i + 1], vx[i]))  # (lat, lng)
    return coords


def _extract_tmap_coords(features: list) -> List[tuple]:
    """TMAP GeoJSON features에서 (lat, lng) 튜플 리스트를 추출합니다."""
    coords = []
    for feature in features:
        geom = feature.get("geometry", {})
        if geom.get("type") == "LineString":
            for lng, lat in geom.get("coordinates", []):
                coords.append((lat, lng))
    return coords


def _sample_coords(coords: List[tuple], interval_m: float = SAMPLE_INTERVAL_M) -> List[tuple]:
    """누적 거리 기반으로 interval_m 간격마다 좌표를 샘플링합니다.

    시작점과 끝점은 항상 포함됩니다.
    """
    if not coords:
        return []
    sampled = [coords[0]]
    accumulated = 0.0
    for i in range(1, len(coords)):
        prev = coords[i - 1]
        curr = coords[i]
        accumulated += _haversine_m(prev[0], prev[1], curr[0], curr[1])
        if accumulated >= interval_m:
            sampled.append(curr)
            accumulated = 0.0
    # 끝점이 마지막 샘플과 다를 경우 추가
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    return sampled


def _score_for_coord(lat: float, lng: float) -> tuple:
    """safety_grid에서 최근접 격자의 (score, grade)를 반환합니다."""
    df = _load_grid()
    idx = ((df["lat"] - lat) ** 2 + (df["lng"] - lng) ** 2).idxmin()
    row = df.loc[idx]
    return float(row["score"]), str(row["grade"])


def _score_to_grade(segments: list) -> str:
    """구간 등급 비율로 경로 전체 등급을 결정합니다 (상대평가 기반)."""
    if not segments:
        return "보통"
    total = len(segments)
    safe_cnt = sum(1 for s in segments if s.grade == "안전")
    danger_cnt = sum(1 for s in segments if s.grade == "위험")
    if danger_cnt / total >= 0.3:
        return "위험"
    if safe_cnt / total >= 0.5:
        return "안전"
    return "보통"


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/safe-route", response_model=RouteResponse)
def get_safe_route(req: RouteRequest):
    """TMAP 도보 경로 API로 경로를 조회하고 각 경로의 안전점수를 계산합니다."""
    tmap_key = os.getenv("TMAP_APP_KEY")
    if not tmap_key:
        raise HTTPException(status_code=500, detail="TMAP_APP_KEY 환경변수가 설정되지 않았습니다.")

    headers = {
        "appKey": tmap_key,
        "Content-Type": "application/json",
    }
    body = {
        "startX": str(req.origin_lng),
        "startY": str(req.origin_lat),
        "endX": str(req.dest_lng),
        "endY": str(req.dest_lat),
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "startName": "출발지",
        "endName": "도착지",
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(TMAP_PEDESTRIAN_URL, headers=headers, json=body)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"TMAP API 오류: {e.response.status_code} {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"TMAP API 연결 실패: {str(e)}")

    data = resp.json()
    features = data.get("features", [])
    if not features:
        raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.")

    # 소요시간 추출 (첫 번째 feature의 properties)
    duration_sec = features[0].get("properties", {}).get("totalTime", 0)
    duration_min = round(duration_sec / 60)

    # 좌표 추출
    coords = _extract_tmap_coords(features)
    if not coords:
        raise HTTPException(status_code=404, detail="경로 좌표를 찾을 수 없습니다.")

    # 안전점수 계산용: 100m 간격 샘플링
    sampled = _sample_coords(coords)

    segments: List[SegmentScore] = []
    score_sum = 0.0
    for lat, lng in sampled:
        score, grade = _score_for_coord(lat, lng)
        segments.append(SegmentScore(lat=lat, lng=lng, score=score, grade=grade))
        score_sum += score

    avg_score = round(score_sum / len(segments), 1)
    route_grade = _score_to_grade(segments)

    # 지도 표시용: 원본 좌표 전체 사용
    points = [[lat, lng] for lat, lng in coords]

    result = RouteResult(
        type="safe",
        points=points,
        segments=segments,
        avg_score=avg_score,
        grade=route_grade,
        duration=duration_min,
    )

    return RouteResponse(routes=[result])

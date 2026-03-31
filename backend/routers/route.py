import math
import os
from typing import List

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from routers.safety import _load_grid

router = APIRouter()

KAKAO_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"
SAMPLE_INTERVAL_M = 200  # 샘플링 간격 (미터)


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


def _score_to_grade(avg_score: float) -> str:
    """평균 점수를 등급 문자열로 변환합니다."""
    if avg_score >= 80:
        return "안전"
    elif avg_score >= 60:
        return "보통"
    elif avg_score >= 40:
        return "주의"
    else:
        return "위험"


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/safe-route", response_model=RouteResponse)
def get_safe_route(req: RouteRequest):
    """카카오모빌리티 API로 경로를 조회하고 각 경로의 안전점수를 계산합니다."""
    api_key = os.getenv("KAKAO_REST_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="KAKAO_REST_API_KEY 환경변수가 설정되지 않았습니다.")

    params = {
        "origin": f"{req.origin_lng},{req.origin_lat}",
        "destination": f"{req.dest_lng},{req.dest_lat}",
        "alternatives": "true",
    }
    headers = {"Authorization": f"KakaoAK {api_key}"}

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(KAKAO_DIRECTIONS_URL, params=params, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"카카오 API 오류: {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"카카오 API 연결 실패: {str(e)}")

    data = resp.json()
    kakao_routes = data.get("routes", [])
    if not kakao_routes:
        raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.")

    results: List[RouteResult] = []
    for kakao_route in kakao_routes:
        # duration: 초 → 분 변환
        summary = kakao_route.get("summary", {})
        duration_sec = summary.get("duration", 0)
        duration_min = round(duration_sec / 60)

        # 좌표 추출 및 200m 간격 샘플링
        coords = _extract_coords(kakao_route)
        sampled = _sample_coords(coords)

        if not sampled:
            continue

        # 각 샘플 좌표의 안전점수 계산
        segments: List[SegmentScore] = []
        score_sum = 0.0
        for lat, lng in sampled:
            score, grade = _score_for_coord(lat, lng)
            segments.append(SegmentScore(lat=lat, lng=lng, score=score, grade=grade))
            score_sum += score

        avg_score = round(score_sum / len(segments), 1)
        route_grade = _score_to_grade(avg_score)
        points = [[lat, lng] for lat, lng in sampled]

        results.append(RouteResult(
            type="",  # 아래에서 레이블링
            points=points,
            segments=segments,
            avg_score=avg_score,
            grade=route_grade,
            duration=duration_min,
        ))

    if not results:
        raise HTTPException(status_code=404, detail="유효한 경로를 찾을 수 없습니다.")

    # avg_score가 가장 높은 경로 → "safe", 나머지 → "normal"
    best_idx = max(range(len(results)), key=lambda i: results[i].avg_score)
    results = [
        r.model_copy(update={"type": "safe" if i == best_idx else "normal"})
        for i, r in enumerate(results)
    ]

    return RouteResponse(routes=results)

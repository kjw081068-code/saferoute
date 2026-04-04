import math
import os
from typing import List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from routers.safety import _load_grid

router = APIRouter()

TMAP_PEDESTRIAN_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
TMAP_POI_URL = "https://apis.openapi.sk.com/tmap/pois"
SAMPLE_INTERVAL_M = 100       # 안전점수 샘플링 간격 (미터)
SAFE_ROUTE_MAX_DIST_M = 1000  # 안전경로 지원 최대 직선거리 (미터)
WAYPOINT_INTERVAL_M = 200     # 경유지 간격 (미터)
PERP_OFFSET_M = 50            # 수직 이동 거리 (미터)

# 서울 기준 좌표-거리 변환 상수
LAT_PER_M = 1 / 111_000
LNG_PER_M = 1 / 88_000


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


class PoiItem(BaseModel):
    name: str
    address: str
    lat: float
    lng: float


class PoiSearchResponse(BaseModel):
    results: List[PoiItem]


# ── 내부 유틸 함수 ────────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 거리를 미터 단위로 반환합니다."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _straight_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """서울 기준 직선거리를 미터로 계산합니다."""
    dlat = (lat2 - lat1) * 111_000
    dlng = (lng2 - lng1) * 88_000
    return math.sqrt(dlat ** 2 + dlng ** 2)


def _extract_tmap_coords(features: list) -> List[Tuple[float, float]]:
    """TMAP GeoJSON features에서 (lat, lng) 튜플 리스트를 추출합니다."""
    coords = []
    for feature in features:
        geom = feature.get("geometry", {})
        if geom.get("type") == "LineString":
            for lng, lat in geom.get("coordinates", []):
                coords.append((lat, lng))
    return coords


def _sample_coords(
    coords: List[Tuple[float, float]], interval_m: float = SAMPLE_INTERVAL_M
) -> List[Tuple[float, float]]:
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
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    return sampled


def _score_for_coord(lat: float, lng: float) -> Tuple[float, str]:
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


def _segment_midpoint(p1: Tuple[float, float], p2: Tuple[float, float]) -> Tuple[float, float]:
    return ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)


def _segment_angle(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """p1→p2 방향 각도 (라디안)"""
    return math.atan2(p2[1] - p1[1], p2[0] - p1[0])


def _angle_diff(a1: float, a2: float) -> float:
    """두 각도의 차이 (0 ~ π)"""
    diff = abs(a1 - a2) % (2 * math.pi)
    return diff if diff <= math.pi else 2 * math.pi - diff


def _remove_backtrack(
    coords: List[Tuple[float, float]],
    proximity_m: float = 15.0,
    opposite_threshold: float = 2.09,  # 약 120° 이상이면 반대 방향으로 판단
) -> List[Tuple[float, float]]:
    """경로 내 역주행(같은 도로를 반대 방향으로 지나는) 구간을 제거합니다.

    세그먼트 i와 세그먼트 j의 중간점이 proximity_m 이내이고
    진행 방향이 반대(angle_diff > opposite_threshold)인 경우
    i+1 ~ j 구간을 잘라내고 i에서 j+1로 바로 연결합니다.
    """
    if len(coords) < 4:
        return coords

    result = list(coords)
    changed = True
    while changed:
        changed = False
        n = len(result)
        for i in range(n - 2):
            mid_i = _segment_midpoint(result[i], result[i + 1])
            dir_i = _segment_angle(result[i], result[i + 1])
            for j in range(i + 1, n - 1):
                mid_j = _segment_midpoint(result[j], result[j + 1])
                if _haversine_m(mid_i[0], mid_i[1], mid_j[0], mid_j[1]) > proximity_m:
                    continue
                dir_j = _segment_angle(result[j], result[j + 1])
                if _angle_diff(dir_i, dir_j) >= opposite_threshold:
                    # i+1 ~ j 구간(역주행 왕복)을 제거하고 i → j+1 연결
                    result = result[: i + 1] + result[j + 1 :]
                    changed = True
                    break
            if changed:
                break

    return result


def _call_tmap(headers: dict, body: dict) -> Optional[dict]:
    """TMAP 도보 API를 호출하고 응답 JSON을 반환합니다. 실패 시 None 반환."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(TMAP_PEDESTRIAN_URL, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPStatusError, httpx.RequestError):
        return None


def _interpolate_midpoints(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> List[Tuple[float, float]]:
    """출발-도착 직선을 200m 간격으로 선형 보간하여 중간 지점 리스트를 반환합니다.

    출발/도착 지점은 포함되지 않습니다.
    예: 1000m → n_segments=5 → 중간 지점 4개 (t=0.2, 0.4, 0.6, 0.8)
    n_segments가 1 이하이면 빈 리스트 반환.
    """
    total_m = _straight_distance_m(lat1, lng1, lat2, lng2)
    n_segments = int(total_m / WAYPOINT_INTERVAL_M)
    if n_segments <= 1:
        return []
    midpoints = []
    for i in range(1, n_segments):
        t = i / n_segments
        midpoints.append((
            lat1 + t * (lat2 - lat1),
            lng1 + t * (lng2 - lng1),
        ))
    return midpoints


def _perpendicular_candidates(
    mid: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    offset_m: float = PERP_OFFSET_M,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """mid 지점에서 p1→p2 방향의 수직으로 좌/우 offset_m 지점을 반환합니다.

    반환: (좌측 지점, 우측 지점)
    수직 벡터: (-dlng_m, dlat_m) 방향 정규화 후 미터 단위 이동
    """
    dlat_m = (p2[0] - p1[0]) * 111_000
    dlng_m = (p2[1] - p1[1]) * 88_000
    magnitude = math.sqrt(dlat_m ** 2 + dlng_m ** 2)
    if magnitude == 0:
        return mid, mid

    # 수직 단위 벡터 (좌측): (-dlng_m, dlat_m) 방향
    perp_lat_unit = -dlng_m / magnitude
    perp_lng_unit = dlat_m / magnitude

    delta_lat = perp_lat_unit * offset_m * LAT_PER_M
    delta_lng = perp_lng_unit * offset_m * LNG_PER_M

    left = (mid[0] + delta_lat, mid[1] + delta_lng)
    right = (mid[0] - delta_lat, mid[1] - delta_lng)
    return left, right


def _select_safest_waypoints(req: RouteRequest) -> List[Tuple[float, float]]:
    """출발-도착 구간의 200m 간격 경유지를 안전점수 기준으로 선택합니다.

    각 중간 지점에서 원본 / 좌 50m / 우 50m 후보 3개 중
    safety_grid 점수가 가장 높은 지점을 경유지로 확정합니다.
    """
    midpoints = _interpolate_midpoints(
        req.origin_lat, req.origin_lng, req.dest_lat, req.dest_lng
    )
    if not midpoints:
        return []

    all_points = [
        (req.origin_lat, req.origin_lng),
        *midpoints,
        (req.dest_lat, req.dest_lng),
    ]

    selected = []
    for i, mid in enumerate(midpoints):
        prev = all_points[i]     # mid 이전 지점 (all_points 기준 인덱스 i)
        nxt = all_points[i + 2]  # mid 다음 지점 (all_points 기준 인덱스 i+2)
        left, right = _perpendicular_candidates(mid, prev, nxt)

        candidates = [mid, left, right]
        best = max(candidates, key=lambda c: _score_for_coord(c[0], c[1])[0])
        selected.append(best)

    return selected


def _build_route_result(
    route_type: str,
    coords: List[Tuple[float, float]],
    total_duration_sec: int,
) -> RouteResult:
    """좌표 리스트와 소요시간으로 RouteResult를 생성합니다."""
    sampled = _sample_coords(coords)
    segments: List[SegmentScore] = []
    score_sum = 0.0
    for lat, lng in sampled:
        score, grade = _score_for_coord(lat, lng)
        segments.append(SegmentScore(lat=lat, lng=lng, score=score, grade=grade))
        score_sum += score

    avg_score = round(score_sum / len(segments), 1) if segments else 0.0
    route_grade = _score_to_grade(segments)
    points = [[lat, lng] for lat, lng in coords]

    return RouteResult(
        type=route_type,
        points=points,
        segments=segments,
        avg_score=avg_score,
        grade=route_grade,
        duration=round(total_duration_sec / 60),
    )


def _build_safe_route(req: RouteRequest, headers: dict) -> Optional[RouteResult]:
    """안전 경유지를 통해 구간별 TMAP을 호출하고 경로를 이어붙여 반환합니다.

    200m 구간마다 별도 TMAP 호출 후 좌표를 연결합니다.
    어떤 구간이라도 TMAP 호출 실패 시 None 반환.
    """
    waypoints = _select_safest_waypoints(req)
    all_stops = [
        (req.origin_lat, req.origin_lng),
        *waypoints,
        (req.dest_lat, req.dest_lng),
    ]

    all_coords: List[Tuple[float, float]] = []
    total_duration_sec = 0

    for i in range(len(all_stops) - 1):
        start = all_stops[i]
        end = all_stops[i + 1]

        body = {
            "startX": str(start[1]),
            "startY": str(start[0]),
            "endX": str(end[1]),
            "endY": str(end[0]),
            "reqCoordType": "WGS84GEO",
            "resCoordType": "WGS84GEO",
            "startName": "경유출발",
            "endName": "경유도착",
        }

        data = _call_tmap(headers, body)
        if data is None:
            return None  # 구간 호출 실패 → 상위에서 폴백 처리

        features = data.get("features", [])
        if not features:
            return None

        total_duration_sec += features[0].get("properties", {}).get("totalTime", 0)
        seg_coords = _extract_tmap_coords(features)

        if all_coords and seg_coords:
            seg_coords = seg_coords[1:]  # 이전 구간 끝점 중복 제거
        all_coords.extend(seg_coords)

    if not all_coords:
        return None

    all_coords = _remove_backtrack(all_coords)
    return _build_route_result("safe", all_coords, total_duration_sec)


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/safe-route", response_model=RouteResponse)
def get_safe_route(req: RouteRequest):
    """TMAP 도보 경로 API로 경로를 조회하고 각 경로의 안전점수를 계산합니다."""
    tmap_key = (os.getenv("TMAP_APP_KEY") or "").strip()
    if not tmap_key:
        raise HTTPException(status_code=500, detail="TMAP_APP_KEY 환경변수가 설정되지 않았습니다.")

    headers = {
        "appKey": tmap_key,
        "Content-Type": "application/json",
    }

    # ── 일반 경로 호출 ──────────────────────────────────────────────────────
    normal_body = {
        "startX": str(req.origin_lng),
        "startY": str(req.origin_lat),
        "endX": str(req.dest_lng),
        "endY": str(req.dest_lat),
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "startName": "출발지",
        "endName": "도착지",
    }

    normal_data = _call_tmap(headers, normal_body)
    if normal_data is None:
        raise HTTPException(status_code=502, detail="TMAP API 호출에 실패했습니다.")

    features = normal_data.get("features", [])
    if not features:
        raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.")

    normal_duration_sec = features[0].get("properties", {}).get("totalTime", 0)
    normal_coords = _extract_tmap_coords(features)
    if not normal_coords:
        raise HTTPException(status_code=404, detail="경로 좌표를 찾을 수 없습니다.")

    normal_result = _build_route_result("normal", normal_coords, normal_duration_sec)

    # ── 직선거리 1km 초과 시 일반 경로만 반환 ──────────────────────────────
    straight_dist = _straight_distance_m(
        req.origin_lat, req.origin_lng, req.dest_lat, req.dest_lng
    )
    if straight_dist > SAFE_ROUTE_MAX_DIST_M:
        return RouteResponse(routes=[normal_result])

    # ── 안전 경로 생성 ──────────────────────────────────────────────────────
    safe_result = _build_safe_route(req, headers)

    # 경유지 포함 TMAP 호출 실패 시 일반 경로 좌표로 safe 경로 대체
    if safe_result is None:
        safe_result = _build_route_result("safe", normal_coords, normal_duration_sec)

    return RouteResponse(routes=[safe_result, normal_result])


@router.get("/search-poi", response_model=PoiSearchResponse)
def search_poi(
    q: str = Query(..., description="검색어"),
    count: int = Query(default=5),
    center_lat: Optional[float] = Query(default=None, description="지도 중심 위도"),
    center_lng: Optional[float] = Query(default=None, description="지도 중심 경도"),
):
    """장소명·주소·건물명으로 TMAP POI를 검색하고 후보 목록을 반환합니다."""
    tmap_key = (os.getenv("TMAP_APP_KEY") or "").strip()
    if not tmap_key:
        raise HTTPException(status_code=500, detail="TMAP_APP_KEY 환경변수가 설정되지 않았습니다.")
    params: dict = {
        "version": "1",
        "searchKeyword": q,
        "count": count,
        "appKey": tmap_key,
    }
    if center_lat is not None and center_lng is not None:
        params["centerLat"] = str(center_lat)
        params["centerLon"] = str(center_lng)
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(TMAP_POI_URL, params=params)
        resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError):
        raise HTTPException(status_code=502, detail="TMAP POI 검색 API 호출에 실패했습니다.")

    pois = resp.json().get("searchPoiInfo", {}).get("pois", {}).get("poi", [])
    results = []
    for poi in pois:
        addr_list = poi.get("newAddressList", {}).get("newAddress", [])
        addr = addr_list[0].get("fullAddressRoad", "") if addr_list else ""
        try:
            lat = float(poi.get("frontLat", 0))
            lng = float(poi.get("frontLon", 0))
        except (ValueError, TypeError):
            continue
        results.append(PoiItem(name=poi.get("name", ""), address=addr, lat=lat, lng=lng))
    return PoiSearchResponse(results=results)

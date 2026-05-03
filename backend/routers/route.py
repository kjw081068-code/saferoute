import math
import os
from typing import List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from routers.safety import (
    _cctv_score_for_coord, _safelight_score_for_coord,
    _streetlight_score_for_coord,
    _combined_conv_open24_score_for_coord,
    _police_score_for_coord, _entertainment_score_for_coord,
    score_to_grade_realtime,
)

router = APIRouter()

TMAP_PEDESTRIAN_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
TMAP_POI_URL = "https://apis.openapi.sk.com/tmap/pois"
SAMPLE_INTERVAL_M = 100       # 안전점수 샘플링 간격 (미터)

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
    """모든 요소를 실시간 반경으로 직접 계산해 안전점수를 반환합니다."""
    score = (
        _cctv_score_for_coord(lat, lng)
        + _streetlight_score_for_coord(lat, lng)
        + _safelight_score_for_coord(lat, lng, radius_m=5.0)
        + _combined_conv_open24_score_for_coord(lat, lng)
        + _police_score_for_coord(lat, lng)
        - _entertainment_score_for_coord(lat, lng)
    )
    return score, score_to_grade_realtime(score)


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



def _remove_backtrack(
    coords: List[Tuple[float, float]],
    proximity_m: float = 20.0,
) -> List[Tuple[float, float]]:
    """경로에서 같은 위치를 두 번 지나는 루프 구간을 제거합니다.

    점 i와 점 j(j >= i+2)의 거리가 proximity_m 이내이면
    i+1 ~ j-1 루프를 제거하고 i에서 j로 직접 연결합니다.
    """
    if len(coords) < 3:
        return coords

    result = list(coords)
    changed = True
    while changed:
        changed = False
        n = len(result)
        for i in range(n - 2):
            for j in range(i + 2, n):
                if _haversine_m(result[i][0], result[i][1], result[j][0], result[j][1]) <= proximity_m:
                    result = result[: i + 1] + result[j:]
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


def _find_poi_near(lat: float, lng: float, radius_m: float, tmap_key: str) -> Optional[Tuple[float, float]]:
    """좌표 반경 내 실제 도로 위 POI를 찾아 반환합니다. 없으면 None."""
    for keyword in ["편의점", "지하철역", "버스정류장"]:
        params = {
            "version": "1",
            "searchKeyword": keyword,
            "count": 3,
            "appKey": tmap_key,
            "centerLat": str(lat),
            "centerLon": str(lng),
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(TMAP_POI_URL, params=params)
            resp.raise_for_status()
            pois = resp.json().get("searchPoiInfo", {}).get("pois", {}).get("poi", [])
            for poi in pois:
                try:
                    poi_lat = float(poi.get("frontLat", 0))
                    poi_lng = float(poi.get("frontLon", 0))
                except (ValueError, TypeError):
                    continue
                if poi_lat == 0 or poi_lng == 0:
                    continue
                if _haversine_m(lat, lng, poi_lat, poi_lng) <= radius_m:
                    return (poi_lat, poi_lng)
        except (httpx.HTTPStatusError, httpx.RequestError):
            continue
    return None




def _perpendicular_candidates(
    mid: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    offset_m: float = 100,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """p1→p2 진행방향 기준 mid에서 수직 좌/우 offset_m 지점을 반환합니다."""
    dlat_m = (p2[0] - p1[0]) * 111_000
    dlng_m = (p2[1] - p1[1]) * 88_000
    magnitude = math.sqrt(dlat_m ** 2 + dlng_m ** 2)
    if magnitude == 0:
        return mid, mid
    perp_lat = -dlng_m / magnitude * offset_m * LAT_PER_M
    perp_lng =  dlat_m / magnitude * offset_m * LNG_PER_M
    return (mid[0] + perp_lat, mid[1] + perp_lng), (mid[0] - perp_lat, mid[1] - perp_lng)


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


def _best_ray_waypoint(
    mid: Tuple[float, float],
    prev_pt: Tuple[float, float],
    next_pt: Tuple[float, float],
    ray_length_m: float,
    dest: Tuple[float, float],
    sample_interval_m: float = 30.0,
) -> Optional[Tuple[float, float]]:
    """전방 180° 7개 방향으로 선 스캔, 피크가 안전 등급인 후보 중
    목적지에 가장 가까운 지점을 반환합니다. 없으면 None."""
    dlat_m = (next_pt[0] - prev_pt[0]) * 111_000
    dlng_m = (next_pt[1] - prev_pt[1]) * 88_000
    mag = math.sqrt(dlat_m ** 2 + dlng_m ** 2)
    if mag == 0:
        return None

    # 진행방향 / 수직(왼쪽) 단위벡터
    f_lat, f_lng = dlat_m / mag, dlng_m / mag
    p_lat, p_lng = -f_lng, f_lat

    angles = [math.radians(a) for a in [-90, -60, -30, 0, 30, 60, 90]]
    num_samples = max(1, int(ray_length_m / sample_interval_m))
    candidates: List[Tuple[float, float, float]] = []  # (dist_to_dest, lat, lng)

    for theta in angles:
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        dir_lat = cos_t * f_lat + sin_t * p_lat
        dir_lng = cos_t * f_lng + sin_t * p_lng

        pts = [
            (mid[0] + dir_lat * (k * sample_interval_m) * LAT_PER_M,
             mid[1] + dir_lng * (k * sample_interval_m) * LNG_PER_M)
            for k in range(1, num_samples + 1)
        ]
        scores = [_score_for_coord(pt[0], pt[1])[0] for pt in pts]

        # 증가→감소 전환점(피크) 탐색
        peak_idx = len(scores) - 1
        for j in range(len(scores) - 1):
            if scores[j] >= scores[j + 1]:
                peak_idx = j
                break

        if score_to_grade_realtime(scores[peak_idx]) == "안전":
            dist = _straight_distance_m(pts[peak_idx][0], pts[peak_idx][1], dest[0], dest[1])
            candidates.append((dist, pts[peak_idx][0], pts[peak_idx][1]))

    if not candidates:
        return None

    # 목적지에 가장 가까운 후보 선택
    candidates.sort(key=lambda c: c[0])
    return (candidates[0][1], candidates[0][2])


def _tmap_body(start: Tuple[float, float], end: Tuple[float, float]) -> dict:
    return {
        "startX": str(start[1]), "startY": str(start[0]),
        "endX": str(end[1]), "endY": str(end[0]),
        "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
        "startName": "출발", "endName": "도착",
    }


def _build_safe_route(
    req: RouteRequest,
    headers: dict,
    normal_coords: List[Tuple[float, float]],
    normal_duration_sec: int,
) -> Optional[RouteResult]:
    """반복형 안전경로 탐색.

    위험 구간 발견 시 전방 180° 레이더로 경유지 탐색 후 재라우팅.
    경유지 도착 후 목적지까지 TMAP 재호출 반복 (최대 8회).
    """
    dest = (req.dest_lat, req.dest_lng)
    all_coords: List[Tuple[float, float]] = []
    current_coords = normal_coords

    for _ in range(8):
        sampled = _sample_coords(current_coords, interval_m=50)
        if len(sampled) < 2:
            all_coords.extend(current_coords[1:] if all_coords else current_coords)
            break

        scores_grades = [_score_for_coord(lat, lng) for lat, lng in sampled]

        # 첫 보통/위험 인덱스 탐색
        first_danger_idx = next(
            (i for i, (_, g) in enumerate(scores_grades) if g != "안전"), None
        )

        if first_danger_idx is None:
            all_coords.extend(current_coords[1:] if all_coords else current_coords)
            break

        # 안전 구간 → 위험 직전까지 current_coords 저장
        if first_danger_idx > 0:
            safe_end_pt = sampled[first_danger_idx - 1]
            safe_nc_idx = min(
                range(len(current_coords)),
                key=lambda k: (current_coords[k][0] - safe_end_pt[0]) ** 2
                              + (current_coords[k][1] - safe_end_pt[1]) ** 2,
            )
            slice_start = 1 if all_coords else 0
            all_coords.extend(current_coords[slice_start:safe_nc_idx + 1])
            from_pt = safe_end_pt
        else:
            from_pt = current_coords[0]

        # 연속 위험 구간 길이
        consecutive = sum(
            1 for i in range(first_danger_idx, len(sampled))
            if scores_grades[i][1] != "안전"
        )
        ray_length = max(200.0, consecutive * 50.0)

        danger_pt = sampled[first_danger_idx]
        prev_pt = sampled[first_danger_idx - 1] if first_danger_idx > 0 else from_pt
        next_pt = sampled[min(first_danger_idx + 1, len(sampled) - 1)]
        waypoint = _best_ray_waypoint(
            danger_pt, prev_pt, next_pt, ray_length, dest
        )

        if waypoint is None:
            # 개선 불가 → 나머지 그대로 추가 후 종료
            if first_danger_idx > 0:
                all_coords.extend(current_coords[safe_nc_idx + 1:])
            else:
                all_coords.extend(current_coords[1:] if all_coords else current_coords)
            break

        # from_pt → waypoint TMAP 경로 추가
        wp_data = _call_tmap(headers, _tmap_body(from_pt, waypoint))
        if wp_data:
            wp_coords = _extract_tmap_coords(wp_data.get("features", []))
            if wp_coords:
                all_coords.extend(wp_coords[1:] if all_coords else wp_coords)

        # waypoint → 목적지 새 경로로 다음 반복
        next_data = _call_tmap(headers, _tmap_body(waypoint, dest))
        if next_data is None:
            break
        next_coords = _extract_tmap_coords(next_data.get("features", []))
        if not next_coords:
            break
        current_coords = next_coords

    if not all_coords:
        return None

    all_coords = _remove_backtrack(all_coords)

    return _build_route_result("safe", all_coords, normal_duration_sec)


def _fetch_direct_pedestrian(
    req: RouteRequest, headers: dict
) -> Tuple[List[Tuple[float, float]], int]:
    """출발→도착 직접 도보 경로 1회 TMAP 호출."""
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
    normal_data = _call_tmap(headers, body)
    if normal_data is None:
        raise HTTPException(status_code=502, detail="TMAP API 호출에 실패했습니다.")
    features = normal_data.get("features", [])
    if not features:
        raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.")
    duration_sec = features[0].get("properties", {}).get("totalTime", 0)
    coords = _extract_tmap_coords(features)
    if not coords:
        raise HTTPException(status_code=404, detail="경로 좌표를 찾을 수 없습니다.")
    return coords, duration_sec


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

    # ── 항상 일반 + 안전 둘 다 반환 ──
    normal_coords, normal_duration_sec = _fetch_direct_pedestrian(req, headers)
    normal_result = _build_route_result("normal", normal_coords, normal_duration_sec)

    safe_result = _build_safe_route(req, headers, normal_coords, normal_duration_sec)
    if (
        safe_result is None
        or safe_result.avg_score < normal_result.avg_score  # 점수가 낮을 때만 fallback (같으면 허용)
        or safe_result.duration > normal_result.duration * 1.3
    ):
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

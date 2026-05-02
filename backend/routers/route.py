import math
import os
from typing import List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from routers.safety import _load_grid, _cctv_score_for_coord, _safelight_score_for_coord, score_to_grade_realtime

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
    """격자 기반 점수에서 CCTV·보안등 기여분을 실시간 원형 조회로 교체하여 반환합니다."""
    df = _load_grid()
    idx = ((df["lat"] - lat) ** 2 + (df["lng"] - lng) ** 2).idxmin()
    row = df.loc[idx]

    grid_score = float(row["score"])
    # 격자에 이미 포함된 CCTV 100m 기여분 제거 (공식: min(qty, 4) * 5)
    old_cctv = min(int(row.get("cctv_count", 0)), 4) * 5
    # 격자에 이미 포함된 보안등 80m 기여분 제거 (공식: min(count, 3) * 3)
    old_safelight = min(int(row.get("safelight_count", 0)), 3) * 3
    # 이중 반경 실시간 CCTV 점수 (15m 전체 + 15~30m 절반)
    new_cctv = _cctv_score_for_coord(lat, lng)
    # 5m 반경 실시간 보안등 점수
    new_safelight = _safelight_score_for_coord(lat, lng, radius_m=5.0)

    adjusted = min(max(grid_score - old_cctv - old_safelight + new_cctv + new_safelight, 10.0), 100.0)
    grade = score_to_grade_realtime(adjusted)
    return adjusted, grade


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


def _build_safe_route(
    req: RouteRequest,
    headers: dict,
    normal_coords: List[Tuple[float, float]],
    normal_duration_sec: int,
) -> Optional[RouteResult]:
    """일반경로를 100m마다 점수 확인하며 보통/위험 격자에서 좌우 우회를 시도합니다.

    각 100m 샘플 지점마다:
    - 안전 → 일반경로 그대로 통과
    - 보통/위험 → 진행방향 수직 좌/우 100m 중 더 안전한 점 W 탐색
      - W가 현재보다 점수 높으면 → 이전 점 → W → 다음 점 으로 TMAP 재호출해 교체
      - W가 없거나 더 낮으면 → 그냥 통과
    경유지는 개선이 있을 때만 추가되므로 불필요한 우회 최소화.
    """
    sampled = _sample_coords(normal_coords, interval_m=100)
    if len(sampled) < 2:
        return None

    scores_grades = [_score_for_coord(lat, lng) for lat, lng in sampled]

    # normal_coords에서 target과 가장 가까운 인덱스 찾기 (from_idx 이후)
    def find_nc_idx(target: Tuple[float, float], from_idx: int = 0) -> int:
        best, best_d = from_idx, float("inf")
        for i in range(from_idx, len(normal_coords)):
            d = (normal_coords[i][0] - target[0]) ** 2 + (normal_coords[i][1] - target[1]) ** 2
            if d < best_d:
                best_d, best = d, i
        return best

    final_coords: List[Tuple[float, float]] = []
    nc_pos = 0
    any_replaced = False

    for i in range(1, len(sampled) - 1):
        lat, lng = sampled[i]
        score, grade = scores_grades[i]

        # 현재 샘플 지점의 normal_coords 인덱스
        curr_nc = find_nc_idx(sampled[i], nc_pos)

        if grade == "안전":
            # 안전 → 현재 지점까지 일반경로 그대로
            final_coords.extend(normal_coords[nc_pos: curr_nc + 1])
            nc_pos = curr_nc + 1
            continue

        # 보통/위험 → 진행방향 수직 좌/우 100m 탐색
        prev_pt = sampled[i - 1]
        next_pt = sampled[i + 1]
        left, right = _perpendicular_candidates((lat, lng), prev_pt, next_pt, offset_m=100)
        best_w = max([left, right], key=lambda c: _score_for_coord(c[0], c[1])[0])
        best_w_score = _score_for_coord(best_w[0], best_w[1])[0]

        if best_w_score <= score:
            # 주변도 더 나은 곳 없음 → 그냥 통과
            final_coords.extend(normal_coords[nc_pos: curr_nc + 1])
            nc_pos = curr_nc + 1
            continue

        # W가 더 안전 → 이전 점(prev) → W → 현재 점(curr) TMAP 재호출
        prev_nc = find_nc_idx(prev_pt, max(0, nc_pos - 1))

        def _seg_body(start: Tuple[float, float], end: Tuple[float, float]) -> dict:
            return {
                "startX": str(start[1]), "startY": str(start[0]),
                "endX": str(end[1]), "endY": str(end[0]),
                "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
                "startName": "경유출발", "endName": "경유도착",
            }

        d1 = _call_tmap(headers, _seg_body(prev_pt, best_w))
        d2 = _call_tmap(headers, _seg_body(best_w, (lat, lng)))

        if d1 and d2:
            f1, f2 = d1.get("features", []), d2.get("features", [])
            c1 = _extract_tmap_coords(f1)
            c2 = _extract_tmap_coords(f2)
            if c1 and c2:
                alt = c1 + c2[1:]
                alt_sampled = _sample_coords(alt, interval_m=100)
                if alt_sampled:
                    alt_avg = sum(_score_for_coord(lt, lg)[0] for lt, lg in alt_sampled) / len(alt_sampled)
                    if alt_avg > score:
                        # prev까지 일반경로 + 대체 구간 추가
                        final_coords.extend(normal_coords[nc_pos: prev_nc])
                        final_coords.extend(alt)
                        nc_pos = curr_nc + 1
                        any_replaced = True
                        continue

        # TMAP 실패 또는 개선 없음 → 그냥 통과
        final_coords.extend(normal_coords[nc_pos: curr_nc + 1])
        nc_pos = curr_nc + 1

    # 남은 경로 추가
    final_coords.extend(normal_coords[nc_pos:])

    if not final_coords:
        return None

    if any_replaced:
        final_coords = _remove_backtrack(final_coords)

    return _build_route_result("safe", final_coords, normal_duration_sec)


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

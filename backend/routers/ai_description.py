import os
import re
import json
from typing import List

from google import genai
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import routers.safety as _safety

router = APIRouter()


# ── 요청/응답 모델 ────────────────────────────────────────────────────────────

class SegmentInput(BaseModel):
    lat: float
    lng: float
    score: float
    grade: str


class RouteDescriptionRequest(BaseModel):
    segments: List[SegmentInput]
    avg_score: float
    grade: str


class RouteDescriptionResponse(BaseModel):
    safe_points: List[str]
    warning_points: List[str]
    ai_summary: str


# ── 실시간 반경 방식으로 구간별 상세 데이터 조회 ─────────────────────────────

def _get_segment_detail(lat: float, lng: float, score: float, grade: str) -> dict:
    """실시간 반경 쿼리로 좌표의 안전 요소 개수를 반환합니다."""
    _safety._load_cctv()
    _safety._load_streetlight()
    _safety._load_safelight()
    _safety._load_convenience()
    _safety._load_open24()
    _safety._load_entertainment()
    _safety._load_police()
    _safety._load_firestation()

    x, y = lng * _safety._LNG_M, lat * _safety._LAT_M

    cctv_count = 0
    if _safety._cctv_tree is not None and len(_safety._cctv_qty) > 0:
        idxs = _safety._cctv_tree.query_ball_point([x, y], r=30.0)
        cctv_count = round(float(_safety._cctv_qty[list(idxs)].sum())) if idxs else 0

    street_count = 0
    if _safety._streetlight_tree is not None:
        street_count = len(_safety._streetlight_tree.query_ball_point([x, y], r=30.0))

    safe_count = 0
    if _safety._safelight_tree is not None:
        safe_count = len(_safety._safelight_tree.query_ball_point([x, y], r=10.0))

    conv_count = 0
    if _safety._convenience_tree is not None:
        conv_count = len(_safety._convenience_tree.query_ball_point([x, y], r=_safety._STORE_RADIUS_M))

    open24_count = 0
    if _safety._open24_tree is not None:
        open24_count = len(_safety._open24_tree.query_ball_point([x, y], r=_safety._STORE_RADIUS_M))

    ent_count = 0
    if _safety._entertainment_tree is not None:
        ent_count = len(_safety._entertainment_tree.query_ball_point([x, y], r=50.0))

    police_count = 0
    if _safety._police_tree is not None:
        police_count = len(_safety._police_tree.query_ball_point([x, y], r=200.0))

    firestation_count = 0
    if _safety._firestation_tree is not None:
        firestation_count = len(_safety._firestation_tree.query_ball_point([x, y], r=300.0))

    return {
        "lat": lat,
        "lng": lng,
        "score": score,
        "grade": grade,
        "cctv_count": cctv_count,
        "street_count": street_count,
        "safe_count": safe_count,
        "conv_count": conv_count,
        "open24_count": open24_count,
        "ent_count": ent_count,
        "police_count": police_count,
        "firestation_count": firestation_count,
    }


# ── Gemini 프롬프트 구성 ──────────────────────────────────────────────────────

def _build_prompt(details: List[dict], avg_score: float, grade: str) -> str:
    """경로 상세 데이터를 바탕으로 Gemini 프롬프트를 구성합니다."""
    total = len(details)
    danger_segments = [d for d in details if d["grade"] == "위험"]
    normal_segments = [d for d in details if d["grade"] == "보통"]

    total_cctv = sum(d["cctv_count"] for d in details)
    total_street = sum(d["street_count"] for d in details)
    total_safe = sum(d["safe_count"] for d in details)
    total_conv = sum(d["conv_count"] for d in details)
    total_open24 = sum(d["open24_count"] for d in details)
    total_ent = sum(d["ent_count"] for d in details)
    total_police = sum(d["police_count"] for d in details)
    total_firestation = sum(d["firestation_count"] for d in details)

    avg_cctv = round(total_cctv / total, 1) if total else 0
    avg_street = round(total_street / total, 1) if total else 0
    avg_safe = round(total_safe / total, 1) if total else 0

    danger_info = ""
    if danger_segments:
        d_cctv = round(sum(d["cctv_count"] for d in danger_segments) / len(danger_segments), 1)
        d_street = round(sum(d["street_count"] for d in danger_segments) / len(danger_segments), 1)
        d_ent = round(sum(d["ent_count"] for d in danger_segments) / len(danger_segments), 1)
        danger_info = (
            f"- 위험 구간 수: {len(danger_segments)}개 (전체 {total}개 중)\n"
            f"- 위험 구간 평균 CCTV: {d_cctv}개, 가로등: {d_street}개, 유흥시설: {d_ent}개\n"
        )

    safe_segments = [d for d in details if d["grade"] == "안전"]

    prompt = f"""당신은 보행자 안전 분석 전문가입니다.
아래 경로 데이터를 분석하여, 반드시 아래 JSON 형식으로만 응답하세요.
마크다운, 코드블록, 부연 설명, 다른 텍스트는 절대 포함하지 마세요.

[경로 데이터]
- 전체 구간: {total}개 / 안전 {len(safe_segments)}개 / 보통 {len(normal_segments)}개 / 위험 {len(danger_segments)}개
- 평균 안전점수: {avg_score}점 ({grade} 등급)
- CCTV 평균: 50m당 {avg_cctv}개
- 가로등 평균: 50m당 {avg_street}개 / 보안등 평균: 50m당 {avg_safe}개
- 편의점: {total_conv}개 / 24시간 점포: {total_open24}개
- 경찰서·지구대: {total_police}개 / 소방서: {total_firestation}개
- 유흥시설: {total_ent}개
{danger_info}
[언급 우선순위 — 1개당 안전점수 기여 높은 순]
1순위: 경찰서·지구대 (1개당 14점)
2순위: 소방서 (1개당 10.5점) — 이 앱에서 소방서의 역할은 오직 "야간 대피처·신고처"임. 소방서를 언급할 때는 반드시 "야간 대피처 또는 신고처로 활용 가능" 문구만 사용할 것
3순위: 편의점·24시간 점포 (1개당 7.5점)
4순위: CCTV 근거리 (1개당 12점)
5순위: CCTV 원거리 (1개당 6점)
6순위: 가로등 (1개당 5.5점)
7순위: 보안등 (1개당 4점)
감점: 유흥시설 (1개당 -7.5점)

[작성 규칙]
- safe_points·warning_points는 위 우선순위 순서대로 언급할 것 (높은 가중치 요소부터)
- 반드시 실제 수치(CCTV 몇 개, 가로등 몇 개 등)를 인용해서 이유를 설명할 것
- 밀도 표현 시 "구간당" 표현 금지 — 반드시 "50m당" 또는 "50m 내" 등 거리 단위로 표현할 것
- 조명 언급 시 가로등(avg_street)과 보안등(avg_safe) 중 수치가 더 많은 쪽을 위주로 언급할 것
- 조명 부족을 warning_points에 쓸 때는 가로등·보안등 둘 다 부족한 경우에만 언급할 것
- safe_points와 warning_points는 뚜렷한 장·단점이 있을 때만 작성하고, 없으면 빈 배열 []로 둘 것
- safe_points와 warning_points는 각각 최대 3개까지 작성할 수 있음
- 경찰서·지구대가 1개 이상 있으면 반드시 safe_points에 포함할 것
- 소방서가 1개 이상 있으면 반드시 safe_points에 포함할 것 — 예시 문구: "소방서가 인근에 위치해 야간 대피처·신고처로 활용할 수 있습니다"
- 소방서가 0개면 warning_points에 포함할 것 — 단, 경찰서·지구대가 1개 이상 있으면 신고처 역할이 이미 커버되므로 소방서 부재는 언급하지 말 것
- 소방서 관련 문장에서 위 예시 문구 형태를 유지하고 절대 다른 역할(소화, 구조, 재난 등)을 추가하지 말 것
- 유흥시설이 많으면 야간 주취자 위험도 warning_points에 언급할 것
- ai_summary 규칙:
  1. safe_points·warning_points에서 이미 언급한 내용은 절대 반복하지 말 것
  2. 점수·등급·구간 수·각종 시설 수 등 수치는 일절 포함하지 말 것 (UI에서 별도 표시됨)
  3. 이 경로를 실제로 걷는 보행자에게 필요한 핵심 행동 조언만 작성할 것
  4. 2문장 이내, 절대 초과 금지

[응답 JSON 형식 - 이 JSON만 출력, 다른 텍스트 절대 금지]
{{
  "safe_points": ["장점 문장 (최대 3개, 없으면 빈 배열)"],
  "warning_points": ["위험/단점 문장 (최대 3개, 없으면 빈 배열)"],
  "ai_summary": "핵심 행동 조언 (2문장 이내, 수치 포함 금지)"
}}"""

    return prompt


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/route-description", response_model=RouteDescriptionResponse)
def get_route_description(req: RouteDescriptionRequest):
    """경로 구간 데이터를 분석해 Gemini AI가 생성한 안전 안내 메시지를 반환합니다."""
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")

    if not req.segments:
        raise HTTPException(status_code=400, detail="segments가 비어 있습니다.")

    # 실시간 반경 방식으로 각 구간의 상세 데이터 조회
    details = [_get_segment_detail(seg.lat, seg.lng, seg.score, seg.grade) for seg in req.segments]

    # Gemini API 호출
    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(details, req.avg_score, req.grade)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        # 코드블록(```json ... ```) 제거
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip().rstrip("`").strip()
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"AI 응답 파싱 실패: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini API 호출 실패: {str(e)}")

    return RouteDescriptionResponse(
        safe_points=parsed.get("safe_points", []),
        warning_points=parsed.get("warning_points", []),
        ai_summary=parsed.get("ai_summary", ""),
    )

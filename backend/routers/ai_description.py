import os
from typing import List

from google import genai
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from routers.safety import _load_grid

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
    description: str


# ── safety_grid에서 구간별 상세 데이터 조회 ──────────────────────────────────

def _get_segment_detail(lat: float, lng: float) -> dict:
    """safety_grid에서 lat/lng에 가장 가까운 격자의 상세 데이터를 반환합니다."""
    df = _load_grid()
    idx = ((df["lat"] - lat) ** 2 + (df["lng"] - lng) ** 2).idxmin()
    row = df.loc[idx]
    return {
        "lat": lat,
        "lng": lng,
        "score": float(row["score"]),
        "grade": str(row["grade"]),
        "cctv_count": int(row["cctv_count"]),
        "light_count": int(row["light_count"]),
        "conv_count": int(row["conv_count"]),
        "ent_count": int(row["ent_count"]),
    }


# ── Gemini 프롬프트 구성 ──────────────────────────────────────────────────────

def _build_prompt(details: List[dict], avg_score: float, grade: str) -> str:
    """경로 상세 데이터를 바탕으로 Gemini 프롬프트를 구성합니다."""
    total = len(details)
    danger_segments = [d for d in details if d["grade"] == "위험"]
    normal_segments = [d for d in details if d["grade"] == "보통"]

    total_cctv = sum(d["cctv_count"] for d in details)
    total_light = sum(d["light_count"] for d in details)
    total_conv = sum(d["conv_count"] for d in details)
    total_ent = sum(d["ent_count"] for d in details)

    avg_cctv = round(total_cctv / total, 1) if total else 0
    avg_light = round(total_light / total, 1) if total else 0

    danger_info = ""
    if danger_segments:
        d_cctv = round(sum(d["cctv_count"] for d in danger_segments) / len(danger_segments), 1)
        d_light = round(sum(d["light_count"] for d in danger_segments) / len(danger_segments), 1)
        danger_info = (
            f"- 위험 구간 수: {len(danger_segments)}개 (전체 {total}개 중)\n"
            f"- 위험 구간 평균 CCTV 수: {d_cctv}개\n"
            f"- 위험 구간 평균 가로등 수: {d_light}개\n"
        )

    safe_segments = [d for d in details if d["grade"] == "안전"]

    prompt = f"""당신은 보행자 안전 분석 전문가입니다.
아래는 신림동 귀갓길 경로의 실제 측정 데이터입니다. 이 수치를 근거로 경로가 왜 안전하거나 위험한지 구체적으로 설명하세요.

[경로 데이터]
- 전체 구간: {total}개 / 안전 {len(safe_segments)}개 / 보통 {len(normal_segments)}개 / 위험 {len(danger_segments)}개
- 평균 안전점수: {avg_score}점 ({grade} 등급)
- 경로 전체 CCTV 평균: 구간당 {avg_cctv}개
- 경로 전체 가로등 평균: 구간당 {avg_light}개
- 경로 내 편의점: {total_conv}개, 유흥시설: {total_ent}개
{danger_info}
[작성 규칙]
- 반드시 실제 수치(CCTV 몇 개, 가로등 몇 개 등)를 인용해서 이유를 설명할 것
- 안전하면 왜 안전한지, 위험하면 왜 위험한지 구체적 근거를 제시할 것
- 유흥시설이 많으면 야간 주취자 위험도 언급할 것
- 2~3문장, 마크다운 없이 순수 텍스트로만 작성할 것
- 보행자에게 실질적으로 도움이 되는 행동 조언으로 마무리할 것"""

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

    # safety_grid에서 각 구간의 상세 데이터 조회
    details = [_get_segment_detail(seg.lat, seg.lng) for seg in req.segments]

    # Gemini API 호출
    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(details, req.avg_score, req.grade)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        description = response.text.strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini API 호출 실패: {str(e)}")

    return RouteDescriptionResponse(description=description)

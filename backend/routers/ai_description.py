import os
import re
import json
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
    safe_points: List[str]
    warning_points: List[str]
    ai_summary: str


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
아래 경로 데이터를 분석하여, 반드시 아래 JSON 형식으로만 응답하세요.
마크다운, 코드블록, 부연 설명, 다른 텍스트는 절대 포함하지 마세요.

[경로 데이터]
- 전체 구간: {total}개 / 안전 {len(safe_segments)}개 / 보통 {len(normal_segments)}개 / 위험 {len(danger_segments)}개
- 평균 안전점수: {avg_score}점 ({grade} 등급)
- 경로 전체 CCTV 평균: 구간당 {avg_cctv}개
- 경로 전체 가로등 평균: 구간당 {avg_light}개
- 경로 내 편의점: {total_conv}개, 유흥시설: {total_ent}개
{danger_info}
[작성 규칙]
- safe_points·warning_points: 반드시 실제 수치(CCTV 몇 개, 가로등 몇 개 등)를 인용해서 이유를 설명할 것
- safe_points와 warning_points는 뚜렷한 장·단점이 있을 때만 작성하고, 없으면 빈 배열 []로 둘 것
- safe_points와 warning_points는 각각 최대 2개까지만 작성할 것
- 유흥시설이 많으면 야간 주취자 위험도 언급할 것
- ai_summary 규칙:
  1. safe_points·warning_points에서 이미 언급한 내용은 절대 반복하지 말 것
  2. 점수·등급·구간 수·CCTV 수·가로등 수·편의점 수 등 수치는 일절 포함하지 말 것 (UI에서 별도 표시됨)
  3. 이 경로를 실제로 걷는 보행자에게 필요한 핵심 행동 조언만 작성할 것
  4. 2문장 이내, 절대 초과 금지

[응답 JSON 형식 - 이 JSON만 출력, 다른 텍스트 절대 금지]
{{
  "safe_points": ["장점 문장 (최대 2개, 없으면 빈 배열)"],
  "warning_points": ["위험/단점 문장 (최대 2개, 없으면 빈 배열)"],
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

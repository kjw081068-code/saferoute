from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "safety_grid.csv"

_grid_df: pd.DataFrame | None = None


def _load_grid() -> pd.DataFrame:
    global _grid_df
    if _grid_df is None:
        df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
        df = df.rename(columns={"위도": "lat", "경도": "lng"})
        _grid_df = df
    return _grid_df


class SafetyScore(BaseModel):
    lat: float
    lng: float
    score: float
    grade: str
    cctv_count: int
    light_count: int
    conv_count: int


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
    )

"""백엔드 map-points와 동일 필터로 좌표 JSON을 생성해 프론트 public에 둡니다."""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "data" / "map-points.json"
CCTV_CSV = ROOT / "data" / "cctv_raw.csv"
SL_CSV = ROOT / "data" / "streetlight_raw.csv"


def main() -> None:
    cctv_df = pd.read_csv(CCTV_CSV, encoding="cp949")
    cctv_df = cctv_df[
        (cctv_df["위도"] > 37.0)
        & (cctv_df["위도"] < 38.0)
        & (cctv_df["경도"] > 126.0)
        & (cctv_df["경도"] < 128.0)
    ]
    sl_df = pd.read_csv(SL_CSV, encoding="cp949")
    sl_df = sl_df[
        (sl_df["위도"] > 37.0)
        & (sl_df["위도"] < 38.0)
        & (sl_df["경도"] > 126.0)
        & (sl_df["경도"] < 128.0)
    ]

    out = {
        "cctv": [{"lat": float(r["위도"]), "lng": float(r["경도"])} for _, r in cctv_df.iterrows()],
        "streetlight": [{"lat": float(r["위도"]), "lng": float(r["경도"])} for _, r in sl_df.iterrows()],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"저장: {OUT} (CCTV {len(out['cctv'])}, 가로등 {len(out['streetlight'])})")


if __name__ == "__main__":
    main()

"""백엔드 map-points와 동일 필터로 좌표 JSON을 생성해 프론트 public에 둡니다."""

import json
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
OUT = ROOT / "frontend" / "public" / "data" / "map-points.json"
CCTV_CSV = BACKEND / "data" / "cctv_raw.csv"
SL_CSV = BACKEND / "data" / "streetlight_raw.csv"
ENT_CSV = BACKEND / "data" / "entertainment_gwanak.csv"
CONV_CSV = BACKEND / "data" / "convenience_gwanak.csv"
POLICE_CSV = BACKEND / "data" / "police_gwanak.csv"


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
    ent_df = pd.read_csv(ENT_CSV, encoding="utf-8-sig")
    conv_df = pd.read_csv(CONV_CSV, encoding="utf-8-sig")
    police_df = pd.read_csv(POLICE_CSV, encoding="utf-8-sig")

    out = {
        "cctv": [{"lat": float(r["위도"]), "lng": float(r["경도"])} for _, r in cctv_df.iterrows()],
        "streetlight": [{"lat": float(r["위도"]), "lng": float(r["경도"])} for _, r in sl_df.iterrows()],
        "entertainment": [{"lat": float(r["lat"]), "lng": float(r["lng"])} for _, r in ent_df.iterrows()],
        "convenience": [{"lat": float(r["lat"]), "lng": float(r["lng"])} for _, r in conv_df.iterrows()],
        "police": [{"lat": float(r["lat"]), "lng": float(r["lng"])} for _, r in police_df.iterrows()],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(
        f"저장: {OUT} "
        f"(CCTV {len(out['cctv'])}, 가로등 {len(out['streetlight'])}, "
        f"유흥업소 {len(out['entertainment'])}, 편의점 {len(out['convenience'])}, 경찰서 {len(out['police'])})"
    )


if __name__ == "__main__":
    main()

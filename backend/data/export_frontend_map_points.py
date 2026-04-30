"""백엔드 map-points와 동일 필터로 좌표 JSON을 생성해 프론트 public에 둡니다."""

import json
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
OUT = ROOT / "frontend" / "public" / "data" / "map-points.json"
DATA = BACKEND / "data"


def main() -> None:
    # CCTV: 관악구 + 동작구
    cctv_gwanak = pd.read_csv(DATA / "cctv_raw.csv", encoding="cp949")
    cctv_gwanak = cctv_gwanak[
        cctv_gwanak["위도"].between(37.0, 38.0) & cctv_gwanak["경도"].between(126.0, 128.0)
    ]
    cctv_dongjak = pd.read_csv(DATA / "cctv_dongjak.csv", encoding="utf-8-sig")
    cctv_dongjak = cctv_dongjak.rename(columns={"lat": "위도", "lng": "경도"})
    cctv_df = pd.concat([cctv_gwanak[["위도","경도"]], cctv_dongjak[["위도","경도"]]], ignore_index=True)

    # 가로등: 관악구 + 동작구 가로등 + 동작구 보안등
    sl_gwanak = pd.read_csv(DATA / "streetlight_raw.csv", encoding="cp949")
    sl_gwanak = sl_gwanak[
        sl_gwanak["위도"].between(37.0, 38.0) & sl_gwanak["경도"].between(126.0, 128.0)
    ]
    sl_dongjak   = pd.read_csv(DATA / "streetlight_dongjak.csv", encoding="utf-8-sig").rename(columns={"lat":"위도","lng":"경도"})
    safe_dongjak = pd.read_csv(DATA / "safelight_dongjak.csv",   encoding="utf-8-sig").rename(columns={"lat":"위도","lng":"경도"})
    sl_df = pd.concat([sl_gwanak[["위도","경도"]], sl_dongjak[["위도","경도"]], safe_dongjak[["위도","경도"]]], ignore_index=True)

    ent_df    = pd.read_csv(DATA / "entertainment_gwanak.csv", encoding="utf-8-sig")
    conv_df   = pd.read_csv(DATA / "convenience_gwanak.csv",   encoding="utf-8-sig")
    police_df = pd.read_csv(DATA / "police_gwanak.csv",        encoding="utf-8-sig")

    out = {
        "cctv":          [{"lat": float(r["위도"]), "lng": float(r["경도"])} for _, r in cctv_df.iterrows()],
        "streetlight":   [{"lat": float(r["위도"]), "lng": float(r["경도"])} for _, r in sl_df.iterrows()],
        "entertainment": [{"lat": float(r["lat"]),  "lng": float(r["lng"])}  for _, r in ent_df.iterrows()],
        "convenience":   [{"lat": float(r["lat"]),  "lng": float(r["lng"])}  for _, r in conv_df.iterrows()],
        "police":        [{"lat": float(r["lat"]),  "lng": float(r["lng"])}  for _, r in police_df.iterrows()],
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

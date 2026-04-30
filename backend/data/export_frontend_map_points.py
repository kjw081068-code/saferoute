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

    # 관악구: 좌표 1건 = 1마커
    cctv_gwanak_pts = [{"lat": float(r["위도"]), "lng": float(r["경도"])} for _, r in cctv_gwanak.iterrows()]
    # 동작구: qty만큼 마커 반복 (실제 카메라 대수 반영)
    cctv_dongjak_pts = [
        {"lat": float(r["lat"]), "lng": float(r["lng"])}
        for _, r in cctv_dongjak.iterrows()
        for _ in range(int(r.get("qty", 1)))
    ]

    # 가로등: 관악구 + 동작구 가로등
    sl_gwanak = pd.read_csv(DATA / "streetlight_raw.csv", encoding="cp949")
    sl_gwanak = sl_gwanak[
        sl_gwanak["위도"].between(37.0, 38.0) & sl_gwanak["경도"].between(126.0, 128.0)
    ]
    sl_dongjak = pd.read_csv(DATA / "streetlight_dongjak.csv", encoding="utf-8-sig").rename(columns={"lat": "위도", "lng": "경도"})
    sl_df = pd.concat([sl_gwanak[["위도", "경도"]], sl_dongjak[["위도", "경도"]]], ignore_index=True)

    # 보안등: 동작구 보안등 별도
    safe_dongjak = pd.read_csv(DATA / "safelight_dongjak.csv", encoding="utf-8-sig")

    # 유흥업소: 관악구 + 동작구
    ent_df = pd.concat([
        pd.read_csv(DATA / "entertainment_gwanak.csv", encoding="utf-8-sig"),
        pd.read_csv(DATA / "entertainment_dongjak.csv", encoding="utf-8-sig"),
    ], ignore_index=True).drop_duplicates(subset=["lat", "lng"])

    # 편의점: 관악구 + 동작구
    conv_df = pd.concat([
        pd.read_csv(DATA / "convenience_gwanak.csv", encoding="utf-8-sig"),
        pd.read_csv(DATA / "convenience_dongjak.csv", encoding="utf-8-sig"),
    ], ignore_index=True).drop_duplicates(subset=["lat", "lng"])

    # 경찰서: 관악구 + 동작구
    police_df = pd.concat([
        pd.read_csv(DATA / "police_gwanak.csv", encoding="utf-8-sig"),
        pd.read_csv(DATA / "police_dongjak.csv", encoding="utf-8-sig"),
    ], ignore_index=True).drop_duplicates(subset=["lat", "lng"])

    out = {
        "cctv":          cctv_gwanak_pts + cctv_dongjak_pts,
        "streetlight":   [{"lat": float(r["위도"]), "lng": float(r["경도"])} for _, r in sl_df.iterrows()],
        "safelight":     [{"lat": float(r["lat"]),  "lng": float(r["lng"])}  for _, r in safe_dongjak.iterrows()],
        "entertainment": [{"lat": float(r["lat"]),  "lng": float(r["lng"])}  for _, r in ent_df.iterrows()],
        "convenience":   [{"lat": float(r["lat"]),  "lng": float(r["lng"])}  for _, r in conv_df.iterrows()],
        "police":        [{"lat": float(r["lat"]),  "lng": float(r["lng"])}  for _, r in police_df.iterrows()],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(
        f"저장: {OUT}\n"
        f"  CCTV {len(out['cctv'])} (관악 {len(cctv_gwanak_pts)} + 동작 {len(cctv_dongjak_pts)}대)\n"
        f"  가로등 {len(out['streetlight'])}, 보안등 {len(out['safelight'])}, "
        f"유흥업소 {len(out['entertainment'])}, 편의점 {len(out['convenience'])}, 경찰서 {len(out['police'])}"
    )


if __name__ == "__main__":
    main()

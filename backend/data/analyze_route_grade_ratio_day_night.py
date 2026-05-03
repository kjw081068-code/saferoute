"""
경로 샘플(동작구 내 100m 격자 점)에 대해 등급 비율을 낮/밤으로 각각 집계합니다.

- '낮': 편의점·24시 점포를 cap 만점으로 가정(한국시 08~22와 동일).
- '밤': 편의점·24시 점포를 실제 반경 반영(한국시 22~익일 08과 동일).

실제 TMAP 경로 좌표가 있으면 --path-csv lat,lng 한 줄씩 넣어 동일 분석 가능합니다.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

# backend 루트에서 routers import
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import routers.safety as sm  # noqa: E402
from routers.route import _score_for_coord  # noqa: E402

# 동작구 바운딩박스 (analyze_distribution.py 와 동일)
LAT_MIN, LAT_MAX = 37.490, 37.535814
LNG_MIN, LNG_MAX = 126.916, 126.988477

# 격자 간격 (m) — route.py 의 경로 구간 샘플과 맞추려면 100
STEP_M = 100.0
LAT_PER_M = 1 / 111_000
LNG_PER_M = 1 / 88_000


def grade_bucket(grade: str) -> str:
    g = grade.strip()
    if "위험" in g:
        return "위험"
    if "보통" in g:
        return "보통"
    if "안전" in g:
        return "안전"
    return "기타"


def iter_grid_points(step_m: float) -> Iterable[Tuple[float, float]]:
    lat = LAT_MIN
    while lat <= LAT_MAX + 1e-9:
        lng = LNG_MIN
        while lng <= LNG_MAX + 1e-9:
            yield (lat, lng)
            lng += step_m * LNG_PER_M
        lat += step_m * LAT_PER_M


def load_path_csv(path: Path) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        if r.fieldnames and "lat" in r.fieldnames and "lng" in r.fieldnames:
            for row in r:
                try:
                    pts.append((float(row["lat"]), float(row["lng"])))
                except (KeyError, ValueError):
                    continue
        else:
            f.seek(0)
            for row in csv.reader(f):
                if len(row) < 2:
                    continue
                try:
                    pts.append((float(row[0]), float(row[1])))
                except ValueError:
                    continue
    return pts


def count_grades(points: List[Tuple[float, float]], is_night: bool) -> Tuple[int, int, int, int]:
    orig = sm.store_proximity_night_window_kst
    sm.store_proximity_night_window_kst = lambda now=None: is_night  # noqa: ARG005
    try:
        danger = normal = safe = other = 0
        for lat, lng in points:
            _, grade = _score_for_coord(lat, lng)
            b = grade_bucket(grade)
            if b == "위험":
                danger += 1
            elif b == "보통":
                normal += 1
            elif b == "안전":
                safe += 1
            else:
                other += 1
        return danger, normal, safe, other
    finally:
        sm.store_proximity_night_window_kst = orig


def print_ratio(label: str, danger: int, normal: int, safe: int, other: int) -> None:
    total = danger + normal + safe + other
    if total == 0:
        print(f"{label}: 샘플 없음")
        return
    print(f"\n=== {label} (n={total}) ===")
    for name, c in [("위험", danger), ("보통", normal), ("안전", safe), ("기타", other)]:
        pct = 100.0 * c / total
        print(f"  {name}: {c} ({pct:.2f}%)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--path-csv",
        type=Path,
        default=None,
        help="lat,lng 또는 lat,lng 컬럼 CSV. 없으면 동작구 100m 격자 사용.",
    )
    p.add_argument("--step-m", type=float, default=STEP_M, help="격자 간격(m), --path-csv 없을 때만")
    args = p.parse_args()

    if args.path_csv:
        points = load_path_csv(args.path_csv)
        print(f"경로/점 CSV: {args.path_csv} ({len(points)}점)")
    else:
        points = list(iter_grid_points(args.step_m))
        print(f"동작구 {args.step_m}m 격자 샘플: {len(points)}점")

    d_n, n_n, s_n, o_n = count_grades(points, is_night=True)
    d_d, n_d, s_d, o_d = count_grades(points, is_night=False)

    print_ratio("밤 모드 (편의점·24시 실측)", d_n, n_n, s_n, o_n)
    print_ratio("낮 모드 (편의점·24시 만점)", d_d, n_d, s_d, o_d)


if __name__ == "__main__":
    main()

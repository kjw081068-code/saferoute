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

import numpy as np

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


def collect_scores_and_grades(
    points: List[Tuple[float, float]], is_night: bool
) -> Tuple[List[float], Tuple[int, int, int, int]]:
    """점수 목록 + (위험, 보통, 안전, 기타) 개수. 등급은 `score_to_grade_realtime`와 동일."""
    orig = sm.store_proximity_night_window_kst
    sm.store_proximity_night_window_kst = lambda now=None: is_night  # noqa: ARG005
    scores: List[float] = []
    try:
        danger = normal = safe = other = 0
        for lat, lng in points:
            sc, grade = _score_for_coord(lat, lng)
            scores.append(float(sc))
            b = grade_bucket(grade)
            if b == "위험":
                danger += 1
            elif b == "보통":
                normal += 1
            elif b == "안전":
                safe += 1
            else:
                other += 1
        return scores, (danger, normal, safe, other)
    finally:
        sm.store_proximity_night_window_kst = orig


def count_grades(points: List[Tuple[float, float]], is_night: bool) -> Tuple[int, int, int, int]:
    _, counts = collect_scores_and_grades(points, is_night)
    return counts


def print_ratio(label: str, danger: int, normal: int, safe: int, other: int) -> None:
    total = danger + normal + safe + other
    if total == 0:
        print(f"{label}: 샘플 없음")
        return
    print(f"\n=== {label} (n={total}) ===")
    for name, c in [("위험", danger), ("보통", normal), ("안전", safe), ("기타", other)]:
        pct = 100.0 * c / total
        print(f"  {name}: {c} ({pct:.2f}%)")


def print_score_summary(scores: List[float]) -> None:
    if not scores:
        print("  점수 요약: 샘플 없음")
        return
    arr = np.array(scores, dtype=float)
    qs = [0, 5, 10, 25, 50, 75, 90, 95, 100]
    pct = np.percentile(arr, qs)
    print("  점수 요약 (분위):")
    print(
        f"    min={arr.min():.2f}  "
        + "  ".join(f"p{q}={pct[i]:.2f}" for i, q in enumerate(qs) if q not in (0, 100))
        + f"  max={arr.max():.2f}  mean={arr.mean():.2f}"
    )


def print_ascii_histogram(title: str, scores: List[float], bins: int = 28, bar_width: int = 46) -> None:
    """터미널용 텍스트 히스토그램(막대는 #)."""
    if not scores:
        print(f"\n--- {title}: 히스토그램 생략(점 없음) ---")
        return
    arr = np.array(scores, dtype=float)
    counts, edges = np.histogram(arr, bins=bins)
    mx = int(counts.max()) if counts.size else 0
    mx = mx if mx > 0 else 1
    print(f"\n--- {title} 점수 히스토그램 ({bins}구간, 막대 최대폭={bar_width}) ---")
    for i in range(len(counts)):
        lo, hi = float(edges[i]), float(edges[i + 1])
        c = int(counts[i])
        bar_len = int(bar_width * c / mx)
        bar = "#" * bar_len
        # 등급 경계 S=0, S=20이 [lo, hi) 안에 있으면 표시
        tag = ""
        if lo <= 0 < hi:
            tag += "[S=0]"
        if lo < 20 <= hi or (lo == 20 and hi > 20):
            tag += "[S=20]"
        extra = f" {tag}" if tag else ""
        print(f"  [{lo:7.2f},{hi:7.2f}) {c:5d} |{bar}{extra}")


def print_ascii_histogram_fixed_bin_width(
    title: str,
    scores: List[float],
    bin_width: float = 2.0,
    bar_width: int = 46,
) -> None:
    """터미널용 텍스트 히스토그램(고정 구간폭, 예: 2점 단위)."""
    if not scores:
        print(f"\n--- {title}: 히스토그램 생략(점 없음) ---")
        return
    if bin_width <= 0:
        raise ValueError("bin_width는 0보다 커야 합니다.")

    arr = np.array(scores, dtype=float)
    lo = math.floor(float(arr.min()) / bin_width) * bin_width
    hi = math.ceil(float(arr.max()) / bin_width) * bin_width
    edges = np.arange(lo, hi + bin_width, bin_width, dtype=float)
    counts, edges = np.histogram(arr, bins=edges)

    mx = int(counts.max()) if counts.size else 0
    mx = mx if mx > 0 else 1

    print(f"\n--- {title} 점수 히스토그램 ({bin_width:g}점 단위, 막대 최대폭={bar_width}) ---")
    for i in range(len(counts)):
        a = float(edges[i])
        b = float(edges[i + 1])
        c = int(counts[i])
        bar_len = int(bar_width * c / mx)
        bar = "#" * bar_len

        tag = ""
        if a <= 0 < b:
            tag += "[S=0]"
        if a <= 20 < b:
            tag += "[S=20]"
        extra = f" {tag}" if tag else ""
        print(f"  [{a:7.2f},{b:7.2f}) {c:5d} |{bar}{extra}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--path-csv",
        type=Path,
        default=None,
        help="lat,lng 또는 lat,lng 컬럼 CSV. 없으면 동작구 100m 격자 사용.",
    )
    p.add_argument("--step-m", type=float, default=STEP_M, help="격자 간격(m), --path-csv 없을 때만")
    p.add_argument(
        "--bin-width",
        type=float,
        default=2.0,
        help="히스토그램 구간폭(점수 단위). 예: 2면 2점 단위 히스토그램",
    )
    args = p.parse_args()

    if args.path_csv:
        points = load_path_csv(args.path_csv)
        print(f"경로/점 CSV: {args.path_csv} ({len(points)}점)")
    else:
        points = list(iter_grid_points(args.step_m))
        print(f"동작구 {args.step_m}m 격자 샘플: {len(points)}점")

    print(
        "\n등급 기준(safety.score_to_grade_realtime): "
        "S < 0 위험 | 0 <= S < 20 보통 | S >= 20 안전"
    )

    scores_night, (d_n, n_n, s_n, o_n) = collect_scores_and_grades(points, is_night=True)
    scores_day, (d_d, n_d, s_d, o_d) = collect_scores_and_grades(points, is_night=False)

    print_ratio("밤 모드 (편의점·24시 실측)", d_n, n_n, s_n, o_n)
    print_score_summary(scores_night)
    print_ascii_histogram_fixed_bin_width("밤 모드", scores_night, bin_width=args.bin_width)

    print_ratio("낮 모드 (편의점·24시 만점)", d_d, n_d, s_d, o_d)
    print_score_summary(scores_day)
    print_ascii_histogram_fixed_bin_width("낮 모드", scores_day, bin_width=args.bin_width)


if __name__ == "__main__":
    main()

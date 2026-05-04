"""
상호명으로 카카오 API 좌표 검색 후 open24_dongjak.csv에 추가
사용법: python add_place_to_open24.py "상호명1" "상호명2" ...
예시:  python add_place_to_open24.py "이름없는약국" "흑석24시내과"
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../backend/.env"))
API_KEY = os.environ["KAKAO_REST_API_KEY"]

CSV_PATH   = os.path.join(os.path.dirname(__file__), "open24_dongjak.csv")
SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
HEADERS    = {"Authorization": f"KakaoAK {API_KEY}"}

# 동작구 중심 좌표 (검색 우선순위 기준점)
DONGJAK_X = 126.9439
DONGJAK_Y = 37.4963


def search_place(name: str) -> list:
    """상호명으로 동작구 근처 검색, 후보 목록 반환"""
    params = {
        "query":  name,
        "x":      DONGJAK_X,
        "y":      DONGJAK_Y,
        "radius": 5000,
        "size":   5,
    }
    resp = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=10)
    if resp.status_code != 200:
        print(f"  [오류] {resp.status_code}: {resp.text[:100]}")
        return []
    return resp.json().get("documents", [])


def pick_candidate(docs: list, query: str) -> dict | None:
    """후보가 1개면 자동 선택, 여러 개면 사용자가 선택"""
    if not docs:
        return None
    if len(docs) == 1:
        return docs[0]

    print(f"\n  '{query}' 검색 결과 {len(docs)}개:")
    for i, d in enumerate(docs):
        print(f"    [{i+1}] {d['place_name']}  |  {d.get('road_address_name') or d.get('address_name')}  |  {d['category_name']}")
    while True:
        sel = input("  번호 선택 (0=건너뜀): ").strip()
        if sel == "0":
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(docs):
            return docs[int(sel) - 1]
        print("  올바른 번호를 입력하세요.")


def main():
    names = sys.argv[1:]
    if not names:
        print("사용법: python add_place_to_open24.py \"상호명1\" \"상호명2\" ...")
        return

    # 기존 CSV 로드
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    else:
        df = pd.DataFrame(columns=["name", "lat", "lng", "category", "address"])

    added = []
    for name in names:
        print(f"\n🔍 '{name}' 검색 중...")
        docs = search_place(name)
        picked = pick_candidate(docs, name)

        if picked is None:
            print(f"  ✗ '{name}' 건너뜀")
            continue

        new_row = {
            "name":     picked["place_name"],
            "lat":      float(picked["y"]),
            "lng":      float(picked["x"]),
            "category": picked["category_name"],
            "address":  picked.get("road_address_name") or picked.get("address_name", ""),
        }

        # 중복 확인
        dup = df[(df["name"] == new_row["name"]) & (df["lat"] == new_row["lat"])]
        if not dup.empty:
            print(f"  ⚠ 이미 존재: {new_row['name']}")
            continue

        added.append(new_row)
        print(f"  ✓ 추가: {new_row['name']}  ({new_row['lat']}, {new_row['lng']})")

    if added:
        df = pd.concat([df, pd.DataFrame(added)], ignore_index=True)
        df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"\n✓ {len(added)}개 추가 저장 완료 (총 {len(df)}개)")
    else:
        print("\n추가된 항목 없음")


if __name__ == "__main__":
    main()

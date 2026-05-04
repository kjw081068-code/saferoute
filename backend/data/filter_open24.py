# -*- coding: utf-8 -*-
"""
open24_dongjak.csv에서 안전과 무관한 카테고리 제거
유지: 음식점, 카페, 목욕탕/사우나, 편의점, 슈퍼마켓, 식품판매, 스터디카페, 만화방, 보드카페
제거: 열쇠, 도장, 건설, 시공, 퀵서비스, 이삿짐, 전자담배, 무인민원, 전자제품, 미용,
       꽃집, 세차장, 부동산, 주차장, 택배, 사진관, 골프, 탁구, 헬스클럽, 뽑기방,
       어린이집, 언론, 기업, 문구, 미술, 인테리어, 교육, 세탁, 자동차, 동물병원
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import os
import pandas as pd

CSV_PATH = os.path.join(os.path.dirname(__file__), "open24_dongjak.csv")
df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")

print(f"정제 전: {len(df)}개\n")

# 안전 관련 유지할 최상위 카테고리 키워드
KEEP_KEYWORDS = [
    "음식점",
    "카페",
    "목욕탕",
    "사우나",
    "찜질방",
    "편의점",
    "슈퍼마켓",
    "식품",
    "스터디",
    "만화방",
    "보드카페",
    "노래",      # 노래방/노래연습장 (이미 제거됐지만 혹시 남아있으면 처리)
    "약국",
    "동물병원",  # 심야 응급 역할
]

# 명확히 제거할 카테고리 키워드
REMOVE_KEYWORDS = [
    "열쇠", "도장", "인장",
    "건설", "시공", "설비", "인테리어", "인테리어",
    "퀵서비스", "이삿짐",
    "전자담배", "담배",
    "무인민원", "무인우편",
    "전자제품", "컴퓨터수리", "컴퓨터서비스",
    "미용실", "헤어", "피부관리", "네일",
    "꽃집", "화훼",
    "세차", "자동차",
    "부동산",
    "주차",
    "택배", "퀵",
    "사진관", "사진",
    "골프",
    "탁구",
    "헬스클럽", "스포츠센터", "피트니스",
    "뽑기",
    "어린이집", "유치원",
    "언론", "미디어", "신문",
    "기업", "회사",
    "문구", "미술",
    "교육", "학원",
    "세탁",
]

def should_keep(cat: str) -> bool:
    if pd.isna(cat) or cat.strip() == "":
        return False  # 카테고리 없는 것 제거
    cat_l = cat.lower()

    # 먼저 제거 키워드 검사
    for kw in REMOVE_KEYWORDS:
        if kw in cat:
            return False

    # 유지 키워드 검사
    for kw in KEEP_KEYWORDS:
        if kw in cat:
            return True

    return False  # 해당 안되면 제거

keep_mask = df["category"].apply(should_keep)
removed = df[~keep_mask]
df_clean = df[keep_mask].reset_index(drop=True)

print("=== 제거된 항목 ===")
for _, row in removed.iterrows():
    print(f"  {row['name']:<30} | {row['category']}")

print(f"\n정제 후: {len(df_clean)}개 (제거: {len(removed)}개)\n")

# 카테고리별 잔존 현황
print("=== 잔존 카테고리 ===")
for cat, cnt in df_clean["category"].value_counts().items():
    print(f"  {cnt:3d}개  {cat}")

df_clean.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
print(f"\n✓ 저장 완료: {CSV_PATH}")

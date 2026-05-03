import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import math
import pandas as pd

df = pd.read_csv("firestation_dongjak.csv", encoding="utf-8-sig")
print(f"전체: {len(df)}개")

exclude = ["어린이집", "화장실", "예방과", "구조대", "의용소방대"]
df = df[~df["name"].str.contains("|".join(exclude))].reset_index(drop=True)
print(f"부속시설 제거 후: {len(df)}개")

def dist_m(r1, r2):
    dlat = (float(r1["lat"]) - float(r2["lat"])) * 111320
    dlng = (float(r1["lng"]) - float(r2["lng"])) * 88000
    return math.sqrt(dlat**2 + dlng**2)

df = df.sort_values("name").reset_index(drop=True)
keep = []
for i in range(len(df)):
    dup = any(dist_m(df.iloc[i], df.iloc[j]) < 300 for j in keep)
    if not dup:
        keep.append(i)

df = df.iloc[keep].reset_index(drop=True)
print(f"중복 제거 후: {len(df)}개")
for _, r in df.iterrows():
    print(f"  - {r['name']} ({r['lat']:.6f}, {r['lng']:.6f})")

df.to_csv("firestation_dongjak.csv", index=False, encoding="utf-8-sig")
print("✓ firestation_dongjak.csv 저장 완료")

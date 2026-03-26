import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd

files = [
    "bell_raw.xlsx",
    "cctv_raw.csv",
    "crime_raw.csv",
    "streetlight_raw.csv",
]

lat_keywords = ["위도", "lat", "latitude", "y좌표", "y_coord", "ycoord", "wgs84y"]
lon_keywords = ["경도", "lon", "lng", "longitude", "x좌표", "x_coord", "xcoord", "wgs84x"]

for fname in files:
    print(f"\n{'='*60}")
    print(f"파일명: {fname}")
    try:
        if fname.endswith(".xlsx"):
            df = pd.read_excel(fname)
            encoding_info = ""
        else:
            encoding_info = "utf-8"
            for enc in ["utf-8", "euc-kr", "cp949"]:
                try:
                    df = pd.read_csv(fname, encoding=enc)
                    encoding_info = enc
                    break
                except UnicodeDecodeError:
                    continue

        print(f"총 행 수  : {len(df)}")
        print(f"컬럼 수   : {len(df.columns)}")
        print(f"컬럼 목록 : {list(df.columns)}")
        if encoding_info:
            print(f"인코딩    : {encoding_info}")

        cols_norm = {c: c.lower().replace(" ", "").replace("_", "") for c in df.columns}
        lat_cols = [c for c, cn in cols_norm.items() if any(k in cn for k in lat_keywords)]
        lon_cols = [c for c, cn in cols_norm.items() if any(k in cn for k in lon_keywords)]
        print(f"위도 컬럼 : {lat_cols if lat_cols else '없음'}")
        print(f"경도 컬럼 : {lon_cols if lon_cols else '없음'}")

    except Exception as e:
        print(f"오류: {e}")

print(f"\n{'='*60}")
print("분석 완료")

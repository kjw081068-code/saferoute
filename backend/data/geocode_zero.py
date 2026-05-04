# -*- coding: utf-8 -*-
import json, time
import urllib.request
from pathlib import Path
from collections import Counter

KAKAO_KEY = '6a6f6b2cab199a95211f978b7c240214'
DATA_DIR = Path(__file__).parent

with open(DATA_DIR / 'zero_score_sample.json', encoding='utf-8') as f:
    samples = json.load(f)

results = []
errors = 0

print(f'샘플 {len(samples)}개 역지오코딩 시작...')

for i, coord in enumerate(samples):
    lat = coord['lat']
    lng = coord['lng']
    url = f'https://dapi.kakao.com/v2/local/geo/coord2address.json?x={lng}&y={lat}'
    req = urllib.request.Request(url, headers={'Authorization': f'KakaoAK {KAKAO_KEY}'})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        docs = data.get('documents', [])
        if docs:
            addr = docs[0]
            road = addr.get('road_address')
            jibun = addr.get('address')
            if road:
                results.append({
                    'lat': lat, 'lng': lng,
                    'type': 'road',
                    'region_1': road.get('region_1depth_name', ''),
                    'region_2': road.get('region_2depth_name', ''),
                    'region_3': road.get('region_3depth_name', ''),
                    'road_name': road.get('road_name', ''),
                })
            elif jibun:
                results.append({
                    'lat': lat, 'lng': lng,
                    'type': 'jibun',
                    'region_1': jibun.get('region_1depth_name', ''),
                    'region_2': jibun.get('region_2depth_name', ''),
                    'region_3': jibun.get('region_3depth_name', ''),
                    'road_name': '',
                })
        else:
            results.append({
                'lat': lat, 'lng': lng,
                'type': 'no_address',
                'region_1': '', 'region_2': '', 'region_3': '', 'road_name': ''
            })
    except Exception as e:
        errors += 1
        results.append({
            'lat': lat, 'lng': lng,
            'type': 'error',
            'region_1': '', 'region_2': '', 'region_3': '', 'road_name': ''
        })

    if (i + 1) % 50 == 0:
        print(f'  {i+1}/{len(samples)} 완료...')
    time.sleep(0.05)

print(f'\n완료. 에러: {errors}개')

with open(DATA_DIR / 'zero_score_geocoded.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# ── 분석 ──────────────────────────────────────────
region3_counter = Counter()
no_addr = 0

for r in results:
    if r['type'] == 'no_address':
        no_addr += 1
    elif r['type'] != 'error':
        key = r['region_3'] if r['region_3'] else r['region_2']
        region3_counter[key] += 1

print(f'\n=== 행정구역별 분포 (상위 30개) ===')
print(f'주소 없음(하천/수면/산림 등): {no_addr}개 ({no_addr/len(results)*100:.1f}%)')
print()
for region, cnt in region3_counter.most_common(30):
    pct = cnt / len(results) * 100
    bar = '#' * int(pct * 2)
    print(f'  {region:<20} {cnt:4d}개  {pct:5.1f}%  {bar}')

# region_2(구) 기준 요약
print('\n=== 구 단위 요약 ===')
region2_counter = Counter()
for r in results:
    if r['type'] not in ('no_address', 'error'):
        region2_counter[r['region_2']] += 1
for region, cnt in region2_counter.most_common():
    pct = cnt / len(results) * 100
    print(f'  {region:<15} {cnt:4d}개  {pct:5.1f}%')

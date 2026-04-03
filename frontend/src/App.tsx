import React, { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import styles from './App.module.css';

const SILLIM_STATION = { lat: 37.4846, lng: 126.9294 };
const MAP_ZOOM_LEVEL = 4;
/** `panBy` 한 번에 이동할 픽셀 (동네 줌 기준) */
const MAP_PAN_STEP_PX = 120;

const PIN_W = 30;
const PIN_H = 42;
/** CCTV·가로등 마커 이미지(픽셀) — `public/markers/*.svg` */
const MAP_DOT_SIZE = 14;

/**
 * 클러스터 크기 단계(치킨 샘플과 동일 패턴). 줌이 바뀔 때마다 격자가 다시 계산되어
 * 묶인 개수·원 크기가 자연스럽게 바뀜.
 */
const CLUSTER_CALCULATOR = [12, 45, 110, 360];

function clusterCountText(count: number): string {
  if (count > 999) return '999+';
  return String(count);
}

/** CCTV=파랑, 가로등=주황, 유흥업소=빨강 계열 — 클러스터 원만으로 구분 */
function clusterStylesFor(kind: 'cctv' | 'streetlight' | 'entertainment' | 'convenience'): Array<Record<string, string>> {
  const fills: [string, string, string, string, string] =
    kind === 'cctv'
      ? [
          'rgba(59, 130, 246, 0.9)',
          'rgba(37, 99, 235, 0.92)',
          'rgba(29, 78, 216, 0.94)',
          'rgba(30, 58, 138, 0.95)',
          'rgba(23, 37, 84, 0.96)',
        ]
      : kind === 'streetlight'
      ? [
          'rgba(251, 191, 36, 0.92)',
          'rgba(245, 158, 11, 0.92)',
          'rgba(217, 119, 6, 0.94)',
          'rgba(180, 83, 9, 0.95)',
          'rgba(146, 64, 14, 0.96)',
        ]
      : kind === 'entertainment'
      ? [
          'rgba(239, 68, 68, 0.9)',
          'rgba(220, 38, 38, 0.92)',
          'rgba(185, 28, 28, 0.94)',
          'rgba(153, 27, 27, 0.95)',
          'rgba(127, 29, 29, 0.96)',
        ]
      : [
          'rgba(22, 163, 74, 0.9)',
          'rgba(21, 128, 61, 0.92)',
          'rgba(20, 83, 45, 0.94)',
          'rgba(14, 116, 144, 0.95)',
          'rgba(6, 78, 59, 0.96)',
        ];
  const sizes = [32, 40, 48, 56, 64];
  return sizes.map((px, i) => ({
    width: `${px}px`,
    height: `${px}px`,
    borderRadius: `${px / 2}px`,
    background: fills[i],
    color: '#fff',
    textAlign: 'center',
    fontWeight: '700',
    lineHeight: `${px}px`,
    fontSize: px >= 48 ? '14px' : '12px',
    border: '2px solid rgba(255,255,255,0.92)',
    boxSizing: 'border-box',
  }));
}

function pinSvgDataUrl(fill: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${PIN_W}" height="${PIN_H}" viewBox="0 0 30 42"><path fill="${fill}" stroke="rgba(0,0,0,0.22)" stroke-width="1" d="M15 2C8.4 2 3 7.2 3 13.5 3 19.5 15 40 15 40s12-20.5 12-26.5C27 7.2 21.6 2 15 2z"/><circle cx="15" cy="14" r="3.5" fill="#fff"/></svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

type RouteId = 'safe' | 'normal';

type MapPickTarget = 'origin' | 'destination';

type RouteCardData = {
  id: RouteId;
  title: string;
  avg_score: number;
  grade: string;
  duration: number;
  riskNote: string;
};

/** 출발/도착: 장소명(건물·역·가게 등) 우선, 주소는 하단 칸 */
type LocationField = {
  placeName: string;
  address: string;
};

/** TMAP POI 검색 결과 한 항목 */
type PoiItem = { name: string; address: string; lat: number; lng: number };

const emptyLocation = (): LocationField => ({ placeName: '', address: '' });

function hasLocationValue(loc: LocationField): boolean {
  return Boolean(loc.placeName.trim() || loc.address.trim());
}

/** coord2Address 결과 → 장소명(가능 시) + 전체 주소 */
function locationFromGeocodeResult(r: Coord2AddressResult): LocationField {
  const address = pickAddressFromGeocodeResult(r);
  const bn = r.road_address?.building_name?.trim();
  return {
    placeName: bn ?? '',
    address,
  };
}

/** 지도 오버레이·요약용 한 줄 표시 */
function formatLocationLabel(loc: LocationField): string {
  const p = loc.placeName.trim();
  const a = loc.address.trim();
  if (p && a) return `${p} · ${a}`;
  if (p) return p;
  return a;
}

/** POST /api/safe-route 응답의 경로 한 개 */
type ApiRouteResult = {
  type: string;
  points: number[][];
  segments: { lat: number; lng: number; score: number; grade: string }[];
  avg_score: number;
  grade: string;
  duration: number;
};

const ROUTE_STROKE_WEIGHT = 6;
/** 일반 경로(백엔드 type normal) 단색 */
const NORMAL_ROUTE_BLUE = '#2563eb';

/** 구간 등급별 선 색 (백엔드 segments.grade) */
function segmentGradeColor(grade: string): string {
  const g = grade.trim();
  if (g === '안전') return '#4ade80';
  if (g === '보통') return '#facc15';
  if (g === '위험') return '#f87171';
  if (g.includes('주의')) return '#facc15';
  return '#facc15';
}

/** 위도·경도(도) 기준 거리 제곱 — 가까운 꼭짓점 찾기용 */
function squaredDegDist(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const dLat = lat1 - lat2;
  const dLng = lng1 - lng2;
  return dLat * dLat + dLng * dLng;
}

/** points[fromIdx]부터 끝까지 중 (lat,lng)에 가장 가까운 꼭짓점 인덱스 (경로 진행 방향 유지) */
function closestPointIndexFrom(
  points: number[][],
  lat: number,
  lng: number,
  fromIdx: number
): number {
  let best = fromIdx;
  let bestD = Infinity;
  for (let i = fromIdx; i < points.length; i++) {
    const d = squaredDegDist(points[i]![0], points[i]![1], lat, lng);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

/**
 * segments 샘플 좌표를 points 폴리라인에 투영해 구간 경계를 잡고,
 * 구간마다 grade 색의 Polyline을 이어 그립니다.
 */
function buildPolylinesFromSegments(
  maps: KakaoGlobal['maps'],
  points: number[][],
  segments: { lat: number; lng: number; grade: string }[]
): KakaoPolyline[] {
  if (points.length < 2 || segments.length === 0) return [];

  const n = segments.length;
  /** boundaries[j] = segment[j] 구간 시작 꼭짓점 인덱스, boundaries[n] = 끝 */
  const boundaries: number[] = new Array(n + 1);
  boundaries[0] = 0;
  for (let j = 1; j < n; j++) {
    const idx = closestPointIndexFrom(points, segments[j]!.lat, segments[j]!.lng, boundaries[j - 1]!);
    boundaries[j] = Math.max(idx, boundaries[j - 1]!);
  }
  boundaries[n] = points.length - 1;

  const polylines: KakaoPolyline[] = [];
  for (let j = 0; j < n; j++) {
    let start = boundaries[j]!;
    let end = boundaries[j + 1]!;
    if (end < start) end = start;
    if (start === end) {
      if (end < points.length - 1) end += 1;
      else if (start > 0) start -= 1;
    }
    if (start > end) [start, end] = [end, start];

    const slice = points.slice(start, end + 1);
    if (slice.length < 2) continue;

    const path = slice.map(([lat, lng]) => new maps.LatLng(lat, lng));
    polylines.push(
      new maps.Polyline({
        path,
        strokeWeight: ROUTE_STROKE_WEIGHT,
        strokeColor: segmentGradeColor(segments[j]!.grade),
        strokeOpacity: 0.95,
        strokeStyle: 'solid',
      })
    );
  }
  return polylines;
}

/** 일반 경로: points 전체를 파란 Polyline 한 줄로 */
function buildNormalRouteBluePolylines(maps: KakaoGlobal['maps'], points: number[][]): KakaoPolyline[] {
  if (points.length < 2) return [];
  const path = points.map(([lat, lng]) => new maps.LatLng(lat, lng));
  return [
    new maps.Polyline({
      path,
      strokeWeight: ROUTE_STROKE_WEIGHT,
      strokeColor: NORMAL_ROUTE_BLUE,
      strokeOpacity: 0.92,
      strokeStyle: 'solid',
    }),
  ];
}

function fitMapToRoutePoints(map: KakaoMap, maps: KakaoGlobal['maps'], routeList: ApiRouteResult[]) {
  const bounds = new maps.LatLngBounds();
  for (const r of routeList) {
    for (const pt of r.points) {
      bounds.extend(new maps.LatLng(pt[0], pt[1]));
    }
  }
  map.setBounds(bounds);
}

async function resolveLatLng(
  geocoder: Geocoder,
  loc: LocationField,
  coordRef: MutableRefObject<{ lat: number; lng: number } | null>
): Promise<{ lat: number; lng: number }> {
  if (coordRef.current) {
    return coordRef.current;
  }
  const q = formatLocationLabel(loc).trim();
  if (!q) {
    throw new Error('주소 또는 장소를 입력하거나 지도에서 선택하세요.');
  }
  return new Promise((resolve, reject) => {
    geocoder.addressSearch(q, (result, status) => {
      if (status !== window.kakao.maps.services.Status.OK || !result?.length) {
        reject(new Error(`주소 검색에 실패했습니다: ${q}`));
        return;
      }
      const lat = parseFloat(result[0]!.y);
      const lng = parseFloat(result[0]!.x);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        reject(new Error('좌표로 변환하지 못했습니다.'));
        return;
      }
      resolve({ lat, lng });
    });
  });
}

function riskNoteFromRoute(r: ApiRouteResult): string {
  const hasDanger = r.segments.some((s) => s.grade.includes('위험'));
  const hasMid = r.segments.some((s) => s.grade.includes('보통') || s.grade.includes('주의'));
  if (hasDanger) return '경로에 위험 등급 구간이 포함되어 있습니다. 지도의 빨간 선을 확인하세요.';
  if (hasMid) return '보통·주의 구간이 있습니다. 노란 선 구간을 확인하세요.';
  return '대부분 안전 등급 구간입니다.';
}

function scoreBandClass(score: number): 'bandHigh' | 'bandMid' | 'bandLow' {
  if (score >= 80) return 'bandHigh';
  if (score >= 50) return 'bandMid';
  return 'bandLow';
}

function formatKoreanTime(d: Date) {
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

function isNight(d: Date) {
  const h = d.getHours();
  return h >= 19 || h < 6;
}

function pickAddressFromGeocodeResult(r: Coord2AddressResult): string {
  const road = r.road_address?.address_name?.trim();
  if (road) return road;
  return r.address.address_name;
}

const SAFETY_API_BASE = process.env.REACT_APP_API_URL?.trim() || 'http://localhost:8000';

type MapPointSafety = {
  score: number;
  grade: string;
  lat: number;
  lng: number;
  cctv_count: number;
  light_count: number;
  conv_count: number;
  ent_count: number;
};

/** 백엔드 grade → UI 색상 구분 */
function safetyGradeVariant(grade: string): 'safe' | 'caution' | 'danger' {
  const g = grade.trim().toLowerCase();
  if (grade.includes('위험') || g === 'danger' || g === 'high_risk') return 'danger';
  if (grade.includes('보통') || g === 'normal' || g === 'medium' || g === 'caution') return 'caution';
  return 'safe';
}

const KAKAO_SDK_SCRIPT_ID = 'kakao-maps-sdk';
let kakaoSdkLoadPromise: Promise<void> | null = null;

function loadKakaoSdk(): Promise<void> {
  if (window.kakao?.maps) {
    return Promise.resolve();
  }
  // index.html에서 이미 SDK 스크립트가 로드된 경우 (autoload=false → window.kakao만 존재)
  if (window.kakao) {
    return Promise.resolve();
  }
  if (kakaoSdkLoadPromise) return kakaoSdkLoadPromise;

  kakaoSdkLoadPromise = new Promise<void>((resolve, reject) => {
    const key = process.env.REACT_APP_KAKAO_MAP_KEY;
    if (!key) {
      reject(new Error('REACT_APP_KAKAO_MAP_KEY 환경변수가 설정되지 않았습니다.'));
      return;
    }

    const existing = document.getElementById(KAKAO_SDK_SCRIPT_ID) as HTMLScriptElement | null;
    if (existing && existing.src.includes('YOUR_KAKAO_KEY')) {
      existing.parentElement?.removeChild(existing);
    }

    const s = document.createElement('script');
    s.id = KAKAO_SDK_SCRIPT_ID;
    s.type = 'text/javascript';
    s.async = true;
    s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(
      key
    )}&autoload=false&libraries=services,clusterer`;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('카카오맵 SDK 로드에 실패했습니다.'));
    document.head.appendChild(s);
  });

  return kakaoSdkLoadPromise;
}

function disposeRoutePolylines(mapRef: MutableRefObject<Partial<Record<RouteId, KakaoPolyline[]>>>) {
  for (const list of Object.values(mapRef.current)) {
    list?.forEach((p) => p.setMap(null));
  }
  mapRef.current = {};
}

/** 안전·일반 경로 폴리라인을 동시에 표시 (일반 파랑을 먼저 깔고 안전 색상을 위에) */
function showAllRoutePolylinesOnMap(
  map: KakaoMap | null,
  polyRef: MutableRefObject<Partial<Record<RouteId, KakaoPolyline[]>>>
) {
  if (!map) return;
  (['normal', 'safe'] as const).forEach((id) => {
    polyRef.current[id]?.forEach((p) => p.setMap(map));
  });
}

function App() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<KakaoMap | null>(null);
  const originMarkerRef = useRef<KakaoMarker | null>(null);
  const destMarkerRef = useRef<KakaoMarker | null>(null);
  const mapPickTargetRef = useRef<MapPickTarget | null>(null);
  const cctvClustererRef = useRef<KakaoMarkerClusterer | null>(null);
  const lightClustererRef = useRef<KakaoMarkerClusterer | null>(null);
  const entClustererRef = useRef<KakaoMarkerClusterer | null>(null);
  const convClustererRef = useRef<KakaoMarkerClusterer | null>(null);
  const cctvMarkersRef = useRef<KakaoMarker[]>([]);
  const lightMarkersRef = useRef<KakaoMarker[]>([]);
  const entMarkersRef = useRef<KakaoMarker[]>([]);
  const convMarkersRef = useRef<KakaoMarker[]>([]);
  const showCctvRef = useRef(false);
  const showStreetlightRef = useRef(false);
  const showEntRef = useRef(false);
  const showConvRef = useRef(false);
  const geocoderRef = useRef<Geocoder | null>(null);
  const originCoordRef = useRef<{ lat: number; lng: number } | null>(null);
  const destCoordRef = useRef<{ lat: number; lng: number } | null>(null);
  const routePolylinesRef = useRef<Partial<Record<RouteId, KakaoPolyline[]>>>({});

  const [mapPickTarget, setMapPickTarget] = useState<MapPickTarget | null>(null);
  const [showCctv, setShowCctv] = useState(false);
  const [showStreetlight, setShowStreetlight] = useState(false);
  const [showEnt, setShowEnt] = useState(false);
  const [showConv, setShowConv] = useState(false);
  const [origin, setOrigin] = useState<LocationField>(emptyLocation);
  const [destination, setDestination] = useState<LocationField>(emptyLocation);
  const [originQuery, setOriginQuery] = useState('');
  const [destQuery, setDestQuery] = useState('');
  const [originSuggestions, setOriginSuggestions] = useState<PoiItem[]>([]);
  const [destSuggestions, setDestSuggestions] = useState<PoiItem[]>([]);
  const [activeSearchInput, setActiveSearchInput] = useState<'origin' | 'destination' | null>(null);
  const searchBlurTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingEnterRef = useRef<{ origin: string | null; destination: string | null }>({ origin: null, destination: null });
  const originQueryRef = useRef('');
  const destQueryRef = useRef('');
  // 현재 suggestions가 어떤 쿼리에 대한 결과인지 추적
  const originSuggestionsQueryRef = useRef('');
  const destSuggestionsQueryRef = useRef('');
  const [now, setNow] = useState(() => new Date());
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedRouteId, setSelectedRouteId] = useState<RouteId>('safe');
  const [routeApiResults, setRouteApiResults] = useState<ApiRouteResult[] | null>(null);
  const [routeFetchLoading, setRouteFetchLoading] = useState(false);
  const [routeFetchError, setRouteFetchError] = useState<string | null>(null);
  const [mapPointSafety, setMapPointSafety] = useState<MapPointSafety | null>(null);
  const [safetyLoading, setSafetyLoading] = useState(false);
  const [safetyError, setSafetyError] = useState<string | null>(null);

  const safetyFetchHandlerRef = useRef<(lat: number, lng: number) => void>(() => {});

  mapPickTargetRef.current = mapPickTarget;
  originQueryRef.current = originQuery;
  destQueryRef.current = destQuery;

  const buildPoiUrl = (q: string) => {
    const base = `${SAFETY_API_BASE}/api/search-poi?q=${encodeURIComponent(q)}&count=5`;
    const center = mapInstanceRef.current?.getCenter();
    if (center) {
      return `${base}&center_lat=${center.getLat()}&center_lng=${center.getLng()}`;
    }
    return base;
  };

  // 출발지 검색 debounce
  useEffect(() => {
    if (originQuery.trim().length < 2) { setOriginSuggestions([]); return; }
    const q = originQuery;
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(buildPoiUrl(q));
        if (!res.ok) return;
        const data = (await res.json()) as { results?: PoiItem[] };
        originSuggestionsQueryRef.current = q;
        setOriginSuggestions(data.results ?? []);
      } catch { setOriginSuggestions([]); }
    }, 50);
    return () => clearTimeout(timer);
  }, [originQuery]);

  // 도착지 검색 debounce
  useEffect(() => {
    if (destQuery.trim().length < 2) { setDestSuggestions([]); return; }
    const q = destQuery;
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(buildPoiUrl(q));
        if (!res.ok) return;
        const data = (await res.json()) as { results?: PoiItem[] };
        destSuggestionsQueryRef.current = q;
        setDestSuggestions(data.results ?? []);
      } catch { setDestSuggestions([]); }
    }, 50);
    return () => clearTimeout(timer);
  }, [destQuery]);

  const handleSearchFocus = (target: 'origin' | 'destination') => {
    if (searchBlurTimerRef.current) clearTimeout(searchBlurTimerRef.current);
    setActiveSearchInput(target);
  };

  const handleSearchBlur = () => {
    searchBlurTimerRef.current = setTimeout(() => setActiveSearchInput(null), 150);
  };

  showCctvRef.current = showCctv;
  showStreetlightRef.current = showStreetlight;
  showEntRef.current = showEnt;
  showConvRef.current = showConv;

  safetyFetchHandlerRef.current = (lat: number, lng: number) => {
    void (async () => {
      setSafetyLoading(true);
      setSafetyError(null);
      try {
        const params = new URLSearchParams({
          lat: String(lat),
          lng: String(lng),
        });
        const res = await fetch(`${SAFETY_API_BASE}/api/safety-score?${params}`);
        if (!res.ok) {
          throw new Error(`서버 응답 ${res.status}`);
        }
        const data = (await res.json()) as { score?: unknown; grade?: unknown; cctv_count?: unknown; light_count?: unknown; conv_count?: unknown; ent_count?: unknown };
        const score = Number(data.score);
        const grade = typeof data.grade === 'string' ? data.grade.trim() : '';
        if (!Number.isFinite(score) || !grade) {
          throw new Error('응답 형식이 올바르지 않습니다.');
        }
        setMapPointSafety({
          score, grade, lat, lng,
          cctv_count: Number(data.cctv_count ?? 0),
          light_count: Number(data.light_count ?? 0),
          conv_count: Number(data.conv_count ?? 0),
          ent_count: Number(data.ent_count ?? 0),
        });
      } catch (e) {
        setMapPointSafety(null);
        setSafetyError(e instanceof Error ? e.message : '안전 점수를 불러오지 못했습니다.');
      } finally {
        setSafetyLoading(false);
      }
    })();
  };

  const canSearch = hasLocationValue(origin) && hasLocationValue(destination);

  const routes = useMemo<RouteCardData[]>(() => {
    if (!routeApiResults?.length) return [];
    const order = (t: string) => (t === 'safe' ? 0 : t === 'normal' ? 1 : 2);
    return [...routeApiResults]
      .sort((a, b) => order(a.type) - order(b.type))
      .map((r) => ({
        id: r.type as RouteId,
        title: r.type === 'safe' ? '안전 경로' : '일반 경로',
        avg_score: r.avg_score,
        grade: r.grade,
        duration: r.duration,
        riskNote: riskNoteFromRoute(r),
      }));
  }, [routeApiResults]);

  const selectedRoute = routes.find((r) => r.id === selectedRouteId) ?? routes[0];

  const handleFindRoute = () => {
    if (!canSearch) return;
    void (async () => {
      setHasSearched(true);
      setRouteFetchLoading(true);
      setRouteFetchError(null);
      disposeRoutePolylines(routePolylinesRef);
      setRouteApiResults(null);
      try {
        const geocoder = geocoderRef.current;
        if (!geocoder) {
          throw new Error('지도가 아직 준비되지 않았습니다. 잠시 후 다시 시도하세요.');
        }
        const { lat: origin_lat, lng: origin_lng } = await resolveLatLng(geocoder, origin, originCoordRef);
        const { lat: dest_lat, lng: dest_lng } = await resolveLatLng(geocoder, destination, destCoordRef);

        const res = await fetch(`${SAFETY_API_BASE}/api/safe-route`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            origin_lat,
            origin_lng,
            dest_lat,
            dest_lng,
          }),
        });

        if (!res.ok) {
          const errText = await res.text();
          throw new Error(errText || `서버 오류 ${res.status}`);
        }

        const data = (await res.json()) as { routes?: ApiRouteResult[] };
        const list = data.routes;
        if (!list?.length) {
          throw new Error('경로 응답이 비어 있습니다.');
        }

        const kakaoMaps = window.kakao?.maps;
        const map = mapInstanceRef.current;
        if (!kakaoMaps || !map) {
          throw new Error('지도 객체를 찾을 수 없습니다.');
        }

        const nextPolylines: Partial<Record<RouteId, KakaoPolyline[]>> = {};
        for (const r of list) {
          const id = r.type as RouteId;
          if (id === 'normal') {
            nextPolylines[id] = buildNormalRouteBluePolylines(kakaoMaps, r.points);
          } else {
            nextPolylines[id] = buildPolylinesFromSegments(kakaoMaps, r.points, r.segments);
          }
        }
        routePolylinesRef.current = nextPolylines;

        const hasSafe = list.some((r) => r.type === 'safe');
        const initialId = (hasSafe ? 'safe' : (list[0]!.type as RouteId)) as RouteId;
        setRouteApiResults(list);
        setSelectedRouteId(initialId);
        showAllRoutePolylinesOnMap(map, routePolylinesRef);
        fitMapToRoutePoints(map, kakaoMaps, list);
      } catch (e) {
        disposeRoutePolylines(routePolylinesRef);
        setRouteApiResults(null);
        setRouteFetchError(e instanceof Error ? e.message : '경로를 찾지 못했습니다.');
      } finally {
        setRouteFetchLoading(false);
      }
    })();
  };

  const clearOrigin = () => {
    setOrigin(emptyLocation());
    setOriginQuery('');
    setOriginSuggestions([]);
    originCoordRef.current = null;
    originMarkerRef.current?.setMap(null);
    originMarkerRef.current = null;
    setMapPickTarget((prev) => (prev === 'origin' ? null : prev));
    setHasSearched(false);
    disposeRoutePolylines(routePolylinesRef);
    setRouteApiResults(null);
    setRouteFetchError(null);
  };

  const clearDestination = () => {
    setDestination(emptyLocation());
    setDestQuery('');
    setDestSuggestions([]);
    destCoordRef.current = null;
    destMarkerRef.current?.setMap(null);
    destMarkerRef.current = null;
    setMapPickTarget((prev) => (prev === 'destination' ? null : prev));
    setHasSearched(false);
    disposeRoutePolylines(routePolylinesRef);
    setRouteApiResults(null);
    setRouteFetchError(null);
  };

  const handleSearchEnter = (target: 'origin' | 'destination', query: string) => {
    const q = query.trim();
    if (!q) return;
    const suggestions = target === 'origin' ? originSuggestions : destSuggestions;
    const suggestionsQuery = target === 'origin' ? originSuggestionsQueryRef.current : destSuggestionsQueryRef.current;
    // suggestions가 현재 입력과 동일한 쿼리의 결과일 때만 즉시 선택
    if (suggestions.length > 0 && suggestionsQuery.trim() === q) {
      pendingEnterRef.current[target] = null;
      handleSelectPoi(target, suggestions[0]!);
    } else {
      // stale 결과이거나 아직 없음 → 최신 결과 올 때까지 대기
      pendingEnterRef.current[target] = q;
    }
  };

  const handleSelectPoiRef = useRef<(target: 'origin' | 'destination', poi: PoiItem) => void>(() => {});

  const handleSelectPoi = (target: 'origin' | 'destination', poi: PoiItem) => {
    const loc: LocationField = { placeName: poi.name, address: poi.address };
    const coord = { lat: poi.lat, lng: poi.lng };
    const map = mapInstanceRef.current;
    const kakaoMaps = window.kakao?.maps;

    if (target === 'origin') {
      setOrigin(loc);
      setOriginQuery(poi.name);
      setOriginSuggestions([]);
      originCoordRef.current = coord;
      if (map && kakaoMaps) {
        const pos = new kakaoMaps.LatLng(poi.lat, poi.lng);
        originMarkerRef.current?.setMap(null);
        originMarkerRef.current = new kakaoMaps.Marker({ position: pos, map });
      }
    } else {
      setDestination(loc);
      setDestQuery(poi.name);
      setDestSuggestions([]);
      destCoordRef.current = coord;
      if (map && kakaoMaps) {
        const pos = new kakaoMaps.LatLng(poi.lat, poi.lng);
        destMarkerRef.current?.setMap(null);
        destMarkerRef.current = new kakaoMaps.Marker({ position: pos, map });
      }
    }
  };
  handleSelectPoiRef.current = handleSelectPoi;

  // 출발지 suggestions 도착 시 pending enter 처리
  useEffect(() => {
    if (originSuggestions.length === 0) return;
    const pending = pendingEnterRef.current.origin;
    if (!pending) return;
    // 방금 도착한 suggestions가 Enter 칠 때의 쿼리와 같을 때만 선택
    if (originSuggestionsQueryRef.current.trim() !== pending) return;
    pendingEnterRef.current.origin = null;
    handleSelectPoiRef.current('origin', originSuggestions[0]!);
  }, [originSuggestions]);

  // 도착지 suggestions 도착 시 pending enter 처리
  useEffect(() => {
    if (destSuggestions.length === 0) return;
    const pending = pendingEnterRef.current.destination;
    if (!pending) return;
    // 방금 도착한 suggestions가 Enter 칠 때의 쿼리와 같을 때만 선택
    if (destSuggestionsQueryRef.current.trim() !== pending) return;
    pendingEnterRef.current.destination = null;
    handleSelectPoiRef.current('destination', destSuggestions[0]!);
  }, [destSuggestions]);

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    const el = mapContainerRef.current;
    if (!el) return;

    let cancelled = false;

    void (async () => {
      try {
        await loadKakaoSdk();
      } catch (e) {
        if (!cancelled) {
          setSafetyError(e instanceof Error ? e.message : '카카오맵 SDK 로드에 실패했습니다.');
        }
        return;
      }

      const kakao = window.kakao;
      if (cancelled || !kakao?.maps || !mapContainerRef.current) return;

      kakao.maps.load(() => {
        if (cancelled || !mapContainerRef.current) {
          return;
        }

        const map = new kakao.maps.Map(mapContainerRef.current, {
          center: new kakao.maps.LatLng(SILLIM_STATION.lat, SILLIM_STATION.lng),
          level: MAP_ZOOM_LEVEL,
        });
        mapInstanceRef.current = map;

        const geocoder = new kakao.maps.services.Geocoder();
        geocoderRef.current = geocoder;

        const originImage = new kakao.maps.MarkerImage(
          pinSvgDataUrl('#2563eb'),
          new kakao.maps.Size(PIN_W, PIN_H),
          { offset: new kakao.maps.Point(PIN_W / 2, PIN_H) }
        );
        const destImage = new kakao.maps.MarkerImage(
          pinSvgDataUrl('#ef4444'),
          new kakao.maps.Size(PIN_W, PIN_H),
          { offset: new kakao.maps.Point(PIN_W / 2, PIN_H) }
        );

        const handleMapClick = (mouseEvent: KakaoMouseEvent) => {
          const latlng = mouseEvent.latLng;
          const lat = latlng.getLat();
          const lng = latlng.getLng();

          safetyFetchHandlerRef.current(lat, lng);

          const target = mapPickTargetRef.current;
          if (!target) return;

          geocoder.coord2Address(lng, lat, (result, status) => {
            if (cancelled) return;
            if (status !== kakao.maps.services.Status.OK || !result?.length) {
              return;
            }

            const loc = locationFromGeocodeResult(result[0]);

            if (target === 'origin') {
              setOrigin(loc);
              setOriginQuery(formatLocationLabel(loc));
              setOriginSuggestions([]);
              originCoordRef.current = { lat, lng };
              originMarkerRef.current?.setMap(null);
              const marker = new kakao.maps.Marker({
                position: latlng,
                map,
                image: originImage,
              });
              originMarkerRef.current = marker;
            } else {
              setDestination(loc);
              setDestQuery(formatLocationLabel(loc));
              setDestSuggestions([]);
              destCoordRef.current = { lat, lng };
              destMarkerRef.current?.setMap(null);
              const marker = new kakao.maps.Marker({
                position: latlng,
                map,
                image: destImage,
              });
              destMarkerRef.current = marker;
            }

            setMapPickTarget(null);
          });
        };

        kakao.maps.event.addListener(map, 'click', handleMapClick);

        // CCTV·가로등·유흥업소: 프론트 정적 JSON + 이미지 마커 (`public/data/map-points.json`, `public/markers/*.svg`)
        const base = process.env.PUBLIC_URL || '';
        const cctvIcon = new kakao.maps.MarkerImage(
          `${base}/markers/cctv-dot.svg`,
          new kakao.maps.Size(MAP_DOT_SIZE, MAP_DOT_SIZE),
          { offset: new kakao.maps.Point(MAP_DOT_SIZE / 2, MAP_DOT_SIZE / 2) }
        );
        const lightIcon = new kakao.maps.MarkerImage(
          `${base}/markers/streetlight-dot.svg`,
          new kakao.maps.Size(MAP_DOT_SIZE, MAP_DOT_SIZE),
          { offset: new kakao.maps.Point(MAP_DOT_SIZE / 2, MAP_DOT_SIZE / 2) }
        );
        const entIcon = new kakao.maps.MarkerImage(
          `${base}/markers/entertainment-dot.svg`,
          new kakao.maps.Size(MAP_DOT_SIZE, MAP_DOT_SIZE),
          { offset: new kakao.maps.Point(MAP_DOT_SIZE / 2, MAP_DOT_SIZE / 2) }
        );
        const convIcon = new kakao.maps.MarkerImage(
          `${base}/markers/conv-dot.svg`,
          new kakao.maps.Size(MAP_DOT_SIZE, MAP_DOT_SIZE),
          { offset: new kakao.maps.Point(MAP_DOT_SIZE / 2, MAP_DOT_SIZE / 2) }
        );

        void (async () => {
          try {
            const res = await fetch(`${base}/data/map-points.json`);
            if (!res.ok) return;
            if (cancelled) return;
            const data = (await res.json()) as {
              cctv: { lat: number; lng: number }[];
              streetlight: { lat: number; lng: number }[];
              entertainment: { lat: number; lng: number }[];
              convenience: { lat: number; lng: number }[];
            };

            const ClustererCtor = kakao.maps.MarkerClusterer;
            if (!ClustererCtor) return;

            const cctvMarkers = data.cctv.map(
              (pt) =>
                new kakao.maps.Marker({
                  position: new kakao.maps.LatLng(pt.lat, pt.lng),
                  image: cctvIcon,
                })
            );
            cctvMarkersRef.current = cctvMarkers;

            const lightMarkers = data.streetlight.map(
              (pt) =>
                new kakao.maps.Marker({
                  position: new kakao.maps.LatLng(pt.lat, pt.lng),
                  image: lightIcon,
                })
            );
            lightMarkersRef.current = lightMarkers;

            const entMarkers = (data.entertainment ?? []).map(
              (pt) =>
                new kakao.maps.Marker({
                  position: new kakao.maps.LatLng(pt.lat, pt.lng),
                  image: entIcon,
                })
            );
            entMarkersRef.current = entMarkers;

            const convMarkers = (data.convenience ?? []).map(
              (pt) =>
                new kakao.maps.Marker({
                  position: new kakao.maps.LatLng(pt.lat, pt.lng),
                  image: convIcon,
                })
            );
            convMarkersRef.current = convMarkers;

            const mapNow = mapInstanceRef.current;
            /** 1 = 모든 줌에서 클러스터 활성(레벨↑ 축소할 때만 켜지던 현상 제거) */
            const clusterMinLevel = 1;
            const cctvCluster = new ClustererCtor({
              map: null,
              averageCenter: true,
              minLevel: clusterMinLevel,
              calculator: CLUSTER_CALCULATOR,
              texts: clusterCountText,
              styles: clusterStylesFor('cctv'),
            });
            const lightCluster = new ClustererCtor({
              map: null,
              averageCenter: true,
              minLevel: clusterMinLevel,
              calculator: CLUSTER_CALCULATOR,
              texts: clusterCountText,
              styles: clusterStylesFor('streetlight'),
            });
            const entCluster = new ClustererCtor({
              map: null,
              averageCenter: true,
              minLevel: clusterMinLevel,
              calculator: CLUSTER_CALCULATOR,
              texts: clusterCountText,
              styles: clusterStylesFor('entertainment'),
            });
            const convCluster = new ClustererCtor({
              map: null,
              averageCenter: true,
              minLevel: clusterMinLevel,
              calculator: CLUSTER_CALCULATOR,
              texts: clusterCountText,
              styles: clusterStylesFor('convenience'),
            });
            cctvClustererRef.current = cctvCluster;
            lightClustererRef.current = lightCluster;
            entClustererRef.current = entCluster;
            convClustererRef.current = convCluster;

            if (mapNow) {
              if (showCctvRef.current) {
                cctvCluster.addMarkers(cctvMarkers);
                cctvCluster.setMap(mapNow);
              }
              if (showStreetlightRef.current) {
                lightCluster.addMarkers(lightMarkers);
                lightCluster.setMap(mapNow);
              }
              if (showEntRef.current) {
                entCluster.addMarkers(entMarkers);
                entCluster.setMap(mapNow);
              }
              if (showConvRef.current) {
                convCluster.addMarkers(convMarkers);
                convCluster.setMap(mapNow);
              }
            }
          } catch (_) {
            // 정적 포인트 로드 실패 시 무시
          }
        })();
      });
    })();

    return () => {
      cancelled = true;
      disposeRoutePolylines(routePolylinesRef);
      geocoderRef.current = null;
      mapInstanceRef.current = null;
      originMarkerRef.current = null;
      destMarkerRef.current = null;
      cctvClustererRef.current?.setMap(null);
      lightClustererRef.current?.setMap(null);
      entClustererRef.current?.setMap(null);
      convClustererRef.current?.setMap(null);
      cctvClustererRef.current = null;
      lightClustererRef.current = null;
      entClustererRef.current = null;
      convClustererRef.current = null;
      if (el) {
        el.innerHTML = '';
      }
    };
  }, []);

  const panMap = (dx: number, dy: number) => {
    mapInstanceRef.current?.panBy(dx, dy);
  };

  const toggleCctv = () => {
    const next = !showCctv;
    setShowCctv(next);
    if (next) {
      cctvClustererRef.current?.addMarkers(cctvMarkersRef.current);
      cctvClustererRef.current?.setMap(mapInstanceRef.current);
    } else {
      cctvMarkersRef.current.forEach((m) => m.setMap(null));
      cctvClustererRef.current?.clear();
    }
  };

  const toggleStreetlight = () => {
    const next = !showStreetlight;
    setShowStreetlight(next);
    if (next) {
      lightClustererRef.current?.addMarkers(lightMarkersRef.current);
      lightClustererRef.current?.setMap(mapInstanceRef.current);
    } else {
      lightMarkersRef.current.forEach((m) => m.setMap(null));
      lightClustererRef.current?.clear();
    }
  };

  const toggleEnt = () => {
    const next = !showEnt;
    setShowEnt(next);
    if (next) {
      entClustererRef.current?.addMarkers(entMarkersRef.current);
      entClustererRef.current?.setMap(mapInstanceRef.current);
    } else {
      entMarkersRef.current.forEach((m) => m.setMap(null));
      entClustererRef.current?.clear();
    }
  };

  const toggleConv = () => {
    const next = !showConv;
    setShowConv(next);
    if (next) {
      convClustererRef.current?.addMarkers(convMarkersRef.current);
      convClustererRef.current?.setMap(mapInstanceRef.current);
    } else {
      convMarkersRef.current.forEach((m) => m.setMap(null));
      convClustererRef.current?.clear();
    }
  };

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <header className={styles.brandBlock}>
          <div className={styles.logoMark} aria-hidden />
          <div>
            <h1 className={styles.appName}>보통의하루</h1>
            <p className={styles.appTagline}>안심 귀갓길 내비게이터</p>
          </div>
        </header>

        <div className={styles.form}>
          <div className={styles.fieldBlock} role="group" aria-labelledby="origin-label">
            <div className={styles.label} id="origin-label">
              출발지
            </div>
            <div className={styles.inputRow}>
              <div
                className={`${styles.locationColumn} ${hasLocationValue(origin) ? styles.locationColumnHasClear : ''}`}
              >
                {hasLocationValue(origin) && (
                  <button
                    type="button"
                    className={styles.locationClear}
                    onClick={(e) => {
                      e.stopPropagation();
                      clearOrigin();
                    }}
                    aria-label="출발지 지우기"
                  >
                    ×
                  </button>
                )}
                <div className={styles.inputWrap}>
                  <input
                    id="origin-search"
                    aria-label="출발지 검색"
                    className={`${styles.input} ${styles.inputPlace} ${
                      mapPickTarget === 'origin' ? styles.inputActive : ''
                    }`}
                    value={originQuery}
                    onChange={(e) => { setOriginQuery(e.target.value); setMapPickTarget(null); }}
                    onFocus={() => { setMapPickTarget('origin'); handleSearchFocus('origin'); }}
                    onBlur={handleSearchBlur}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSearchEnter('origin', originQuery); }}
                    placeholder="장소, 건물명, 주소로 검색"
                    autoComplete="off"
                  />
                  {activeSearchInput === 'origin' && originSuggestions.length > 0 && (
                    <ul className={styles.suggestionList}>
                      {originSuggestions.map((poi, i) => (
                        <li
                          key={i}
                          className={styles.suggestionItem}
                          onMouseDown={() => handleSelectPoi('origin', poi)}
                        >
                          <span className={styles.suggestionName}>{poi.name}</span>
                          <span className={styles.suggestionAddr}>{poi.address}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
              <span className={styles.fieldHint}>지도를 클릭해서 설정하세요</span>
            </div>
          </div>

          <div className={styles.fieldBlock} role="group" aria-labelledby="destination-label">
            <div className={styles.label} id="destination-label">
              도착지
            </div>
            <div className={styles.inputRow}>
              <div
                className={`${styles.locationColumn} ${
                  hasLocationValue(destination) ? styles.locationColumnHasClear : ''
                }`}
              >
                {hasLocationValue(destination) && (
                  <button
                    type="button"
                    className={styles.locationClear}
                    onClick={(e) => {
                      e.stopPropagation();
                      clearDestination();
                    }}
                    aria-label="도착지 지우기"
                  >
                    ×
                  </button>
                )}
                <div className={styles.inputWrap}>
                  <input
                    id="destination-search"
                    aria-label="도착지 검색"
                    className={`${styles.input} ${styles.inputPlace} ${
                      mapPickTarget === 'destination' ? styles.inputActive : ''
                    }`}
                    value={destQuery}
                    onChange={(e) => { setDestQuery(e.target.value); setMapPickTarget(null); }}
                    onFocus={() => { setMapPickTarget('destination'); handleSearchFocus('destination'); }}
                    onBlur={handleSearchBlur}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSearchEnter('destination', destQuery); }}
                    placeholder="장소, 건물명, 주소로 검색"
                    autoComplete="off"
                  />
                  {activeSearchInput === 'destination' && destSuggestions.length > 0 && (
                    <ul className={styles.suggestionList}>
                      {destSuggestions.map((poi, i) => (
                        <li
                          key={i}
                          className={styles.suggestionItem}
                          onMouseDown={() => handleSelectPoi('destination', poi)}
                        >
                          <span className={styles.suggestionName}>{poi.name}</span>
                          <span className={styles.suggestionAddr}>{poi.address}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
              <span className={styles.fieldHint}>지도를 클릭해서 설정하세요</span>
            </div>
          </div>

          <button
            type="button"
            className={styles.primaryButton}
            onClick={handleFindRoute}
            disabled={!canSearch || routeFetchLoading}
          >
            {routeFetchLoading ? '경로 찾는 중…' : '안전 경로 찾기'}
          </button>
        </div>

        <section className={styles.safetyPanel} aria-live="polite" aria-label="지도 클릭 지점 안전도">
          <div className={styles.safetyPanelTitle}>지도 클릭 지점 안전도</div>
          {safetyLoading && <div className={styles.safetyPanelMuted}>불러오는 중…</div>}
          {!safetyLoading && safetyError && <div className={styles.safetyPanelError}>{safetyError}</div>}
          {!safetyLoading && !safetyError && mapPointSafety && (
            <div className={styles.safetyPanelBody}>
              <div className={styles.safetyScoreRow}>
                <span className={styles.safetyScoreLabel}>점수</span>
                <span
                  className={`${styles.safetyScoreValue} ${
                    styles[`safetyGrade_${safetyGradeVariant(mapPointSafety.grade)}`]
                  }`}
                >
                  {mapPointSafety.score}점
                </span>
              </div>
              <div className={styles.safetyGradeRow}>
                <span className={styles.safetyGradeLabel}>등급</span>
                <span
                  className={`${styles.safetyGradeBadge} ${
                    styles[`safetyGrade_${safetyGradeVariant(mapPointSafety.grade)}`]
                  }`}
                >
                  {mapPointSafety.grade}
                </span>
              </div>
              <div className={styles.safetyDetailRow}>
                <span>CCTV</span><span>{mapPointSafety.cctv_count}대</span>
              </div>
              <div className={styles.safetyDetailRow}>
                <span>가로등</span><span>{mapPointSafety.light_count}개</span>
              </div>
              <div className={styles.safetyDetailRow}>
                <span>편의점</span><span>{mapPointSafety.conv_count}개</span>
              </div>
              <div className={styles.safetyDetailRow}>
                <span>유흥업소</span><span>{mapPointSafety.ent_count}개</span>
              </div>
              <div className={styles.safetyCoords}>
                {mapPointSafety.lat.toFixed(5)}, {mapPointSafety.lng.toFixed(5)}
              </div>
            </div>
          )}
          {!safetyLoading && !safetyError && !mapPointSafety && (
            <div className={styles.safetyPanelMuted}>지도를 클릭하면 이 위치의 안전 점수를 불러옵니다.</div>
          )}
        </section>

        <section className={styles.routeSection} aria-label="경로 비교">
          {!hasSearched ? (
            <div className={styles.emptyState}>
              출발지와 도착지를 입력한 뒤
              <br />
              「안전 경로 찾기」를 눌러주세요.
            </div>
          ) : routeFetchLoading ? (
            <div className={styles.emptyState}>경로를 불러오는 중입니다…</div>
          ) : routeFetchError ? (
            <div className={styles.safetyPanelError}>{routeFetchError}</div>
          ) : routes.length === 0 ? (
            <div className={styles.emptyState}>표시할 경로가 없습니다.</div>
          ) : (
            <>
              <div className={styles.routeCards}>
                {routes.map((r) => {
                  const selected = r.id === selectedRouteId;
                  const band = scoreBandClass(r.avg_score);
                  return (
                    <button
                      key={r.id}
                      type="button"
                      className={`${styles.routeCard} ${selected ? styles.routeCardSelected : ''}`}
                      onClick={() => setSelectedRouteId(r.id)}
                      aria-pressed={selected}
                    >
                      <div className={styles.routeCardHeader}>
                        <span className={styles.routeCardTitle}>{r.title}</span>
                        <span className={`${styles.routeScore} ${styles[`score_${band}`]}`}>
                          평균 {r.avg_score}점
                        </span>
                      </div>
                      <div className={styles.routeCardMeta}>
                        <span className={styles.routeGrade}>등급 {r.grade}</span>
                        <span className={styles.routeTime}>소요 {r.duration}분</span>
                      </div>
                    </button>
                  );
                })}
              </div>

              {selectedRoute && (
                <div className={styles.riskPanel}>
                  <div className={styles.riskPanelLabel}>선택 경로 · 위험 구간 안내</div>
                  <p className={styles.riskPanelText}>{selectedRoute.riskNote}</p>
                </div>
              )}
            </>
          )}
        </section>
      </aside>

      <main className={styles.mapArea}>
        <div className={styles.topRightClock} aria-label="현재 시각">
          <span className={styles.clockIcon} aria-hidden>
            {isNight(now) ? '🌙' : '☀️'}
          </span>
          <span className={styles.clockText}>{formatKoreanTime(now)}</span>
        </div>

        <div className={styles.mapShell}>
          <div ref={mapContainerRef} className={styles.mapCanvas} aria-label="카카오맵" />
          <div className={styles.layerTogglePanel}>
            <button
              type="button"
              className={`${styles.layerToggleBtn} ${showCctv ? styles.layerToggleBtnCctv : styles.layerToggleBtnOff}`}
              onClick={toggleCctv}
              aria-pressed={showCctv}
            >
              📷 CCTV
            </button>
            <button
              type="button"
              className={`${styles.layerToggleBtn} ${showStreetlight ? styles.layerToggleBtnLight : styles.layerToggleBtnOff}`}
              onClick={toggleStreetlight}
              aria-pressed={showStreetlight}
            >
              💡 가로등
            </button>
            <button
              type="button"
              className={`${styles.layerToggleBtn} ${showEnt ? styles.layerToggleBtnEnt : styles.layerToggleBtnOff}`}
              onClick={toggleEnt}
              aria-pressed={showEnt}
            >
              🍺 유흥업소
            </button>
            <button
              type="button"
              className={`${styles.layerToggleBtn} ${showConv ? styles.layerToggleBtnConv : styles.layerToggleBtnOff}`}
              onClick={toggleConv}
              aria-pressed={showConv}
            >
              🏪 편의점
            </button>
          </div>
          <div className={styles.mapOverlay} aria-hidden>
            <div className={styles.mapPlaceholderInner}>
              <div className={styles.mapPlaceholderTitle}>카카오맵</div>
              <div className={styles.mapPlaceholderSubtitle}>
                {mapPickTarget === 'origin' && '출발지: 지도에서 위치를 선택하세요'}
                {mapPickTarget === 'destination' && '도착지: 지도에서 위치를 선택하세요'}
                {!mapPickTarget &&
                  (hasLocationValue(origin) && hasLocationValue(destination)
                    ? `${formatLocationLabel(origin)} → ${formatLocationLabel(destination)}`
                    : '출발지 · 도착지를 입력하거나 지도에서 선택하세요')}
              </div>
            </div>
          </div>

          <div className={styles.mapPanPad} role="group" aria-label="지도 이동">
            <span className={styles.mapPanCell} aria-hidden />
            <button
              type="button"
              className={styles.mapPanBtn}
              onClick={() => panMap(0, -MAP_PAN_STEP_PX)}
              aria-label="지도 위로 이동"
            >
              ↑
            </button>
            <span className={styles.mapPanCell} aria-hidden />
            <button
              type="button"
              className={styles.mapPanBtn}
              onClick={() => panMap(-MAP_PAN_STEP_PX, 0)}
              aria-label="지도 왼쪽으로 이동"
            >
              ←
            </button>
            <span className={styles.mapPanCell} aria-hidden />
            <button
              type="button"
              className={styles.mapPanBtn}
              onClick={() => panMap(MAP_PAN_STEP_PX, 0)}
              aria-label="지도 오른쪽으로 이동"
            >
              →
            </button>
            <span className={styles.mapPanCell} aria-hidden />
            <button
              type="button"
              className={styles.mapPanBtn}
              onClick={() => panMap(0, MAP_PAN_STEP_PX)}
              aria-label="지도 아래로 이동"
            >
              ↓
            </button>
            <span className={styles.mapPanCell} aria-hidden />
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;

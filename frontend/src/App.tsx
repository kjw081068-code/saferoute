import React, { useEffect, useMemo, useRef, useState } from 'react';
import styles from './App.module.css';

const SILLIM_STATION = { lat: 37.4846, lng: 126.9294 };
const MAP_ZOOM_LEVEL = 4;
/** `panBy` 한 번에 이동할 픽셀 (동네 줌 기준) */
const MAP_PAN_STEP_PX = 120;

const PIN_W = 30;
const PIN_H = 42;

function pinSvgDataUrl(fill: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${PIN_W}" height="${PIN_H}" viewBox="0 0 30 42"><path fill="${fill}" stroke="rgba(0,0,0,0.22)" stroke-width="1" d="M15 2C8.4 2 3 7.2 3 13.5 3 19.5 15 40 15 40s12-20.5 12-26.5C27 7.2 21.6 2 15 2z"/><circle cx="15" cy="14" r="3.5" fill="#fff"/></svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

type RouteId = 'safe' | 'normal';

type MapPickTarget = 'origin' | 'destination';

type RouteMock = {
  id: RouteId;
  title: string;
  score: number;
  gradeLabel: string;
  durationMin: number;
  riskNote: string;
};

/** 출발/도착: 장소명(건물·역·가게 등) 우선, 주소는 하단 칸 */
type LocationField = {
  placeName: string;
  address: string;
};

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

const SAFETY_API_BASE = 'http://localhost:8000';

type MapPointSafety = {
  score: number;
  grade: string;
  lat: number;
  lng: number;
};

/** 백엔드 grade → UI 색상 구분 */
function safetyGradeVariant(grade: string): 'safe' | 'caution' | 'danger' {
  const g = grade.trim().toLowerCase();
  if (grade.includes('위험') || g === 'danger' || g === 'high_risk') return 'danger';
  if (grade.includes('보통') || g === 'normal' || g === 'medium' || g === 'caution') return 'caution';
  return 'safe';
}

function App() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<KakaoMap | null>(null);
  const originMarkerRef = useRef<KakaoMarker | null>(null);
  const destMarkerRef = useRef<KakaoMarker | null>(null);
  const mapPickTargetRef = useRef<MapPickTarget | null>(null);

  const [mapPickTarget, setMapPickTarget] = useState<MapPickTarget | null>(null);
  const [origin, setOrigin] = useState<LocationField>(emptyLocation);
  const [destination, setDestination] = useState<LocationField>(emptyLocation);
  const [now, setNow] = useState(() => new Date());
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedRouteId, setSelectedRouteId] = useState<RouteId>('safe');
  const [mapPointSafety, setMapPointSafety] = useState<MapPointSafety | null>(null);
  const [safetyLoading, setSafetyLoading] = useState(false);
  const [safetyError, setSafetyError] = useState<string | null>(null);

  const safetyFetchHandlerRef = useRef<(lat: number, lng: number) => void>(() => {});

  mapPickTargetRef.current = mapPickTarget;

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
        const data = (await res.json()) as { score?: unknown; grade?: unknown };
        const score = Number(data.score);
        const grade = typeof data.grade === 'string' ? data.grade.trim() : '';
        if (!Number.isFinite(score) || !grade) {
          throw new Error('응답 형식이 올바르지 않습니다.');
        }
        setMapPointSafety({ score, grade, lat, lng });
      } catch (e) {
        setMapPointSafety(null);
        setSafetyError(e instanceof Error ? e.message : '안전 점수를 불러오지 못했습니다.');
      } finally {
        setSafetyLoading(false);
      }
    })();
  };

  const canSearch = hasLocationValue(origin) && hasLocationValue(destination);

  const routes = useMemo<RouteMock[]>(
    () => [
      {
        id: 'safe',
        title: '안전 경로',
        score: 78,
        gradeLabel: '안전',
        durationMin: 18,
        riskNote:
          '대로 위주로 이동하며 주요 구간은 가로등이 확보되어 있습니다. 혼잡 시간대에는 유동인구가 많은 쪽으로 잠시 우회하는 것을 권장합니다.',
      },
      {
        id: 'normal',
        title: '일반 경로',
        score: 41,
        gradeLabel: '위험',
        durationMin: 13,
        riskNote: '신림로 구간은 가로등이 부족해 주의가 필요합니다.',
      },
    ],
    []
  );

  const selectedRoute = routes.find((r) => r.id === selectedRouteId) ?? routes[0];

  const handleFindRoute = () => {
    if (!canSearch) return;
    setHasSearched(true);
    setSelectedRouteId('safe');
  };

  const clearOrigin = () => {
    setOrigin(emptyLocation());
    originMarkerRef.current?.setMap(null);
    originMarkerRef.current = null;
    setMapPickTarget((prev) => (prev === 'origin' ? null : prev));
    setHasSearched(false);
  };

  const clearDestination = () => {
    setDestination(emptyLocation());
    destMarkerRef.current?.setMap(null);
    destMarkerRef.current = null;
    setMapPickTarget((prev) => (prev === 'destination' ? null : prev));
    setHasSearched(false);
  };

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    const el = mapContainerRef.current;
    const kakao = window.kakao;
    if (!el || !kakao?.maps) {
      return;
    }

    let cancelled = false;

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
            originMarkerRef.current?.setMap(null);
            const marker = new kakao.maps.Marker({
              position: latlng,
              map,
              image: originImage,
            });
            originMarkerRef.current = marker;
          } else {
            setDestination(loc);
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
    });

    return () => {
      cancelled = true;
      mapInstanceRef.current = null;
      originMarkerRef.current = null;
      destMarkerRef.current = null;
      if (el) {
        el.innerHTML = '';
      }
    };
  }, []);

  const panMap = (dx: number, dy: number) => {
    mapInstanceRef.current?.panBy(dx, dy);
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
                    id="origin-place"
                    aria-label="출발지 장소명"
                    className={`${styles.input} ${styles.inputPlace} ${
                      mapPickTarget === 'origin' ? styles.inputActive : ''
                    }`}
                    value={origin.placeName}
                    onChange={(e) => setOrigin((o) => ({ ...o, placeName: e.target.value }))}
                    onClick={() => setMapPickTarget('origin')}
                    onFocus={() => setMapPickTarget('origin')}
                    placeholder="건물·역·가게 이름 (있는 경우)"
                    autoComplete="off"
                  />
                </div>
                <div className={styles.addressFieldLabel}>주소</div>
                <div className={styles.inputWrap}>
                  <input
                    id="origin-address"
                    aria-label="출발지 주소"
                    className={`${styles.input} ${styles.inputAddress} ${
                      mapPickTarget === 'origin' ? styles.inputActive : ''
                    }`}
                    value={origin.address}
                    onChange={(e) => setOrigin((o) => ({ ...o, address: e.target.value }))}
                    onClick={() => setMapPickTarget('origin')}
                    onFocus={() => setMapPickTarget('origin')}
                    placeholder="주소"
                    autoComplete="off"
                  />
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
                    id="destination-place"
                    aria-label="도착지 장소명"
                    className={`${styles.input} ${styles.inputPlace} ${
                      mapPickTarget === 'destination' ? styles.inputActive : ''
                    }`}
                    value={destination.placeName}
                    onChange={(e) => setDestination((o) => ({ ...o, placeName: e.target.value }))}
                    onClick={() => setMapPickTarget('destination')}
                    onFocus={() => setMapPickTarget('destination')}
                    placeholder="건물·역·가게 이름 (있는 경우)"
                    autoComplete="off"
                  />
                </div>
                <div className={styles.addressFieldLabel}>주소</div>
                <div className={styles.inputWrap}>
                  <input
                    id="destination-address"
                    aria-label="도착지 주소"
                    className={`${styles.input} ${styles.inputAddress} ${
                      mapPickTarget === 'destination' ? styles.inputActive : ''
                    }`}
                    value={destination.address}
                    onChange={(e) => setDestination((o) => ({ ...o, address: e.target.value }))}
                    onClick={() => setMapPickTarget('destination')}
                    onFocus={() => setMapPickTarget('destination')}
                    placeholder="주소"
                    autoComplete="off"
                  />
                </div>
              </div>
              <span className={styles.fieldHint}>지도를 클릭해서 설정하세요</span>
            </div>
          </div>

          <button
            type="button"
            className={styles.primaryButton}
            onClick={handleFindRoute}
            disabled={!canSearch}
          >
            안전 경로 찾기
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
          ) : (
            <>
              <div className={styles.routeCards}>
                {routes.map((r) => {
                  const selected = r.id === selectedRouteId;
                  const band = scoreBandClass(r.score);
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
                        <span className={`${styles.routeScore} ${styles[`score_${band}`]}`}>{r.score}점</span>
                      </div>
                      <div className={styles.routeCardMeta}>
                        <span className={styles.routeGrade}>등급 {r.gradeLabel}</span>
                        <span className={styles.routeTime}>소요 {r.durationMin}분</span>
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className={styles.riskPanel}>
                <div className={styles.riskPanelLabel}>선택 경로 · 위험 구간 안내</div>
                <p className={styles.riskPanelText}>{selectedRoute.riskNote}</p>
              </div>
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

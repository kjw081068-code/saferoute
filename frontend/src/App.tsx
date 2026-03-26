import React, { useEffect, useMemo, useState } from 'react';
import styles from './App.module.css';
import mockMap from './assets/mock-map.svg';

type SafetyLevel = 'danger' | 'caution' | 'safe';

type RouteResult = {
  id: 'safe' | 'normal';
  title: string;
  summary: string;
  distanceKm: number;
  durationMin: number;
  notes: string[];
};

function clampScore(score: number) {
  return Math.max(0, Math.min(100, Math.round(score)));
}

function scoreToLevel(score: number): SafetyLevel {
  if (score <= 39) return 'danger';
  if (score <= 69) return 'caution';
  return 'safe';
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

function App() {
  const [origin, setOrigin] = useState('신림역 4번 출구');
  const [destination, setDestination] = useState('서울대입구역 인근');
  const [now, setNow] = useState(() => new Date());
  const [hasSearched, setHasSearched] = useState(false);

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const mock = useMemo(() => {
    const safeScore = clampScore(82);
    const normalScore = clampScore(55);
    const routes: RouteResult[] = [
      {
        id: 'safe',
        title: '안전 경로',
        summary: '밝은 대로 위주, CCTV/유동인구 가정 반영',
        distanceKm: 2.7,
        durationMin: 36,
        notes: ['대로·가로등 구간 우선', '사람 많은 구간 우회', '취약구간 회피(가정)'],
      },
      {
        id: 'normal',
        title: '일반 경로',
        summary: '최단거리 위주 (골목 포함 가능)',
        distanceKm: 2.1,
        durationMin: 28,
        notes: ['최단거리 중심', '골목/주택가 포함 가능(가정)'],
      },
    ];

    return {
      safeScore,
      normalScore,
      routes,
    };
  }, []);

  const activeScore = hasSearched ? mock.safeScore : 0;
  const activeLevel = scoreToLevel(activeScore);

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <div className={styles.brandRow}>
          <div className={styles.logoMark} aria-hidden />
          <div>
            <div className={styles.appName}>안심길</div>
            <div className={styles.appTagline}>신림동 야간 안전 귀가 경로</div>
          </div>
        </div>

        <div className={styles.form}>
          <label className={styles.label} htmlFor="origin">
            출발지
          </label>
          <input
            id="origin"
            className={styles.input}
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            placeholder="출발지를 입력하세요"
          />

          <label className={styles.label} htmlFor="destination">
            도착지
          </label>
          <input
            id="destination"
            className={styles.input}
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            placeholder="도착지를 입력하세요"
          />

          <button
            type="button"
            className={styles.primaryButton}
            onClick={() => setHasSearched(true)}
            disabled={!origin.trim() || !destination.trim()}
          >
            안전 경로 찾기
          </button>
        </div>

        <section className={styles.results}>
          <div className={styles.sectionHeaderRow}>
            <div className={styles.sectionTitle}>경로 결과</div>
            <div className={styles.badgeMuted}>{hasSearched ? 'mock' : '대기'}</div>
          </div>

          {!hasSearched ? (
            <div className={styles.emptyState}>
              출발지와 도착지를 입력한 뒤
              <br />
              “안전 경로 찾기”를 눌러주세요.
            </div>
          ) : (
            <div className={styles.routeCompare}>
              {mock.routes.map((r) => (
                <div
                  key={r.id}
                  className={`${styles.routeCard} ${r.id === 'safe' ? styles.routeCardSafe : styles.routeCardNormal}`}
                >
                  <div className={styles.routeTopRow}>
                    <div className={styles.routeTitle}>{r.title}</div>
                    <div className={styles.routeMeta}>
                      {r.distanceKm.toFixed(1)}km · {r.durationMin}분
                    </div>
                  </div>
                  <div className={styles.routeSummary}>{r.summary}</div>
                  <ul className={styles.routeNotes}>
                    {r.notes.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className={styles.scoreSection}>
          <div className={styles.sectionHeaderRow}>
            <div className={styles.sectionTitle}>안전 점수</div>
            <div className={styles.scoreValue}>
              <span className={`${styles.scoreNumber} ${styles[`score_${activeLevel}`]}`}>{activeScore}</span>
              <span className={styles.scoreUnit}>/ 100</span>
            </div>
          </div>

          <div className={styles.scoreBar} role="img" aria-label={`안전 점수 ${activeScore}점`}>
            <div
              className={`${styles.scoreFill} ${styles[`scoreFill_${activeLevel}`]}`}
              style={{ width: `${activeScore}%` }}
            />
          </div>
          <div className={styles.scoreLegend}>
            <span className={styles.legendDanger}>위험</span>
            <span className={styles.legendCaution}>보통</span>
            <span className={styles.legendSafe}>안전</span>
          </div>
        </section>
      </aside>

      <main className={styles.mapArea}>
        <div className={styles.topRightClock} aria-label="현재 시각">
          <span className={styles.clockIcon} aria-hidden>
            {isNight(now) ? '🌙' : '☀️'}
          </span>
          <span className={styles.clockText}>{formatKoreanTime(now)}</span>
        </div>

        <div className={styles.mapPlaceholder} role="img" aria-label="지도 영역 자리 표시자">
          <img className={styles.mapImage} src={mockMap} alt="" aria-hidden />
          <div className={styles.mapPlaceholderTitle}>지도 영역 (추후 카카오맵)</div>
          <div className={styles.mapPlaceholderSubtitle}>
            {origin.trim()} → {destination.trim()}
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;

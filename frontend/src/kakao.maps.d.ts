export {};

declare global {
  interface Window {
    kakao: KakaoGlobal;
  }

  interface KakaoMap {
    panBy(dx: number, dy: number): void;
  }

  interface KakaoLatLng {
    getLat(): number;
    getLng(): number;
  }

  interface KakaoMapOptions {
    center: KakaoLatLng;
    level: number;
  }

  interface KakaoMarker {
    setMap(map: KakaoMap | null): void;
  }

  interface KakaoMarkerClusterer {
    setMap(map: KakaoMap | null): void;
  }

  interface KakaoMarkerClustererOptions {
    map?: KakaoMap | null;
    averageCenter?: boolean;
    /**
     * 클러스터링이 동작하기 시작하는 최소 지도 레벨(카카오: 숫자가 클수록 축소).
     * 값이 크면 충분히 축소하기 전까지는 개별 마커에 가깝게 보일 수 있음. 1이면 모든 줌에서 묶음.
     */
    minLevel?: number;
    /** 클러스터 포함 개수 구간 경계 — 구간 수 = styles 길이 − 1 */
    calculator?: number[];
    /** calculator 구간마다 표시할 문자열(보통 개수). 배열 또는 (count) => string */
    texts?: ((count: number) => string) | string[];
    /** 클러스터 HTML 마커 스타일 — calculator 구간별로 적용 */
    styles?: Array<Record<string, string>>;
    markers?: KakaoMarker[];
  }

  interface KakaoMarkerOptions {
    position: KakaoLatLng;
    map?: KakaoMap;
    image?: KakaoMarkerImage;
  }

  interface KakaoMarkerImage {}

  interface KakaoSize {}

  interface KakaoPoint {}

  interface KakaoMouseEvent {
    latLng: KakaoLatLng;
  }

  interface Coord2AddressResult {
    address: { address_name: string };
    road_address?: {
      address_name: string;
      /** 건물명 (있을 때만) */
      building_name?: string | null;
    } | null;
  }
}

interface Geocoder {
  coord2Address(
    lng: number,
    lat: number,
    callback: (result: Coord2AddressResult[] | null, status: string) => void
  ): void;
}

interface KakaoGlobal {
  maps: {
    load(callback: () => void): void;
    LatLng: new (lat: number, lng: number) => KakaoLatLng;
    Map: new (container: HTMLElement, options: KakaoMapOptions) => KakaoMap;
    Marker: new (options: KakaoMarkerOptions) => KakaoMarker;
    MarkerClusterer: new (options: KakaoMarkerClustererOptions) => KakaoMarkerClusterer;
    MarkerImage: new (imageSrc: string, size: KakaoSize, options?: { offset?: KakaoPoint }) => KakaoMarkerImage;
    Size: new (width: number, height: number) => KakaoSize;
    Point: new (x: number, y: number) => KakaoPoint;
    event: {
      addListener(target: unknown, type: string, handler: (e: KakaoMouseEvent) => void): void;
      removeListener(target: unknown, type: string, handler: (e: KakaoMouseEvent) => void): void;
    };
    services: {
      Geocoder: new () => Geocoder;
      Status: { OK: string };
    };
  };
}

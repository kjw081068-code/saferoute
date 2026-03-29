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

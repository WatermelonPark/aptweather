/* aptweather service worker
   - HTML(navigation): network-first  → 배포 즉시 반영, 오프라인이면 캐시
   - 정적 자산: cache-first (+백그라운드 갱신)
   - 외부 도메인(GA·카카오 SDK)은 건드리지 않음
*/
const VERSION = 'v4'; // 리브랜딩(아공맵): manifest 이름 교체 반영. 옛 캐시를 버려야 새 매니페스트가 뜬다.
const CACHE = `aptweather-${VERSION}`;

const PRECACHE = [
  '/',
  '/404.html',
  '/burini-test/',
  '/app_icon.png',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-192.png',
  '/icons/maskable-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      // 일부 자원이 실패해도 설치가 깨지지 않도록 개별 처리
      .then((c) => Promise.all(PRECACHE.map((u) => c.add(u).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // GA·카카오 등은 통과

  // HTML 문서: network-first
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match('/')))
    );
    return;
  }

  // 정적 자산: cache-first + 백그라운드 갱신
  e.respondWith(
    caches.match(req).then((hit) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => hit);
      return hit || network;
    })
  );
});

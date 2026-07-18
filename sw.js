/* aptweather service worker
   - HTML(navigation): network-first  → 배포 즉시 반영, 오프라인이면 캐시
   - 정적 자산: cache-first (+백그라운드 갱신)
   - 외부 도메인(GA·카카오 SDK)은 건드리지 않음
*/
const VERSION = 'v6'; // data.js 분리(2026-07-19). 데이터가 인라인이던 옛 HTML 캐시를 반드시 버려야 한다.
const CACHE = `aptweather-${VERSION}`;

const PRECACHE = [
  '/',
  '/data.js',
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

  // data.js: HTML과 같은 데이터라 network-first (cache-first면 통계가 stale 된다)
  // 정적 자산 규칙보다 반드시 먼저 판정할 것.
  if (url.pathname === '/data.js') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

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

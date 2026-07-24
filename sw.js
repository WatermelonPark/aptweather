/* aptweather service worker
   - HTML(navigation): network-first  → 배포 즉시 반영, 오프라인이면 캐시
   - 정적 자산: cache-first (+백그라운드 갱신)
   - 외부 도메인(GA·카카오 SDK)은 건드리지 않음
*/
const VERSION = 'v20'; // 이메일/인스타/네이버 발행 채널 전면 제거 — 구독 폼·Buttondown·
                       // send_newsletter/send_instagram/make_naver_post 삭제, privacy 정리
const CACHE = `aptweather-${VERSION}`;

const PRECACHE = [
  '/',
  '/data-core.js',   // 홈이 실제로 읽는 것
  '/app.css',
  '/chart-4.4.1.umd.js',
  '/cycle/',
  '/404.html',
  '/burini-test/',
  '/investor-test/',
  '/redev-test/',
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

  // data.js·app.css: HTML과 한 몸이라 network-first.
  //  - data.js를 cache-first로 두면 통계가 stale 된다.
  //  - app.css는 원래 HTML 인라인이라 마크업과 원자적으로 배포됐다. 외부화 후
  //    cache-first로 두면 새 마크업 + 옛 CSS가 한 박자 공존해 색 토큰을 바꿀 때
  //    깨진 중간 상태가 보인다. 그 원자성을 유지한다.
  //  - chart-4.4.1.umd.js는 파일명에 버전이 박혀 있어 cache-first로 안전하다.
  // 정적 자산 규칙보다 반드시 먼저 판정할 것.
  if (url.pathname === '/data.js' || url.pathname === '/app.css'
      || url.pathname === '/data-core.js' || url.pathname === '/data-rest.json'
      || url.pathname === '/data-trend.json') {
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

/* aptweather service worker
   - HTML(navigation): network-first  → 배포 즉시 반영, 오프라인이면 캐시
   - 정적 자산: cache-first (+백그라운드 갱신)
   - 외부 도메인(GA·카카오 SDK)은 건드리지 않음
*/
// ⚠️ 올릴 때는 **현재 값을 읽어** +1 한다. 기억한 숫자를 박으면 그 사이 다른
// 세션이 올려둔 버전을 덮어 뒤로 돌아간다 — 2026-08-15에 v107을 v102로 되돌린
// 실사고가 그렇게 났다(sed로 패턴을 잡아 하드코딩 값으로 치환). 되돌아간 번호는
// 배포 이력을 못 읽게 만들고, 다음 사람이 이미 쓴 번호를 재사용하게 한다.
// 단조 증가는 test_sw_version_only_moves_forward가 지킨다.
const VERSION = 'v111'; // 홈 개선 3건 — 주간 지도·원자료 카드·결과 예시
const CACHE = `aptweather-${VERSION}`;

const PRECACHE = [
  '/',
  '/data-core.js',   // 홈이 실제로 읽는 것
  '/sido-geo.js',    // 홈 지도 모드 경계(기본 모드라 프리캐시)
  '/app.css',
  '/chart-4.4.1.umd.js',
  '/cycle/',
  '/404.html',
  '/burini-test/',
  '/investor-test/',
  '/redev-test/',
  '/favicon.svg',
  '/app_icon.png',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-192.png',
  '/icons/maskable-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      // 일부 자원이 실패해도 설치가 깨지지 않도록 개별 처리.
      // ⚠️ cache:'reload' — 기본 모드면 c.add()가 **브라우저 HTTP 캐시**를 탄다.
      //    GitHub Pages가 max-age=600을 주므로, 배포 직후 VERSION을 올려 설치되는
      //    회차가 옛 자산을 집어 새 캐시에 넣을 수 있다. 그러면 cache-first 자산은
      //    다음 VERSION 범프까지 스테일이 굳는다(2026-08-08 디자인 세션 제보).
      .then((c) => Promise.all(PRECACHE.map(
        (u) => c.add(new Request(u, { cache: 'reload' })).catch(() => null))))
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
  //  - sido-geo.js는 여기 넣지 않는다(2026-08-10 리뷰로 정정). 아래 정적 자산
  //    분기가 '캐시 즉시 응답 + 백그라운드 갱신'이라 재생성분은 다음 방문에
  //    따라온다 — 경계선이 한 방문 늦는 건 데이터 스테일과 달리 무해하고,
  //    network-first로 두면 파서 블로킹 스크립트가 매 방문 네트워크 왕복을 기다린다.
  if (url.pathname === '/data.js' || url.pathname === '/app.css'
      || url.pathname === '/data-core.js' || url.pathname === '/data-rest.json'
      || url.pathname === '/data-size.json'
      || url.pathname === '/data-trend.json' || url.pathname === '/data-sgg.json') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          // ⚠️ res.ok를 안 보면 404/5xx 본문(에러 HTML)이 그대로 캐시에 들어가
          //    정상 프리캐시본을 덮는다 — 그 뒤 오프라인이면 폴백이 쓰레기를 준다
          //    (2026-08-07 감사에서 격리 재현). 정적 분기는 원래 이걸 검사한다.
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
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
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
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

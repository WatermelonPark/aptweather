# -*- coding: utf-8 -*-
"""네이버 검색 모니터 — 타겟 키워드의 상위 글과 우리 노출을 본다.

왜 필요한가: 우리는 구글 쪽만 Search Console로 보고 있고 네이버는 깜깜하다.
그런데 유통 주력이 네이버 블로그다(이웃 189명). 어떤 글이 이미 그 자리를
차지하고 있는지 모르는 채로 쓰면 감으로 쓰는 것이다.

무엇을 알 수 있나:
  1. 타겟 키워드 상위 글의 제목·출처·날짜 → **경쟁 각도 파악**(가장 쓸모 있다)
  2. 우리 블로그/사이트가 결과에 잡히는가 → 색인 여부와 대략의 위치
  3. 주기적으로 돌리면 변화 추이

⚠️ 한계를 분명히 한다. 검색 API의 결과 순서는 API 자체 정렬(sim=정확도순,
date=최신순)이라 **통합검색 화면의 실제 순위와 다르다.** 그래서 "몇 위"를
단정하지 않고 'API 순번'이라고만 적는다. 순위를 정확히 보려면 사람이 직접
검색하는 수밖에 없다 — 그건 이 도구가 대신할 수 없다.

공식 API만 쓴다(스크래핑 없음). 무료 일 25,000회라 이 용도엔 넉넉하다
(1회 실행 = 키워드수 × 3).

준비 — 구 developers.naver.com이 아니라 **NAVER Cloud Platform API HUB**다.
2026-08-14 실측 기준으로 호스트·경로·헤더가 모두 구 방식과 다르다:
  ncloud.com → Application Services → NAVER API HUB → Application 등록
  (검색 API 선택) → Application Management → 인증 정보 → Client ID/Secret
  환경변수로 둔다(기존 도구들과 같은 방식):
    NAVER_CLIENT_ID=...  NAVER_CLIENT_SECRET=...

사용:
  python tools/naver_serp.py                    # 기본 키워드 세트
  python tools/naver_serp.py "대구 미분양" "부산 입주물량"
  python tools/naver_serp.py --json             # 기계가 읽을 형태로
"""
import datetime
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 우리 것으로 인정할 출처. 블로그 주소가 바뀌면 여기만 고친다.
OURS = ('agongmap.co.kr', 'blog.naver.com/startupbd')

# 2026-08-14 네이버 키워드도구 실측에서 검색량이 확인된 것 위주.
# 검색량 10 수준인 조합(경기입주물량 등)은 넣어도 배울 게 없어 뺐다.
DEFAULT_KEYWORDS = [
    '대구 미분양',          # 1,180 — 우리 주제 중 최대 시장
    '부산 미분양아파트',     # 3,340
    '서울 미분양',          # 240
    '아파트 공급',          # 390, 경쟁 중간 — 우리가 노릴 만한 유일한 헤드
    '서울 입주물량',        # 110
    '주간 아파트 시세',      # 70 — 우리 /weekly/가 겨냥하는 자리
    '집값 전망',            # 5,570 — 블로그 기획글 겨냥
    '전세가율',             # 1,240
]

# 카페를 넣는 이유: 부동산은 카페 글이 검색 상위를 자주 먹는다.
# 뉴스(/search/v1/news)도 신청돼 있으나 경쟁 상대가 아니라 소재원이라 뺐다.
CORPORA = [('blog', '블로그'), ('webkr', '웹문서'), ('cafearticle', '카페')]

# API HUB 게이트웨이. 확장자(.json)를 붙이면 404다 — 구 openapi.naver.com과
# 다른 지점이라 바꿀 때 주의(2026-08-14 실측).
API = 'https://naverapihub.apigw.ntruss.com/search/v1/%s'

# 회차 기록. 실행할 때마다 그 순간의 화면만 보고 끝나면 "지난주보다 나아졌나"에
# 답할 근거가 없다. 발행을 막 시작한 지금이 베이스라인을 잡을 유일한 시점이다.
#
# 자리를 tools/로 잡되 **git에는 올리지 않는다**(.gitignore).
#  - drafts/에 두지 않는 이유: 초안 정리에 함께 쓸려 나가기 쉽다.
#  - 그렇다고 추적하면 안 되는 이유: 이 파일에는 남의 블로그 제목과 상호가
#    쌓인다. 저장소가 공개라 그대로 노출된다 — 출처 표기 규칙과 같은 뿌리다
#    (2026-08-15 리뷰 지적). 우리가 보려고 모으는 경쟁 정보를 남의 이름째로
#    공개할 이유가 없다.
HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'serp-history.jsonl')


def hist_append(rec):
    rec = dict(rec, d=datetime.date.today().isoformat())
    with io.open(HIST, 'a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def hist_last(mode, key):
    """같은 질문의 직전 기록. 없으면 None — 첫 회차라는 뜻이다."""
    if not os.path.exists(HIST):
        return None
    last = None
    for line in io.open(HIST, encoding='utf-8'):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get('mode') == mode and r.get('key') == key:
            last = r
    return last


def _get(kind, query, display=10, sort='sim'):
    # strip 필수 — 콘솔에서 복사하면 앞뒤 공백·개행이 딸려오기 쉽고,
    # 네이버는 헤더 값에 공백이 있으면 그대로 인증 실패를 낸다.
    cid = os.environ.get('NAVER_CLIENT_ID', '').strip()
    sec = os.environ.get('NAVER_CLIENT_SECRET', '').strip()
    if not cid or not sec:
        raise SystemExit(
            'NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없다.\n'
            '  ncloud.com → NAVER API HUB → Application Management → 인증 정보\n'
            '  PowerShell:  $env:NAVER_CLIENT_ID="..."; $env:NAVER_CLIENT_SECRET="..."\n'
            '  bash:        export NAVER_CLIENT_ID=... NAVER_CLIENT_SECRET=...')
    url = (API % kind) + '?' + urllib.parse.urlencode(
        {'query': query, 'display': display, 'sort': sort})
    req = urllib.request.Request(url, headers={
        'X-NCP-APIGW-API-KEY-ID': cid, 'X-NCP-APIGW-API-KEY': sec})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        # 실패 원인은 본문 JSON에 들어온다. 이걸 버리면 "401"만 남아서
        # 키가 틀린 건지 경로가 틀린 건지 못 가른다(실제로 한 번 헤맸다).
        try:
            detail = e.read().decode('utf-8', 'replace')[:300]
        except Exception:
            detail = ''
        raise RuntimeError('HTTP %s %s' % (e.code, detail)) from None


def _clean(s):
    """API가 검색어에 <b> 태그를 박아 돌려준다. 사람이 읽을 형태로 되돌린다."""
    for a, b in (('<b>', ''), ('</b>', ''), ('&lt;', '<'), ('&gt;', '>'),
                 ('&amp;', '&'), ('&quot;', '"'), ('&#39;', "'")):
        s = s.replace(a, b)
    return s.strip()


def probe(keyword, display=10):
    """한 키워드를 블로그·웹문서·카페에서 조회하고 우리 것 여부를 표시한다."""
    out = {'keyword': keyword, 'hits': {}, 'ours': []}
    for kind, label in CORPORA:
        rows = []
        try:
            d = _get(kind, keyword, display=display)
        except SystemExit:
            raise
        except Exception as e:
            out.setdefault('errors', []).append('%s: %s' % (label, e))
            out['hits'][label] = rows
            continue
        for i, it in enumerate(d.get('items') or [], 1):
            link = it.get('link', '') + it.get('bloggerlink', '')
            row = {
                'n': i,
                'title': _clean(it.get('title', '')),
                'src': _clean(it.get('bloggername', '') or it.get('cafename', '') or
                              urllib.parse.urlparse(it.get('link', '')).netloc),
                'date': it.get('postdate', ''),
                'link': it.get('link', ''),
            }
            rows.append(row)
            if any(o in link for o in OURS):
                out['ours'].append(dict(row, corpus=label))
        out['hits'][label] = rows
    return out


def indexed(query, display=50):
    """그 글이 색인됐는가만 본다 — 순위와 섞어 보면 안 된다.

    ⚠️ 이걸 따로 둔 이유(2026-08-15 실측 오판). 색인 여부를 정확도순(sim)
    상위 10개로 판정하면 **색인된 글도 '없음'으로 나온다.** 실제로 발행한 글이
    네이버 블로그탭 최신순 1위인데 sim 상위 10에 없어서 두 번이나 미색인으로
    잘못 보고했다.

    색인 여부는 최신순(date)으로, 넓게(기본 50개) 훑어야 한다. 우리 글이
    거기 있으면 색인된 것이다 — 그 자리가 몇 번째인지는 별개 문제다.
    """
    out = []
    for kind, label in CORPORA[:1]:          # 블로그만 보면 된다
        try:
            d = _get(kind, query, display=display, sort='date')
        except SystemExit:
            raise
        except Exception as e:
            return None, '%s: %s' % (label, e)
        for i, it in enumerate(d.get('items') or [], 1):
            link = it.get('link', '') + it.get('bloggerlink', '')
            if any(o in link for o in OURS):
                out.append((i, _clean(it.get('title', '')), it.get('link', '')))
    return out, None


def main(argv):
    if '--index' in argv:
        qs = [a for a in argv if not a.startswith('--')]
        if not qs:
            raise SystemExit('색인을 확인할 제목(또는 그 일부)을 인자로 줄 것')
        rec = '--record' in argv
        for q in qs:
            hits, err = indexed(q)
            if err:
                print('  ! %s — %s' % (q, err))
                continue
            prev = hist_last('index', q) if rec else None
            if hits:
                for n, t, u in hits:
                    print('  ✅ 색인됨 — %s' % t[:60])
                    print('     최신순 %d번째 · %s' % (n, u))
            else:
                print('  ❌ 최신순 50개 안에 없음 — %s' % q)
            if prev is not None:
                was, now = bool(prev.get('hit')), bool(hits)
                if was != now:
                    print('     ↳ 변화: %s → %s (직전 %s)'
                          % ('색인됨' if was else '없음',
                             '색인됨' if now else '없음', prev['d']))
                else:
                    print('     ↳ %s 이후 그대로' % prev['d'])
            if rec:
                hist_append(dict(mode='index', key=q, hit=bool(hits),
                                 n=(hits[0][0] if hits else None),
                                 link=(hits[0][2] if hits else None)))
        print('\n※ 색인 여부만 본 것이다. 통합검색 노출 순위는 사람이 직접 검색해야 안다.')
        if rec:
            print('※ %s 에 기록했다.' % os.path.relpath(HIST, ROOT))
        return 0

    as_json = '--json' in argv
    kws = [a for a in argv if not a.startswith('--')] or DEFAULT_KEYWORDS
    results = [probe(k) for k in kws]

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0

    for r in results:
        print('\n' + '=' * 72)
        print('[%s]' % r['keyword'])
        if r.get('errors'):
            print('  ! ' + ' / '.join(r['errors']))
        if r['ours']:
            for o in r['ours']:
                print('  ★ 우리 노출: %s API순번 %d — %s' % (o['corpus'], o['n'], o['title'][:40]))
        else:
            # ⚠️ '없음'은 색인 안 됐다는 뜻이 아니다. 정확도순 상위 10에 없다는
            # 뜻일 뿐이다 — 이걸 미색인으로 읽어 두 번 오판했다(2026-08-15).
            print('  ☆ 정확도순 상위 10에는 없음 (색인 여부는 --index 로 확인)')
        for _, label in CORPORA:
            rows = r['hits'].get(label) or []
            if not rows:
                continue
            print('  -- %s --' % label)
            for x in rows[:5]:
                print('   %2d. %-44s | %s' % (x['n'], x['title'][:44], x['src'][:22]))

        # 회차 비교 — 지난번과 달라진 것만 짚는다. 매번 같은 목록을 다시 읽는 건
        # 사람이 못 한다.
        top = [x['title'] for x in (r['hits'].get('블로그') or [])[:10]]
        if '--record' in argv:
            prev = hist_last('serp', r['keyword'])
            if prev:
                fresh = [t for t in top if t not in (prev.get('top') or [])]
                gone = [t for t in (prev.get('top') or []) if t not in top]
                print('  ── %s 대비 ──' % prev['d'])
                if not fresh and not gone:
                    print('     상위 10 변동 없음')
                for t in fresh[:4]:
                    print('     + %s' % t[:56])
                for t in gone[:2]:
                    print('     − %s' % t[:56])
            hist_append(dict(mode='serp', key=r['keyword'], top=top,
                             ours=[o['title'] for o in r['ours']]))
    print('\n' + '=' * 72)
    print('⚠️ API 순번은 통합검색 실제 순위가 아니다(API 자체 정렬).')
    print('   경쟁 글의 각도를 보는 용도로 읽을 것.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

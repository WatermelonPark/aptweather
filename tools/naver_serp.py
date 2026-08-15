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
        for q in qs:
            hits, err = indexed(q)
            if err:
                print('  ! %s — %s' % (q, err))
            elif hits:
                for n, t, u in hits:
                    print('  ✅ 색인됨 — %s' % t[:60])
                    print('     최신순 %d번째 · %s' % (n, u))
            else:
                print('  ❌ 최신순 50개 안에 없음 — %s' % q)
        print('\n※ 색인 여부만 본 것이다. 통합검색 노출 순위는 사람이 직접 검색해야 안다.')
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
            print('  ☆ 우리 글 없음(각 상위 10)')
        for _, label in CORPORA:
            rows = r['hits'].get(label) or []
            if not rows:
                continue
            print('  -- %s --' % label)
            for x in rows[:5]:
                print('   %2d. %-44s | %s' % (x['n'], x['title'][:44], x['src'][:22]))
    print('\n' + '=' * 72)
    print('⚠️ API 순번은 통합검색 실제 순위가 아니다(API 자체 정렬).')
    print('   경쟁 글의 각도를 보는 용도로 읽을 것.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

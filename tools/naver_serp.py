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

공식 API만 쓴다(스크래핑 없음). 무료 일 25,000회라 이 용도엔 넉넉하다.

준비:
  developers.naver.com → 애플리케이션 등록 → 사용 API '검색' 선택
  발급받은 값을 환경변수로 둔다(기존 도구들과 같은 방식):
    NAVER_CLIENT_ID=...  NAVER_CLIENT_SECRET=...

사용:
  python tools/naver_serp.py                    # 기본 키워드 세트
  python tools/naver_serp.py "대구 미분양" "부산 입주물량"
  python tools/naver_serp.py --json             # 기계가 읽을 형태로
"""
import io
import json
import os
import sys
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
# 검색량 0인 조합(경기입주물량 10 등)은 넣어도 배울 게 없어 뺐다.
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

API = 'https://openapi.naver.com/v1/search/%s.json'


def _get(kind, query, display=10, sort='sim'):
    cid = os.environ.get('NAVER_CLIENT_ID', '')
    sec = os.environ.get('NAVER_CLIENT_SECRET', '')
    if not cid or not sec:
        raise SystemExit(
            'NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없다.\n'
            '  developers.naver.com → 애플리케이션 등록 → 사용 API "검색"\n'
            '  PowerShell:  $env:NAVER_CLIENT_ID="..."; $env:NAVER_CLIENT_SECRET="..."\n'
            '  bash:        export NAVER_CLIENT_ID=... NAVER_CLIENT_SECRET=...')
    url = (API % kind) + '?' + urllib.parse.urlencode(
        {'query': query, 'display': display, 'sort': sort})
    req = urllib.request.Request(url, headers={
        'X-Naver-Client-Id': cid, 'X-Naver-Client-Secret': sec})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def _clean(s):
    """API가 검색어에 <b> 태그를 박아 돌려준다. 사람이 읽을 형태로 되돌린다."""
    for a, b in (('<b>', ''), ('</b>', ''), ('&lt;', '<'), ('&gt;', '>'),
                 ('&amp;', '&'), ('&quot;', '"'), ('&#39;', "'")):
        s = s.replace(a, b)
    return s.strip()


def probe(keyword, display=10):
    """한 키워드에 대해 블로그·웹문서 결과를 모아 우리 것 여부를 표시한다."""
    out = {'keyword': keyword, 'blog': [], 'web': [], 'ours': []}
    for kind in ('blog', 'webkr'):
        try:
            d = _get(kind, keyword, display=display)
        except SystemExit:
            raise
        except Exception as e:
            out.setdefault('errors', []).append('%s: %s' % (kind, e))
            continue
        for i, it in enumerate(d.get('items') or [], 1):
            link = it.get('link', '') + it.get('bloggerlink', '')
            row = {
                'n': i,
                'title': _clean(it.get('title', '')),
                'src': _clean(it.get('bloggername', '') or
                              urllib.parse.urlparse(it.get('link', '')).netloc),
                'date': it.get('postdate', ''),
                'link': it.get('link', ''),
            }
            out['blog' if kind == 'blog' else 'web'].append(row)
            if any(o in link for o in OURS):
                out['ours'].append({'kind': kind, **row})
    return out


def main(argv):
    as_json = '--json' in argv
    kws = [a for a in argv if not a.startswith('--')] or DEFAULT_KEYWORDS
    results = [probe(k) for k in kws]

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0

    for r in results:
        print('\n' + '=' * 62)
        print('[%s]' % r['keyword'])
        if r.get('errors'):
            print('  ! ' + ' / '.join(r['errors']))
        if r['ours']:
            for o in r['ours']:
                print('  ★ 우리 노출: %s API순번 %d — %s' % (o['kind'], o['n'], o['title'][:40]))
        else:
            print('  ☆ 우리 글 없음(상위 10)')
        print('  -- 블로그 상위 --')
        for b in r['blog'][:5]:
            print('   %2d. %-42s | %s' % (b['n'], b['title'][:42], b['src'][:18]))
        if r['web']:
            print('  -- 웹문서 상위 --')
            for w in r['web'][:5]:
                print('   %2d. %-42s | %s' % (w['n'], w['title'][:42], w['src'][:24]))
    print('\n' + '=' * 62)
    print('⚠️ API 순번은 통합검색 실제 순위가 아니다(API 자체 정렬).')
    print('   경쟁 글의 각도를 보는 용도로 읽을 것.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

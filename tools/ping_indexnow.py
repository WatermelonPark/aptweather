# -*- coding: utf-8 -*-
"""IndexNow 핑 — 네이버·빙에 변경된 URL의 재크롤을 즉시 요청한다.

키 파일: 저장소 루트의 {key}.txt (사이트에도 배포됨), 키 값은 .indexnow_key(비커밋).
사용: python tools/ping_indexnow.py [url ...]   (인자 없으면 기본 4개 URL)
      python tools/ping_indexnow.py --sitemap     (sitemap.xml의 전체 URL 제출)

--sitemap을 쓰면 생활권 페이지가 늘거나 줄어도 자동으로 따라간다.
(2026-07-19 이전에는 배치가 / 와 /weekly/ 2개만 보내, zone 37장은
 한 번도 색인 요청된 적이 없었다.)
키 파일이 없으면 조용히 건너뛴다.
"""
import io, os, sys, json
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'https://www.agongmap.co.kr'
DEFAULT = ['/', '/weekly/', '/faq/', '/burini-test/', '/cycle/']


def main():
    keyfile = os.path.join(ROOT, '.indexnow_key')
    if os.path.exists(keyfile):
        key = io.open(keyfile).read().strip()
    else:
        # ⚠️ IndexNow 키는 설계상 공개값이다 — 사이트 루트의 {key}.txt를 검색엔진이
        # 직접 받아 소유권을 확인한다. 그래서 비커밋 .indexnow_key가 없으면 커밋된
        # 키 파일에서 읽는다. 이게 없어서 클라우드 배치에는 핑이 아예 없었고,
        # 2026-08-06 URL 전면 교체(생활권 31곳 → 시도 20곳)가 색인 요청 없이 나갔다.
        import glob as _glob
        cand = [f for f in _glob.glob(os.path.join(ROOT, '*.txt'))
                if len(os.path.basename(f)) == 36 and
                all(ch in '0123456789abcdef' for ch in os.path.basename(f)[:32])]
        if not cand:
            print('indexnow skip: 키 파일 없음')
            return
        key = os.path.basename(cand[0])[:32]
    args = sys.argv[1:]
    if args and args[0] == '--sitemap':
        sm = os.path.join(ROOT, 'sitemap.xml')
        if not os.path.exists(sm):
            print('indexnow skip: sitemap.xml 없음')
            return
        import re as _re
        urls = _re.findall(r'<loc>\s*(.*?)\s*</loc>', io.open(sm, encoding='utf-8').read())
        if not urls:
            print('indexnow skip: sitemap.xml에 URL이 없음')
            return
    else:
        urls = [SITE + u for u in (args or DEFAULT)]
    payload = json.dumps({
        'host': 'www.agongmap.co.kr',
        'key': key,
        'keyLocation': '%s/%s.txt' % (SITE, key),
        'urlList': urls,
    }).encode('utf-8')
    req = urllib.request.Request('https://api.indexnow.org/indexnow', data=payload,
                                 headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print('indexnow:', r.status, 'urls:', len(urls))
    except Exception as e:
        print('indexnow skip:', str(e)[:120])


if __name__ == '__main__':
    main()

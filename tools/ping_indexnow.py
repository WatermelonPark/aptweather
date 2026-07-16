# -*- coding: utf-8 -*-
"""IndexNow 핑 — 네이버·빙에 변경된 URL의 재크롤을 즉시 요청한다.

키 파일: 저장소 루트의 {key}.txt (사이트에도 배포됨), 키 값은 .indexnow_key(비커밋).
사용: python tools/ping_indexnow.py [url ...]   (인자 없으면 기본 4개 URL)
키 파일이 없으면 조용히 건너뛴다.
"""
import io, os, sys, json
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'https://www.aptweather.co.kr'
DEFAULT = ['/', '/weekly/', '/faq/', '/burini-test/']


def main():
    keyfile = os.path.join(ROOT, '.indexnow_key')
    if not os.path.exists(keyfile):
        print('indexnow skip: .indexnow_key 없음')
        return
    key = io.open(keyfile).read().strip()
    urls = [SITE + u for u in (sys.argv[1:] or DEFAULT)]
    payload = json.dumps({
        'host': 'www.aptweather.co.kr',
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

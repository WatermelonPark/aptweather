# -*- coding: utf-8 -*-
"""발행이 확인된 알림 이슈를 닫는다.

발행일 알림(.github/workflows/write-reminder.yml)이 만든 이슈는 사람이 닫아야
"발행했다"는 기록이 됐다. 주 2회 클릭이 쌓이면 결국 안 닫게 되고, 그러면
열린 이슈 목록이 신호가 아니라 잡음이 된다(2026-08-30에 4건이 밀려 있었다).

그래서 블로그 RSS로 실제 발행을 확인해 닫는다. **기록은 그대로 남긴다** —
닫기 전에 어떤 글이 그 이슈를 해소했는지 댓글로 적는다.

⚠️ 보수적으로 판단한다. 틀려서 안 쓴 글을 썼다고 닫으면 그 회차가 조용히
사라진다. 그래서:
  · 제목이 아니라 **카테고리**로 맞춘다(제목은 매주 바뀌고 손으로 고치기도 한다)
  · 이슈의 예정일 **이후에** 올라온 글만 인정한다
  · 글 하나는 이슈 하나만 닫는다(주간 이슈가 둘 밀려 있는데 글은 하나면 하나만)
  · RSS를 못 읽거나 gh가 없으면 아무것도 안 닫고 끝낸다

사용:
  python tools/close_published_issues.py            # 실제로 닫는다
  python tools/close_published_issues.py --dry-run  # 무엇을 닫을지만 보여준다
"""
import datetime
import json
import re
import subprocess
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REPO = 'WatermelonPark/aptweather'
RSS = 'https://rss.blog.naver.com/startupbd.xml'

# 알림 이슈의 '종류' → 블로그 카테고리. 카테고리로 맞추는 이유는 제목과 달리
# 발행할 때 바뀌지 않기 때문이다.
KIND_TO_CATEGORY = {
    '주간 시세': '주간 아파트 시세',
    '지역 공급': '지역별 아파트 공급',
    '사이클 이론': '부동산 사이클',
}

MONTHS = {m: i for i, m in enumerate(
    'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(), 1)}


def fetch_posts():
    """RSS에서 (발행일, 카테고리, 제목, 주소)를 뽑는다. 실패하면 None."""
    try:
        req = urllib.request.Request(
            RSS, headers={'User-Agent': 'agongmap-publish-check/1.0'})
        raw = urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'replace')
    except Exception as e:
        print('RSS를 못 읽었다 — 아무것도 닫지 않는다: %s' % e)
        return None
    out = []
    for item in re.findall(r'<item>(.*?)</item>', raw, re.S):
        def pick(tag, cdata=True):
            pat = (r'<%s><!\[CDATA\[(.*?)\]\]></%s>' if cdata else r'<%s>(.*?)</%s>')
            m = re.search(pat % (tag, tag), item, re.S)
            return m.group(1).strip() if m else ''
        pub = re.search(r'<pubDate>(.*?)</pubDate>', item, re.S)
        d = None
        if pub:
            m = re.search(r'(\d{1,2})\s+(\w{3})\s+(\d{4})', pub.group(1))
            if m and m.group(2) in MONTHS:
                d = datetime.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        url = re.search(r'<guid>(.*?)</guid>', item, re.S)
        if d:
            out.append(dict(date=d, cat=pick('category'), title=pick('title'),
                            url=url.group(1).strip() if url else ''))
    return out


def open_issues():
    try:
        r = subprocess.run(
            ['gh', 'issue', 'list', '--repo', REPO, '--state', 'open',
             '--limit', '50', '--json', 'number,title'],
            capture_output=True, text=True, timeout=60, encoding='utf-8')
    except Exception as e:
        print('gh 실행 실패: %s' % e)
        return None
    if r.returncode != 0:
        print('gh 오류: %s' % (r.stderr or '').strip()[:200])
        return None
    out = []
    for it in json.loads(r.stdout or '[]'):
        m = re.match(r'\[발행\]\s+(\d{4})-(\d{2})-(\d{2})\s+(.+?)\s*$', it['title'])
        if not m:
            continue                      # 알림 이슈가 아니면 건드리지 않는다
        kind = m.group(4).strip()
        cat = KIND_TO_CATEGORY.get(kind)
        if not cat:
            continue
        out.append(dict(n=it['number'], kind=kind, cat=cat,
                        due=datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
    out.sort(key=lambda x: x['due'])      # 오래된 것부터 — 글 하나에 이슈 하나
    return out


def main(argv):
    dry = '--dry-run' in argv
    posts = fetch_posts()
    if posts is None:
        return 0
    issues = open_issues()
    if issues is None:
        return 0
    if not issues:
        print('열린 알림 이슈가 없다.')
        return 0

    used, closed = set(), 0
    for iss in issues:
        cand = [p for p in posts
                if p['cat'] == iss['cat'] and p['date'] >= iss['due']
                and p['url'] not in used]
        if not cand:
            print('· #%d %s %s — 아직 발행 안 됨' % (iss['n'], iss['due'], iss['kind']))
            continue
        cand.sort(key=lambda p: p['date'])
        p = cand[0]
        used.add(p['url'])
        body = ('✅ 발행 확인 — %s\n\n**%s**\n%s\n\n'
                '이 이슈는 블로그 RSS에서 발행이 확인되어 자동으로 닫혔습니다'
                '(`tools/close_published_issues.py`). 카테고리와 발행일로 맞춘 것이라,'
                ' 다른 글이 잘못 잡혔다면 다시 열어 주세요.'
                % (p['date'], p['title'], p['url']))
        print('%s #%d %s %s → %s' % ('[dry]' if dry else '닫음', iss['n'],
                                     iss['due'], iss['kind'], p['title'][:40]))
        if dry:
            continue
        r = subprocess.run(['gh', 'issue', 'close', str(iss['n']), '--repo', REPO,
                            '--comment', body],
                           capture_output=True, text=True, timeout=60, encoding='utf-8')
        if r.returncode != 0:
            print('   ! 닫기 실패: %s' % (r.stderr or '').strip()[:160])
        else:
            closed += 1
    print('\n%d건 닫음.' % closed if not dry else '\n(dry-run — 아무것도 닫지 않았다)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

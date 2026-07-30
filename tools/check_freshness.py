# -*- coding: utf-8 -*-
"""라이브 데이터가 원천보다 뒤처졌는지 검사 — 배치 실패·소스 단절 감시.

왜 '나이'만으로는 안 되나 (2026-07-30 실사고):
  주간은 월요일 기준일을 목요일에 발표한다. 그래서 목요일 아침엔 정상일 때도
  직전 데이터가 10일 됐고, 한 회차를 통째로 놓친 날도 똑같이 10일이다.
  둘이 구별되지 않으니 임계를 어떻게 잡아도 그날은 못 잡는다(10 이하로 내리면
  매주 목요일 오탐). 월간·연간은 발표일이 고정도 아니라 더 심하다.
  → 원천의 최신 시점을 직접 조회해 라이브와 대조한다.

grace가 봐주는 것:
  '원천이 더 최신'이 정상인 유일한 구간은 발표 직후~다음 배치 전이다. 배치가
  매일 20시에 돌고 이 검사는 22시에 도니 그 창은 사실상 없다 — 22시에도 뒤처져
  있으면 그날 배치가 못 받은 것이다. 그래서 grace는 대부분 형식적이고(월간·기본통계는
  발표일 나이보다 낮게 잡아 사실상 즉시 실패), 주간만 '수요일 밤 9일'을 넘겼는지로
  목요일 당일 판정에 쓴다. 연간은 grace 없음.

사용: KOSIS_API_KEY=... RONE_API_KEY=... python tools/check_freshness.py
      실패(뒤처짐) 시 exit 1 — GitHub Actions가 알림 메일을 보낸다.
"""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

try:  # 윈도우 콘솔(cp949)에서 —·← 때문에 죽지 않게
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_adv_data as U  # noqa: E402  (표 설정을 배치와 공유 — 단일 출처)

SITE = 'https://www.agongmap.co.kr'
UA = {'User-Agent': 'agongmap-watchdog'}
TODAY = datetime.date.today()

# 계열별 정상 최대 나이(일). 이 안쪽이면 '발표 직후 배치 전'일 수 있어 봐준다.
# 주간 9는 감시를 배치 뒤(22시)에 돌린다는 전제에 기댄다. 기준일은 월요일이고
# 발표는 그 주 목요일이라 정상 최대는 수요일 밤의 9일. 목요일 밤에 10일이면
# 그날 배치가 회차를 놓친 것이므로 당일 잡힌다. 감시를 배치 앞으로 옮기면
# 매주 목요일 오탐이 나니, cron을 바꿀 땐 이 값도 10으로 되돌려야 한다.
GRACE_WEEKLY = 9
GRACE_MONTHLY = 50     # 매월 15일경 전월분 발표
GRACE_BASIC = 100      # 인허가·착공·준공이 약 2개월 지연(정상 최대 ~95일)


def get_json(url):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=60).read().decode('utf-8', 'replace'))


def live_adv_stats():
    """라이브 data.js(ADV) + data-rest.json(STATS)."""
    txt = urllib.request.urlopen(
        urllib.request.Request(SITE + '/data.js', headers=UA), timeout=60
    ).read().decode('utf-8', 'replace')
    m = re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});', txt, re.S)
    if not m:
        print('FAIL: data.js에서 ADV 블록을 찾지 못했습니다 (배포가 깨졌을 수 있음)')
        sys.exit(1)
    adv = json.loads(m.group(1))
    stats = (get_json(SITE + '/data-rest.json') or {}).get('STATS') or {}
    return adv, stats


def rone_latest(tbl, cycle):
    """R-ONE은 과거부터 페이징된다 — 마지막 페이지가 최신이다."""
    base = ('https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do'
            '?KEY=%s&Type=json&STATBL_ID=%s&DTACYCLE_CD=%s'
            % (os.environ.get('RONE_API_KEY', ''), tbl, cycle))
    head = get_json(base + '&pIndex=1&pSize=1')
    total = None
    for blk in head.get('SttsApiTblData', []):
        for h in blk.get('head', []) or []:
            if 'list_total_count' in h:
                total = h['list_total_count']
    if not total:
        raise RuntimeError('list_total_count 없음')
    rows = []
    for blk in get_json(base + '&pIndex=%d&pSize=1000' % ((total // 1000) + 1)).get('SttsApiTblData', []):
        if 'row' in blk:
            rows = blk['row']
    if cycle == 'WK':
        vals = [(r.get('WRTTIME_DESC') or '').strip() for r in rows]
        vals = [v for v in vals if len(v) == 10]
    else:
        vals = [str(r.get('WRTTIME_IDTFR_ID') or '') for r in rows]
        vals = [v for v in vals if len(v) == 6 and v.isdigit()]
    if not vals:
        raise RuntimeError('시점 파싱 실패')
    return max(vals)


def kosis_latest(org, tbl, objn, prd, extra=None):
    p = {'method': 'getList', 'apiKey': os.environ.get('KOSIS_API_KEY', ''),
         'format': 'json', 'jsonVD': 'Y', 'orgId': org, 'tblId': tbl,
         'itmId': 'ALL', 'prdSe': prd, 'newEstPrdCnt': '1'}
    for i in range(1, objn + 1):
        p['objL%d' % i] = 'ALL'
    p.update(extra or {})
    d = get_json('https://kosis.kr/openapi/Param/statisticsParameterData.do?'
                 + urllib.parse.urlencode(p))
    if isinstance(d, dict) and d.get('err'):
        raise RuntimeError('KOSIS err %s' % d.get('err'))
    prds = sorted({r.get('PRD_DE') for r in d if r.get('PRD_DE')})
    if not prds:
        raise RuntimeError('시점 없음')
    return prds[-1]


def digits(s):
    return re.sub(r'\D', '', str(s))


def age_days(period):
    """'20260727'/'202606'/'2026' → 그 시점 시작일로부터의 경과일."""
    n = digits(period)
    try:
        if len(n) >= 8:
            d = datetime.date(int(n[:4]), int(n[4:6]), int(n[6:8]))
        elif len(n) == 6:
            d = datetime.date(int(n[:4]), int(n[4:6]), 1)
        elif len(n) == 4:
            d = datetime.date(int(n), 1, 1)
        else:
            return None
    except ValueError:
        return None
    return (TODAY - d).days


def check(label, ours, getter, grace):
    """원천이 더 최신이고 grace를 넘겨 뒤처졌으면 실패 사유를 반환."""
    if not ours:
        return '%s: 라이브 값이 비어 있음' % label
    try:
        src = getter()
    except Exception as e:
        print('  %-12s %-12s 원천 조회 건너뜀 (%s)' % (label, ours, str(e)[:40]))
        return None
    o, s = digits(ours), digits(src)
    age = age_days(ours)
    behind = len(o) == len(s) and s > o
    mark = ''
    if behind:
        mark = '  ← 원천 %s' % src
        if grace is None or (age is not None and age > grace):
            print('  %-12s %-12s %s일%s  실패' % (label, ours, age, mark))
            return '%s(라이브 %s < 원천 %s, 경과 %s일)' % (label, ours, src, age)
        mark += ' (발표 직후 가능 — grace %d일 내)' % grace
    print('  %-12s %-12s %s일%s' % (label, ours, age, mark))
    return None


def main():
    adv, stats = live_adv_stats()
    fails = []
    print('[시세 — 원천 R-ONE]')
    wk = ((adv.get('weekly') or {}).get('rows') or [{}])[-1].get('p')
    fails.append(check('주간', wk, lambda: rone_latest(U.RONE_TBL['maega'], 'WK'), GRACE_WEEKLY))
    mo = ((adv.get('monthly') or {}).get('rows') or [{}])[-1].get('p')
    fails.append(check('월간', mo, lambda: rone_latest(U.RONE_MONTHLY_TBL['maega'], 'MM'), GRACE_MONTHLY))

    print('[기본통계 — 원천 KOSIS]')
    for name, cfg in sorted(U.BASIC_CONF.items()):
        D = stats.get(name) or {}
        last = (D.get('dates') or [None])[-1]
        fails.append(check(name, last,
                           lambda c=cfg: kosis_latest(c['org'], c['tbl'], c['objn'], 'M'),
                           GRACE_BASIC))
    if '규모별' in stats:
        sz = U.SIZE_TBLS[0][1]
        last = (stats['규모별'].get('dates') or [None])[-1]
        fails.append(check('규모별', last,
                           lambda: kosis_latest('408', sz, 3, 'M', {'objL1': '01'}),
                           GRACE_BASIC))

    print('[연간 — 원천 KOSIS]')
    for name, cfg in sorted(U.ANNUAL_CONF.items()):
        D = stats.get(name) or {}
        last = (D.get('dates') or [None])[-1]
        fails.append(check(name, last,
                           lambda c=cfg: kosis_latest(c['org'], c['tbl'], c['objn'], 'Y'),
                           None))

    bad = [f for f in fails if f]
    print('')
    if bad:
        print('FAIL: 원천보다 뒤처진 계열 %d개' % len(bad))
        for b in bad:
            print('  - %s' % b)
        print('  → update-cloud 실행 이력, 해당 KOSIS 표 ID 변경/폐지 여부 확인')
        sys.exit(1)
    print('OK: 모든 계열이 원천과 같은 시점입니다.')


if __name__ == '__main__':
    main()

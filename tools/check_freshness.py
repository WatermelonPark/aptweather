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
SKIPPED = []           # 원천 조회 실패로 판정하지 못한 계열

# 계열별 정상 최대 나이(일). 이 안쪽이면 '발표 직후 배치 전'일 수 있어 봐준다.
# 주간 9는 감시를 배치 뒤(22시)에 돌린다는 전제에 기댄다. 기준일은 월요일이고
# 발표는 그 주 목요일이라 정상 최대는 수요일 밤의 9일. 목요일 밤에 10일이면
# 그날 배치가 회차를 놓친 것이므로 당일 잡힌다. 감시를 배치 앞으로 옮기면
# 매주 목요일 오탐이 나니, cron을 바꿀 땐 이 값도 10으로 되돌려야 한다.
GRACE_WEEKLY = 9
GRACE_MONTHLY = 50     # 매월 15일경 전월분 발표
GRACE_BASIC = 100      # 인허가·착공·준공이 약 2개월 지연(정상 최대 ~95일)
GRACE_HUB = 45         # update-hub는 월 1회(매월 1일) — 한 번 걸러도 알아채는 선


def get_json(url):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=60).read().decode('utf-8', 'replace'))


def live_adv_stats():
    """라이브 data.js(ADV) + data-rest.json·data-size.json(STATS)."""
    txt = urllib.request.urlopen(
        urllib.request.Request(SITE + '/data.js', headers=UA), timeout=60
    ).read().decode('utf-8', 'replace')
    m = re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});', txt, re.S)
    if not m:
        print('FAIL: data.js에서 ADV 블록을 찾지 못했습니다 (배포가 깨졌을 수 있음)')
        sys.exit(1)
    adv = json.loads(m.group(1))
    stats = (get_json(SITE + '/data-rest.json') or {}).get('STATS') or {}
    # 2026-08-01 split_data가 '규모별'(186KB)을 data-size.json으로 분리하면서
    # rest에서 빠졌다. 여기서 합치지 않으면 아래 `if '규모별' in stats` 게이트가
    # 영영 안 걸려 감시가 조용히 꺼진다(2026-08-04 감사에서 실제로 꺼져 있었음).
    # 지연 로드 파일이 늘어나면 이 목록에도 추가할 것.
    for lazy in ('/data-size.json',):
        try:
            stats.update((get_json(SITE + lazy) or {}).get('STATS') or {})
        except Exception as e:
            print('  경고: %s 조회 실패 (%s) — 그 계열 감시는 이번 회차 건너뜀'
                  % (lazy, str(e)[:40]))
    return adv, stats


def live_hub_meta():
    """라이브 tools/data/hub_permits.json의 meta(수집 시점)."""
    return (get_json(SITE + '/tools/data/hub_permits.json') or {}).get('meta') or {}


PNG_SIG = bytes([137, 80, 78, 71, 13, 10, 26, 10])


def live_card_basis():
    """라이브 공유 카드(share/weekly-map.png)에 심긴 조사기준일.

    카드는 /weekly/의 og:image다 — 카카오·트위터 미리보기가 이걸 쓴다. 데이터가
    아니라 그림이라 감시 밖에 있었고, 2026-07-13 카드가 3주 넘게 '이번 주 아파트
    시세 지도'로 걸려 있었는데 아무 신호도 없었다(2026-08-06 발견). 원인은 클라우드
    배치에 pillow가 없어 생성 스텝이 매 회차 조용히 죽은 것.

    PIL 없이 PNG tEXt 청크를 직접 읽는다 — 감시 잡에 이미지 라이브러리를 들이지
    않으려는 것이다. 청크는 [길이4][타입4][데이터][CRC4]의 배열이고, tEXt 데이터는
    키와 값을 NUL 하나로 이어 붙인 형태다.
    """
    raw = urllib.request.urlopen(
        urllib.request.Request(SITE + '/share/weekly-map.png', headers=UA), timeout=60).read()
    if raw[:8] != PNG_SIG:
        return None
    i = 8
    while i + 8 <= len(raw):
        n = int.from_bytes(raw[i:i + 4], 'big')
        typ = raw[i + 4:i + 8]
        if typ == b'IEND':
            break
        if typ == b'tEXt':
            k, _, v = raw[i + 8:i + 8 + n].partition(bytes([0]))
            if k == b'agongmap-basis':
                return v.decode('ascii', 'replace')
        i += 12 + n
    return None


def check_age(label, stamp, grace):
    """수집 시점 도장(YYYY-MM-DD)이 grace일보다 오래됐으면 실패 사유를 반환.

    원천 대조(check)와 달리 '언제 마지막으로 받아왔나'만 본다 — 건축HUB는 원천에
    '최신 시점' 질의가 없고, 있어도 일일 쿼터를 감시가 축내면 안 된다.
    """
    if not stamp:
        return '%s: 수집 시점 도장이 없음' % label
    age = age_days(stamp)
    if age is None:
        return '%s: 수집 시점 해석 불가(%s)' % (label, stamp)
    if age > grace:
        print('  %-12s %-12s %s일  실패 (grace %d일)' % (label, stamp, age, grace))
        return '%s(마지막 수집 %s, 경과 %s일 > %d일)' % (label, stamp, age, grace)
    print('  %-12s %-12s %s일' % (label, stamp, age))
    return None


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


def ecos_latest():
    """한국은행 ECOS CD금리(721Y001, 월). 최근 1년만 받아 최신 시점을 본다."""
    url = ('https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/50/721Y001/M'
           '/%d%02d/%d%02d/2010000'
           % (os.environ.get('ECOS_API_KEY', ''),
              TODAY.year - 1, TODAY.month, TODAY.year, TODAY.month))
    rows = (get_json(url).get('StatisticSearch') or {}).get('row') or []
    times = [str(r.get('TIME') or '') for r in rows]
    times = [t for t in times if len(t) == 6 and t.isdigit()]
    if not times:
        raise RuntimeError('시점 없음')
    return max(times)


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
        # 원천이 잠깐 죽는 건 흔하다 — 한둘은 넘기고, 대량 건너뜀만 아래에서 잡는다.
        SKIPPED.append(label)
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
    # 키가 비면 모든 원천 조회가 '건너뜀'이 되어 감시가 조용히 통과한다.
    # 감시자가 무력해진 것을 감시할 사람은 없으니 여기서 바로 실패시킨다.
    missing = [k for k in ('KOSIS_API_KEY', 'RONE_API_KEY', 'ECOS_API_KEY')
               if not os.environ.get(k)]
    if missing:
        print('FAIL: %s 없음 — 원천 대조를 할 수 없습니다 (시크릿 확인)' % ', '.join(missing))
        sys.exit(1)

    adv, stats = live_adv_stats()
    fails = []
    print('[시세 — 원천 R-ONE]')
    wk = ((adv.get('weekly') or {}).get('rows') or [{}])[-1].get('p')
    fails.append(check('주간', wk, lambda: rone_latest(U.RONE_TBL['maega'], 'WK'), GRACE_WEEKLY))
    # 공유 카드는 라이브 데이터와 같은 주차여야 한다. 원천이 아니라 **라이브 주간**과
    # 대조하는 게 핵심 — 배치가 데이터를 못 받은 날은 위 '주간' 검사가 이미 잡고,
    # 여기서 보려는 건 '데이터는 새 주차인데 카드만 안 만들어진' 상태다.
    try:
        cb = live_card_basis()
        if cb is None:
            print('  공유카드: 기준일 메타 없음 — 옛 카드가 배포돼 있거나 생성기가 낡음')
            fails.append('공유카드: 기준일 메타가 없다(생성 스텝이 죽었는지 확인)')
        elif wk and cb != wk:
            print('  공유카드: %s (라이브 주간 %s) — 뒤처짐' % (cb, wk))
            fails.append('공유카드가 %s에 멈춤 — 라이브 주간은 %s (og:image가 옛 주차)' % (cb, wk))
        else:
            print('  공유카드: %s — 라이브 주간과 일치' % cb)
    except Exception as e:
        SKIPPED.append('공유카드')
        print('  공유카드: 조회 실패(%s) — 이번 회차 판정 못 함' % str(e)[:50])

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

    # 분양·미분양은 BASIC_CONF가 아니라 SUPPLY_CONF에 있어 예전엔 감시에서 통째로
    # 빠져 있었다(2026-07-31 발견). 새 지표를 추가할 때 감시에도 들어왔는지
    # 확인하는 자리가 여기다 — 라이브 STATS 계열 수와 아래 점검 수가 맞아야 한다.
    print('[공급 파이프라인 — 원천 R-ONE]')
    for name, cfg in sorted(U.SUPPLY_CONF.items()):
        D = stats.get(name) or {}
        last = (D.get('dates') or [None])[-1]
        fails.append(check(name, last,
                           lambda c=cfg: rone_latest(c['tbl'], 'MM'),
                           GRACE_MONTHLY))

    print('[금리 — 원천 한국은행 ECOS]')
    D = stats.get('금리') or {}
    fails.append(check('금리', (D.get('dates') or [None])[-1],
                       ecos_latest, GRACE_MONTHLY))

    print('[연간 — 원천 KOSIS]')
    for name, cfg in sorted(U.ANNUAL_CONF.items()):
        D = stats.get(name) or {}
        last = (D.get('dates') or [None])[-1]
        fails.append(check(name, last,
                           lambda c=cfg: kosis_latest(c['org'], c['tbl'], c['objn'], 'Y'),
                           None))

    # 간판 지표(순부족)의 공급·재고 입력이 통째로 여기서 온다. update-hub가 실패하거나
    # (쿼터 소진·타임아웃·push 실패) hub_permits.json이 옛 시점에 굳어도 예전엔
    # 아무 신호가 없었다 — 다음 정기 실행이 한 달 뒤라 최대 두 달까지 조용히 정지했다
    # (2026-08-04 감사). 월 1회 실행이므로 한 번 걸러도 알아채도록 grace를 45일로 둔다.
    print('[건축HUB — 원천 건축HUB(수집 시점 기준)]')
    try:
        hm = live_hub_meta()
        fails.append(check_age('HUB준공', hm.get('fetched'), GRACE_HUB))
        fails.append(check_age('HUB멸실', hm.get('fetched_demol'), GRACE_HUB))
        if not hm.get('activate'):
            # activate=false면 라이브 스코어가 pre-HUB로 되돌아간 것이다. 의도한
            # 롤백일 수 있으나 조용히 그 상태로 굳는 것을 막는다.
            fails.append('HUB activate=false — 라이브 스코어가 pre-HUB 산식으로 돌아가 있음')
    except Exception as e:
        fails.append('HUB 메타 조회 실패(%s) — hub_permits.json 배포 확인 필요' % str(e)[:60])

    # 커버리지 가드: 라이브에 있는데 위에서 한 번도 대조 안 한 계열을 잡는다.
    # 분양·미분양이 SUPPLY_CONF에 있다는 이유로 몇 주간 감시 밖에 있었다 — 사람이
    # 기억으로 막을 일이 아니라서, 새 계열이 늘면 감시가 스스로 실패하게 둔다.
    covered = (set(U.BASIC_CONF) | set(U.ANNUAL_CONF) | set(U.SUPPLY_CONF)
               | {'규모별', '금리'})
    uncovered = sorted(set(stats) - covered)
    if uncovered:
        fails.append('감시 누락 계열 %s — check_freshness.py에 대조를 추가할 것'
                     % ', '.join(uncovered))

    bad = [f for f in fails if f]
    print('')
    if bad:
        # 뒤처짐과 감시 누락이 섞이므로 제목은 중립적으로 쓴다.
        print('FAIL: 문제 %d건' % len(bad))
        for b in bad:
            print('  - %s' % b)
        print('  → update-cloud 실행 이력, 해당 KOSIS 표 ID 변경/폐지 여부 확인')
        sys.exit(1)
    if len(SKIPPED) * 2 > len(fails):
        # 절반 넘게 못 봤으면 'OK'는 근거가 없다. 통과시키면 감시가 켜져 있는
        # 채로 아무것도 안 보는 상태가 된다 — 그게 가장 위험한 실패다.
        print('FAIL: %d/%d 계열을 원천과 대조하지 못했습니다 — %s'
              % (len(SKIPPED), len(fails), ', '.join(SKIPPED)))
        print('  → API 키 만료·표 ID 변경·원천 장애 여부 확인')
        sys.exit(1)
    if SKIPPED:
        print('참고: %s 계열은 원천 조회 실패로 건너뜀' % ', '.join(SKIPPED))
    print('OK: 모든 계열이 원천과 같은 시점입니다.')


if __name__ == '__main__':
    main()

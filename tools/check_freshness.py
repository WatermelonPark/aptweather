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
import time
import urllib.parse
import urllib.request

try:  # 윈도우 콘솔(cp949)에서 —·← 때문에 죽지 않게
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_adv_data as U  # noqa: E402  (표 설정을 배치와 공유 — 단일 출처)
import sido_zones as SZ      # noqa: E402  (지역 정의의 정본 — 손 목록 금지)
import make_indicator_pages as I  # noqa: E402  (공개일·클램프 규칙 공유)
import split_data as S       # noqa: E402  (지연 로드 분리 규칙을 공유 — 부작용 없는 import)

SITE = 'https://www.agongmap.co.kr'
UA = {'User-Agent': 'agongmap-watchdog'}
TODAY = datetime.date.today()
SKIPPED = []           # 원천 조회 실패로 판정하지 못한 계열(재시도까지 실패)
RETRYQ = []            # 1차 조회 실패 — 한 텀 쉬고 다시 볼 (label, ours, getter, grace)
# 조회 **자체**가 실패한 것. SKIPPED가 대부분을 덮지만 SKIPPED는 'SKIPPED×2 >
# len(fails)' 게이트의 분자로도 쓰이므로, 그 산수를 건드리지 않으려고 별도로 둔다.
# 이 목록이 비어 있다는 건 "네트워크는 멀쩡했고 판정은 순수히 데이터로 났다"는 뜻이고,
# 그때는 새 IP로 다시 봐도 답이 같다(아래 EXIT_DETERMINISTIC).
FETCH_FAIL = []

# 개수 게이트('SKIPPED×2 > len(fails)')로는 표현할 수 없는 것: 계열마다 값어치가
# 다르다. 연간 4계열이 빠지는 건 무해하지만(1년에 한 번 바뀐다) 주간이 빠지는 건
# 아니다 — 이 감시를 만든 이유가 주간이고, 2026-07-30 실사고가 난 계열도 주간이다.
# 그런데 R-ONE 하나가 죽으면 주간·월간·분양·미분양이 **함께** 빠지면서도 17계열 중
# 4개라 임계 아래에 머문다. 그래서 그날 밤 주간이 미검증인 채로 초록불이 떴다
# (2026-08-15 주입 시험으로 재현). 여기 있는 계열은 개수와 무관하게 실패시킨다.
#
# 늘릴 때 주의: 이건 민감도를 올리는 목록이라 오경보 빈도와 직결된다. '못 봤다'가
# 곧 '경보'가 될 만큼 중요한 계열만 넣을 것 — 판정은 retry로 나가므로 recheck가
# 새 IP로 한 번 더 보고, 거기서도 실패해야 최종 red다.
CRITICAL_SERIES = ('주간',)

RETRY_WAIT = 75        # 초. 순간 장애는 넘기고, 잡 타임아웃(30분) 예산 안에 든다.
FETCH_TIMEOUT = 25     # 원천 호출 타임아웃. 재시도 패스에서는 20으로 줄인다 —
                       # 광역 장애면 어차피 다 실패하는데 같은 시간을 또 쓸 이유가 없다.
# ⚠️ 60초였는데 25로 내렸다(2026-08-15 리뷰). 산수가 예산을 넘겼다: 원천 대조는
# 17계열 = HTTP 21회를 **직렬**로 돌고(R-ONE은 계열당 head+본문 2회), 광역 장애면
# 전부 타임아웃을 꽉 채운다. 60초면 1차만 21×60 = 21분이고, 여기에 대기 75초와
# 재시도 패스(~7분)를 더하면 28~31분 — watchdog.yml의 `timeout-minutes: 30`을
# 넘긴다. 넘기는 순간 `steps.check.outputs.verdict`가 안 찍혀 판정 없이 잡이 죽고,
# recheck가 빈 verdict를 받아 같은 30분을 또 쓴다. **하필 재시도 층을 넣은
# 이유(어느 계열이 문제인지 말해주기)가 그때 사라진다.**
# (verdict가 비면 recheck로 떨어지는 건 의도된 안전 방향이다 — watchdog.yml의
#  `!= 'ok' && != 'final'` 참고. 여기서 말하는 건 '예산을 넘기면 안 된다'는 쪽이다.)
# 25초 근거: 정상 응답은 2~3초다(update-cloud.yml 머리 주석의 실측). 10배 여유다.
# ⚠️ 예산 재계산(2026-08-26, 지역명 충돌 검사 추가): 원천 호출이 21 → 25회가 됐다
# (충돌 검사가 표 2개 × head+본문 = 4회). 최악 1차 25×25 + 사이트 5×20 = 12.1분,
# 대기 75초와 재시도 패스를 더해 21.7분 — 30분 예산 안(여유 8.3분)이다.
# 여기에 호출을 더 얹을 땐 **곱해서 다시 확인할 것**. 이 파일의 '최악 N분' 주석은
# 과거 두 번 다 과소평가였다.
# 근본 대책은 268행대 파생 페이지 감시처럼 ThreadPoolExecutor로 병렬화하는 것이다
# (그러면 1차가 1분대로 떨어져 timeout-minutes도 되돌릴 수 있다).

# 우리 사이트(GitHub Pages) 조회 타임아웃. 원천과 달리 여기는 우리가 띄운 정적
# 파일이라 훨씬 빠르다 — 2026-08-15 실측으로 data.js(2.1MB) 0.46초, 나머지는 전부
# 0.3초대다. 그런데 6곳에 60초가 박혀 있었다(실측의 120배). 예산 계산에서 이게
# 5×60 = 5분을 차지해, FETCH_TIMEOUT만 내려서는 산수가 안 맞았다.
# 20초면 실측의 40배 여유이고 1차 최악에서 200초를 덜어낸다.
SITE_TIMEOUT = 20

# 전체 예산(광역 장애로 전부 타임아웃을 꽉 채우는 최악):
#   1차 = 원천 21회×25s(8.8분) + 사이트 5회×20s(1.7분) + 파생 20p 병렬8×15s(~0.8분)
#       ≈ 11분  →  대기 75초  →  재시도 21회×20s ≈ 7분   합계 ≈ 19분
# watchdog.yml의 timeout-minutes: 30 안에 든다. 이 숫자들을 바꿀 땐 **곱해서**
# 다시 확인할 것 — 주석의 "최악 N분"은 두 번 다 과소평가였다(원래 "~15분"이라고
# 적혀 있었으나 실제로는 30분을 넘겼다).

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
        urllib.request.Request(url, headers=UA), timeout=FETCH_TIMEOUT
    ).read().decode('utf-8', 'replace'))


def live_adv_stats():
    """라이브 data.js(ADV) + data-rest.json·data-size.json(STATS)."""
    txt = urllib.request.urlopen(
        urllib.request.Request(SITE + '/data.js', headers=UA), timeout=SITE_TIMEOUT
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
    # 지연 로드 파일 목록은 split_data가 실제로 쓰는 경로에서 뽑는다 — 손으로
    # 옮겨 적으면 분리 파일이 하나 늘 때 감시만 조용히 뒤처진다.
    # ⚠️ 조회에 실패하면 **반드시 신호를 남긴다**. 예전엔 print만 하고 넘어가서
    # 그 계열이 아래 `if '규모별' in stats` 게이트에 안 걸려 감시가 조용히 꺼졌고,
    # 커버리지 가드는 '초과 계열'만 보므로 원리적으로 못 잡았다(2026-08-07 감사).
    # SKIPPED에 넣어야 main()의 '절반 넘게 못 봤으면 OK는 근거가 없다' 게이트에도 걸린다.
    for lazy in ('/' + f for f in S.LAZY_FILES):
        try:
            got = (get_json(SITE + lazy) or {}).get('STATS') or {}
            if not got:
                SKIPPED.append(lazy + '(빈 응답)')
                print('  경고: %s 응답에 STATS가 없다 — 그 계열 감시가 꺼진다' % lazy)
            stats.update(got)
        except Exception as e:
            SKIPPED.append(lazy)
            print('  경고: %s 조회 실패 (%s) — 그 계열 감시가 이번 회차 꺼진다'
                  % (lazy, str(e)[:40]))
    return adv, stats


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
        urllib.request.Request(SITE + '/share/weekly-map.png', headers=UA), timeout=SITE_TIMEOUT).read()
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


def _q_to_date(q):
    """'2026Q2' → 그 분기 마지막 날. 통계가 분기 단위라 '며칠 지났나'를 재려면 필요."""
    y, n = int(q[:4]), int(q[5])
    m = n * 3
    d = 31 if m in (3, 12) else 30
    return '%04d-%02d-%02d' % (y, m, d)


# ⚠️ 여기 17곳은 **실제 행정구역만**이다. 저장분에는 집계 행이 섞여 있어
# (STATS 22곳 = 17시도 + 전국·수도권·지방·기타광역시·기타지방,
#  ADV.sido 20곳 = 17시도 + 전국·수도권·지방) 전부 더하면 전국의 세 배가 나온다.
# 개수가 20/22/17로 달라 보이는 건 집계를 몇 개 안고 있느냐의 차이일 뿐이다.
# 손으로 옮겨 적으면 정본(개칭·구성 변경)에서 갈라져 합계 검사가 행을 조용히
# 건너뛴다 — 이 파일이 LAZY_STATS에서 겪은 그 패턴이라 sido_zones에서 유도한다.
SIDO17 = [z for z in SZ.ORDER if z not in SZ.AGG]
CAPITAL3 = [z for z in SIDO17 if SZ.REGION[z] == '수도권']
LOCAL14 = [r for r in SIDO17 if r not in CAPITAL3]

# 검사할 (부분들, 전체) 쌍. 시도합=전국 하나만 보면 '어딘가 틀렸다'까지만 알지만,
# 집계 관계를 함께 보면 수도권/지방 중 어느 쪽인지 갈려 범위가 1/3로 줄어든다.
# 넷 다 2026-08-08 실측으로 전 구간 성립을 확인하고 넣었다.
SUM_RULES = (
    (SIDO17, '전국', '17시도합=전국'),
    (CAPITAL3, '수도권', '수도권=서울+경기+인천'),
    (LOCAL14, '지방', '지방=나머지14'),
    (['수도권', '지방'], '전국', '전국=수도권+지방'),
)

# 이 검사가 도는 계열 — 원천이 시도별과 독립 '전국' 행을 함께 주는 것들.
SUM_SERIES = ('준공', '착공', '인허가', '분양', '미분양')


def check_sido_sum(stats):
    """17시도 합(null→0) == 저장된 '전국' 행. **전 구간**을 본다.

    왜 필요한가: 나이·원천 대조는 **최신 시점 하나**만 본다. 그런데 모든 수집이
    '최근 N개'만 다시 받으므로 그 창 밖 과거는 최초 시딩 판본이 영구히 굳는다
    (BASIC_MONTHS 8 / ANNUAL_YEARS 3 / RECENT_WEEKS 20 …). 2026-08-08 감사에서
    전세가율 2,593셀·매매지수 6,041셀·주간 시세 360행(제주도가 아니라 제주시)이
    그렇게 굳어 있던 게 드러났는데, 그 전까지 감시는 매일 OK였다.

    이 불변식은 **API를 한 번도 부르지 않는다** — 저장분 안에서 시도 합과 전국
    행을 맞춰보는 것이라 공짜이고, 과거 어느 칸이 오염돼도 그 시점에서 깨진다.
    2026-08-08 실측으로 준공 191/191·착공 186/186·인허가 234/234·분양 129/129·
    미분양 241/241 전부 정확히 성립함을 확인하고 넣었다.

    ⚠️ null은 결측이 아니라 0으로 센다(KOSIS 규약, 위 실측이 그 증거다). 다만
    계열이 그 지역에서 **시작되기 전**의 null은 0이 아니므로, 전국 행이 None인
    시점은 건너뛴다(세종 2012.07 출범 같은 경우가 여기 걸린다).
    """
    out = []
    print('[저장분 정합 — 합계 관계 4종 (API 호출 없음)]')
    for k in SUM_SERIES:
        d = stats.get(k)
        if not d or not d.get('dates') or not (d.get('series') or {}).get('전국'):
            continue
        ser, dates = d['series'], d['dates']
        # 시도 행이 통째로 사라진 것 자체가 사고다(2026-08-06 세종 36110이 존
        # 매핑에서 소거된 전례). 그 경우 아래 합계는 자연히 어긋나지만, 원인이
        # '값이 틀렸다'가 아니라 '행이 없다'라는 걸 따로 말해줘야 헤매지 않는다.
        gone = [r for r in SIDO17 if r not in ser]
        if gone:
            out.append('%s 시도 행 결측: %s — 수집이 그 지역을 통째로 흘렸다'
                       % (k, ', '.join(gone)))
        marks = []
        for parts, whole, label in SUM_RULES:
            # 행이 빠졌으면 합을 **검증할 수 없다**. 없는 걸 0으로 세고 비교하면
            # '값이 틀렸다'는 오탐이 되고, 진짜 원인(행 결측)은 위 `gone`이 말한다.
            if whole not in ser or any(p not in ser for p in parts):
                marks.append('%s(축없음)' % label)
                continue
            bad, n = [], 0
            for i, dt in enumerate(dates):
                v = ser[whole][i] if i < len(ser[whole]) else None
                if v is None:
                    continue
                n += 1
                # 없는 행은 0으로 센다 — 행 자체의 결측은 위 `gone`이 따로 보고한다.
                tot = sum((ser[p][i] or 0) for p in parts
                          if p in ser and i < len(ser[p]))
                if abs(tot - v) > 1:           # 소수 계열의 반올림 여유
                    bad.append('%s(%s %s vs 합 %s)' % (dt, whole, v, tot))
            if bad:
                marks.append('%s ❌%d' % (label, len(bad)))
                # ⚠️ 교정 명령은 계열 소속대로. 분양·미분양은 SUPPLY_CONF 소속이라
                # --heal-basic이 assert로 죽는다 — R-ONE 전량 재시딩(--seed-supply)이 경로다.
                heal = ('--seed-supply' if k in U.SUPPLY_CONF else '--heal-basic %s' % k)
                out.append('%s %s 어긋남 %d건: %s%s — 과거 칸이 굳었을 수 있다'
                           ' (tools/update_adv_data.py %s 로 교정)'
                           % (k, label, len(bad), ', '.join(bad[:3]),
                              ' 외' if len(bad) > 3 else '', heal))
            else:
                marks.append('%s %d/%d' % (label, n, n))
        print('  %-5s %s' % (k, ' · '.join(marks)))
    return out


# 공개일은 생성기의 것을 그대로 쓴다 — 값 사본은 한쪽만 바뀌는 순간 클램프
# 기대값이 갈라져 매일 오탐이거나 진짜 스테일이 가려진다.
INDICATOR_PUBLISHED = I.PUBLISHED


def check_derived_pages(adv, stats):
    """라이브 정적 페이지가 **실제로 지금 데이터로 구워졌는지**.

    지금까지 감시는 data.js만 봤다. 그런데 배포되는 건 그걸로 구운 페이지들이고,
    생성기가 실패해도 데이터 커밋은 진행되던 시절이 있었다(2026-08-07에 exit 1로
    바뀌기 전). 그러면 **데이터는 새 시점, 화면은 옛 시점**인 채로 배포된다 —
    data.js만 보는 감시로는 원리적으로 못 잡는다. 사람이 20장을 열어볼 수도 없다.

    각 페이지가 이미 화면에 찍고 있는 시점 표기를 읽어 데이터와 맞춰본다.
    표기가 아예 없으면 그것도 실패다 — 페이지 구조가 바뀌었는데 감시가 옛 자리를
    보고 있다는 뜻이라, 조용히 통과시키면 감시가 꺼진 채로 남는다.
    """
    out = []
    print('[파생 페이지 — 화면이 데이터와 같은 시점인가]')
    try:
        # zones는 이름 목록이 아니라 지역 딕셔너리 리스트다({'z':'서울', ...}).
        # ⚠️ 집계 셋(전국·수도권·지방)도 페이지가 **있다**(zone/전국/ 등, 같은
        # 생성기가 굽는다). 예전엔 '없다'는 틀린 전제로 빼서, 유입이 가장 많은
        # 전국 페이지의 스테일을 원리적으로 못 잡았다(2026-08-10 리뷰).
        zones = (adv.get('sido') or {}).get('zones') or []
        names = [z.get('z') for z in zones if isinstance(z, dict) and z.get('z')]
        # ⚠️ 기대 시점은 페이지가 실제로 찍는 그 값이어야 한다. 정규식이 잡는
        # '기준 · 분기 적정물량' 문자열의 날짜는 **미분양 기준월**(ADV.sido.unsold_prd)
        # 이다 — 준공 최신월과 비교하면 두 표의 발표 시점이 어긋나는 회차(별개
        # 표라 매년 가능)에 정상 페이지 17곳이 전부 오탐, 반대 조합이면 진짜
        # 스테일을 놓친다(2026-08-10 리뷰).
        exp = (adv.get('sido') or {}).get('unsold_prd')
        if not names or not exp:
            SKIPPED.append('파생 페이지')
            print('  판정 못 함 — sido.zones 또는 sido.unsold_prd가 비었다')
            return out
        # 20페이지를 직렬로 돌면 CDN이 느릴 때 최대 20×60s — 잡 타임아웃을 스스로
        # 넘겨 진짜 신호가 가려진다(2026-08-10 리뷰). 병렬 8 + 15s면 정상시 2 RTT.
        from concurrent.futures import ThreadPoolExecutor

        def _get(n):
            try:
                return n, urllib.request.urlopen(urllib.request.Request(
                    SITE + '/zone/' + urllib.parse.quote(n) + '/', headers=UA),
                    timeout=15).read().decode('utf-8', 'replace')
            except Exception as e:
                return n, e
        with ThreadPoolExecutor(8) as ex:
            got = list(ex.map(_get, names))
        bad = []
        for n, h in got:
            if isinstance(h, Exception):
                bad.append('%s(조회실패 %s)' % (n, str(h)[:20]))
                continue
            m = re.search(r'(\d{4}\.\d{2}) 기준 · 분기 적정물량', h)
            if not m:
                bad.append('%s(시점 표기 없음)' % n)
            elif m.group(1) != exp:
                bad.append('%s(%s)' % (n, m.group(1)))
        if bad:
            print('  지역 %d/%d 일치 — 어긋남: %s' % (len(names) - len(bad), len(names),
                                                 ', '.join(bad[:5])))
            out.append('지역 페이지 %d곳이 데이터(%s)와 다른 시점: %s%s'
                       ' — 생성기가 실패했거나 배포가 안 된 것'
                       % (len(bad), exp, ', '.join(bad[:5]),
                          ' 외' if len(bad) > 5 else ''))
        else:
            print('  지역 %d/%d 일치 (%s)' % (len(names), len(names), exp))
    except Exception as e:
        SKIPPED.append('파생 페이지(지역)')
        print('  지역 판정 못 함 — %s' % str(e)[:60])

    # 지표 페이지 둘. 전세가율은 화면 문구, 입주물량은 JSON-LD의 dateModified를 쓴다
    # (화면에 시점 문구가 없다). ⚠️ dateModified는 datePublished보다 과거가 되지
    # 않도록 클램프된다 — 그 규칙을 모르고 비교하면 매일 오탐이 난다(실제로 처음에
    # 그렇게 짰다가 2026-08-08 예행에서 잡았다).
    try:
        jr = (stats.get('전세가율') or {}).get('dates', [None])[-1]
        h = urllib.request.urlopen(urllib.request.Request(
            SITE + '/jeonse-ratio/', headers=UA), timeout=SITE_TIMEOUT).read().decode('utf-8', 'replace')
        m = re.search(r'(\d{4}\.\d{2}) 기준', h)
        if not m:
            out.append('/jeonse-ratio/에 시점 표기가 없다 — 페이지 구조가 바뀌었는지 확인')
            print('  전세가율  시점 표기 없음')
        elif jr and m.group(1) != jr:
            out.append('/jeonse-ratio/가 %s인데 데이터는 %s' % (m.group(1), jr))
            print('  전세가율  %s (데이터 %s) — 어긋남' % (m.group(1), jr))
        else:
            print('  전세가율  %s 일치' % m.group(1))
    except Exception as e:
        SKIPPED.append('파생 페이지(전세가율)')
        print('  전세가율  판정 못 함 — %s' % str(e)[:60])

    try:
        o = adv.get('occupancy') or {}
        act = [r['p'] for r in (o.get('rows') or []) if not r.get('e')]
        want = None
        if act:
            m = re.match(r'^(\d{4})Q([1-4])$', act[-1])
            if m:
                want = max('%s-%02d-01' % (m.group(1), int(m.group(2)) * 3),
                           INDICATOR_PUBLISHED)
        h = urllib.request.urlopen(urllib.request.Request(
            SITE + '/moveins/', headers=UA), timeout=SITE_TIMEOUT).read().decode('utf-8', 'replace')
        m = re.search(r'"dateModified":\s*"(\d{4}-\d{2}-\d{2})"', h)
        if not m:
            out.append('/moveins/에 dateModified가 없다 — 페이지 구조가 바뀌었는지 확인')
            print('  입주물량  dateModified 없음')
        elif want and m.group(1) != want:
            out.append('/moveins/ dateModified가 %s인데 데이터 기준으로는 %s'
                       % (m.group(1), want))
            print('  입주물량  %s (기대 %s) — 어긋남' % (m.group(1), want))
        else:
            print('  입주물량  %s 일치' % m.group(1))
    except Exception as e:
        SKIPPED.append('파생 페이지(입주물량)')
        print('  입주물량  판정 못 함 — %s' % str(e)[:60])
    return out


def check_region_collisions():
    """원천의 지역 계층에서 **우리 지역 키와 마지막 조각이 겹치는 행**을 찾는다.

    왜 이걸 보는가(2026-08-26, 타겟유저 문서 A 회신에서 발견):
    배치는 R-ONE 계층 이름의 마지막 조각을 지역 키로 쓴다
    (`full.rsplit('>', 1)[-1]` — update_adv_data의 주간·월간 시세). 2026-07
    행정구역 개편에서 광주·전남 위에 `전남광주`가 끼어들었을 때 우리가 무사했던
    게 이 설계 덕이다. `전남광주>광주` → '광주'로 그대로 잡혔다.

    ⚠️ 그런데 이 설계는 **마지막 조각이 유일할 때만** 옳다. 예컨대 원천이
    `경기>동부1권>광주시`를 '광주시' 대신 '광주'로 줄이는 순간, 경기 광주시 값이
    광역시 광주 자리에 섞여 들어간다. 값은 그럴듯하게 나오고 합계 검사도
    통과한다 — **조용히 틀린 데이터**가 되는 경로다.

    나이·합계 검사는 이걸 원리적으로 못 잡는다(시점도 맞고 합도 맞는다).
    그래서 이름 충돌을 따로 본다. 표 하나만 봐도 충분하다 — 재편은 표별로 따로
    오지 않고 R-ONE 계층 전체에 한꺼번에 온다.
    """
    keys = set(U.WEEKLY_REGIONS)
    fails = []
    for label, tbl, cycle in (('주간 시세', U.RONE_TBL['maega'], 'WK'),
                              ('월간 시세', U.RONE_MONTHLY_TBL['maega'], 'MM')):
        try:
            names = rone_region_names(tbl, cycle)
        except Exception as e:
            # 조회 실패는 '충돌 없음'이 아니다 — 못 본 것이다. FETCH_FAIL로 보내
            # 새 IP 재확인 쪽으로 분류되게 한다(SKIPPED는 게이트 분자라 안 쓴다).
            FETCH_FAIL.append('지역명 충돌(%s)' % label)
            print('  %-10s 지역 목록 조회 실패 (%s)' % (label, str(e)[:40]))
            continue
        tails = {}
        for full in names:
            tails.setdefault(full.rsplit('>', 1)[-1], []).append(full)
        hit = {k: v for k, v in tails.items() if k in keys and len(v) > 1}
        if hit:
            for k, v in sorted(hit.items()):
                fails.append('%s 지역명 충돌: %r가 %d개 행에 걸린다 — %s'
                             % (label, k, len(v), ', '.join(sorted(v))))
            print('  %-10s 행 %d개 · 충돌 %d건  실패' % (label, len(names), len(hit)))
        else:
            print('  %-10s 행 %d개 · 충돌 없음' % (label, len(names)))
    return fails


def rone_region_names(tbl, cycle):
    """R-ONE 표의 지역 계층 이름 집합(최신 한 시점).

    이름만 필요하므로 최신 한 페이지만 받는다 — 시점 값은 안 본다.
    """
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
    names = set()
    for blk in get_json(base + '&pIndex=%d&pSize=1000'
                        % ((total // 1000) + 1)).get('SttsApiTblData', []):
        for r in blk.get('row', []) or []:
            nm = (r.get('CLS_FULLNM') or '').strip()
            if nm:
                names.add(nm)
    if not names:
        raise RuntimeError('지역 행 없음')
    return names


def check_age(label, stamp, grace):
    """수집 시점 도장(YYYY-MM-DD)이 grace일보다 오래됐으면 실패 사유를 반환.

    원천 대조(check)와 달리 '언제 마지막으로 받아왔나'만 본다 — 원천에 '최신 시점'
    질의가 없거나, 있어도 일일 쿼터를 감시가 축내면 안 되는 소스에 쓴다.
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


def rone_latest(tbl, cycle, since=None):
    """R-ONE은 과거부터 페이징된다 — 마지막 페이지가 최신이다.

    ⚠️ since(START_WRTTIME)를 주면 서버측에서 기간을 잘라 받는다. 큰 표는 마지막
    페이지 번호가 깊어지고(미분양 55,987행=56쪽), R-ONE이 그 요청을 간헐적으로
    응답 없이 끊는다 — 2026-08-11·14 감시가 미분양에서 실제로 이걸로 실패했다
    (브라우저 UA를 쓰는 배치도 같은 오류로 실패해, UA나 재시도 문제가 아니다).
    감시는 '원천이 우리보다 최신인가'만 보므로 **우리 시점을 하한**으로 잡으면
    된다 — 더 최신이면 반드시 창 안에 들어오니 탐지 능력은 그대로다.
    """
    base = ('https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do'
            '?KEY=%s&Type=json&STATBL_ID=%s&DTACYCLE_CD=%s'
            % (os.environ.get('RONE_API_KEY', ''), tbl, cycle))
    if since:
        base += '&START_WRTTIME=%s' % since
    head = get_json(base + '&pIndex=1&pSize=1')
    total = None
    for blk in head.get('SttsApiTblData', []):
        for h in blk.get('head', []) or []:
            if 'list_total_count' in h:
                total = h['list_total_count']
    if not total and since:
        # 창이 통째로 비면 {'RESULT':{'CODE':'INFO-200'}}가 온다. 여기서 예외를
        # 던지면 '원천 조회 실패'로 읽혀 오경보가 된다 — 필터를 풀고 다시 본다.
        print('  (%s START_WRTTIME=%s 구간이 비어 전량 조회로 되돌림)' % (tbl, since))
        return rone_latest(tbl, cycle)
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


def check(label, ours, getter, grace, _retry=True):
    """원천이 더 최신이고 grace를 넘겨 뒤처졌으면 실패 사유를 반환."""
    if not ours:
        return '%s: 라이브 값이 비어 있음' % label
    try:
        src = getter()
    except Exception as e:
        if _retry:
            # 바로 '건너뜀'으로 확정하지 않는다 — 2026-08-12 원천(KOSIS·R-ONE)
            # 광역 타임아웃 때 잡 2개(=IP 2개)가 다 죽어 오경보가 났다. 실패분을
            # 모아 한 텀 쉬고 retry_failed()가 다시 본다. 그래도 실패하면 그때
            # SKIPPED에 들어가 아래 게이트가 잡는다.
            RETRYQ.append((label, ours, getter, grace))
            print('  %-12s %-12s 원천 조회 실패 (%s) — 막판에 재시도'
                  % (label, ours, str(e)[:40]))
            return None
        # 재시도까지 실패 — 한둘은 넘기고, 대량 건너뜀만 아래에서 잡는다.
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


def retry_failed(fails, wait=None):
    """1차에서 원천 조회에 실패한 계열만 한 텀 쉬고 다시 대조한다.

    잡 단위 재시도(새 IP)는 KOSIS의 IP 차단용이고, 이건 **원천 자체가 잠깐
    죽는** 경우용이다(2026-08-12: 양쪽 IP 모두 타임아웃 → 다음 날 자연 회복).
    판정 게이트를 무디게 하는 게 아니다 — 재시도까지 실패하면 SKIPPED에 들어가
    기존 게이트가 그대로 잡고, 성공하면 뒤처짐 검사도 그대로 받는다.
    """
    global FETCH_TIMEOUT
    if not RETRYQ:
        return
    w = RETRY_WAIT if wait is None else wait
    print('')
    print('[재시도 — 원천 조회 실패 %d계열, %d초 쉬고 다시]' % (len(RETRYQ), w))
    time.sleep(w)
    FETCH_TIMEOUT = 20
    for label, ours, getter, grace in RETRYQ:
        # ⚠️ 뒤처짐(진짜 사유)만 fails에 넣는다. None까지 넣으면 계열당 항목이
        # 두 개가 되어 'SKIPPED×2 > len(fails)' 게이트의 분모가 부풀고, 지속
        # 광역 장애(14/18)가 28>32 거짓으로 **OK를 찍는다** — 감시가 켜진 채
        # 아무것도 안 보는 상태다(2026-08-13 리뷰에서 재현·확정한 회귀).
        r = check(label, ours, getter, grace, _retry=False)
        if r:
            fails.append(r)
    del RETRYQ[:]


EXIT_RETRYABLE = 1      # 조회가 한 군데라도 실패했다 — 새 IP로 다시 볼 가치가 있다
EXIT_DETERMINISTIC = 2  # 네트워크는 멀쩡했다 — 다시 봐도 답이 같다


def _verdict_exit():
    """실패를 '다시 볼 값어치가 있는가'로 갈라 종료 코드를 정한다.

    왜: watchdog.yml은 1차(freshness)를 '의심'으로만 쓰고 판정을 recheck에
    넘긴다 — 새 러너=새 IP라 KOSIS IP 차단을 걸러내려는 설계다. 그런데 실패가
    **순수 뒤처짐**(조회는 다 성공했고 우리 데이터가 늦은 것)일 때는 IP와
    아무 상관이 없다. 그 경우 recheck는 결정론적인 답을 확인하려고 21회 호출과
    최대 30분을 다시 쓴다. 장애 밤에는 두 층이 곱해져 84회가 된다.

    ⚠️ 안전 방향: **애매하면 EXIT_RETRYABLE**이다. 잘못 분류해도 양쪽 다
    빨간불은 뜬다(재시도로 잘못 보내면 오늘과 똑같고, 결정론으로 잘못 보내면
    즉시 red다) — 어느 쪽도 감시가 조용해지지 않는다. 이 성질이 이 변경의
    전제이므로, 여기에 '조용히 통과' 분기를 추가하지 말 것.
    """
    trouble = list(SKIPPED) + list(FETCH_FAIL)
    if trouble:
        print('VERDICT=retry  (조회 실패 %d건: %s — 새 IP로 재확인할 값어치가 있다)'
              % (len(trouble), ', '.join(trouble[:6])))
        sys.exit(EXIT_RETRYABLE)
    print('VERDICT=final  (조회는 전부 성공 — 데이터 자체의 문제라 재확인해도 답이 같다)')
    sys.exit(EXIT_DETERMINISTIC)


def main():
    # 키가 비면 모든 원천 조회가 '건너뜀'이 되어 감시가 조용히 통과한다.
    # 감시자가 무력해진 것을 감시할 사람은 없으니 여기서 바로 실패시킨다.
    missing = [k for k in ('KOSIS_API_KEY', 'RONE_API_KEY', 'ECOS_API_KEY')
               if not os.environ.get(k)]
    if missing:
        print('FAIL: %s 없음 — 원천 대조를 할 수 없습니다 (시크릿 확인)' % ', '.join(missing))
        # 시크릿은 두 잡이 같은 저장소 것을 읽으므로 새 IP로 다시 봐도 똑같이 없다.
        print('VERDICT=final  (시크릿 부재는 재확인 대상이 아니다)')
        sys.exit(EXIT_DETERMINISTIC)

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
    # 지연 로드로 뺀 계열은 split_data.LAZY_STATS가 정본이다. 목록을 여기 손으로
    # 옮겨 적으면 거기 계열이 하나 늘 때 감시만 조용히 뒤처진다 — '규모별'이
    # data-size.json으로 빠졌을 때 실제로 그렇게 감시가 꺼져 있었다(2026-08-04).
    # 라이브에 있어야 할 계열이 사라진 것 자체가 실패다. 조회 실패로 못 받은
    # 경우는 위 live_adv_stats가 SKIPPED에 남겨 뒀다.
    for fname, series in S.LAZY_FILES.items():
        for name in series:
            if name not in stats:
                fails.append('%s이(가) 라이브에 없다 — %s 배포·조회 확인 필요'
                             % (name, fname))
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
        # 하한은 우리 시점 한 달 전 — 원천이 더 최신이면 반드시 이 창에 들어온다.
        # 값이 이상하면(파싱 실패) since 없이 예전처럼 전량을 훑는다.
        since = None
        if last and len(digits(last)) >= 6:
            since = digits(last)[:6]
            y, m = int(since[:4]), int(since[4:6]) - 1
            if m <= 0:
                y, m = y - 1, 12
            since = '%04d%02d' % (y, m)
        fails.append(check(name, last,
                           lambda c=cfg, sc=since: rone_latest(c['tbl'], 'MM', sc),
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

    # 간판 지표(순부족)의 공급·재고 입력. 2026-08-06까지는 건축HUB 단지 수집이
    # 여기 있었는데, 미래 공급을 인허가 기반 준공예정으로 세던 게 착공 기준 대비
    # 1.29~1.68배 과대라 통째로 걷어냈다. 지금 입력은 위에서 이미 대조한 국토부
    # 준공·착공(SUPPLY_CONF)뿐이라 별도 감시 구획이 필요 없다.
    # 대신 라이브 점수 블록이 옛 시점에 굳는 것만 본다 — data-core.js의 ADV.sido가
    # 갱신을 멈추면 홈 표의 미래 구간이 조용히 정지한다.
    print('[시도 공급 지표 — ADV.sido]')
    try:
        core = urllib.request.urlopen(
            urllib.request.Request(SITE + '/data-core.js', headers=UA),
            timeout=SITE_TIMEOUT).read().decode('utf-8', 'replace')
        # ⚠️ 정규식으로 'L' 값만 긁지 않는다 — 키 순서가 바뀌면 조용히 못 찾는다.
        # ADV 블록을 통째로 파싱해 지역 수까지 본다.
        m = re.search(r'const ADV=(\{.*?\});\s*const STATS', core, re.S)
        sido = json.loads(m.group(1)).get('sido') if m else None
        if not sido or not sido.get('zones'):
            fails.append('라이브 data-core.js에 ADV.sido가 없다 — 홈 표가 안 그려진다')
        else:
            n_z = len(sido['zones'])
            print('  실적 마지막 분기 %s · 착공 %s · 미래 %d분기 · 지역 %d곳'
                  % (sido.get('L'), sido.get('S'), sido.get('H', 0), n_z))
            if n_z < 20:
                fails.append('ADV.sido 지역이 %d곳뿐이다(20곳이어야 함) — 빠진 곳: %s'
                             % (n_z, ', '.join(sido.get('missing') or ['?'])))
            fails.append(check_age('시도 지표', None if not sido.get('L') else
                                   _q_to_date(sido['L']), 200))
    except Exception as e:
        # 이건 조회 실패다 — SKIPPED에는 안 넣는다(위 게이트의 분자를 바꾸면
        # 안 되므로). 대신 FETCH_FAIL에 남겨 '새 IP로 재확인' 쪽으로 분류되게 한다.
        FETCH_FAIL.append('ADV.sido')
        fails.append('ADV.sido 조회 실패(%s) — data-core.js 배포 확인 필요' % str(e)[:60])

    print('[지역 계층 — 이름 충돌 (배치의 rsplit 매핑이 성립하는가)]')
    fails.extend(check_region_collisions())

    fails.extend(check_sido_sum(stats))
    fails.extend(check_derived_pages(adv, stats))

    # 커버리지 가드: 라이브에 있는데 위에서 한 번도 대조 안 한 계열을 잡는다.
    # 분양·미분양이 SUPPLY_CONF에 있다는 이유로 몇 주간 감시 밖에 있었다 — 사람이
    # 기억으로 막을 일이 아니라서, 새 계열이 늘면 감시가 스스로 실패하게 둔다.
    covered = (set(U.BASIC_CONF) | set(U.ANNUAL_CONF) | set(U.SUPPLY_CONF)
               | set(S.LAZY_STATS) | {'금리'})
    uncovered = sorted(set(stats) - covered)
    if uncovered:
        fails.append('감시 누락 계열 %s — check_freshness.py에 대조를 추가할 것'
                     % ', '.join(uncovered))

    retry_failed(fails)
    _gate(fails)


def _gate(fails):
    """판정 게이트. 통과하면 그냥 돌아오고, 아니면 _verdict_exit로 나간다.

    main()에서 떼어 둔 이유는 시험 때문이다 — 게이트가 main 안에 있으면 원천을
    스무 번 부르지 않고는 '주간이 빠졌을 때 실패하나'를 확인할 수 없다.
    `fails`는 계열별 check() 결과 목록이고, 통과한 계열은 None이 들어 있어
    len(fails)가 곧 '검사한 계열 수'다(아래 개수 게이트의 분모).
    """
    bad = [f for f in fails if f]
    print('')
    if bad:
        # 뒤처짐과 감시 누락이 섞이므로 제목은 중립적으로 쓴다.
        print('FAIL: 문제 %d건' % len(bad))
        for b in bad:
            print('  - %s' % b)
        print('  → update-cloud 실행 이력, 해당 KOSIS 표 ID 변경/폐지 여부 확인')
        _verdict_exit()
    lost = [s for s in CRITICAL_SERIES if s in SKIPPED]
    if lost:
        # 개수 게이트보다 먼저 본다. 4/17은 임계를 못 넘지만 그 4개가 주간을
        # 포함하면 '오늘 주간을 확인하지 못했다'는 뜻이고, 그건 초록불로 덮을
        # 사실이 아니다(위 CRITICAL_SERIES 주석 참고).
        print('FAIL: 핵심 계열을 대조하지 못했습니다 — %s' % ', '.join(lost))
        print('  → 원천(R-ONE) 장애·API 키·표 ID 확인. 개수와 무관하게 실패시킨다')
        _verdict_exit()
    if len(SKIPPED) * 2 > len(fails):
        # 절반 넘게 못 봤으면 'OK'는 근거가 없다. 통과시키면 감시가 켜져 있는
        # 채로 아무것도 안 보는 상태가 된다 — 그게 가장 위험한 실패다.
        print('FAIL: %d/%d 계열을 원천과 대조하지 못했습니다(%d초 쉬고 재시도까지 실패) — %s'
              % (len(SKIPPED), len(fails), RETRY_WAIT, ', '.join(SKIPPED)))
        print('  → API 키 만료·표 ID 변경·원천 장애 여부 확인')
        _verdict_exit()
    if SKIPPED:
        print('참고: %s 계열은 원천 조회 실패로 건너뜀' % ', '.join(SKIPPED))
    print('VERDICT=ok')
    print('OK: 모든 계열이 원천과 같은 시점입니다.')


if __name__ == '__main__':
    main()

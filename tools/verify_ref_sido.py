# -*- coding: utf-8 -*-
"""기준표과 동일한 지역 단위(시도)로 밴드 산출·대조.

지금까지의 오차 원인: 기준표 적정물량은 **시도 단위**인데
생활권과 비교하려고 인구비중으로 쪼갰다. 그 배분이 오차를 넣는다.
(수도권 55,000을 서울권 35.6%로 쪼개면 19,566 — 실제 서울 공급의 2배)

여기서는 배분 없이 기준표과 같은 단위로 산출해 직접 대조한다.
수도권 = 서울+인천+경기 (기준표 표의 '수도권' 그대로).
금리 급변동기는 제외한다.


⚠️ 대체 경로(2026-08-01): 유실된 kapt.json(단지별 준공)·trade_raw.json(실거래)은
재수집(21,641단지 개별 호출 + 실거래 전량)보다 **저장소에 이미 있는 더 나은 자료**로
갈아타는 게 맞다 —
  · 공급 = tools/data/hub_permits.json done_q (건축HUB 준공 실측, 시군구×분기, 659만 세대)
  · 가격 = tools/cache/index_levels.json / zone_index.json (R-ONE 아파트 매매지수 레벨·저점)
HUB는 사이트 공급과 동일 소스라 scale.json(K-apt↔호갱↔사이트 척도 환산)도 불필요해진다.
"""
import io, os, sys, json, re, statistics, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, 'data')

# 입력은 tools/data에서 읽는다. 예전엔 세션 스크래치패드 절대경로를 박아뒀는데,
# 그 디렉터리가 비워지면서 이 도구가 통째로 실행 불가가 됐다(2026-07-31 발견).
# rate_shock.json은 tools/rate_shock.py로 언제든 재생성된다. 나머지 셋은
# 실거래·단지 원자료 캐시라 아직 저장소에 없다 — 아래 안내대로 다시 만들어야 한다.
REBUILD = {
    'rate_shock.json': 'python tools/rate_shock.py 로 재생성',
    'kapt.json':       '단지별 준공 — 재수집 대신 hub_permits.json done_q로 갈아탈 것(위 docstring)',
    'trade_raw.json':  '실거래 원자료 — 재수집 대신 R-ONE 지수(cache/index_levels.json)로 갈아탈 것',
    'lawd.json':       '법정동 코드 캐시 — tools/gen_lawd.py --write 로 재생성(복원 완료)',
}


def need(fn):
    p = os.path.join(DATA, fn)
    if not os.path.exists(p):
        print('입력 없음: tools/data/%s' % fn)
        print('  → %s' % REBUILD.get(fn, '재생성 방법 미상'))
        sys.exit(2)
    return json.load(io.open(p, encoding='utf-8'))


EXCL = set(need('rate_shock.json')['excl_quarters'])
kapt = need('kapt.json')
cache = need('trade_raw.json')
lawd = need('lawd.json')

SD = {'서울특별시': '수도권', '인천광역시': '수도권', '경기도': '수도권',
      '부산광역시': '부산', '대구광역시': '대구', '광주광역시': '광주',
      '대전광역시': '대전', '울산광역시': '울산', '세종특별자치시': '세종',
      '강원특별자치도': '강원', '충청북도': '충북', '충청남도': '충남',
      '전북특별자치도': '전북', '경상북도': '경북', '경상남도': '경남',
      '제주특별자치도': '제주'}
GG = {'동구', '서구', '남구', '북구', '광산구'}     # 광주 자치구


def sd_of(sd_full, sg):
    if '통합' in sd_full:                     # 2026 광주+전남 통합
        return '광주' if sg in GG else '전남'
    return SD.get(sd_full)


# ── 공급 ─────────────────────────────────────────────────────────
sup = collections.defaultdict(lambda: collections.defaultdict(int))
for d in kapt:
    s = sd_of(d['sd'], d['sg'])
    if s:
        sup[s]['%sQ%d' % (d['ym'][:4], (int(d['ym'][4:6]) - 1) // 3 + 1)] += d['n']

# ── 가격 ─────────────────────────────────────────────────────────
cd2s = {}
for k, cd in lawd.items():
    a, b = k.split('|')
    s = sd_of(a, b)
    if s:
        cd2s[cd] = s
pool = collections.defaultdict(lambda: collections.defaultdict(list))
for key, vals in cache.items():
    if not vals:
        continue
    cd, ym = key.split('_')
    s = cd2s.get(cd)
    if s:
        pool[s]['%sQ%d' % (ym[:4], (int(ym[4:6]) - 1) // 3 + 1)] += vals
price = {s: {q: statistics.median(v) for q, v in qm.items() if len(v) >= 20}
         for s, qm in pool.items()}

src = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
adv = json.loads(re.search(r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/',
                           src, re.S).group(1))
REF = adv['occupancy']['ref']

WIN, MA = 2, 4
qn = lambda q: int(q[:4]) * 4 + int(q[5]) - 1
ql = lambda n: '%dQ%d' % (n // 4, n % 4 + 1)


def med3(v, w=3):
    return [statistics.median(v[max(0, i - w // 2):min(len(v), i + w // 2 + 1)])
            for i in range(len(v))]


def band(s, amp, gap, excl=True):
    pm = price.get(s, {})
    qs = sorted(pm, key=qn)
    if len(qs) < 24:
        return None
    vals = [pm[q] for q in qs]
    sm, W = med3(vals), 3
    raw = [i for i in range(W, len(vals) - W)
           if sm[i] == min(sm[i - W:i + W + 1])
           and (sm[i] < sm[i - W] * (1 - amp) or sm[i] < sm[i + W] * (1 - amp))
           and (not excl or qs[i] not in EXCL)]
    ids = []
    for i in raw:
        if ids and i - ids[-1] < gap:
            if sm[i] < sm[ids[-1]]:
                ids[-1] = i
        else:
            ids.append(i)
    if not ids:
        return None
    d = sup.get(s, {})
    obs = []
    for i in ids:
        for j in range(max(0, i - WIN), min(len(qs), i + WIN + 1)):
            n = qn(qs[j])
            obs.append(sum(d.get(ql(n - k), 0) for k in range(MA)) / MA)
    q1, q2, q3 = statistics.quantiles(sorted(obs), n=4)
    return {'lo': round(q1), 'mid': round(q2), 'hi': round(q3), 'n': len(ids),
            'turns': [qs[i] for i in ids]}


ORDER = ['수도권', '부산', '대구', '경남', '경북', '광주', '전남', '대전',
         '충남', '충북', '전북', '강원', '울산', '제주', '세종']

for excl, lab in ((True, '금리 급변동기 제외'), (False, '제외 안 함(대조)')):
    print()
    print('=== 기준표과 동일 단위(시도) · %s ===' % lab)
    print('%-6s %4s %8s %8s %8s %8s %7s %s' % (
        '지역', '반전', '기준표', '하단', '중앙', '상단', '비율', '판정'))
    print('-' * 70)
    rs, inb, tot = [], 0, 0
    for s in ORDER:
        r = REF.get(s)
        b = band(s, 0.05, 6, excl)
        if not b or not r:
            continue
        tot += 1
        ratio = r / b['mid']
        ok = b['lo'] <= r <= b['hi']
        inb += ok
        rs.append(ratio)
        print('%-6s %4d %8s %8s %8s %8s %7.2f %s' % (
            s, b['n'], format(r, ','), format(b['lo'], ','), format(b['mid'], ','),
            format(b['hi'], ','), ratio,
            '밴드안' if ok else ('상단초과' if r > b['hi'] else '하단미만')))
    print('-' * 70)
    if rs:
        print('밴드 안 %d/%d (%.0f%%) · 비율 중앙 %.2f · 평균 %.2f · ±25%% 안 %d곳'
              % (inb, tot, inb / tot * 100, statistics.median(rs),
                 statistics.mean(rs), sum(1 for x in rs if 0.8 <= x <= 1.25)))

print()
print('=== 참고: 반전 시점 (금리 제외 후) ===')
for s in ORDER:
    b = band(s, 0.05, 6, True)
    if b:
        print('  %-6s %d회  %s' % (s, b['n'], ', '.join(b['turns'])))

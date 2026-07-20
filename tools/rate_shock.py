# -*- coding: utf-8 -*-
"""금리 급변동기 식별 — 신쌤 논리의 전제.

신쌤 강의: "부동산 시장의 외부 변수가 영향을 주는 거는 대부분 금리예요.
금리 말고 다른 것들에 영향을 주는 경우는 거의 없습니다.
IMF·서브프라임·레고랜드 같은 외부 변수가 시장의 사이클을 늘리거나 줄이거나 합니다."

즉 시장은 대체로 수급이 결정하지만, 금리가 급변하는 국면에서는 금리가 지배한다.
그 구간의 반전점을 '공급이 만든 반전'으로 세면 순환논증이 된다.

CD금리(91일) 시계열로 급변동기를 데이터로 식별한다.
"""
import sys, os, io, json, collections, statistics
ROOT = r'C:\Users\shpar\OneDrive\문서\Claude\aptweather'
SC = r'C:\Users\shpar\AppData\Local\Temp\claude\C--Users-shpar-OneDrive----Claude\6daa8fa3-db54-41a3-bab0-72d67ac03f73\scratchpad'
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import update_adv_data as U

# ── CD금리 수집 (한국은행 ECOS) ──────────────────────────────────
try:
    rate = U.fetch_rate() if hasattr(U, 'fetch_rate') else None
except Exception:
    rate = None

if not rate:
    # data.js의 STATS['금리']에서 읽는다
    import re
    src = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    st = json.loads(re.search(r'/\*STATS_DATA_START\*/\s*const STATS=(\{.*?\});?\s*/\*STATS_DATA_END\*/',
                              src, re.S).group(1))
    g = st.get('금리', {})
    dates, series = g.get('dates', []), g.get('series', {})
    cd = series.get('CD(91일)') or list(series.values())[0]
    rate = {}
    for d, v in zip(dates, cd):
        if v is None:
            continue
        m = re.match(r'^(\d{4})[.\/-]?(\d{1,2})', str(d))
        if m:
            rate['%s%02d' % (m.group(1), int(m.group(2)))] = float(v)

ps = sorted(rate)
print('CD금리: %s ~ %s (%d개월)' % (ps[0], ps[-1], len(ps)))

# ── 급변동 판정: 12개월 변화폭 ───────────────────────────────────
def ym_add(p, k):
    y, m = int(p[:4]), int(p[4:6]) + k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return '%d%02d' % (y, m)


chg = {}
for p in ps:
    q = ym_add(p, -12)
    if q in rate:
        chg[p] = rate[p] - rate[q]

TH = 1.0     # 12개월 ±1.0%p 이상 = 급변동
shock = sorted(p for p, d in chg.items() if abs(d) >= TH)
print('12개월 변화 ±%.1f%%p 이상인 달: %d개' % (TH, len(shock)))

# 연속 구간으로 묶기
runs, cur = [], []
for p in shock:
    if cur and ym_add(cur[-1], 1) != p:
        runs.append((cur[0], cur[-1]))
        cur = []
    cur.append(p)
if cur:
    runs.append((cur[0], cur[-1]))

print()
print('=== 금리 급변동 구간 ===')
for a, b in runs:
    d0 = chg.get(a, 0)
    lab = '급등' if d0 > 0 else '급락'
    peak = max((abs(chg[p]) for p in chg if a <= p <= b), default=0)
    print('  %s ~ %s  %s (최대 %.1f%%p)' % (a, b, lab, peak))

# 앞뒤 6개월 여유를 둔 제외 구간(분기)
EXCL = set()
for a, b in runs:
    s, e = ym_add(a, -6), ym_add(b, 6)
    p = s
    while p <= e:
        EXCL.add('%sQ%d' % (p[:4], (int(p[4:6]) - 1) // 3 + 1))
        p = ym_add(p, 1)
print()
print('제외 분기 %d개 (앞뒤 6개월 여유 포함)' % len(EXCL))
print('  ', ' '.join(sorted(EXCL)[:40]), '...' if len(EXCL) > 40 else '')

io.open(os.path.join(SC, 'rate_shock.json'), 'w', encoding='utf-8').write(
    json.dumps({'runs': runs, 'excl_quarters': sorted(EXCL)}, ensure_ascii=False))
print('저장: rate_shock.json')

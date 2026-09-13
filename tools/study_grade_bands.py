# -*- coding: utf-8 -*-
"""판정 등급 구간별 이후 16분기 실질 상승률 — 재현 스크립트 (2026-09-13).

docs/2026-09-13-판정기준-재검토-결과.md ②의 수치를 만든다. 배치·시험에는 들어가지
않는다. 지금 화면이 쓰는 sido_zones 산식을 과거 분기에 그대로 적용해 순부족비를
만들고, 매매지수를 ECOS 901Y009 소비자물가 총지수로 나눈 실질 상승률과 맞댄다.

사용:
    ECOS_API_KEY=... python tools/study_grade_bands.py [결과.json]
"""
import io
import json
import math
import os
import random
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else None
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import sido_zones as SZ  # noqa: E402

st = json.loads(re.search(r'const STATS\s*=\s*(\{.*?\});?\s*(?:/\*|const |$)',
                          io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read(),
                          re.S).group(1))

# ---- 물가: ECOS 901Y009 총지수, 분기 ----
k = os.environ['ECOS_API_KEY']
u = ('https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/400/901Y009/Q/2006Q1/2026Q4/0' % k)
rows = json.loads(urllib.request.urlopen(u, timeout=40).read().decode('utf-8'))['StatisticSearch']['row']
CPI = {SZ.qidx(int(r['TIME'][:4]), int(r['TIME'][5])): float(r['DATA_VALUE']) for r in rows}


def q_avg(ser, dates):
    o = {}
    for d, v in zip(dates, ser):
        if v is None:
            continue
        y, m = int(d[:4]), int(d[5:7])
        o.setdefault(SZ.qidx(y, (m - 1) // 3 + 1), []).append(v)
    return {i: sum(v) / len(v) for i, v in o.items() if len(v) == 3}


M = st['매매지수']
RATE = q_avg(st['금리']['series'].get('전국') or list(st['금리']['series'].values())[0],
             st['금리']['dates'])

SIDO = [z for z in SZ.ORDER if z not in SZ.AGG]
H = SZ.LEAD_Q
W = SZ.BACKLOG_WINDOW
FWD = 16

samples = []
for z in SIDO:
    ref = SZ.REF_Q[z]
    dn = SZ.quarterly(st, '준공', z)
    sq = SZ.quarterly(st, '착공', z)
    dby = SZ.demol_q(st, z)
    px = q_avg(M['series'][z], M['dates'])
    if not dn or not sq:
        continue
    lo_dn, lo_st = min(dn), min(sq)
    for L in range(SZ.qidx(2010, 1), SZ.qidx(2026, 4)):
        # 과거 재고창이 준공 자료 안에, 미래 공급이 L 시점에 이미 알려진 착공 안에 있어야 한다
        if L - W + 1 < lo_dn or L - H + 1 < lo_st:
            continue
        if L not in dn or L not in sq:
            continue
        if not (L in px and L + FWD in px and L in CPI and L + FWD in CPI):
            continue
        inow = sum(dn.get(i, 0) - SZ.demol_of(dby, SZ.qparts(i)[0]) - ref
                   for i in range(L - W + 1, L + 1))
        fut = sum(sq.get(i - H, 0) * SZ.CONV for i in range(L + 1, L + H + 1))
        need = ref * H
        ratio = (need - fut - inow) / need
        real = (px[L + FWD] / px[L]) / (CPI[L + FWD] / CPI[L]) - 1
        rw = [RATE[i] for i in range(L, L + FWD + 1) if i in RATE]
        samples.append({'z': z, 'L': L, 'ratio': ratio, 'real': real * 100,
                        'rate_span': (max(rw) - min(rw)) if rw else None})

# 같은 분기의 시장 전체 흐름을 뺀 값 — 공통 사이클이 아니라 '같은 시점 지역 간' 차이를 본다
byL = {}
for s in samples:
    byL.setdefault(s['L'], []).append(s['real'])
for s in samples:
    v = byL[s['L']]
    s['rel'] = s['real'] - sum(v) / len(v)

BANDS = [('<0', -9, 0.0), ('0~0.25', 0.0, 0.25), ('0.25~0.5', 0.25, 0.5),
         ('0.5~1.0', 0.5, 1.0), ('≥1.0', 1.0, 99)]


def band(r):
    for name, lo, hi in BANDS:
        if lo <= r < hi:
            return name


def summarize(sub, key):
    out = []
    for name, lo, hi in BANDS:
        v = sorted(s[key] for s in sub if lo <= s['ratio'] < hi)
        regs = sorted({s['z'] for s in sub if lo <= s['ratio'] < hi})
        if v:
            out.append({'band': name, 'n': len(v), 'mean': sum(v) / len(v),
                        'median': v[len(v) // 2], 'regions': len(regs)})
        else:
            out.append({'band': name, 'n': 0, 'mean': None, 'median': None, 'regions': 0})
    return out


def diff_boot(sub, key, reps=3000, seed=7):
    """0.25~0.5 평균 − 0~0.25 평균. 분기 창이 16분기씩 겹쳐 표본이 독립이 아니므로
    지역 단위로 통째로 다시 뽑는다(클러스터 부트스트랩)."""
    regs = sorted({s['z'] for s in sub})
    by = {z: [s for s in sub if s['z'] == z] for z in regs}

    def stat(pool):
        a = [s[key] for s in pool if 0.0 <= s['ratio'] < 0.25]
        b = [s[key] for s in pool if 0.25 <= s['ratio'] < 0.5]
        if not a or not b:
            return None
        return sum(b) / len(b) - sum(a) / len(a)

    point = stat(sub)
    rnd = random.Random(seed)
    got = []
    for _ in range(reps):
        pool = []
        for _z in regs:
            pool += by[rnd.choice(regs)]
        d = stat(pool)
        if d is not None:
            got.append(d)
    got.sort()
    lo = got[int(0.025 * len(got))]
    hi = got[int(0.975 * len(got)) - 1]
    p_le0 = sum(1 for d in got if d <= 0) / len(got)
    return {'point': point, 'ci95': [lo, hi], 'share_le0': p_le0, 'reps': len(got)}


calm = [s for s in samples if s['rate_span'] is not None and s['rate_span'] <= 1.5]
res = {
    'n_samples': len(samples), 'n_calm': len(calm),
    'L_range': [SZ.qkey(min(s['L'] for s in samples)), SZ.qkey(max(s['L'] for s in samples))],
    'regions': sorted({s['z'] for s in samples}),
    'all_real': summarize(samples, 'real'),
    'all_rel': summarize(samples, 'rel'),
    'calm_real': summarize(calm, 'real'),
    'diff_all_real': diff_boot(samples, 'real'),
    'diff_all_rel': diff_boot(samples, 'rel'),
    'diff_calm_real': diff_boot(calm, 'real'),
}
# 두 하위 구간이 어느 지역·시기로 채워졌는지 — 한두 지역이 구간을 독점하면 차이는 지역 효과다
for name, lo, hi in (('0~0.25', 0.0, 0.25), ('0.25~0.5', 0.25, 0.5)):
    cnt = {}
    for s in samples:
        if lo <= s['ratio'] < hi:
            cnt[s['z']] = cnt.get(s['z'], 0) + 1
    res['who_' + name] = sorted(cnt.items(), key=lambda x: -x[1])
res['samples']=samples
# 한 지역씩 빼고 차이를 다시 잰다 — 한 곳이 하위 구간을 독점하면 차이는 그 지역 효과다
loo=[]
for z0 in sorted({s['z'] for s in samples}):
    sub=[s for s in samples if s['z']!=z0]
    a=[s['real'] for s in sub if 0<=s['ratio']<0.25]; b=[s['real'] for s in sub if 0.25<=s['ratio']<0.5]
    ar=[s['rel'] for s in sub if 0<=s['ratio']<0.25]; br=[s['rel'] for s in sub if 0.25<=s['ratio']<0.5]
    lt=[s['real'] for s in sub if s['ratio']<0]
    if a and b:
        loo.append({'drop':z0,'d_real':sum(b)/len(b)-sum(a)/len(a),'d_rel':sum(br)/len(br)-sum(ar)/len(ar),
                    'lo':sum(a)/len(a),'hi':sum(b)/len(b),'neg':sum(lt)/len(lt) if lt else None})
res['loo']=loo
if OUT:
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(res, ensure_ascii=False, indent=1))
print('\n[한 지역씩 제외] 0~0.25 / 0.25~0.5 / <0 실질 평균, 차이(실질·상대)')
for r in loo:
    print('   -%-5s  %+6.2f / %+6.2f / %+6.2f   차이 %+6.2f · %+6.2f'%(r['drop'],r['lo'],r['hi'],r['neg'] if r['neg'] is not None else float('nan'),r['d_real'],r['d_rel']))
# 겹치지 않는 창만: 지역마다 16분기 간격으로 하나씩
nono=[s for s in samples if (s['L']-min(x['L'] for x in samples))%16==0]
for nm,lo,hi in (('<0',-9,0),('0~0.25',0,0.25),('0.25~0.5',0.25,0.5),('0.5~1.0',0.5,1),('≥1.0',1,99)):
    v=[s['real'] for s in nono if lo<=s['ratio']<hi]
    print('   [겹침 없음] %-9s n=%2d 평균 %+.2f%%'%(nm,len(v),sum(v)/len(v) if v else float('nan')))


def fmt(rows):
    return '\n'.join('   %-9s n=%4d  지역 %2d  평균 %+7.2f%%  중앙 %+7.2f%%'
                     % (r['band'], r['n'], r['regions'], r['mean'] if r['mean'] is not None else float('nan'),
                        r['median'] if r['median'] is not None else float('nan')) for r in rows)


print('표본 %d개 (분기 %s ~ %s, 지역 %d곳) · 금리 잔잔 %d개'
      % (res['n_samples'], res['L_range'][0], res['L_range'][1], len(res['regions']), res['n_calm']))
print('\n[전체] 이후 16분기 실질 상승률');            print(fmt(res['all_real']))
print('\n[전체] 같은 분기 시장 평균을 뺀 상대 성과');  print(fmt(res['all_rel']))
print('\n[금리 잔잔: 창 안 CD금리 폭 ≤1.5%p] 실질');   print(fmt(res['calm_real']))
for key in ('diff_all_real', 'diff_all_rel', 'diff_calm_real'):
    d = res[key]
    print('\n%s  0.25~0.5 − 0~0.25 = %+.2f%%p  95%%구간 [%+.2f, %+.2f]  (차이≤0 비율 %.1f%%)'
          % (key, d['point'], d['ci95'][0], d['ci95'][1], 100 * d['share_le0']))
print('\n0~0.25 채운 지역:', res['who_0~0.25'])
print('0.25~0.5 채운 지역:', res['who_0.25~0.5'])

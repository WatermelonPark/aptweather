# -*- coding: utf-8 -*-
"""/cycle/ 고리 검증 재산정.

여섯 고리의 지역별 상관을 한 기준으로 다시 계산해 cycle/index.html의 D 블록에
넣을 값을 만든다. 전에는 1회성 분석의 결과를 페이지에 직접 적어두었기 때문에
지역 모델이 바뀌어도 따라오지 못했다. 2026-09 광주·전남 통합처럼 판정 단위가
바뀌면 이 스크립트를 다시 돌린다.

분석 대상은 시도에서 세종·제주를 뺀 곳이다. 세종은 2012년 출범이라 시계열이
짧고 계획도시라 전국 사이클과 따로 움직이며, 제주는 분기 공급량이 작아 한두
단지가 상관을 좌우한다. 고리 작동 점수(cycle_strength)만 전 시도를 낸다.

사용법:
    python tools/rebuild_cycle_analysis.py           # 계산 결과를 표로 출력
    python tools/rebuild_cycle_analysis.py --write   # cycle/index.html의 D를 갱신
"""
import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sido_zones as SZ      # noqa: E402  (지역 정의의 정본 — 손 목록 금지)

EXCLUDE = ('세종', '제주')
SIDO = [z for z in SZ.ORDER if z not in SZ.AGG]
PANEL = [z for z in SIDO if z not in EXCLUDE]
SUDO = ('서울', '경기', '인천')
RATE_FROM = 2015        # 금리 고리를 보는 시작 연도. 그 전은 CD금리가 거의 평평해 변화가 없다
SIG_P = 0.10             # 유의 판정 문턱. 시도당 표본이 40~80개라 0.05는 과하게 좁다


# ---------- 통계 ----------

def _betacf(a, b, x):
    tiny, eps = 1e-30, 3e-12
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < tiny:
            d = tiny
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < tiny:
            d = tiny
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def _betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lb = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
          + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lb) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lb) * _betacf(b, a, 1.0 - x) / b


def corr(x, y):
    """피어슨 상관과 양측 p값. 표본이 모자라면 (nan, nan, n)."""
    n = len(x)
    if n < 5:
        return float('nan'), float('nan'), n
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if not sx or not sy:
        return float('nan'), float('nan'), n
    r = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)
    r = max(-0.999999, min(0.999999, r))
    df = n - 2
    t = r * math.sqrt(df / (1.0 - r * r))
    p = _betai(0.5 * df, 0.5, df / (df + t * t))
    return r, p, n


def detrend(v):
    """선형 추세를 뺀 잔차. 수준끼리의 상관이 추세만 보고 커지는 것을 막는다."""
    n = len(v)
    xs = list(range(n))
    mx, mv = sum(xs) / n, sum(v) / n
    den = sum((x - mx) ** 2 for x in xs)
    if not den:
        return list(v)
    b = sum((x - mx) * (a - mv) for x, a in zip(xs, v)) / den
    return [a - (mv + b * (x - mx)) for x, a in zip(xs, v)]


# ---------- 데이터 ----------

def load_stats(path=None):
    txt = open(path or os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    m = re.search(r'const STATS\s*=\s*(\{.*?\});?\s*(?:/\*|const |$)', txt, re.S)
    return json.loads(m.group(1))


def qkey(d):
    y, mo = int(d[:4]), int(d[5:7])
    return (y, (mo - 1) // 3 + 1)


def qshift(k, lag):
    y, q = k
    return (y + (q - 1 + lag) // 4, (q - 1 + lag) % 4 + 1)


def q_avg(series, dates):
    """분기 평균. 지수처럼 수준으로 읽는 계열에 쓴다."""
    o = {}
    for d, v in zip(dates, series):
        if v is not None:
            o.setdefault(qkey(d), []).append(v)
    return {k: sum(v) / len(v) for k, v in o.items() if len(v) == 3}


def q_sum(series, dates):
    """분기 합. 물량처럼 유량으로 읽는 계열에 쓴다. KOSIS의 null은 진짜 0이다."""
    o = {}
    for d, v in zip(dates, series):
        o.setdefault(qkey(d), []).append(0.0 if v is None else v)
    return {k: sum(v) for k, v in o.items() if len(v) == 3}


def y_avg(series, dates):
    o = {}
    for d, v in zip(dates, series):
        if v is not None:
            o.setdefault(d[:4], []).append(v)
    return {k: sum(v) / len(v) for k, v in o.items() if len(v) == 12}


def y_sum(series, dates):
    o = {}
    for d, v in zip(dates, series):
        o.setdefault(d[:4], []).append(0.0 if v is None else v)
    return {k: sum(v) for k, v in o.items() if len(v) == 12}


def pct_change(d):
    ks = sorted(d)
    return {b: (d[b] / d[a] - 1.0) for a, b in zip(ks, ks[1:]) if d[a]}


def paired(src, tgt, lag, shift=qshift):
    xs, ys = [], []
    for k in sorted(src):
        t = shift(k, lag)
        if t in tgt:
            xs.append(src[k])
            ys.append(tgt[t])
    return xs, ys


# ---------- 고리별 계산 ----------

def prep(st):
    """시도별로 쓰는 파생 계열을 한 번에 만들어 둔다."""
    M, J, DN, ST, PM = (st['매매지수'], st['전세지수'], st['준공'],
                        st['착공'], st['인허가'])
    d = {}
    for r in SIDO:
        e = {}
        e['qm'] = q_avg(M['series'][r], M['dates'])
        e['qj'] = q_avg(J['series'][r], J['dates'])
        e['dm'] = pct_change(e['qm'])
        e['dj'] = pct_change(e['qj'])
        e['qdone'] = q_sum(DN['series'][r], DN['dates'])
        e['qstart'] = q_sum(ST['series'][r], ST['dates'])
        e['qpermit'] = q_sum(PM['series'][r], PM['dates'])
        e['ym'] = y_avg(M['series'][r], M['dates'])
        e['ypermit'] = y_sum(PM['series'][r], PM['dates'])
        # 최근 12분기 누적 준공. 유량이 아니라 쌓인 재고를 보는 고리1의 설명변수다
        ks = sorted(e['qdone'])
        e['stock12'] = {k: sum(e['qdone'][x] for x in ks[max(0, i - 11):i + 1])
                        for i, k in enumerate(ks) if i >= 11}
        d[r] = e
    return d


def link1_capital(P):
    """고리1: 공급이 쌓이면 전세가 눌린다. 수도권 분기로 본다."""
    done, dj = {}, {}
    for k in P['서울']['qdone']:
        if all(k in P[s]['qdone'] for s in SUDO):
            done[k] = sum(P[s]['qdone'][k] for s in SUDO)
    for k in P['서울']['dj']:
        if all(k in P[s]['dj'] for s in SUDO):
            # 수도권 전세 변화는 세 시도의 단순 평균으로 본다
            dj[k] = sum(P[s]['dj'][k] for s in SUDO) / 3.0
    xs, ys = paired(done, dj, 1)
    r, p, n = corr(detrend(xs), detrend(ys))
    # 공급 수준 3분위별로 다음 분기 전세 상승률이 어떻게 갈리는지 본다
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    cut = len(order) // 3
    groups = (order[:cut], order[cut:2 * cut], order[2 * cut:])
    rise = [round(sum(ys[i] for i in g) / len(g) * 100, 2) for g in groups]
    return {'levels': ['공급 적음', '보통', '공급 많음'], 'jeonse_rise': rise,
            'r': round(r, 2), 'p': round(p, 3), 'lag': 1, 'n': n}


def link2_sync(P):
    """고리2: 전세가 매매를 떠받친다. 시도별 동시 상관."""
    out = []
    for r in PANEL:
        ks = sorted(set(P[r]['dm']) & set(P[r]['dj']))
        c, p, n = corr([P[r]['dm'][k] for k in ks], [P[r]['dj'][k] for k in ks])
        out.append({'region': r, 'corr': round(c, 2), 'sudo': r in SUDO,
                    'p': round(p, 4), 'n': n})
    out.sort(key=lambda x: -x['corr'])
    return out


def link2_lagcurve(P):
    """고리2의 시차 곡선. 시도별 평균을 뺀 뒤 패널로 합쳐 본다."""
    curve = []
    for lag in range(4):
        xs, ys = [], []
        for r in PANEL:
            a, b = paired(P[r]['dj'], P[r]['dm'], lag)
            if len(a) < 8:
                continue
            ma, mb = sum(a) / len(a), sum(b) / len(b)
            xs += [v - ma for v in a]
            ys += [v - mb for v in b]
        c, p, n = corr(xs, ys)
        curve.append({'lag': lag, 'r': round(c, 3), 'p': round(p, 4), 'n': n})
    return curve


def _yshift(k, lag):
    return str(int(k) + lag)


def link3_permit(P):
    """고리3: 매매가 오르면 이듬해 인허가가 는다. 연 단위로 본다."""
    out = []
    for r in PANEL:
        dm = pct_change(P[r]['ym'])
        dp = pct_change(P[r]['ypermit'])
        xs, ys = paired(dm, dp, 1, shift=_yshift)
        c, p, n = corr(xs, ys)
        out.append({'region': r, 'r': round(c, 2), 'sudo': r in SUDO,
                    'p': round(p, 3), 'n': n})
    out.sort(key=lambda x: -x['r'])
    strong = [x['region'] for x in out if x['r'] >= 0.30]
    broken = [x['region'] for x in out if x['r'] < 0.10]
    sm = [x['r'] for x in out if x['region'] in strong]
    bm = [x['r'] for x in out if x['region'] in broken]
    split = {'strong_mean': round(sum(sm) / len(sm), 2) if sm else 0.0,
             'strong_regions': strong,
             'broken_mean': round(sum(bm) / len(bm), 2) if bm else 0.0,
             'broken_regions': broken}
    return out, split


def _mshift(k, lag):
    y, mo = int(k[:4]), int(k[5:7])
    t = (y * 12 + mo - 1) + lag
    return '%04d.%02d' % (t // 12, t % 12 + 1)


def _roll12(series, dates):
    v = {d[:7]: (0.0 if x is None else x) for d, x in zip(dates, series)}
    ks = sorted(v)
    return {k: sum(v[x] for x in ks[max(0, i - 11):i + 1])
            for i, k in enumerate(ks) if i >= 11}


def link45_leadtime(st):
    """고리4와 5: 인허가는 곧 착공으로, 착공은 몇 해 뒤 준공으로 이어진다."""
    PM, ST, DN = st['인허가'], st['착공'], st['준공']
    permit = _roll12(PM['series']['전국'], PM['dates'])
    start = _roll12(ST['series']['전국'], ST['dates'])
    done = _roll12(DN['series']['전국'], DN['dates'])
    best = max(((corr(*paired(permit, start, L, shift=_mshift))[0], L)
                for L in range(0, 25)), key=lambda x: x[0])
    l4 = {'r': round(best[0], 2), 'lag_months': best[1]}

    def peak(lo, hi):
        s = {k: v for k, v in start.items() if lo <= k < hi}
        cand = [(corr(*paired(s, done, L, shift=_mshift))[0], L)
                for L in range(18, 61)]
        cand = [c for c in cand if c[0] == c[0]]
        return max(cand, key=lambda x: x[0]) if cand else (float('nan'), 0)

    mid = '2018.01'
    o_r, o_l = peak('0000', mid)
    n_r, n_l = peak(mid, '9999')
    a_r, a_l = peak('0000', '9999')
    return l4, {'old_months': o_l, 'new_months': n_l, 'old_r': round(o_r, 3),
                'new_r': round(n_r, 3), 'all_months': a_l, 'all_r': round(a_r, 3)}


def link6_movein(P):
    """고리6: 입주가 쏟아지면 전세가 눌린다. 시차는 0분기와 1분기 중 강한 쪽을 쓴다."""
    out = []
    for r in PANEL:
        cand = []
        for lag in (0, 1):
            xs, ys = paired(P[r]['qdone'], P[r]['dj'], lag)
            c, p, n = corr(xs, ys)
            if c == c:
                cand.append((c, p, n, lag))
        if not cand:
            continue
        c, p, n, lag = min(cand)          # 이론 부호가 음이라 가장 낮은 쪽을 고른다
        sig = bool(p < SIG_P and c < 0)
        out.append({'region': r, 'r': round(c, 2), 'lag': lag,
                    'zone': '수도권' if r in SUDO else '지방',
                    'p': round(p, 3), 'sig': sig, 'n': n,
                    'lagtxt': ('즉시' if lag == 0 else '1분기 뒤') if sig
                              else '효과 약함'})
    out.sort(key=lambda x: x['r'])
    return out


def link6_capital(P):
    """서울만 보면 입주 효과가 약하다. 수도권으로 묶으면 살아나는지 확인한다.

    본문이 "서울 −0.08이 수도권으로 묶으면 −0.38"이라고 인용하는 값이라,
    지역 모델이 바뀌면 이 숫자도 같이 다시 계산해야 한다.
    """
    done, dj = {}, {}
    for k in P['서울']['qdone']:
        if all(k in P[s]['qdone'] for s in SUDO):
            done[k] = sum(P[s]['qdone'][k] for s in SUDO)
    for k in P['서울']['dj']:
        if all(k in P[s]['dj'] for s in SUDO):
            dj[k] = sum(P[s]['dj'][k] for s in SUDO) / 3.0
    cand = []
    for lag in (0, 1):
        c, p, n = corr(*paired(done, dj, lag))
        if c == c:
            cand.append((round(c, 2), round(p, 3), n, lag))
    c, p, n, lag = min(cand)
    return {'r': c, 'p': p, 'n': n, 'lag': lag}


# 한 시도가 단일 생활권인지, 여러 도시가 흩어져 있는지에 따라 입주 효과가
# 갈린다. 본문이 이 대비를 인용하므로 분류를 여기에 둔다. 전남광주는 광역시와
# 도가 섞여 어느 쪽도 아니라 양쪽에서 뺀다.
METRO = ('부산', '대구', '인천', '대전', '울산')
PROVINCE = ('경기', '강원', '충북', '충남', '전북', '경북', '경남')


def link6_scale(l6):
    """단일 도시(광역시)와 여러 도시가 섞인 도의 입주 효과를 갈라 본다."""
    d = {x['region']: x['r'] for x in l6}
    def avg(group):
        v = [d[r] for r in group if r in d]
        return round(sum(v) / len(v), 2) if v else 0.0
    weak = [x['region'] for x in l6 if not x['sig']]
    return {'metro': avg(METRO), 'province': avg(PROVINCE), 'weak': weak}


def supply_ratio(st):
    """공급이 넉넉한 곳일수록 전세가율이 높다. 보급률과 전세가율을 맞춰 본다."""
    B, JR = st['보급률'], st['전세가율']
    rows = []
    for r in PANEL:
        bs = [v for v in B['series'].get(r, []) if v]
        js = [v for v in JR['series'].get(r, [])[-12:] if v is not None]
        if not bs or not js:
            continue
        rows.append({'region': r, 'bogup': round(bs[-1], 1),
                     'jratio': round(sum(js) / len(js), 1)})
    rows.sort(key=lambda x: x['region'])
    c, p, n = corr([x['bogup'] for x in rows], [x['jratio'] for x in rows])
    return rows, round(c, 2), round(p, 4)


def rate_link(st, P):
    """금리가 오르면 매매가 눌린다. 수도권 분기로 본다."""
    R = st['금리']
    base = R['series'].get('전국') or list(R['series'].values())[0]
    qr = q_avg(base, R['dates'])
    dm = {}
    for k in P['서울']['dm']:
        if all(k in P[s]['dm'] for s in SUDO):
            dm[k] = sum(P[s]['dm'][k] for s in SUDO) / 3.0
    ks = sorted(qr)
    dr = {b: qr[b] - qr[a] for a, b in zip(ks, ks[1:]) if b[0] >= RATE_FROM}
    xs, ys = paired(dr, dm, 0)
    c, p, n = corr(xs, ys)
    return {'r': round(c, 2), 'p': round(p, 4), 'n': n}


def cycle_strength(P):
    """여섯 고리 중 그 지역에서 실제로 작동하는 것이 몇 개인지 센다.

    고리마다 이론이 말하는 부호가 있다. 부호가 맞고 우연으로 보기 어려우면
    (양측 p가 0.10 미만) 작동하는 것으로 세어 1점을 준다. 세종과 제주는
    표본이 짧아 점수가 낮게 나오지만, 빼지 않고 그대로 보여준다.
    """
    rows = []
    for r in SIDO:
        e = P[r]
        score, detail = 0, {}
        tests = (
            # 고리1: 입주가 많은 분기일수록 다음 분기 전세가 눌린다(추세는 빼고 본다)
            ('l1', paired(e['qdone'], e['dj'], 1), -1),
            # 고리2: 전세가 오르면 매매도 오른다
            ('l2', (lambda ks: ([e['dj'][k] for k in ks], [e['dm'][k] for k in ks]))
                   (sorted(set(e['dm']) & set(e['dj']))), +1),
            # 고리3: 매매가 오르면 이듬해 인허가가 는다
            ('l3', paired(pct_change(e['ym']), pct_change(e['ypermit']), 1, shift=_yshift), +1),
            # 고리4: 인허가가 나면 곧 착공으로 이어진다
            ('l4', paired(e['qpermit'], e['qstart'], 1), +1),
            # 고리5: 착공은 두세 해 뒤 준공이 된다
            ('l5', paired(e['qstart'], e['qdone'], 11), +1),
            # 고리6: 입주가 쏟아지면 전세가 눌린다
            ('l6', min((corr(*paired(e['qdone'], e['dj'], L))[:2] + (L,)
                        for L in (0, 1)), key=lambda x: x[0]), -1),
        )
        for key, data, sign in tests:
            if key == 'l6':
                c, p = data[0], data[1]
            elif key == 'l1':
                xs, ys = data
                c, p, _ = (corr(detrend(xs), detrend(ys)) if len(xs) >= 5
                           else (float('nan'), float('nan'), 0))
            else:
                c, p, _ = corr(*data)
            ok = bool(c == c and p == p and p < SIG_P and c * sign > 0)
            detail[key] = ok
            score += 1 if ok else 0
        rows.append({'region': r, 'score': score, 'detail': detail})
    rows.sort(key=lambda x: -x['score'])
    return rows


# ---------- 조립 ----------

# 페이지의 차트가 실제로 읽는 키. 여기에 있는 것만 D에 넣는다.
KEYS = ('sync', 'link1_new', 'link3_regional', 'link6_regional', 'cycle_strength')

# 계산은 하되 페이지에는 싣지 않는 값. 본문에 이미 글자로 적혀 있어 D에 두면
# 같은 숫자를 두 곳에 보관하는 셈이고, 방문자는 읽지도 않을 5KB를 받게 된다.
# 대신 ANALYSIS 파일에 남겨 다음 재산정 때 견주고 시험이 본문과 대조한다.
ARCHIVE_ONLY = ('l2_lagcurve', 'link3_split', 'supply_ratio', 'sr_corr',
                'leadtime', 'cycle_links', 'confidence')

# 페이지 어디서도 읽지 않는 채로 남아 있던 값들. 지역 모델이 바뀌어도 따라오지
# 못해 옛 지역명이 그대로 남으므로 갱신할 때 같이 지운다.
DROP = ARCHIVE_ONLY + ('flow_vs_stock', 'flow_mean', 'stock_mean',
                       'sudo_mean', 'jibang_mean', 'seoul', 'seoul_l2',
                       'rate_facts')

# 계산 결과를 통째로 남기는 자리. 페이지에서 뺀 근거가 여기 있다.
ANALYSIS = os.path.join(ROOT, 'tools', 'data', 'cycle_analysis.json')


def build(st):
    P = prep(st)
    sync = link2_sync(P)
    lagc = link2_lagcurve(P)
    l1 = link1_capital(P)
    l3, l3split = link3_permit(P)
    l4, lead = link45_leadtime(st)
    l6 = link6_movein(P)
    sr, sr_corr, sr_p = supply_ratio(st)
    rate = rate_link(st, P)
    l6_sudo = link6_capital(P)
    l6_scale = link6_scale(l6)
    strength = cycle_strength(P)

    sync_mean = sum(x['corr'] for x in sync) / len(sync)
    sync_pos = sum(1 for x in sync if x['corr'] > 0 and x['p'] < SIG_P)
    l6_sig = [x for x in l6 if x['sig']]
    l6_mean = sum(x['r'] for x in l6_sig) / len(l6_sig) if l6_sig else 0.0
    l3_mean = sum(x['r'] for x in l3) / len(l3)
    lag_best = max(lagc, key=lambda x: x['r'])

    links = [
        {'from': '누적공급\n부족', 'to': '전세가\n상승', 'lag': '구조적',
         'r': l1['r'], 'desc': '공급 늘면 전세 눌림(1분기 시차)',
         'strong': abs(l1['r']) >= 0.25, 'sign': '역'},
        {'from': '전세가\n상승', 'to': '매매가\n상승', 'lag': '동시~선행',
         'r': round(sync_mean, 2), 'desc': '전세가 매매를 떠받쳐 밀어올림',
         'strong': True, 'sign': '정'},
        {'from': '매매가\n상승', 'to': '인허가\n증가', 'lag': '약 1년',
         'r': round(l3_mean, 2), 'desc': '건설사 관망 후 사업 추진',
         'strong': False, 'sign': '정'},
        {'from': '인허가\n증가', 'to': '착공\n증가',
         'lag': '동시' if l4['lag_months'] <= 2 else '%d개월' % l4['lag_months'],
         'r': l4['r'], 'desc': '인허가 나면 곧 착공', 'strong': True, 'sign': '정'},
        {'from': '착공\n증가', 'to': '준공\n증가', 'lag': '2~3년+',
         'r': lead['all_r'], 'desc': '공사기간(길어지는 중)', 'strong': True,
         'sign': '정'},
        {'from': '준공\n증가', 'to': '전세가\n하락', 'lag': '약 1분기',
         'r': round(l6_mean, 2), 'desc': '입주물량이 전세를 누름', 'strong': True,
         'sign': '역'},
    ]

    conf = {
        'link1': {'level': '높음', 'r': l1['r'],
                  'basis': '수도권 분기 추세제거 후 상관 %.2f(1분기 시차). 공급 늘면 전세 눌림' % l1['r'],
                  'n': '수도권 분기 %d개' % l1['n']},
        'link2': {'level': '매우 높음', 'r': round(sync_mean, 2),
                  'basis': '%d개 시도 중 %d곳에서 양(+)·통계적으로 유의. 평균 %.2f'
                           % (len(sync), sync_pos, sync_mean),
                  'n': '시도당 분기 %d개' % sync[0]['n']},
        'link3': {'level': '지역별로 갈림', 'r': l3split['strong_mean'],
                  'basis': '택지 여유 지역(%s)은 1년 뒤 인허가로 이어짐(평균 %.2f). 택지 포화된 곳(%s)은 끊김'
                           % ('·'.join(l3split['strong_regions'][:3]),
                              l3split['strong_mean'],
                              '·'.join(l3split['broken_regions'][:3])),
                  'n': '시도별 연 %d개' % l3[0]['n']},
        'link45': {'level': '매우 높음', 'r': lead['all_r'],
                   'basis': '착공→준공 리드타임이 과거 %d개월→최근 %d개월로 증가. 관계 자체는 r %.2f로 견고'
                            % (lead['old_months'], lead['new_months'], lead['all_r']),
                   'n': '전국 월별'},
        'link6': {'level': '높음(지역한정)', 'r': round(l6_mean, 2),
                  'basis': '%d개 시도 중 %d곳에서 음(-) 유의. 전국 단위에선 안 보이고 지역서만 나타남'
                           % (len(l6), len(l6_sig)),
                  'n': ('시도당 분기 %d개' % min(x['n'] for x in l6)
                        if min(x['n'] for x in l6) == max(x['n'] for x in l6)
                        else '시도당 분기 %d~%d개' % (min(x['n'] for x in l6),
                                                 max(x['n'] for x in l6)))},
        'rate': {'level': '매우 높음', 'r': rate['r'],
                 'basis': '수도권 금리변화 vs 매매변화 상관 %.2f' % rate['r'],
                 'n': '분기 %d개' % rate['n']},
    }

    return {
        'sync': [{k: v for k, v in x.items() if k in ('region', 'corr', 'sudo')}
                 for x in sync],
        'l2_lagcurve': [{'lag': x['lag'], 'r': x['r'], 'p': x['p']} for x in lagc],
        'link1_new': {k: l1[k] for k in ('levels', 'jeonse_rise', 'r', 'p', 'lag')},
        'link3_regional': [{k: v for k, v in x.items() if k in ('region', 'r', 'sudo')}
                           for x in l3],
        'link3_split': l3split,
        'link6_regional': [{k: v for k, v in x.items()
                            if k in ('region', 'r', 'lag', 'zone', 'p', 'sig', 'lagtxt')}
                           for x in l6],
        'supply_ratio': sr,
        'sr_corr': sr_corr,
        'leadtime': lead,
        'cycle_strength': [{'region': x['region'], 'score': x['score']}
                           for x in strength],
        'cycle_links': links,
        'confidence': conf,
        '_extra': {'sync_mean': round(sync_mean, 3), 'sync_pos': sync_pos,
                   'l6_sig': len(l6_sig), 'l6_total': len(l6),
                   'l3_mean': round(l3_mean, 3), 'lag_best': lag_best,
                   'rate': rate, 'sr_p': sr_p, 'l4': l4, 'l6_sudo': l6_sudo, 'l6_scale': l6_scale,
                   'seoul': {'sync': next(x['corr'] for x in sync if x['region'] == '서울'),
                             'l6': next(x['r'] for x in l6 if x['region'] == '서울')},
                   'strength_detail': strength},
    }


def splice(page, D):
    """cycle/index.html의 const D에서 우리가 다시 계산한 키만 갈아끼운다."""
    txt = open(page, encoding='utf-8').read()
    m = re.search(r'(const D=)(\{.*?\});\n', txt, re.S)
    if not m:
        raise RuntimeError('cycle 페이지에서 const D를 찾지 못했다')
    cur = json.loads(m.group(2))
    for k in KEYS:
        if k not in D:
            raise RuntimeError('재계산 결과에 %s가 없다' % k)
        cur[k] = D[k]
    for k in DROP:
        cur.pop(k, None)
    dead = [k for k in cur if not re.search(r'D\.%s\b|D\[.%s.\]' % (k, k),
                                           txt[:m.start()] + txt[m.end():])]
    if dead:
        raise RuntimeError('페이지가 읽지 않는 키가 D에 남았다: %s'
                           % ', '.join(sorted(dead)))
    new = m.group(1) + json.dumps(cur, ensure_ascii=False) + ';\n'
    out = txt[:m.start()] + new + txt[m.end():]
    open(page, 'w', encoding='utf-8', newline='\n').write(out)
    return len(cur)


def report(D):
    x = D['_extra']
    print('[고리2] 전세→매매 동조성 (%d곳)' % len(D['sync']))
    for r in D['sync']:
        print('  %-6s %.2f' % (r['region'], r['corr']))
    print('  평균 %.3f · 양이면서 유의한 곳 %d/%d'
          % (x['sync_mean'], x['sync_pos'], len(D['sync'])))
    print('  시차곡선: ' + ', '.join('lag%d r=%.3f(p=%.3f)' % (c['lag'], c['r'], c['p'])
                                   for c in D['l2_lagcurve']))
    print()
    print('[고리1] 수도권 누적공급→전세: r=%.2f p=%.3f · 3분위 상승률 %s'
          % (D['link1_new']['r'], D['link1_new']['p'], D['link1_new']['jeonse_rise']))
    print()
    print('[고리3] 매매→이듬해 인허가')
    for r in D['link3_regional']:
        print('  %-6s %+.2f' % (r['region'], r['r']))
    s = D['link3_split']
    print('  작동 %s (평균 %.2f) / 끊김 %s (평균 %.2f)'
          % ('·'.join(s['strong_regions']), s['strong_mean'],
             '·'.join(s['broken_regions']), s['broken_mean']))
    print()
    print('[고리4·5] 인허가→착공 r=%.2f(%d개월) · 착공→준공 과거 %d개월(r %.2f) → 최근 %d개월(r %.2f)'
          % (x['l4']['r'], x['l4']['lag_months'], D['leadtime']['old_months'],
             D['leadtime']['old_r'], D['leadtime']['new_months'], D['leadtime']['new_r']))
    print()
    print('[고리6] 준공→전세 (음이고 유의한 곳 %d/%d)' % (x['l6_sig'], x['l6_total']))
    for r in D['link6_regional']:
        print('  %-6s %+.2f p=%.3f %s %s'
              % (r['region'], r['r'], r['p'], '유의' if r['sig'] else '  ', r['lagtxt']))
    print()
    print('[보급률↔전세가율] r=%.2f (p=%.4f, %d곳)'
          % (D['sr_corr'], x['sr_p'], len(D['supply_ratio'])))
    print('[서울/수도권] 서울 sync %.2f · 서울 link6 %.2f · 수도권으로 묶으면 %.2f (lag%d, p=%.3f)'
          % (x['seoul']['sync'], x['seoul']['l6'], x['l6_sudo']['r'],
             x['l6_sudo']['lag'], x['l6_sudo']['p']))
    print('[고리6 스케일] 광역시 평균 %.2f · 도 평균 %.2f · 효과 약한 곳 %s'
          % (x['l6_scale']['metro'], x['l6_scale']['province'],
             '·'.join(x['l6_scale']['weak'])))
    print('[금리] 수도권 금리변화↔매매변화 r=%.2f (분기 %d개)'
          % (x['rate']['r'], x['rate']['n']))
    print()
    print('[고리 작동 점수] 6점 만점')
    for r in x['strength_detail']:
        d = r['detail']
        print('  %-6s %d점  %s' % (r['region'], r['score'],
                                  ' '.join(k if d[k] else '·' for k in
                                           ('l1', 'l2', 'l3', 'l4', 'l5', 'l6'))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='cycle/index.html을 갱신한다')
    ap.add_argument('--data', default=None, help='읽을 data.js 경로')
    ap.add_argument('--json', default=None, help='계산 결과를 이 경로에 저장한다')
    a = ap.parse_args()
    st = load_stats(a.data)
    D = build(st)
    report(D)
    if a.write:
        n = splice(os.path.join(ROOT, 'cycle', 'index.html'), D)
        path = a.json or ANALYSIS
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        open(path, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(D, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
        print('\ncycle/index.html 갱신: 차트가 읽는 키 %d개를 다시 계산했다(D는 키 %d개)'
              % (len(KEYS), n))
        print('계산 근거 전체: %s' % os.path.relpath(path, ROOT))
    elif a.json:
        open(a.json, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(D, ensure_ascii=False, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()

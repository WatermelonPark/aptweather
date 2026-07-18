# -*- coding: utf-8 -*-
"""적정 입주물량 밴드 재산출·진단 도구.

방법론(신쌤): 하단 = 하락→상승 전환(저점) 시점의 입주물량,
              상단 = 상승→하락 전환(고점) 시점의 입주물량.
소스: 실거래 매매가격지수(KOSIS DT_KAB_11672_S1, 2006~) 분기평균에서 전환점을 찾고,
      그 시점 입주물량(ADV.occupancy, 준공실적 2017~ · ±2분기 평균)을 읽는다.

⚠️ 근본 한계(2026-07 기준):
  - 입주물량 실측이 2017Q1~ 이라 그 이전 전환점은 매칭 불가.
  - 2021~2023 사이클이 금리쇼크에 지배되어, 저점은 대부분 2023Q1(금리 피크아웃)에
    몰리고 사이클 고점(2021~22)은 쇼크로 제외됨 → '공급 기반' 전환점 분리가 어렵다.
  - 따라서 산출값은 참고용이며, 표본·신뢰도를 함께 보고 판단할 것.
    기존 신쌤 HWP 밴드가 더 안정적일 수 있다.

사용:
  python tools/recompute_bands.py              # 진단 리포트만 (덮어쓰지 않음)
  python tools/recompute_bands.py --json        # 실측 제안 밴드를 JSON으로 출력
  (index.html 반영은 값 검토 후 수동으로. 자동 --apply는 의도적으로 만들지 않음.)
"""
import io, os, re, sys, json, statistics, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import update_adv_data as U  # noqa: E402

SALE_IDX = {'orgId': '408', 'tblId': 'DT_KAB_11672_S1'}   # 아파트 매매 실거래가격지수
SHOCK = (2021.75, 2023.5)    # 금리쇼크기 — 고점(상단) 전환만 제외
MIN_GAP_Q = 6                # 전환점 최소 이격 (분기) — 미세 진동 배제
AMP = 0.04                   # 극값 최소 진폭 (4%) — 완만한 사이클 저점도 포착
HALF = 2                     # 입주물량 ±분기 평균 창

def qnum(q):  y, k = q.split('Q'); return int(y) + (int(k) - 1) * 0.25
def qkey(p):  return '%sQ%d' % (p[:4], (int(p[4:6]) - 1) // 3 + 1)
def in_shock(q): return SHOCK[0] <= qnum(q) <= SHOCK[1]


def fetch_sale_index_quarterly():
    """실거래 매매지수 → {지역: {분기: 지수}} (분기평균)."""
    raw = U.kosis(dict(SALE_IDX, objL1='ALL', itmId='ALL', prdSe='M', newEstPrdCnt='250'))
    idx = {}
    for r in raw:
        reg = (r.get('C1_NM') or '').strip()
        try: v = float(r['DT'])
        except (TypeError, ValueError, KeyError): continue
        idx.setdefault(reg, {}).setdefault(qkey(r['PRD_DE']), []).append(v)
    return {reg: {q: sum(vs) / len(vs) for q, vs in qm.items()} for reg, qm in idx.items()}


def trim_rebasing(series):
    """직전 분기 대비 25%+ 급변(지수 리베이싱)하면 그 분기부터 절단."""
    qs = sorted(series, key=qnum); out = {}; prev = None
    for q in qs:
        v = series[q]
        if prev is not None and abs(v / prev - 1) > 0.25: break
        out[q] = v; prev = v
    return out


def turning_points(series):
    """분기 지수 → (저점 리스트, 고점 리스트). 3분기 median 스무딩 + window±2 극값
    + 진폭 AMP + 최소 이격 MIN_GAP_Q."""
    qs = sorted(series, key=qnum)
    if len(qs) < 9: return [], []
    sm = [statistics.median([series[qs[j]] for j in range(max(0, i - 1), min(len(qs), i + 2))])
          for i in range(len(qs))]
    lows, highs = [], []; W = 2
    for i in range(W, len(qs) - W):
        c = sm[i]; win = sm[i - W:i + W + 1]
        if c == min(win) and (c < sm[i - W] * (1 - AMP) or c < sm[i + W] * (1 - AMP)): lows.append(qs[i])
        if c == max(win) and (c > sm[i - W] * (1 + AMP) or c > sm[i + W] * (1 + AMP)): highs.append(qs[i])

    def thin(pts, better):
        pts = sorted(pts, key=qnum); out = []
        for p in pts:
            if out and qnum(p) - qnum(out[-1]) < MIN_GAP_Q * 0.25:
                if better(series[p], series[out[-1]]): out[-1] = p
            else: out.append(p)
        return out
    return thin(lows, lambda a, b: a < b), thin(highs, lambda a, b: a > b)


PAST_FROM = (2011, 1)   # 밴드 재산출용 준공실적 확장 시작 (2011~2016 = 금리쇼크 없는 정상 사이클)

def load_occupancy():
    src = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    adv = json.loads(re.search(r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/',
                               src, re.S).group(1))
    occ = adv['occupancy']
    regions = occ['regions']
    by = {reg: {row['p']: row['v'][i] for row in occ['rows']} for i, reg in enumerate(regions)}
    # 과거 준공실적(2011~2016) 병합 — 사이트 데이터는 2017~ 뿐이라, 재산출 전환점 매칭을 위해 확장
    first_p = occ['rows'][0]['p']                          # 보통 '2017Q1'
    end = (int(first_p[:4]), (int(first_p[5]) - 1) * 3 + 1)   # 그 직전월까지
    end = (end[0] - 1, 12) if end[1] == 1 else (end[0], end[1] - 1)
    comp = U.fetch_completions(PAST_FROM, end, regions)
    pastq = U._complete_quarters(comp, regions)           # {(y,q): {reg: 호}}
    for (y, q), row in pastq.items():
        label = '%dQ%d' % (y, q)
        for reg, v in row.items():
            by.setdefault(reg, {}).setdefault(label, v)
    return regions, by, occ.get('band', {}), occ.get('ref', {})


def occ_around(by, reg, q):
    if reg not in by: return None
    qn = qnum(q)
    vals = [v for qq, v in by[reg].items() if v is not None and abs(qnum(qq) - qn) <= HALF * 0.25 + 1e-6]
    return sum(vals) / len(vals) if vals else None


def main():
    as_json = '--json' in sys.argv
    idxq = fetch_sale_index_quarterly()
    regions, occby, oldband, ref = load_occupancy()

    rows, proposal = [], {}
    for reg in regions:
        series = idxq.get(reg)
        lows, highs = ([], [])
        if series: lows, highs = turning_points(trim_rebasing(series))
        MINY = PAST_FROM[0]   # 입주물량 매칭 가능 하한 (준공 확장 시작연도)
        lows = [q for q in lows if qnum(q) >= MINY]                       # 저점: 회복점이라 쇼크기도 포함
        highs = [q for q in highs if qnum(q) >= MINY and not in_shock(q)]  # 고점: 쇼크기 제외
        lo_v = [x for x in (occ_around(occby, reg, q) for q in lows) if x]
        hi_v = [x for x in (occ_around(occby, reg, q) for q in highs) if x]
        lo = round(statistics.median(lo_v)) if lo_v else None
        hi = round(statistics.median(hi_v)) if hi_v else None
        # 신뢰도: 저·고 각 2표본 이상 + 하단<상단
        conf = 'LOW'
        if lo and hi and lo < hi and len(lo_v) >= 2 and len(hi_v) >= 2: conf = 'MED'
        proposal[reg] = {'lo': lo, 'hi': hi, 'nlo': len(lo_v), 'nhi': len(hi_v),
                         'lows': lows, 'highs': highs, 'conf': conf}
        rows.append((reg, lo, hi, len(lo_v), len(hi_v), oldband.get(reg, []), conf))

    if as_json:
        print(json.dumps({r: {'lo': p['lo'], 'hi': p['hi'], 'conf': p['conf']}
                          for r, p in proposal.items()}, ensure_ascii=False, indent=2))
        return

    print('적정 입주물량 밴드 재산출 리포트 (실거래지수 전환점 × 입주물량)')
    print('=' * 74)
    print(f"{'지역':<5}{'실측하단':>7}{'실측상단':>7}{'표본저/고':>9}{'신뢰도':>6}   {'기존밴드':>15}")
    print('-' * 74)
    for reg, lo, hi, nlo, nhi, ob, conf in rows:
        print(f"{reg:<5}{(lo if lo else '-'):>7}{(hi if hi else '-'):>7}"
              f"{f'{nlo}/{nhi}':>9}{conf:>6}   {str(ob):>15}")
    print('-' * 74)
    print('전환점 상세:')
    for reg in regions:
        p = proposal[reg]
        print(f"  {reg}: 저점{p['lows'] or '없음'} 고점{p['highs'] or '없음'}")
    print('=' * 74)
    med = sum(1 for r in rows if r[6] == 'MED')
    print(f"신뢰도 MED(저·고 각 2표본+) 지역: {med}/{len(rows)}.  나머지는 표본 부족 → 기존 밴드 유지 권장.")
    print('⚠️ 저점이 2023Q1(금리 피크아웃)에 몰리고 사이클 고점(2021~22)은 쇼크로 제외됨 —')
    print('   공급 기반 전환점 분리가 어려워 산출값은 참고용. 채택은 지역별 전환점을 보고 수동 판단할 것.')


if __name__ == '__main__':
    main()

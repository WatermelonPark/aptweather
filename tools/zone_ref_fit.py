# -*- coding: utf-8 -*-
"""2단계: 생활권별 적정물량(refq) 직접 적합.

1단계 결론: 공급->가격 관계는 실재하되 금리에 가려져 있다(금리 잔잔 구간에서
r=-0.12~-0.19, 순열 p<0.05). 그래서 저점 1~2개를 역산하는 대신, 금리 잔잔한
분기 전체를 써서 "러닝재고가 향후 가격을 가장 잘 설명하는" refq를 존별로 찾는다.

현재값(기준선): refq_z = ref[시도] * share_z  (share = 존세대수/시도세대수) <- 이게 '안분'.
적합값:         refq_z = k_z * refq_z(기준선).  k_z를 데이터로 정한다.

과적합 통제: k를 (M1)전역 1개 -> (M2)시도별 -> (M3)존별+수축 순으로 늘리며
기간 홀드아웃(전반 적합/후반 평가, 반대도)으로 비교한다.

⚠️ 결론: 존별 적합은 과적합으로 실패했고 안분 유지가 확정됐다(재시도 금지).
   이 파일은 그 검증 기록으로 남긴다. share의 잣대는 2026-07-31에 인구 ->
   주민등록세대수로 바뀌었다(9c52489) — 위 설명은 그 이후 기준이다.
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update_adv_data as U
import zone_index_xcheck3 as X

ANCHOR = 2010 * 4


def zone_ref_base():
    """존 -> (기준 refq(분기 세대), 시도). make_zone_pages.calc()의 share 규칙 복제."""
    t = io.open(os.path.join(HERE, os.pardir, 'data.js'), encoding='utf-8').read()
    import re
    adv = json.loads(re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});\s*/\*ADV_DATA_END\*/',
                               t, re.S).group(1))
    O, LZ = adv['occupancy'], adv['livezone']
    SP = LZ.get('sidopop') or {}
    out = {}
    for z in LZ['zones']:
        ps = '수도권' if z['region'] == '수도권' else (z.get('psido') or '수도권')
        band = (O.get('band') or {}).get(ps)
        refq = (O.get('ref') or {}).get(ps) or (sum(band) / 2 if band else None)
        if not refq:
            continue
        share = min(1.0, z['pop'] / (SP.get(ps) or z['pop'] or 1))
        out[z['z']] = (refq * share, ps, z['pop'])
    return out


def inventory(done, ref, upto):
    """max(0, I + 순공급 - ref)를 ANCHOR부터 굴린 분기별 재고 시계열."""
    I, out = 0.0, {}
    for q in range(ANCHOR, upto + 1):
        I = max(0.0, I + done.get(q, 0) - ref)
        out[q] = I
    return out


def main():
    zq, done, stock, rq = X.load()
    base = zone_ref_base()
    qmax = max(max(s) for s in zq.values())
    print('%-10s %8s %8s %8s   %s' % ('생활권', '기준refq', '분기준공', '비율', '재고>0 비율 / 최종재고'))
    npin = 0
    for z in sorted(zq):
        if z not in base:
            continue
        ref, ps, pop = base[z]
        qs = [q for q in range(ANCHOR, qmax + 1)]
        avg = sum(done[z].get(q, 0) for q in qs) / len(qs)
        inv = inventory(done[z], ref, qmax)
        pos = sum(1 for q in qs if inv[q] > 0) / len(qs)
        if pos < 0.05:
            npin += 1
        print('%-10s %8.0f %8.0f %8.2f   %5.0f%%  %9.0f' % (z, ref, avg, avg / ref if ref else 0,
                                                            pos * 100, inv[qmax]))
    print('\n재고가 거의 항상 0인 존: %d개 (이런 존은 재고가 정보를 못 담는다)' % npin)


if __name__ == '__main__':
    main()


# ---------------------------------------------------------------- 적합 -------
FWD = 8            # 향후 2년
CALM = 0.5         # 금리 잔잔한 분기 비율(1단계에서 정한 기준)


def make_panel(zq, done, stock, rq, refmap, fwd=FWD):
    """refmap(존->refq)로 재고를 굴려 (분기내 demean된) x,y 셀을 만든다.
    x = 재고/재고규모(%), y = 향후 fwd분기 지수변화(%). mv = 예측창 내 기준금리 이동폭."""
    r = rq['기준금리']
    qs = sorted(set(q for s in zq.values() for q in s))
    qs = [q for q in qs if q >= ANCHOR]
    qmax = qs[-1]
    inv = {z: inventory(done[z], refmap[z], qmax) for z in refmap if z in done}
    cells = []
    for q in qs:
        if q + fwd > qmax:
            break
        cell = []
        for z, s in zq.items():
            a, b = s.get(q), s.get(q + fwd)
            if not a or not b or z not in inv or not stock.get(z):
                continue
            cell.append((z, inv[z][q] / stock[z] * 100, (b / a - 1) * 100))
        if len(cell) < 20:
            continue
        mi = sum(c[1] for c in cell) / len(cell)
        mg = sum(c[2] for c in cell) / len(cell)
        win = [r[k] for k in range(q, q + fwd + 1) if k in r]
        mv = (max(win) - min(win)) if win else 0.0
        for z, i, g in cell:
            cells.append({'z': z, 'q': q, 'x': i - mi, 'y': g - mg, 'mv': mv})
    return cells


def calm_cut(cells, frac=CALM):
    s = sorted(c['mv'] for c in cells)
    return s[int(len(s) * frac) - 1]


def score(cells, cut, qfilter=None):
    """목적함수: -corr(재고, 향후수익). 클수록 좋다(기준표 방향)."""
    sub = [c for c in cells if c['mv'] <= cut and (qfilter is None or qfilter(c['q']))]
    if len(sub) < 50:
        return -9.0, 0
    r, n = X.corr([c['x'] for c in sub], [c['y'] for c in sub])
    return -r, len(set(c['q'] for c in sub))

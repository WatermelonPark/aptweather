# -*- coding: utf-8 -*-
"""러닝재고 바닥(max(0,·)) 상한 변형 검증 + 순위 영향.

2단계에서 나온 핵심 발견. 라이브 running_shortage()는 재고를 max(0, ·)로 깎아
'부족'이 누적되지 않는다. 그 결과 서울권처럼 만성 부족인 존은 재고가 늘 0에
붙어 정보를 잃는다(재고>0 비율 6%). 바닥을 풀거나 상한을 두면 예측력이 크게
오른다 — 파라미터를 하나도 늘리지 않고서.

  상한 m = 부족을 최대 m분기치 적정물량까지만 누적(그 이상은 수요 이탈로 간주).
  m=0이 현행, m=None이 무제한.

실행: python tools/zone_floor_cap.py
"""
import sys, io, json, re, os, random, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zone_ref_fit2 as F2
import zone_index_xcheck3 as X

VARIANTS = [(0, '0 = 현행'), (4, '4분기(1년)'), (8, '8분기(2년)'),
            (16, '16분기(4년)'), (32, '32분기(8년)'), (None, '무제한')]


def inv_cap(done, ref, upto, anchor, m):
    lo = None if m is None else -m * ref
    I, out = 0.0, {}
    for q in range(anchor, upto + 1):
        I = I + done.get(q, 0) - ref
        if lo is not None and I < lo:
            I = lo
        out[q] = I
    return out


def objective(f, m, fwd=8, perm=None):
    inv = {}
    for z in f.zones:
        src = perm[z] if perm else z
        ref = f.base[src][0]
        st = f.stock[src] or 1
        iv = inv_cap(f.done[src], ref, f.qmax, f.anchor, m)
        inv[z] = {q: v / st * 100 for q, v in iv.items()}
    xs, ys = [], []
    for q in f.calmq:
        cell = []
        for z in f.zones:
            a, b = f.zq[z].get(q), f.zq[z].get(q + fwd)
            if not a or not b:
                continue
            cell.append((inv[z][q], (b / a - 1) * 100))
        if len(cell) < 20:
            continue
        mi = sum(c[0] for c in cell) / len(cell)
        mg = sum(c[1] for c in cell) / len(cell)
        xs += [c[0] - mi for c in cell]
        ys += [c[1] - mg for c in cell]
    return -X.corr(xs, ys)[0]


def main():
    f = F2.Fitter()
    zones = f.zones[:]
    print('예측력 (금리 잔잔 %d분기, refq는 현재 안분값 그대로)' % len(f.calmq))
    print('  %-14s %8s %8s %8s %8s   %s' % ('부족 누적 상한', 'fwd4Q', 'fwd8Q', 'fwd12Q', 'fwd16Q', 'p(fwd8Q)'))
    for m, nm in VARIANTS:
        v = [objective(f, m, fw) for fw in (4, 8, 12, 16)]
        random.seed(5)
        null = []
        for _ in range(300):
            sh = zones[:]
            random.shuffle(sh)
            null.append(objective(f, m, 8, perm=dict(zip(zones, sh))))
        p = sum(1 for x in null if x >= v[1]) / len(null)
        print('  %-14s %+8.3f %+8.3f %+8.3f %+8.3f   %.3f' % (nm, v[0], v[1], v[2], v[3], p))


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""공급 -> 가격 (횡단면) 검정 + 금리 급변 구간 제외.

xcheck2는 시점 평균을 빼서 금리의 '공통' 효과는 제거했지만, 금리 충격이 존마다
다르게 먹히는 부분(고가·고레버리지 존이 더 크게 반응)은 횡단면 노이즈로 남는다.
여기서는 각 관측의 예측 구간 [q, q+FWD]에서 금리가 얼마나 움직였는지로 셀을
정렬해, 금리 급변 셀을 단계적으로 버리며 상관이 살아나는지 본다(민감도 곡선).
임의의 컷오프 하나를 고르면 그게 곧 p-해킹이라 전 구간을 함께 보고한다.
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update_adv_data as U

ZI = os.path.join(HERE, 'cache', 'zone_index.json')
HUB = os.path.join(HERE, 'data', 'hub_permits.json')
RATES = os.path.join(HERE, 'cache', 'rates.json')
START = 2010 * 4


def qk(m):
    return int(m[:4]) * 4 + (int(m[5:7]) - 1) // 3


def load():
    zi = json.load(io.open(ZI, encoding='utf-8'))['maega']['zones']
    hp = json.load(io.open(HUB, encoding='utf-8'))
    z_of = U._hub_zone_map(U._load_bdong_map())
    done, stock = {}, {}
    for cd, v in hp['sgg'].items():
        z = z_of.get(cd)
        if not z:
            continue
        d = done.setdefault(z, {})
        for q, n in (v.get('done_q') or {}).items():
            y, qq = q.split('Q')
            d[int(y) * 4 + int(qq) - 1] = d.get(int(y) * 4 + int(qq) - 1, 0) + n
        for q, n in (v.get('demol_q') or {}).items():
            y, qq = q.split('Q')
            k = int(y) * 4 + int(qq) - 1
            d[k] = d.get(k, 0) - n
        stock[z] = stock.get(z, 0) + sum((v.get('done_q') or {}).values())
    zq = {z: {qk(m): v for m, v in zip(d['months'], d['vals'])} for z, d in zi.items() if z in done}
    rt = json.load(io.open(RATES, encoding='utf-8'))
    rq = {}
    for nm, s in rt.items():
        q = {}
        for m, v in s.items():
            q.setdefault(qk(m), []).append(v)
        rq[nm] = {k: sum(v) / len(v) for k, v in q.items()}
    return zq, done, stock, rq


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0, n
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    return (sxy / (sxx * syy) ** .5 if sxx > 0 and syy > 0 else 0.0), n


def build(zq, done, stock, rq, LOOK, FWD, ratenm):
    r = rq[ratenm]
    qs = sorted(set(q for s in zq.values() for q in s))
    qs = [q for q in qs if q >= START]
    cells = []
    for q in qs:
        if q + FWD > qs[-1]:
            break
        cell = []
        for z, s in zq.items():
            a, b = s.get(q), s.get(q + FWD)
            if not a or not b or not stock.get(z):
                continue
            sup = sum(done[z].get(k, 0) for k in range(q - LOOK + 1, q + 1))
            cell.append((z, sup / stock[z] * 100, (b / a - 1) * 100))
        if len(cell) < 20:
            continue
        mi = sum(c[1] for c in cell) / len(cell)
        mg = sum(c[2] for c in cell) / len(cell)
        # 예측 구간 내 금리 최대 이동폭(%p)
        win = [r[k] for k in range(q, q + FWD + 1) if k in r]
        mv = (max(win) - min(win)) if win else 0.0
        for z, i, g in cell:
            cells.append({'z': z, 'q': q, 'x': i - mi, 'y': g - mg, 'mv': mv})
    return cells


def main():
    zq, done, stock, rq = load()
    LOOK, FWD = 12, 8
    for ratenm in ('기준금리', '주담대'):
        cells = build(zq, done, stock, rq, LOOK, FWD, ratenm)
        cells.sort(key=lambda c: c['mv'])
        print('=== %s 기준으로 금리 급변 구간 제외 (look=%dQ, fwd=%dQ) ===' % (ratenm, LOOK, FWD))
        print('  %-12s %-16s %-9s %s' % ('유지 비율', '금리이동 상한(%p)', '상관 r', 'n(분기수)'))
        for keep in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3):
            k = int(len(cells) * keep)
            sub = cells[:k]
            r, n = corr([c['x'] for c in sub], [c['y'] for c in sub])
            nq = len(set(c['q'] for c in sub))
            print('  %-12s %-16.2f %+.3f     %d' % ('%d%%' % (keep * 100), sub[-1]['mv'], r, nq))
        print()
    # 가장 잔잔한 절반에서 사분위 스프레드
    cells = build(zq, done, stock, rq, LOOK, FWD, '기준금리')
    cells.sort(key=lambda c: c['mv'])
    calm = cells[:len(cells) // 2]
    calm.sort(key=lambda c: c['x'])
    k = len(calm) // 4
    print('[금리 잔잔한 절반] 공급강도 사분위별 향후 2년 초과수익')
    for i, nm in enumerate(['최저 25%', '2분위', '3분위', '최고 25%']):
        seg = calm[i * k:(i + 1) * k] if i < 3 else calm[3 * k:]
        print('  %-8s 공급편차 %+6.1f%%p -> 초과수익 %+5.2f%%p' %
              (nm, sum(c['x'] for c in seg) / len(seg), sum(c['y'] for c in seg) / len(seg)))
    print('\n제외된 시기:', ', '.join(sorted(set(
        '%dQ%d' % (c['q'] // 4, c['q'] % 4 + 1) for c in cells[len(cells) // 2:]))[:14]), '...')


if __name__ == '__main__':
    main()

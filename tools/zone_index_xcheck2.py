# -*- coding: utf-8 -*-
"""공급 강도 -> 향후 가격 (횡단면 검정).

앞선 '저점에서의 공급' 검정은 두 이유로 무력했다: (1) HUB 준공이 2003년 이전
희박해 초기 저점이 오염됐고, (2) 2013/2023 저점은 전 존이 동시에 겪은 전국
사이클(금리·정책)이라 공급으로 설명될 수 없다.

그래서 시점별 전국 평균을 빼고(=전국 사이클 제거) 남는 '존별 편차'만으로
묻는다: 어떤 분기에 공급이 (자기 존 기준으로) 유난히 많았던 존은, 그 뒤
2년간 가격이 (전국 대비) 덜 올랐는가?
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update_adv_data as U

ZI = os.path.join(HERE, 'cache', 'zone_index.json')
HUB = os.path.join(HERE, 'data', 'hub_permits.json')
START = 2010 * 4      # HUB 준공이 탄탄해진 뒤(3년 소급해도 2007)
LOOK = 12             # 공급 강도 = 직전 12분기 누적
FWD = 8               # 향후 8분기(2년) 가격 변화


def qk(ym):
    return int(ym[:4]) * 4 + (int(ym[5:7]) - 1) // 3


def zone_series():
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
        stock[z] = sum((v.get('done_q') or {}).values()) + stock.get(z, 0)
    return done, stock


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0, n
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0, n
    return sxy / (sxx * syy) ** 0.5, n


def main():
    zi = json.load(io.open(ZI, encoding='utf-8'))['maega']['zones']
    done, stock = zone_series()
    # 존별 분기 지수(월->분기 말)
    zq = {}
    for z, d in zi.items():
        if z not in done:
            continue
        s = {}
        for m, v in zip(d['months'], d['vals']):
            s[qk(m)] = v
        zq[z] = s
    qs = sorted(set(q for s in zq.values() for q in s))
    qs = [q for q in qs if q >= START]

    raw, panel = [], []
    for q in qs:
        if q + FWD > qs[-1]:
            break
        cell = []
        for z, s in zq.items():
            a, b = s.get(q), s.get(q + FWD)
            if not a or not b or not stock.get(z):
                continue
            sup = sum(done[z].get(k, 0) for k in range(q - LOOK + 1, q + 1))
            intensity = sup / stock[z] * 100        # 재고 대비 순공급(%) — 존 규모 정규화
            g = (b / a - 1) * 100
            cell.append((z, intensity, g))
        if len(cell) < 20:
            continue
        mi = sum(c[1] for c in cell) / len(cell)
        mg = sum(c[2] for c in cell) / len(cell)
        for z, i, g in cell:
            raw.append((i, g))
            panel.append((z, q, i - mi, g - mg))    # 시점 평균 제거 = 전국 사이클 제거

    r0, n0 = corr([a for a, _ in raw], [b for _, b in raw])
    r1, n1 = corr([a for _, _, a, _ in panel], [b for _, _, _, b in panel])
    print('공급강도(직전3년 순공급/재고 %%) -> 향후 2년 지수변화')
    print('  원자료          r = %+.3f  (n=%d)' % (r0, n0))
    print('  전국사이클 제거  r = %+.3f  (n=%d)   <- 기준표 모형이 맞다면 음(-)이어야' % (r1, n1))

    # 사분위별 평균(해석용)
    p = sorted(panel, key=lambda x: x[2])
    k = len(p) // 4
    print('\n  공급강도 사분위별 향후 2년 초과수익(전국대비 %%p)')
    for i, nm in enumerate(['최저 25%', '2분위', '3분위', '최고 25%']):
        seg = p[i * k:(i + 1) * k] if i < 3 else p[3 * k:]
        print('    %-8s 공급편차 %+6.1f%%p -> 초과수익 %+5.2f%%p' %
              (nm, sum(x[2] for x in seg) / len(seg), sum(x[3] for x in seg) / len(seg)))

    # 존별
    byz = {}
    for z, q, i, g in panel:
        byz.setdefault(z, []).append((i, g))
    rs = []
    for z, v in byz.items():
        r, n = corr([a for a, _ in v], [b for _, b in v])
        rs.append((r, z, n))
    rs.sort()
    neg = sum(1 for r, _, _ in rs if r < 0)
    print('\n  존별 상관: 음(-)인 존 %d / %d' % (neg, len(rs)))
    print('    가장 음: ', ', '.join('%s %+.2f' % (z, r) for r, z, _ in rs[:5]))
    print('    가장 양: ', ', '.join('%s %+.2f' % (z, r) for r, z, _ in rs[-5:]))


if __name__ == '__main__':
    main()

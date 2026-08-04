# -*- coding: utf-8 -*-
"""공급 영향권(수요 풀) 지도 — 1단계.

정의(2026-08-01 사용자): 생활권 = 일상 이동권이 아니라 "공급에 따라 가격 방향이
같이 정해지는 영향권". 잔차 가격 동조성(전국 공통 제거)만으로 묶으면 천안아산-구미
(+0.89, 120km)처럼 '동류 시장'(같은 충격 노출)이 오염시키므로, **지리 인접성
(중심 거리) 제약** 하에서만 병합한다 — 수요 풀은 사람이 실제로 옮겨갈 수 있는
범위여야 하기 때문.

강건성: 기간(금리잔잔/전체/전·후반) × 컷(0.2/0.3/0.4) 격자에서 안정된 병합만 채택.
"""
import io, json, math, os, sys, itertools

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zone_ref_fit2 as F2

# 존 중심 좌표(대표 도시, 근사). 인접 판정에만 쓴다 — 정밀할 필요 없음.
COORD = {
 '서울권':(37.55,126.99),'인천권':(37.46,126.70),
 # 경기 8권역(2026-08-05 재편) — 구성 도시 중심의 대략적 무게중심.
 '경기북부권':(37.78,127.05),'경기서북부권':(37.68,126.78),'경기서부권':(37.42,126.82),
 '경기남부권':(37.29,126.99),'경기남부외곽권':(37.10,127.20),'경기동남부권':(37.32,127.13),
 '경기동부권':(37.58,127.20),
 '천안아산권':(36.80,127.10),'서산당진권':(36.84,126.55),'청주권':(36.64,127.49),'대전세종권':(36.40,127.40),
 '춘천권':(37.88,127.73),'원주권':(37.34,127.92),'강릉권':(37.75,128.90),
 '전주권':(35.82,127.15),'군산익산권':(35.96,126.85),'광주권':(35.16,126.85),'목포권':(34.81,126.39),
 '여순광권':(34.95,127.49),
 '대구권':(35.87,128.60),'구미권':(36.12,128.34),'안동권':(36.57,128.73),'포항권':(35.95,129.30),
 '부산권':(35.18,129.08),'김해권':(35.23,128.89),'창원권':(35.23,128.68),'진주권':(35.18,128.11),
 '울산권':(35.54,129.31),'제주권':(33.50,126.53),
}
ADJ_KM = 45.0     # 이 거리 안이면 '인접'(수요가 실제 이동 가능한 범위, 대략 통근권)


def km(a, b):
    (la1, lo1), (la2, lo2) = COORD[a], COORD[b]
    dx = (lo1 - lo2) * 111.0 * math.cos(math.radians((la1 + la2) / 2))
    dy = (la1 - la2) * 111.0
    return math.hypot(dx, dy)


def resid_growth(f, quarters):
    """존별 {q: 분기성장률 - 그 분기 전국평균}."""
    g = {}
    for q in quarters:
        cell = []
        for z in f.zones:
            a, b = f.zq[z].get(q), f.zq[z].get(q + 1)
            if a and b:
                cell.append((z, (b / a - 1) * 100))
        if len(cell) < 30:
            continue
        m = sum(v for _, v in cell) / len(cell)
        for z, v in cell:
            g.setdefault(z, {})[q] = v - m
    return g


def corr_matrix(g, zones):
    C = {}
    for z1, z2 in itertools.combinations(sorted(zones), 2):
        a, b = g.get(z1, {}), g.get(z2, {})
        ks = sorted(set(a) & set(b))
        if len(ks) < 12:
            continue
        xa = [a[k] for k in ks]; xb = [b[k] for k in ks]
        n = len(ks); ma = sum(xa) / n; mb = sum(xb) / n
        sab = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
        sa = sum((x - ma) ** 2 for x in xa); sb = sum((y - mb) ** 2 for y in xb)
        if sa > 0 and sb > 0:
            C[(z1, z2)] = sab / math.sqrt(sa * sb)
    return C


def cluster(C, zones, cut):
    """평균연결 병합, 단 클러스터 간 최단 거리 ADJ_KM 이내(지리 제약)일 때만."""
    cl = [[z] for z in sorted(zones)]

    def link(c1, c2):
        vals = [C.get((min(a, b), max(a, b))) for a in c1 for b in c2]
        vals = [v for v in vals if v is not None]
        return (sum(vals) / len(vals)) if vals else None

    def near(c1, c2):
        return min(km(a, b) for a in c1 for b in c2) <= ADJ_KM

    while True:
        best = None
        for i, j in itertools.combinations(range(len(cl)), 2):
            if not near(cl[i], cl[j]):
                continue
            v = link(cl[i], cl[j])
            if v is not None and v >= cut and (best is None or v > best[0]):
                best = (v, i, j)
        if not best:
            break
        _, i, j = best
        cl[i] = cl[i] + cl[j]
        del cl[j]
    return [tuple(sorted(c)) for c in cl]


def pair_key(cls):
    """클러스터 결과 -> 같은 풀에 든 존 쌍 집합 (안정성 비교용)."""
    s = set()
    for c in cls:
        for a, b in itertools.combinations(c, 2):
            s.add((a, b))
    return s


def main():
    f = F2.Fitter()
    allq = sorted(set(q for s in f.zq.values() for q in s))
    allq = [q for q in allq if q >= f.anchor and q + 1 <= allq[-1]]
    half = len(f.calmq) // 2
    periods = {
        'calm': f.calmq,
        'all': allq,
        'calm전반': f.calmq[:half],
        'calm후반': f.calmq[half:],
    }
    grids = {}
    for pn, qs in periods.items():
        g = resid_growth(f, qs)
        C = corr_matrix(g, f.zones)
        for cut in (0.2, 0.3, 0.4):
            grids[(pn, cut)] = cluster(C, f.zones, cut)

    # 안정성: calm 0.3을 기준으로, 각 존 쌍이 12개 격자 중 몇 번 같은 풀인가
    votes = {}
    for key, cls in grids.items():
        for p in pair_key(cls):
            votes[p] = votes.get(p, 0) + 1
    base = grids[('calm', 0.3)]
    print('=== 기준 지도 (금리잔잔 · 컷 0.3 · 인접 45km 제약) ===')
    for c in sorted(base, key=len, reverse=True):
        if len(c) == 1:
            continue
        stab = [votes.get((a, b), 0) for a, b in itertools.combinations(c, 2)]
        print('  [%d존, 안정 %d/12] %s' % (len(c), min(stab), ' · '.join(c)))
    singles = [c[0] for c in base if len(c) == 1]
    print('  [독립] %s' % ' · '.join(singles))
    print()
    print('=== 강건 병합(12격자 중 10+ 동일 풀인 쌍만으로 재구성) ===')
    strong = {p for p, v in votes.items() if v >= 10}
    # 연결요소
    import collections
    gph = collections.defaultdict(set)
    for a, b in strong:
        gph[a].add(b); gph[b].add(a)
    seen, comps = set(), []
    for z in sorted(f.zones):
        if z in seen or z not in gph:
            continue
        comp, stack = set(), [z]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x); seen.add(x)
            stack += list(gph[x] - comp)
        comps.append(sorted(comp))
    for c in sorted(comps, key=len, reverse=True):
        print('  [%d존] %s' % (len(c), ' · '.join(c)))
    solo = [z for z in sorted(f.zones) if z not in seen]
    print('  [독립/불안정] %s' % ' · '.join(solo))
    json.dump({'base': [list(c) for c in base], 'strong': comps, 'solo': solo},
              io.open(os.path.join(HERE, 'cache', 'zone_pool_map.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    print('\nsaved tools/cache/zone_pool_map.json')


if __name__ == '__main__':
    main()

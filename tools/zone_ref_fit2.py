# -*- coding: utf-8 -*-
"""2단계 본편: 존별 적정물량(refq) 적합 + 기간 홀드아웃 모형비교.

1단계/진단에서 확정된 것:
  - 공급->가격 신호는 금리 잔잔한 구간에서만 잡힌다(순열 p<0.05).
  - 라이브의 max(0,·) 바닥이 정보를 죽인다. 바닥을 빼면 목적함수 0.028 -> 0.176.
    (바닥=재고 소진 후 부족은 누적 안 됨. 뺀 버전=부족이 잠재수요로 누적됨.)
  - 존 고정효과를 넣어도 신호 유지(0.192) => 시간가변 신호가 맞다.
  - 다만 k(=refq 배율)에 대해 목적함수가 평평 => refq는 약하게만 식별된다.

여기서는 k의 자유도를 (M0 고정 -> M1 전역 -> M2 시도별 -> M3 존별+수축) 늘리며
기간을 반으로 갈라 학습/평가를 교차해, 자유도를 늘린 값이 있는지 본다.
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zone_index_xcheck3 as X
import zone_ref_fit as F

FWD = 8
KGRID = [0.3, 0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 1.8, 2.2, 2.8]


def inv_nofloor(d, ref, upto, anchor):
    I, o = 0.0, {}
    for q in range(anchor, upto + 1):
        I = I + d.get(q, 0) - ref
        o[q] = I
    return o


class Fitter(object):
    def __init__(self):
        self.zq, self.done, self.stock, self.rq = X.load()
        self.base = F.zone_ref_base()
        self.zones = sorted(z for z in self.base if z in self.done and z in self.zq)
        self.qmax = max(max(s) for s in self.zq.values())
        self.anchor = F.ANCHOR
        qs = sorted(set(q for s in self.zq.values() for q in s))
        self.qs = [q for q in qs if q >= self.anchor and q + FWD <= qs[-1]]
        r = self.rq['기준금리']
        self.mv = {}
        for q in self.qs:
            w = [r[k] for k in range(q, q + FWD + 1) if k in r]
            self.mv[q] = (max(w) - min(w)) if w else 0.0
        self.ret = {}
        for z in self.zones:
            s = self.zq[z]
            for q in self.qs:
                a, b = s.get(q), s.get(q + FWD)
                if a and b:
                    self.ret[(z, q)] = (b / a - 1) * 100
        calm = sorted(self.mv[q] for q in self.qs)
        self.cut = calm[int(len(calm) * F.CALM) - 1]
        self.calmq = [q for q in self.qs if self.mv[q] <= self.cut]
        self._cache = {}

    def inv(self, z, k):
        key = (z, k)
        if key not in self._cache:
            self._cache[key] = inv_nofloor(self.done[z], self.base[z][0] * k,
                                           self.qmax, self.anchor)
        return self._cache[key]

    def obj(self, kmap, quarters):
        xs, ys = [], []
        for q in quarters:
            cell = []
            for z in self.zones:
                if (z, q) not in self.ret or not self.stock.get(z):
                    continue
                cell.append((self.inv(z, kmap[z])[q] / self.stock[z] * 100, self.ret[(z, q)]))
            if len(cell) < 20:
                continue
            mi = sum(c[0] for c in cell) / len(cell)
            mg = sum(c[1] for c in cell) / len(cell)
            xs += [c[0] - mi for c in cell]
            ys += [c[1] - mg for c in cell]
        if len(xs) < 50:
            return -9.0
        return -X.corr(xs, ys)[0]

    # ---- 모형들 ----
    def fit_global(self, tr):
        return max(KGRID, key=lambda k: self.obj({z: k for z in self.zones}, tr))

    def fit_group(self, tr, groups, k0, passes=3):
        km = {z: k0 for z in self.zones}
        gk = {g: k0 for g in set(groups.values())}
        for _ in range(passes):
            for g in sorted(gk):
                best, bv = gk[g], -9
                for k in KGRID:
                    for z in self.zones:
                        if groups[z] == g:
                            km[z] = k
                    v = self.obj(km, tr)
                    if v > bv:
                        bv, best = v, k
                gk[g] = best
                for z in self.zones:
                    if groups[z] == g:
                        km[z] = best
        return km, gk

    def fit_zone(self, tr, k0, shrink=0.0, passes=3):
        km = {z: k0 for z in self.zones}
        for _ in range(passes):
            for z in self.zones:
                best, bv = km[z], -9
                for k in KGRID:
                    km[z] = k
                    v = self.obj(km, tr) - shrink * (k - k0) ** 2
                    if v > bv:
                        bv, best = v, k
                km[z] = best
        return km


def main():
    f = Fitter()
    print('존 %d개, 금리 잔잔 분기 %d개 (전체 %d), 금리컷 %.2f%%p'
          % (len(f.zones), len(f.calmq), len(f.qs), f.cut))
    mid = f.calmq[len(f.calmq) // 2]
    A = [q for q in f.calmq if q < mid]
    B = [q for q in f.calmq if q >= mid]
    groups = {z: f.base[z][1] for z in f.zones}
    print('학습A %d분기 / 학습B %d분기, 시도그룹 %d개\n' % (len(A), len(B), len(set(groups.values()))))

    rows = []
    for name, tr, te in (('A->B', A, B), ('B->A', B, A)):
        one = {z: 1.0 for z in f.zones}
        res = [('M0 현재값(k=1)', one)]
        kg = f.fit_global(tr)
        res.append(('M1 전역 k=%.2f' % kg, {z: kg for z in f.zones}))
        km2, gk = f.fit_group(tr, groups, kg)
        res.append(('M2 시도별', km2))
        km3 = f.fit_zone(tr, kg, shrink=0.0)
        res.append(('M3 존별', km3))
        km4 = f.fit_zone(tr, kg, shrink=0.02)
        res.append(('M3s 존별+수축', km4))
        print('[%s]  %-18s %10s %10s' % (name, '모형', '학습', '평가(OOS)'))
        for nm, km in res:
            print('        %-18s %+10.3f %+10.3f' % (nm, f.obj(km, tr), f.obj(km, te)))
        rows.append((name, res))
        print()
    return f, rows


if __name__ == '__main__':
    main()

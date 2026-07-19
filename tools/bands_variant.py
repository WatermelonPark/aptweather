# -*- coding: utf-8 -*-
"""밴드 산출 변형 실험 — 금리쇼크기를 저점에서도 제외하면 공급 기반 전환점이 남는가?

recompute_bands.py는 저점을 '회복점이라 쇼크기도 포함'으로 두는데,
그 결과 15개 지역 중 13개의 저점이 2023Q1(금리 피크아웃) 한 점에 몰린다.
그건 공급이 만든 전환점이 아니라 금리가 만든 전환점이라, 공급 기준선의
근거로 쓰면 순환논증이 된다. 저점도 제외했을 때 무엇이 남는지 본다.

이 스크립트는 진단 전용이다. data.js를 건드리지 않는다.
"""
import os, sys, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import recompute_bands as R  # noqa: E402


def run(exclude_shock_lows):
    idxq = R.fetch_sale_index_quarterly()
    regions, occby, oldband, ref = R.load_occupancy()
    out = {}
    for reg in regions:
        s = idxq.get(reg)
        lows, highs = R.turning_points(R.trim_rebasing(s)) if s else ([], [])
        MINY = R.PAST_FROM[0]
        lows = [q for q in lows if R.qnum(q) >= MINY and (not exclude_shock_lows or not R.in_shock(q))]
        highs = [q for q in highs if R.qnum(q) >= MINY and not R.in_shock(q)]
        lo_v = [x for x in (R.occ_around(occby, reg, q) for q in lows) if x]
        hi_v = [x for x in (R.occ_around(occby, reg, q) for q in highs) if x]
        out[reg] = dict(
            lo=round(statistics.median(lo_v)) if lo_v else None,
            hi=round(statistics.median(hi_v)) if hi_v else None,
            nlo=len(lo_v), nhi=len(hi_v), lows=lows, highs=highs,
            band=oldband.get(reg, []), ref=ref.get(reg))
    return out


def main():
    base = run(False)
    var = run(True)
    print('=== 저점에서도 금리쇼크기(2021Q4~2023Q2) 제외 시 ===')
    print('%-5s %9s %7s %9s %7s %14s %7s' %
          ('지역', '현행하단', '표본', '변형하단', '표본', '신쌤밴드', 'ref'))
    print('-' * 72)
    kept = 0
    for reg in base:
        b, v = base[reg], var[reg]
        if v['nlo']:
            kept += 1
        print('%-5s %9s %7d %9s %7d %14s %7s' % (
            reg,
            format(b['lo'], ',') if b['lo'] else '-', b['nlo'],
            format(v['lo'], ',') if v['lo'] else '-', v['nlo'],
            str(b['band']) if b['band'] else '-',
            format(b['ref'], ',') if b['ref'] else '-'))
    print('-' * 72)
    print('저점 표본이 남은 지역: %d / %d' % (kept, len(base)))
    print()
    print('남은 저점 시점:')
    for reg, v in var.items():
        if v['lows']:
            print('  %-5s %s' % (reg, v['lows']))
    print()
    print('전부 사라진 지역:', ', '.join(r for r, v in var.items() if not v['lows']) or '없음')


if __name__ == '__main__':
    main()

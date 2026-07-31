# -*- coding: utf-8 -*-
"""지수 저점 vs HUB 준공(공급) 대조 검증.

기준표 모형: 공급이 적정 아래로 오래 가면 재고가 소진되고, 그 뒤 ~1년쯤에
가격이 오르기 시작한다(=가격 저점). 그렇다면 각 생활권의 '확정 저점' 시점에는
직전 몇 년 누적 준공이 그 존의 역사적 평균보다 낮아야 한다.
대조군으로 가격 '고점'에서 같은 값을 재서, 저점 쪽이 유의하게 낮은지 본다.
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update_adv_data as U

ZI = os.path.join(HERE, 'cache', 'zone_index.json')
HUB = os.path.join(HERE, 'data', 'hub_permits.json')
LOOK = 12          # 저점 직전 몇 분기 누적을 볼지 (12Q = 3년)
LAG = 4            # 기준표 "재고 소진 후 ~1년" -> 저점보다 4분기 앞을 본다


def qkey(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return y * 4 + (m - 1) // 3


def zone_done_series():
    """생활권 -> {분기인덱스: 준공세대}. hub_derive와 같은 존 매핑을 쓴다."""
    hp = json.load(io.open(HUB, encoding='utf-8'))
    z_of = U._hub_zone_map(U._load_bdong_map())
    out = {}
    for cd, v in hp['sgg'].items():
        z = z_of.get(cd)
        if not z:
            continue
        d = out.setdefault(z, {})
        for q, n in (v.get('done_q') or {}).items():
            y, qq = q.split('Q')
            d[int(y) * 4 + int(qq) - 1] = d.get(int(y) * 4 + int(qq) - 1, 0) + n
    return out


def roll(series, end_q, look=LOOK):
    return sum(series.get(q, 0) for q in range(end_q - look + 1, end_q + 1))


def find_peaks(months, vals, win=12, min_run=3.0):
    n = len(vals)
    out = []
    for i in range(n - win):
        lo, hi = max(0, i - win), min(n, i + win + 1)
        if any(vals[j] > vals[i] for j in range(lo, hi)):
            continue
        trough = min(vals[:i + 1])
        if (vals[i] - trough) / trough * 100 < min_run:
            continue
        if out and months.index(out[-1]) > i - win:
            continue
        out.append(months[i])
    return out


def main():
    zi = json.load(io.open(ZI, encoding='utf-8'))['maega']['zones']
    done = zone_done_series()
    rows, lo_all, hi_all = [], [], []
    for z, d in sorted(zi.items()):
        s = done.get(z)
        if not s or not d['months']:
            continue
        # 존 평균 3년 누적(비교 기준): 지수 이력이 있는 구간에서만
        q0, q1 = qkey(d['months'][0]), qkey(d['months'][-1])
        base = [roll(s, q) for q in range(max(q0, min(s) + LOOK), q1 + 1)]
        avg = (sum(base) / len(base)) if base else 0
        if not avg:
            continue
        tro = [t['m'] for t in d['troughs'] if not t['unconf'] and t['m'] >= '2006']
        pks = [m for m in find_peaks(d['months'], d['vals']) if m >= '2006']
        tv = [roll(s, qkey(m) - LAG) / avg for m in tro]
        pv = [roll(s, qkey(m) - LAG) / avg for m in pks]
        lo_all += tv
        hi_all += pv
        rows.append((z, tv, pv))
    print('%-10s %-34s %s' % ('생활권', '저점 시점 공급비(직전3년/평균)', '고점 시점'))
    for z, tv, pv in rows:
        print('%-10s %-34s %s' % (z, ' '.join('%.2f' % x for x in tv) or '-',
                                  ' '.join('%.2f' % x for x in pv) or '-'))
    def stat(a):
        a = sorted(a)
        return (sum(a) / len(a), a[len(a) // 2], len(a)) if a else (0, 0, 0)
    lm, lmed, ln = stat(lo_all)
    hm, hmed, hn = stat(hi_all)
    print()
    print('저점 n=%d  평균 %.2f  중앙 %.2f' % (ln, lm, lmed))
    print('고점 n=%d  평균 %.2f  중앙 %.2f' % (hn, hm, hmed))
    print('저점이 평균(1.00)보다 낮은 비율: %.0f%%' % (100.0 * sum(1 for x in lo_all if x < 1) / max(1, ln)))
    print('고점이 평균(1.00)보다 낮은 비율: %.0f%%' % (100.0 * sum(1 for x in hi_all if x < 1) / max(1, hn)))


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""Task 6 검증: calc() dC 교체(건축HUB 실측) + forward 2→4년 확장 전/후 순위diff.

data.js의 ADV/STATS는 아직 meas/fwd_far를 담고 있지 않을 수 있으므로(다른 세션이
data.js 정식 재생성을 담당 — 이 스크립트는 data.js를 절대 갱신하지 않는다),
update_adv_data.hub_derive(adv)를 메모리 상에서만 호출해 permits['meas']/
permits['fwd_far']를 주입한 뒤, 교체 전(구 dC·2년 forward)/후(신 dC·4년 forward)
tot·순위를 나란히 계산해 표로 찍는다.

'전'을 만드는 방법: make_zone_pages.calc()를 건드리지 않고, 이 파일 안에 Task 6
이전의 원래 산식을 그대로 재현한 calc_old()를 둔다(모듈 재구현 — calc() 자체를
바꿔가며 비교하면 골치 아프다). 신형은 make_zone_pages.calc()를 그대로 호출한다.

실행: python tools/verify_dc_rankdiff.py
"""
import io, os, re, sys, json, datetime

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
os.chdir(ROOT)

import make_zone_pages as M
import update_adv_data as U


# ---------------------------------------------------------------------------
# calc_old: Task 6 이전(H_MAX=8, forward 2년, dC=시도 인구배분만) 산식 재현.
# make_zone_pages.py의 옛 calc() 그대로 옮긴 것 — 비교 기준선 고정용.
# ---------------------------------------------------------------------------

def calc_old(adv, sts):
    H_MAX = 8
    W = M.W
    LB = M.LB
    LZ, O, P, B = adv['livezone'], adv['occupancy'], adv['permits'], adv.get('bubble') or {}
    J = (sts.get('전세가율') or {}).get('series') or {}
    DM = (sts.get('주택멸실') or {}).get('series') or {}
    SP = LZ.get('sidopop') or {}
    act = [r for r in O['rows'] if not r.get('e')]
    ph = P['rows'][-2:]
    today = datetime.date.today()
    cur_q = today.year * 4 + (today.month - 1) // 3

    def qi(k):
        m = re.match(r'^(\d{4})Q([1-4])$', k)
        return int(m.group(1)) * 4 + int(m.group(2)) - 1 if m else None

    allq = {k for zz in LZ['zones'] for k in (zz.get('byq') or {})}
    FUTQ = sorted([k for k in allq if qi(k) is not None and qi(k) > cur_q], key=qi)[:H_MAX]
    HQ = max(1, len(FUTQ))

    def fut_supply(zz):
        b = zz.get('byq') or {}
        return sum(b.get(k, 0) for k in FUTQ), HQ

    out = []
    for z in LZ['zones']:
        ps = '수도권' if z['region'] == '수도권' else (z.get('psido') or '수도권')
        if ps not in O['regions']:
            continue
        oi = O['regions'].index(ps)
        band = (O.get('band') or {}).get(ps)
        refq = (O.get('ref') or {}).get(ps) or (sum(band) / 2 if band else None)
        if not refq:
            continue
        share = min(1.0, z['pop'] / (SP.get(ps) or z['pop'] or 1))
        dY = M.last_of(DM, ps); dQ = dY / 4.0
        fsup, H = fut_supply(z)
        need = refq * H * share
        dA = need - fsup
        n4 = [r['v'][oi] for r in act[-LB:] if r['v'][oi] is not None]
        dB = (refq * len(n4) - (sum(n4) - dQ * len(n4))) * share if n4 else 0
        dC = 0
        if ps in P['regions']:
            pi = P['regions'].index(ps)
            vals = [r['v'][pi] for r in ph]
            if all(v is not None for v in vals):
                pv = sum(vals); plo = P['ref'][ps][0]
                dC = (plo - (pv - dY)) * share
        tot = W[0] * dA + W[1] * dC + W[2] * dB
        out.append(dict(z=z['z'], tot=tot, dA=dA, dC=dC, dB=dB, fq=H))
    out.sort(key=lambda r: -r['tot'])
    return out


def rank_map(rows, key='z'):
    return {r[key]: i + 1 for i, r in enumerate(rows)}


def main():
    adv, sts = M.load()
    before_meas = json.dumps((adv.get('permits') or {}).get('meas'), sort_keys=True, ensure_ascii=False)
    U.hub_derive(adv)   # 메모리 상에서만 meas/fwd_far 주입 — data.js는 절대 갱신 안 함
    after_meas = json.dumps((adv.get('permits') or {}).get('meas'), sort_keys=True, ensure_ascii=False)
    injected = before_meas != after_meas
    print('hub_derive 주입 여부: %s (주입 전 meas=%s)' % (
        '메모리에 새로 주입함' if injected else '이미 data.js에 있던 값과 동일(재계산 결과 일치)',
        before_meas))

    old = calc_old(adv, sts)
    new = M.calc(adv, sts)   # Task 6: dC 교체 + forward 4년

    rank_before = rank_map(old, 'z')
    new_by_name = {r['z']['z']: r for r in new}
    rank_after = {name: i + 1 for i, r in enumerate(new) for name in [r['z']['z']]}

    meas_zones = sorted(r['z']['z'] for r in new if r.get('dcsrc') == 'meas')
    fallback_zones = sorted(r['z']['z'] for r in new if r.get('dcsrc') == 'fallback')
    none_zones = sorted(r['z']['z'] for r in new if r.get('dcsrc') is None)

    print('\n건축HUB 실측(meas) 존 (%d개): %s' % (len(meas_zones), ', '.join(meas_zones) or '(없음)'))
    print('시도 인구배분 폴백(fallback) 존 (%d개)' % len(fallback_zones))
    if none_zones:
        print('dC 계산 불가(폴백 데이터도 없음) 존 (%d개): %s' % (len(none_zones), ', '.join(none_zones)))

    names = sorted(set(rank_before) | set(rank_after))
    rows = []
    for nm in names:
        rb = rank_before.get(nm)
        ra = rank_after.get(nm)
        ob = next((r for r in old if r['z'] == nm), None)
        nr = new_by_name.get(nm)
        tb = ob['tot'] if ob else None
        ta = nr['tot'] if nr else None
        drank = (ra - rb) if (ra is not None and rb is not None) else None
        src = nr.get('dcsrc') if nr else None
        rows.append((nm, tb, ta, rb, ra, drank, src))
    # Δrank 절대값 큰 순으로 정렬해 급변 존이 위에 보이게
    rows.sort(key=lambda r: -abs(r[5] if r[5] is not None else 0))

    print('\n%-8s %14s %14s %6s %6s %7s %10s' % (
        '생활권', 'tot_before', 'tot_after', 'rk전', 'rk후', 'Δrank', 'dC경로'))
    print('-' * 72)
    for nm, tb, ta, rb, ra, dr, src in rows:
        print('%-8s %14s %14s %6s %6s %7s %10s' % (
            nm,
            '%.0f' % tb if tb is not None else '·',
            '%.0f' % ta if ta is not None else '·',
            rb if rb is not None else '·',
            ra if ra is not None else '·',
            ('%+d' % dr) if dr is not None else '·',
            src or '·'))

    print('\n(참고) 이 표는 PARTIAL 데이터 기준이다 — 건축HUB meas/fwd_far가 아직 '
          '%d개 존에만 있고(전국 시딩은 Task 8), forward 2→4년 확장은 모든 존의 '
          'need에 영향을 준다(HQ 8→16, need가 대략 2배로 커짐 — dA 스케일 변화가 '
          '순위보다 절대값(tot) 크기에 더 크게 반영된다).' % len(meas_zones))


if __name__ == '__main__':
    main()

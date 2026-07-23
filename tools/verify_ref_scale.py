# -*- coding: utf-8 -*-
"""적정(수요) 스케일 검증 — HUB준공 분기평균 vs occupancy ref(적정=refq) 대조.

배경: 재설계 대상은 공급 측(occupancy 준공실적 → HUB done_q)뿐이고, 수요 기준선
'적정'(ADV.occupancy.ref[region], calc()가 refq로 읽는 신쌤 상수)은 그대로 유지된다.
이 스크립트는 HUB done_q의 분기 스케일이 그 적정 기준과 맞는지만 진단한다 —
값을 고치지 않는 읽기 전용 도구다. 비율이 지역 간 ~일정하면 스케일 계수 하나로
보정 가능하다는 뜻이고, 들쭉날쭉하면 단일 계수로는 부적합하다는 뜻이다.
실제 보정 계수 적용/미적용 판단은 전량 시드 후 Task 5(순위검토)에서 확정한다.

사용:
  python tools/verify_ref_scale.py

hub_permits.json이 아직 부분 스캔(activate 이전 · done_q 대부분 미채움)이면
그 사실을 알리고 exit 0으로 끝난다(예외 없음 — 스모크 통과 조건).
"""
import io
import os
import re
import sys
import json
import collections
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))          # tools/
SITE_ROOT = os.path.dirname(ROOT)                            # repo root
sys.path.insert(0, ROOT)
import update_adv_data as uad   # _hub_zone_map / _load_bdong_map 재사용 (Task 3)

DATA_JS = os.path.join(SITE_ROOT, 'data.js')
HUB_JSON = os.path.join(ROOT, 'data', 'hub_permits.json')

RECENT_YEARS = 3   # calc()의 최근 3년(LB=12분기) 창과 맞춘다


def load_adv():
    """make_zone_pages.load()와 동일한 패턴으로 data.js에서 ADV 블록만 추출."""
    t = io.open(DATA_JS, encoding='utf-8').read()
    m = re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});\s*/\*ADV_DATA_END\*/', t, re.S)
    assert m, 'data.js에서 ADV_DATA 블록을 찾을 수 없음'
    return json.loads(m.group(1))


def _recent_quarters(n_years):
    """오늘 기준 최근 n_years*4개 분기 라벨 집합 ('YYYYQn')."""
    today = datetime.date.today()
    y, q = today.year, (today.month - 1) // 3 + 1
    out = set()
    for _ in range(n_years * 4):
        out.add('%dQ%d' % (y, q))
        q -= 1
        if q == 0:
            y -= 1
            q = 4
    return out


def zone_done_avg(hp, z_of, n_years=RECENT_YEARS):
    """hub_permits.json의 존별 최근 n_years 분기 done_q 합 → 분기평균.

    반환: {zone: (분기평균, 표본분기수)}. done_q가 없는 시군구(구스키마만 있는 항목)는
    hub_derive와 동일하게 v.get('done_q', {})로 방어해 조용히 0 기여로 취급한다.
    """
    recent = _recent_quarters(n_years)
    by_zone_q = collections.defaultdict(lambda: collections.defaultdict(int))
    for cd, v in hp.get('sgg', {}).items():
        z = z_of.get(cd)
        if not z:
            continue
        for q, n in (v.get('done_q') or {}).items():
            if q in recent:
                by_zone_q[z][q] += n
    out = {}
    for z, qmap in by_zone_q.items():
        if qmap:
            out[z] = (sum(qmap.values()) / len(qmap), len(qmap))
    return out


def zone_region(zz):
    """make_zone_pages.calc()와 동일한 규칙으로 시도(occupancy region)를 정한다."""
    if zz.get('region') == '수도권':
        return '수도권'
    return zz.get('psido') or '수도권'


def zone_refq(O, region):
    """calc()와 동일: ref[region]이 없으면 band 중앙값으로 폴백."""
    refq = (O.get('ref') or {}).get(region)
    if refq:
        return refq
    band = (O.get('band') or {}).get(region)
    return (sum(band) / 2) if band else None


def main():
    hp = json.load(io.open(HUB_JSON, encoding='utf-8'))
    z_of = uad._hub_zone_map(uad._load_bdong_map())
    zavg = zone_done_avg(hp, z_of)

    if not zavg:
        print('done_q 데이터 없음 — 전량 시드 후 재실행 (hub_permits.json은 현재 부분 스캔 상태: '
              'meta.mode=%r, sgg항목 %d개 중 done_q 보유 0개)'
              % (hp.get('meta', {}).get('mode'), len(hp.get('sgg', {}))))
        return 0

    adv = load_adv()
    LZ = adv['livezone']['zones']
    O = adv['occupancy']
    zmeta = {z['z']: z for z in LZ}

    rows = []
    skipped = []
    for z, (avg, nq) in zavg.items():
        zz = zmeta.get(z)
        if not zz:
            skipped.append((z, 'zone 이름이 livezone.zones에 없음'))
            continue
        region = zone_region(zz)
        refq = zone_refq(O, region)
        if not refq:
            skipped.append((z, 'refq(적정) 없음: region=%s' % region))
            continue
        rows.append((z, region, avg, refq, avg / refq, nq))
    rows.sort(key=lambda r: -r[2])

    if not rows:
        print('HUB done_q는 있으나 매칭되는 생활권/적정값이 없음 (zone 이름 불일치 확인 필요)')
        for z, why in skipped:
            print('  스킵: %s — %s' % (z, why))
        return 0

    print('%-10s %-6s %16s %12s %8s %8s' %
          ('생활권', '시도', 'HUB준공_분기평균', 'refq(적정)', '비율', '표본분기'))
    for z, region, avg, refq, ratio, nq in rows:
        print('%-10s %-6s %16.0f %12.0f %8.2f %8d' % (z, region, avg, refq, ratio, nq))
    if skipped:
        print()
        for z, why in skipped:
            print('스킵: %s — %s' % (z, why))

    ratios = [r[4] for r in rows]
    n = len(ratios)
    mean = sum(ratios) / n
    var = sum((x - mean) ** 2 for x in ratios) / n
    sd = var ** 0.5
    cv = (sd / mean) if mean else float('inf')

    print()
    print('표본 %d개 존 — 비율 평균 %.2f · 표준편차 %.2f · 변동계수(CV=sd/mean) %.2f' % (n, mean, sd, cv))
    if n < 5:
        print('판단 보류: 표본이 너무 적음(<5개 존) — 전량 시드 후 재실행 필요')
    elif cv < 0.3:
        print('판단: 비율이 지역 간 비교적 일정함(CV<0.3) → 스케일 계수 하나(~%.2f)로 보정 가능해 보임' % mean)
    else:
        print('판단: 비율이 지역 간 크게 벌어짐(CV>=0.3) → 단일 계수로는 부적합, 지역별 검토 필요')
    return 0


if __name__ == '__main__':
    sys.exit(main())

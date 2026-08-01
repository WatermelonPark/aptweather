# -*- coding: utf-8 -*-
"""적정(수요) 스케일 검증 — HUB준공 분기평균 vs occupancy ref(적정=refq) 대조.

배경: 재설계 대상은 공급 측(occupancy 준공실적 → HUB done_q)뿐이고, 수요 기준선
'적정'(ADV.occupancy.ref[region], calc()가 refq로 읽는 기준표 상수)은 그대로 유지된다.
이 스크립트는 HUB done_q의 분기 스케일이 그 적정 기준과 맞는지만 진단한다 —
값을 고치지 않는 읽기 전용 도구다.

판정 기준(2026-08-01 재정의): **안분 없는 존(share≈1, 광역시·제주)의 비율 평균이
1.00 근처인가**. 이 비율(최근 3년 준공 ÷ 존 적정)은 곧 과잉/부족 신호 자체라 존마다
흩어지는 게 정상이고, 척도 오류는 흩어짐이 아니라 치우침으로 나타난다. 안분 존은
분모가 시도 적정×작은 몫이라 비율이 크게 흔들려(광명 share 0.011 → 2.61) 척도
판정에 못 쓴다. 옛 기준(CV≥0.3이면 부적합)은 성립 불가능한 전제라 정상 상태에서도
경고를 냈다 — 그 거짓 경고가 진짜 문제를 가릴 위험이 있어 바꿨다.

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

# cp949 콘솔에서도 — 등 출력이 죽지 않도록(다른 verify_* 스크립트와 동일 처리).
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))          # tools/
SITE_ROOT = os.path.dirname(ROOT)                            # repo root
sys.path.insert(0, ROOT)
import update_adv_data as uad   # _hub_zone_map / _load_bdong_map 재사용 (Task 3)

HUB_JSON = os.path.join(ROOT, 'data', 'hub_permits.json')

RECENT_YEARS = 3   # calc()의 최근 3년(LB=12분기) 창과 맞춘다



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





def main():
    hp = json.load(io.open(HUB_JSON, encoding='utf-8'))
    z_of = uad._hub_zone_map(uad._load_bdong_map())
    zavg = zone_done_avg(hp, z_of)

    if not zavg:
        print('done_q 데이터 없음 — 전량 시드 후 재실행 (hub_permits.json은 현재 부분 스캔 상태: '
              'meta.mode=%r, sgg항목 %d개 중 done_q 보유 0개)'
              % (hp.get('meta', {}).get('mode'), len(hp.get('sgg', {}))))
        return 0

    # 존 적정은 라이브 calc()가 내는 값(zrefq)을 그대로 쓴다 — 자체 계산을 두면
    # 모델이 바뀔 때 조용히 어긋난다(2026-08-01: 수요 풀 재배선으로 부산·대구권 등의
    # 존 적정이 refq×share에서 달라졌는데 이 도구만 옛 식을 써 평균이 1.12 vs 1.00으로
    # 갈렸다). share도 calc()가 실은 세대수 기준이라 이 파일의 인구식은 이미 낡았다.
    import make_zone_pages as mzp
    adv, sts = mzp.load()
    calc_rows = {r['z']['z']: r for r in mzp.calc(adv, sts)}

    rows = []
    skipped = []
    for z, (avg, nq) in zavg.items():
        cr = calc_rows.get(z)
        if not cr:
            skipped.append((z, 'zone 이름이 livezone.zones에 없음'))
            continue
        zrefq = cr.get('zrefq')
        if not zrefq:
            skipped.append((z, '존 적정(zrefq) 없음: region=%s' % cr.get('ps')))
            continue
        region = cr.get('pool') or cr['ps']
        rows.append((z, region, avg, cr['refq'], cr['share'], avg / zrefq, nq))
    rows.sort(key=lambda r: -r[2])

    if not rows:
        print('HUB done_q는 있으나 매칭되는 생활권/적정값이 없음 (zone 이름 불일치 확인 필요)')
        for z, why in skipped:
            print('  스킵: %s — %s' % (z, why))
        return 0

    print('%-10s %-6s %16s %12s %8s %8s %8s' %
          ('생활권', '시도', 'HUB준공_분기평균', 'refq(적정,REGION)', 'share', '비율(zone기준)', '표본분기'))
    for z, region, avg, refq, share, ratio, nq in rows:
        print('%-10s %-6s %16.0f %12.0f %8.3f %8.2f %8d' % (z, region, avg, refq, share, ratio, nq))
    if skipped:
        print()
        for z, why in skipped:
            print('스킵: %s — %s' % (z, why))

    def _stat(vs):
        n_ = len(vs)
        if not n_:
            return 0.0, 0.0, float('inf'), 0
        m = sum(vs) / n_
        sd_ = (sum((x - m) ** 2 for x in vs) / n_) ** 0.5
        return m, sd_, (sd_ / m if m else float('inf')), n_

    # ⚠️ 판정은 CV가 아니라 '안분 없는 존(share≈1)의 평균이 1에서 얼마나 벗어났나'로
    # 한다(2026-08-01 재정의). 이 비율은 "최근 3년 실제 준공 ÷ 존 적정" — 즉 우리가
    # 재려는 과잉/부족 신호 그 자체라, 지역 간 흩어지는 게 정상이다. 예전 기준(CV≥0.3
    # → 척도 부적합)은 "모든 존이 적정에 비례해 지어야 한다"는 성립 불가능한 전제라
    # 정상 상태에서도 매번 경고를 냈다(실측 CV 0.65).
    # 척도가 어긋나면 흩어짐이 아니라 '치우침'으로 나타나고, 그건 안분 잡음이 안 섞인
    # share≈1 존에서만 깨끗하게 보인다 — 안분 존은 분모(시도 적정×작은 몫)가 작아
    # 비율이 크게 흔들린다(광명 share 0.011 → 비율 2.61, 고양 0.039 → 0.12).
    ratios = [r[5] for r in rows]
    full = [r[5] for r in rows if r[4] >= 0.999]      # 안분 없음(광역시·제주 등)
    part = [r[5] for r in rows if r[4] < 0.999]
    mean, sd, cv, n = _stat(ratios)
    fm, fsd, fcv, fn = _stat(full)
    pm, psd, pcv, pn = _stat(part)

    print()
    print('%-22s %6s %6s %6s %4s' % ('구분', '평균', '표준편차', 'CV', 'n'))
    print('%-22s %6.2f %6.2f %6.2f %4d' % ('전체', mean, sd, cv, n))
    print('%-22s %6.2f %6.2f %6.2f %4d' % ('안분 없음(share=1)', fm, fsd, fcv, fn))
    print('%-22s %6.2f %6.2f %6.2f %4d' % ('안분 있음(share<1)', pm, psd, pcv, pn))
    print()
    if fn < 4:
        print('판단 보류: 안분 없는 존이 %d개뿐 — 척도를 깨끗하게 잴 표본이 부족하다' % fn)
    elif abs(fm - 1.0) <= 0.15:
        print('판단: 척도 정상 — 안분 없는 존 평균 %.2f (1.00 ±0.15 이내). '
              '전체 CV %.2f는 존별 과잉/부족 차이(=재려는 신호)이지 척도 문제가 아니다.'
              % (fm, cv))
    else:
        print('판단: ⚠️ 척도 치우침 의심 — 안분 없는 존 평균이 %.2f로 1.00에서 %.0f%% 벗어났다. '
              'HUB 준공과 적정(ref)이 다른 척도일 수 있으니 ref 산출 근거를 재확인할 것.'
              % (fm, abs(fm - 1) * 100))
    return 0


if __name__ == '__main__':
    sys.exit(main())

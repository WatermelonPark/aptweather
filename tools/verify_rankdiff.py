# -*- coding: utf-8 -*-
"""OLD(pre-HUB) vs NEW(러닝재고, hub_derive activate 강제 주입) 36생활권 순위 diff 검증.

hub_permits.json을 인메모리로 읽어 meta.activate=True로 강제한 뒤
update_adv_data.hub_derive()를 돌려 adv 사본의 permits.done/sched를 채우고,
그 위에서 make_zone_pages.calc()를 다시 돌려 신모델 tot을 구한다.
구모델은 현재 data.js 그대로(done/sched 없음 → 전 존 pre-HUB 폴백)를 calc()한 값이다.

현재(2026-07-24) hub_permits.json은 구스키마(permit_q/start_q)뿐이거나
meta.scanned가 비어 있어 완결성 게이트를 통과하는 존이 없다 — 그 경우 신모델도
전 존이 pre-HUB 폴백을 타므로 구/신 tot·순위가 완전히 같다. 이는 정상이며,
실제 diff는 hub_permits.json이 done_q/sched_q로 시드되고 존이 완결된 뒤 나타난다.

사용: python tools/verify_rankdiff.py
"""
import sys, os, copy

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_zone_pages as M
import update_adv_data as U


def _new_rows(adv, sts, weight_demand=True):
    """adv 사본에 hub_derive를 activate=True로 강제 주입해 신모델 rows를 만든다.

    weight_demand는 그대로 M.calc()/running_shortage()로 전달된다 — Issue #4의
    A안(True, 라이브 기본값)/B안(False, 스펙 원문) 둘 다 같은 refq*share 픽스 위에서 계산.
    """
    adv2 = copy.deepcopy(adv)
    hp = copy.deepcopy(U._load_hub_permits())
    hp.setdefault('meta', {})['activate'] = True
    orig_loader = U._load_hub_permits
    U._load_hub_permits = lambda: hp
    try:
        U.hub_derive(adv2)
    finally:
        U._load_hub_permits = orig_loader
    return M.calc(adv2, sts, weight_demand=weight_demand)


def main():
    adv, sts = M.load()
    old_rows = M.calc(adv, sts)
    new_rows_a = _new_rows(adv, sts, weight_demand=True)    # A안: 수요도 conf 가중(라이브 기본값)
    new_rows_b = _new_rows(adv, sts, weight_demand=False)   # B안: 수요 비가중(스펙 원문)

    old_by_z = {r['z']['z']: r for r in old_rows}
    a_by_z = {r['z']['z']: r for r in new_rows_a}
    b_by_z = {r['z']['z']: r for r in new_rows_b}
    common = [z for z in old_by_z if z in a_by_z and z in b_by_z]
    old_rank = {z: i + 1 for i, z in enumerate(sorted(old_by_z, key=lambda k: -old_by_z[k]['tot']))}
    a_rank = {z: i + 1 for i, z in enumerate(sorted(a_by_z, key=lambda k: -a_by_z[k]['tot']))}
    b_rank = {z: i + 1 for i, z in enumerate(sorted(b_by_z, key=lambda k: -b_by_z[k]['tot']))}

    inv_zones = [z for z in common if a_by_z[z].get('inv_path')]
    if not inv_zones:
        print('[verify_rankdiff] 러닝재고(inventory) 경로를 탄 존 없음 — done/sched 미시드 또는 '
              '완결성 게이트 미통과. 전 존이 pre-HUB 폴백을 유지하므로 구/신 tot·순위가 동일합니다.')
        print('  (seed 완료 + activate 이후 재실행하면 실제 diff가 나타납니다)')
        print()

    # Fix I3: 먼 지평(k=13..20)의 미상쇄 수요 크기 — running_shortage()가 이 구간의
    # sched(준공예정)를 실측 0에 가깝게 받는다는 전제하에, 그 구간이 통째로
    # refq만큼 부족으로 잡힐 때의 상한값(= Σ conf(k)·refq, 공급 상쇄 전). refq에
    # 비례하므로 대도시(refq가 큰 존)일수록 이 값도 커진다 — 지평 캡·문서화 검토용
    # 진단 열이며 모델 자체는 바꾸지 않는다(tot 계산에는 안 쓰인다).
    far_conf_sum = sum(M._conf(k) for k in range(13, 21))   # 고정 상수(현재 가중식으로 ≈1.8)

    def far_demand(row):
        return far_conf_sum * (row.get('refq') or 0)

    print('%-10s %10s %12s %12s %6s %6s %6s  %10s  %s' %
          ('zone', 'tot_old', 'tot_A(가중)', 'tot_B(비가중)', 'rk_old', 'rk_A', 'rk_B', 'far_demand', 'path'))
    for z in sorted(common, key=lambda k: old_rank[k]):
        o, a, b = old_by_z[z], a_by_z[z], b_by_z[z]
        path = 'inventory' if a.get('inv_path') else 'fallback'
        print('%-10s %10.0f %12.0f %12.0f %6d %6d %6d  %10.0f  %s' %
              (z, o['tot'], a['tot'], b['tot'], old_rank[z], a_rank[z], b_rank[z], far_demand(a), path))


if __name__ == '__main__':
    main()

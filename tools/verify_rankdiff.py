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


def _new_rows(adv, sts):
    """adv 사본에 hub_derive를 activate=True로 강제 주입해 신모델 rows를 만든다."""
    adv2 = copy.deepcopy(adv)
    hp = copy.deepcopy(U._load_hub_permits())
    hp.setdefault('meta', {})['activate'] = True
    orig_loader = U._load_hub_permits
    U._load_hub_permits = lambda: hp
    try:
        U.hub_derive(adv2)
    finally:
        U._load_hub_permits = orig_loader
    return M.calc(adv2, sts)


def main():
    adv, sts = M.load()
    old_rows = M.calc(adv, sts)
    new_rows = _new_rows(adv, sts)

    old_by_z = {r['z']['z']: r for r in old_rows}
    new_by_z = {r['z']['z']: r for r in new_rows}
    common = [z for z in old_by_z if z in new_by_z]
    old_rank = {z: i + 1 for i, z in enumerate(sorted(old_by_z, key=lambda k: -old_by_z[k]['tot']))}
    new_rank = {z: i + 1 for i, z in enumerate(sorted(new_by_z, key=lambda k: -new_by_z[k]['tot']))}

    inv_zones = [z for z in common if new_by_z[z].get('inv_path')]
    if not inv_zones:
        print('[verify_rankdiff] 러닝재고(inventory) 경로를 탄 존 없음 — done/sched 미시드 또는 '
              '완결성 게이트 미통과. 전 존이 pre-HUB 폴백을 유지하므로 구/신 tot·순위가 동일합니다.')
        print('  (seed 완료 + activate 이후 재실행하면 실제 diff가 나타납니다)')
        print()

    print('%-10s %10s %10s %6s %6s %6s  %s' % ('zone', 'tot_old', 'tot_new', 'rk_old', 'rk_new', 'drank', 'path'))
    for z in sorted(common, key=lambda k: old_rank[k]):
        o, n = old_by_z[z], new_by_z[z]
        drank = new_rank[z] - old_rank[z]
        path = 'inventory' if n.get('inv_path') else 'fallback'
        print('%-10s %10.0f %10.0f %6d %6d %+6d  %s' %
              (z, o['tot'], n['tot'], old_rank[z], new_rank[z], drank, path))


if __name__ == '__main__':
    main()

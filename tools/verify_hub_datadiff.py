# -*- coding: utf-8 -*-
"""hub_permits.json 두 판본을 같은 모델로 돌려 생활권 순부족·순위 차이를 잰다.

`verify_rankdiff.py`와 목적이 다르다. 저건 **모델** 변경(pre-HUB vs 러닝재고)을
재는 도구고, 이건 모델은 그대로 둔 채 **데이터** 변경(재시딩·중복 제거·수집기
수정 등)이 순부족과 등급을 얼마나 흔드는지 재는 도구다. 데이터 수정이 순위를
움직이는 건 사용자 결정 사항이라, 배포 전에 그 크기를 숫자로 보여줄 수단이
필요하다.

사용:
  python tools/verify_hub_datadiff.py --before before.json --after tools/data/hub_permits.json
  git show <커밋>:tools/data/hub_permits.json > before.json   # 이전 판본 뽑기

두 판본 모두 meta.activate를 강제로 켜서 비교한다 — 한쪽만 켜져 있으면 데이터가
아니라 게이트 차이를 재게 된다. 완결성 게이트(meta.scanned)는 각 판본의 값을
그대로 쓴다: 재시딩 도중 판본은 일부 존이 아직 미완결일 수 있고, 그 사실 자체가
비교 결과에 드러나야 한다.
"""
import argparse
import copy
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_zone_pages as M  # noqa: E402
import update_adv_data as U  # noqa: E402


def rows_for(hub_path, adv, sts):
    """주어진 hub_permits.json으로 hub_derive를 돌린 뒤 calc() rows를 반환."""
    hp = json.load(io.open(hub_path, encoding='utf-8-sig'))
    hp.setdefault('meta', {})['activate'] = True
    adv2 = copy.deepcopy(adv)
    orig = U._load_hub_permits
    U._load_hub_permits = lambda: hp
    try:
        U.hub_derive(adv2)
    finally:
        U._load_hub_permits = orig
    return M.calc(adv2, sts), hp


def _totals(hp):
    done = sched = 0
    for v in (hp.get('sgg') or {}).values():
        done += sum((v.get('done_q') or {}).values())
        sched += sum((v.get('sched_q') or {}).values())
    return done, sched


def _rank_and_grade(rows):
    """calc() rows -> ({존: 표시 순위}, {존: 등급코드}, {존: 순부족}).

    ⚠️ 순위는 tot 내림차순이 아니라 M.zone_order(등급군 -> 군 안에서 tot)로 매긴다 —
    홈·허브·존 페이지의 'N위'가 전부 그 순서를 쓰기 때문이다. tot로만 줄 세우면
    사용자가 화면에서 보는 순위와 다른 숫자를 보고하게 된다.
    등급은 r['gr']['k'](g4~g0)다. r['grade']는 존재하지 않는 키라, 그걸 읽으면
    전 존이 None으로 같아져 '등급 변동 없음'이라는 거짓 안심이 나온다.
    """
    ordered = M.zone_order(rows)
    rank = {r['z']['z']: i + 1 for i, r in enumerate(ordered)}
    gr = {r['z']['z']: r['gr']['k'] for r in rows}
    tot = {r['z']['z']: r['tot'] for r in rows}
    return rank, gr, tot


def main():
    ap = argparse.ArgumentParser(description='hub_permits.json 두 판본의 순부족·순위 차이 측정')
    ap.add_argument('--before', required=True)
    ap.add_argument('--after', required=True)
    ap.add_argument('--top', type=int, default=15, help='순위 변동 상위 N곳 출력(기본 15)')
    args = ap.parse_args()

    adv, sts = M.load()
    before_rows, hp_b = rows_for(args.before, adv, sts)
    after_rows, hp_a = rows_for(args.after, adv, sts)

    db, sb = _totals(hp_b)
    da, sa = _totals(hp_a)
    print('원자료 총량   준공 %s -> %s (%+d) · 준공예정 %s -> %s (%+d)'
          % (format(db, ','), format(da, ','), da - db,
             format(sb, ','), format(sa, ','), sa - sb))
    print('완결 존(scanned 게이트) %d -> %d · 재시딩 진행 %d/%d'
          % (len(hp_b.get('meta', {}).get('scanned', [])),
             len(hp_a.get('meta', {}).get('scanned', [])),
             len(hp_a.get('meta', {}).get('reseed_done', [])),
             len(hp_a.get('meta', {}).get('scanned', []))))
    print()

    rb, gb, tb = _rank_and_grade(before_rows)
    ra, ga, ta = _rank_and_grade(after_rows)
    common = [z for z in rb if z in ra]

    moved = sorted(common, key=lambda z: (-abs(ra[z] - rb[z]), -abs(ta[z] - tb[z])))
    n_moved = sum(1 for z in common if ra[z] != rb[z])
    changed = [z for z in common if gb[z] != ga[z]]
    print('존 %d곳 중 순위 변동 %d곳 · 등급 변동 %d곳' % (len(common), n_moved, len(changed)))
    print()
    print('%-12s %6s %6s %6s   %11s %11s  %s'
          % ('생활권', '순위전', '순위후', '이동', '순부족전', '순부족후', '등급'))
    for z in moved[:args.top]:
        gmark = gb[z] if gb[z] == ga[z] else '%s -> %s' % (gb[z], ga[z])
        print('%-12s %6d %6d %+6d   %11.1f %11.1f  %s'
              % (z, rb[z], ra[z], rb[z] - ra[z], tb[z], ta[z], gmark))

    if changed:
        print()
        print('등급이 바뀐 존:')
        for z in changed:
            print('  %-12s %s -> %s (순부족 %.1f -> %.1f)' % (z, gb[z], ga[z], tb[z], ta[z]))


if __name__ == '__main__':
    main()

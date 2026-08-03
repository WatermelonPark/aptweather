# -*- coding: utf-8 -*-
"""저장된 hub_permits.json에 사업 단위 계상을 소급 적용한다(재수집 없이).

수집기(`_aggregate`)는 2026-08-03부터 (지번, 세대수)로 사업을 묶어 저장하지만,
그 이전에 수집된 항목은 대장 단위 그대로다. units에 지번이 들어 있고
`UNITS_CAP=None`이라 units 세대 합 == done_q+sched_q 합이 성립하므로(실측 확인:
148/148 시군구 일치), 저장된 units만으로 분기 집계를 정확히 다시 만들 수 있다 —
11시간짜리 전량 수집을 한 번 더 하지 않아도 된다.

접는 규칙은 hub_common.collapse_units_by_project 하나를 그대로 쓴다(수집기와
동일 함수 — 규칙이 갈리면 재수집 전후 값이 달라진다).

사용:
  python tools/rebuild_hub_projects.py --dry-run          # 규모만 출력
  python tools/rebuild_hub_projects.py                    # 실제 반영
  python tools/rebuild_hub_projects.py --out other.json

⚠️ demol_q·meta·productive_bjdong은 건드리지 않는다. 멸실은 이 감사에서 실측하지
않았고 값의 대부분이 API가 아니라 벌크파일 백필분이다.
"""
import argparse
import collections
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_common as H  # noqa: E402

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hub_permits.json')


def entry_truncation(entry):
    """units가 done_q+sched_q를 온전히 대표하는가. 대표하면 None, 아니면 (차이, 설명).

    이 도구의 전제는 'units 세대 합 == done_q+sched_q 합'이다(모듈 docstring 참조).
    그 전제가 깨진 항목에서 done_q를 units로부터 다시 만들면 **잘려 나간 만큼이
    조용히 사라진다**. UNITS_CAP=40 시절에 수집된 항목이 정확히 그 상태다
    (2026-08-04 감사: 부산 4개 구 — 강서·해운대·북·사상 — 합계 46,345세대가
    지워질 뻔했고, 로그에서는 정당한 접기 감소와 같은 컬럼에 섞여 구분되지 않았다).
    """
    units = entry.get('units') or []
    if not units:
        return None
    q_sum = (sum((entry.get('done_q') or {}).values())
             + sum((entry.get('sched_q') or {}).values()))
    u_sum = sum(u[1] for u in units)
    # 막아야 하는 건 '재계산하면 줄어드는' 방향뿐이다(q_sum > u_sum = units가 잘렸다).
    # 반대 방향(q_sum < u_sum)은 done_q가 덜 기록된 상태이고 재계산이 이를 올려
    # 바로잡으므로 손실이 아니다 — 여기서 막으면 정상 복구까지 막는다.
    if q_sum <= u_sum:
        return None
    return (q_sum - u_sum,
            'units 합 %s < done_q+sched_q 합 %s (%s개 units, 차 %s세대)'
            % (format(u_sum, ','), format(q_sum, ','), len(units),
               format(q_sum - u_sum, ',')))


def rebuild_entry(entry):
    """sgg 항목 하나 -> (새 항목, 접힌 대장 수, 재고 감소, 미래공급 감소).

    done_q/sched_q는 접은 뒤의 units에서 다시 만든다. 원래 항목에 units가 없으면
    (아주 옛 스키마) 판단 근거가 없으므로 그대로 둔다. units가 잘려 있는 항목도
    그대로 둔다(entry_truncation 참조) — 호출측이 걸러 보내는 것을 전제하지 않고
    여기서도 한 번 더 막는다.
    """
    units = entry.get('units')
    if not units:
        return entry, 0, 0, 0
    if entry_truncation(entry):
        return entry, 0, 0, 0
    kept = H.collapse_units_by_project(units)
    done_q = collections.defaultdict(int)
    sched_q = collections.defaultdict(int)
    for u in kept:
        q = H.to_quarter(u[2])
        if not q:
            continue
        (done_q if u[3] == 'done' else sched_q)[q] += u[1]
    kept.sort(key=lambda u: -u[1])
    kept = [u for u in kept if u[3] == 'done'] + [u for u in kept if u[3] == 'sched']
    new = dict(entry)
    new['units'] = kept
    new['done_q'] = dict(done_q)
    new['sched_q'] = dict(sched_q)
    d_drop = sum((entry.get('done_q') or {}).values()) - sum(done_q.values())
    s_drop = sum((entry.get('sched_q') or {}).values()) - sum(sched_q.values())
    return new, len(units) - len(kept), d_drop, s_drop


def main():
    ap = argparse.ArgumentParser(description='hub_permits.json 사업 단위 계상 소급 적용')
    ap.add_argument('--path', default=DEFAULT)
    ap.add_argument('--out', default=None, help='생략하면 제자리 갱신')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--top', type=int, default=15)
    ap.add_argument('--allow-truncated', action='store_true',
                    help='units가 잘린 항목을 건너뛰고 나머지만 재계산(기본은 중단)')
    args = ap.parse_args()

    d = json.load(io.open(args.path, encoding='utf-8-sig'))
    n_plat = n_unit = 0
    for e in d.get('sgg', {}).values():
        for u in e.get('units') or []:
            n_unit += 1
            if len(u) > 4 and (u[4] or '').strip():
                n_plat += 1
    print('units %s개 중 지번 보유 %s개(%.1f%%)'
          % (format(n_unit, ','), format(n_plat, ','), 100.0 * n_plat / max(n_unit, 1)))
    if n_plat == 0:
        print('지번이 하나도 없다 — 지번 수집(2026-08-03) 이후 재시딩된 파일이어야 한다. 중단.')
        return 2

    # ── 안전장치: 잘린 units를 가진 항목을 먼저 걸러낸다 ──────────────────
    # 전역 게이트(지번 보유 0건)만으로는 '일부 항목만 옛 캡으로 잘린' 상태를 못 잡는다.
    trunc = []
    for k, e in d.get('sgg', {}).items():
        t = entry_truncation(e)
        if t:
            trunc.append((t[0], k, e.get('name'), t[1]))
    if trunc:
        trunc.sort(reverse=True)
        print()
        print('⚠️ units가 done_q+sched_q를 대표하지 못하는 항목 %d개 (합계 %s세대)'
              % (len(trunc), format(sum(x[0] for x in trunc), ',')))
        for diff, k, nm, why in trunc:
            print('   %-8s %-10s %s' % (k, nm, why))
        print('   → 이 항목들은 UNITS_CAP 시절 수집분으로 units가 잘려 있다.')
        print('     그대로 재계산하면 위 세대수가 조용히 사라진다.')
        if not args.allow_truncated:
            print()
            print('중단했다. 해결 방법 둘 중 하나:')
            print('  1) 해당 시군구를 재시딩해 units를 온전히 받은 뒤 다시 실행')
            print('     python tools/fetch_hub_permits.py --full --only <코드>')
            print('  2) 그 항목만 건너뛰고 나머지를 재계산: --allow-truncated')
            return 3
        print('   --allow-truncated — 위 항목은 원본 그대로 두고 나머지만 재계산한다.')
        print()

    rows = []
    tot_d = tot_s = tot_fold = 0
    for k, e in d.get('sgg', {}).items():
        new, folded, d_drop, s_drop = rebuild_entry(e)
        d['sgg'][k] = new
        tot_fold += folded
        tot_d += d_drop
        tot_s += s_drop
        if d_drop or s_drop:
            rows.append((d_drop + s_drop, k, e.get('name'), folded, d_drop, s_drop))

    print('접힌 대장 %s건 · 재고(준공) -%s세대 · 미래공급 포함 준공예정 -%s세대'
          % (format(tot_fold, ','), format(tot_d, ','), format(tot_s, ',')))
    print()
    rows.sort(reverse=True)
    print('%-8s %-10s %8s %12s %12s' % ('코드', '시군구', '접힘', '준공감소', '준공예정감소'))
    for _, k, nm, folded, dd, sd in rows[:args.top]:
        print('%-8s %-10s %8s %12s %12s'
              % (k, nm, format(folded, ','), format(dd, ','), format(sd, ',')))

    if args.dry_run:
        print()
        print('--dry-run — 파일은 그대로 둔다.')
        return 0
    out = args.out or args.path
    with io.open(out, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
    print()
    print('기록 완료: %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())

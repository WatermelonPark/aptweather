"""소급 사업 단위 계상(rebuild_hub_projects) — 항목 단위 재구성 검증.

이 스크립트는 이미 수집된 파일의 done_q/sched_q를 units로부터 다시 만든다.
잘못되면 재수집으로만 복구되므로(전량 11시간), 항등식과 보존 대상을 고정한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import rebuild_hub_projects as R  # noqa: E402

BONG = '강원특별자치도 원주시 단계동 1234번지'
OTHER = '강원특별자치도 원주시 단계동 5678번지'


def _entry(units, done_q=None, sched_q=None, **kw):
    e = {'name': '원주시', 'units': units,
         'done_q': done_q if done_q is not None else {},
         'sched_q': sched_q if sched_q is not None else {}}
    e.update(kw)
    return e


def test_rebuild_recomputes_quarters_from_collapsed_units():
    # 대장 5개가 각각 690을 달고 있다가 사업 1건(690)으로 접힌다.
    units = [['봉화산 e-편한세상', 690, '2004-11', 'done', BONG] for _ in range(5)]
    new, folded, d_drop, s_drop = R.rebuild_entry(_entry(units, {'2004Q4': 3450}))
    assert new['done_q'] == {'2004Q4': 690}
    assert folded == 4 and d_drop == 2760 and s_drop == 0


def test_rebuild_preserves_units_quarter_identity():
    """units 세대 합 == done_q+sched_q 합. 이게 깨지면 존 페이지 '총 N세대'와
    차트 총량이 어긋나 사용자가 버그로 읽는다(UNITS_CAP 폐지의 원래 이유)."""
    units = [['A', 690, '2004-11', 'done', BONG],
             ['A', 690, '2004-12', 'done', BONG],
             ['B', 300, '2030-03', 'sched', OTHER],
             ['C', 120, '2019-07', 'done', '']]      # 지번 없음 — 안 접힘
    new, _, _, _ = R.rebuild_entry(_entry(units))
    assert sum(u[1] for u in new['units']) == \
        sum(new['done_q'].values()) + sum(new['sched_q'].values())
    assert sum(new['done_q'].values()) == 690 + 120
    assert sum(new['sched_q'].values()) == 300


def test_rebuild_keeps_demol_and_other_fields_untouched():
    # 멸실은 이번 감사에서 실측하지 않았고 값의 대부분이 벌크 백필분이다.
    e = _entry([['A', 100, '2020-01', 'done', BONG]], demol_q={'2021Q2': 55})
    new, _, _, _ = R.rebuild_entry(e)
    assert new['demol_q'] == {'2021Q2': 55}
    assert new['name'] == '원주시'


def test_rebuild_noop_on_entry_without_units():
    # 아주 옛 스키마(units 자체가 없음)는 판단 근거가 없으므로 손대지 않는다.
    e = {'name': '어딘가', 'done_q': {'2020Q1': 10}}
    new, folded, d_drop, s_drop = R.rebuild_entry(e)
    assert new is e and folded == 0 and d_drop == 0 and s_drop == 0


def test_rebuild_is_idempotent():
    # 재시딩 중 코드가 갱신되면 일부는 이미 접힌 채 저장된다 — 다시 돌려도 같아야 한다.
    units = [['A', 690, '2004-11', 'done', BONG] for _ in range(3)]
    once, _, _, _ = R.rebuild_entry(_entry(units))
    twice, folded, d_drop, s_drop = R.rebuild_entry(once)
    assert twice['done_q'] == once['done_q']
    assert folded == 0 and d_drop == 0 and s_drop == 0


def test_rebuild_orders_units_done_first_then_by_size():
    # 화면이 done/sched 2섹션이라 저장 순서를 stage별로 유지한다.
    units = [['작은done', 50, '2020-01', 'done', BONG],
             ['큰sched', 900, '2030-01', 'sched', OTHER],
             ['큰done', 700, '2020-01', 'done', OTHER + 'x']]
    new, _, _, _ = R.rebuild_entry(_entry(units))
    stages = [u[3] for u in new['units']]
    assert stages == ['done', 'done', 'sched']
    assert [u[1] for u in new['units'] if u[3] == 'done'] == [700, 50]

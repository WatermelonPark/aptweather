# -*- coding: utf-8 -*-
"""공급 계열의 '완비된 달' 기준은 원천이 실제로 줄 수 있는 이름으로만 재야 한다.

2026-09 실사고. `_drop_incomplete`에 넘기는 기준 집합이 저장 계열의 키
(`set(D['series'])`)였는데, 거기엔 '기타광역시'·'기타지방'이 들어 있다. 그 둘은
`_supply_region()`이 **중간 집계행이라고 일부러 버리는** 이름이라 원천 응답에는
영영 나타나지 않는다. 그래서 `missing`이 절대 비지 않아 **모든 달이 제외됐고**,
분양·미분양 갱신이 며칠간 통째로 멈췄다(배치 로그에 '완비된 달이 없어 건너뜀'이
매 회차). 저장분 미분양이 2026.06에 묶여 있었다.

고약한 점은 이게 **조용했다**는 것이다. 원천 개편 때 틀린 값이 들어오는 걸 막으려고
넣은 가드가 반대로 조용한 정지를 만들었고, 같은 날 추가된 감시 함수가
`WEEKLY_REGIONS` 기준(16곳)으로 따로 재는 바람에 우연히 같은 달을 가리켜 초록불이
떴다. 두 방어선이 서로를 가렸다.

여기서 지키는 것은 두 가지다.
 ① 우리 시도가 다 온 달은 **반드시 살아남는다**(정지 재발 방지).
 ② 한 곳이라도 빠진 달은 **반드시 제외된다**(원래 목적인 조용한 오염 방지).
그리고 기준 집합이 원천에서 도달 가능한 이름들인지도 함께 본다.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), '..', 'update_adv_data.py')


def _full_month():
    return {(2026, 7): {r: 100 for r in U.SUPPLY_SIDO}}


def test_complete_month_survives():
    """이게 깨지면 공급 갱신이 통째로 멈춘다 — 실사고가 정확히 이 모양이었다."""
    f = _full_month()
    U._drop_incomplete(f, U.SUPPLY_SIDO, '분양')
    assert (2026, 7) in f, '우리 시도가 다 온 달이 제외됐다 — 갱신이 멈춘다'


def test_month_missing_a_sido_is_dropped():
    """가드의 원래 목적. 한 곳이 빠지면 롤업 전국이 그만큼 적어지는데 합계 검사는
    양쪽이 똑같이 적어 통과한다 — 조용히 틀린 값이 되는 경로다."""
    f = _full_month()
    f[(2026, 7)].pop('전남광주')
    U._drop_incomplete(f, U.SUPPLY_SIDO, '미분양')
    assert (2026, 7) not in f, '시도가 빠진 달이 통과했다'


def test_completeness_names_are_reachable_from_the_source():
    """기준 집합의 모든 이름은 `_supply_region()`이 실제로 만들어 내는 것이어야 한다.

    도달 불가능한 이름이 하나라도 섞이면 `missing`이 영영 비지 않아 전부 제외된다.
    두 표의 계층이 달라 형태를 둘 다 확인한다(분양 '기타지방>강원', 미분양 '강원>계').
    """
    for r in U.SUPPLY_SIDO:
        got = {U._supply_region('기타지방>%s' % r), U._supply_region('%s>계' % r)}
        assert r in got, '%s 는 원천 계층에서 나올 수 없는 이름이다' % r


def test_call_site_uses_the_canonical_sido_set():
    """호출부가 저장 계열 키를 그대로 넘기지 않는지 본다.

    행동 시험만으로는 호출부가 다시 `regions`로 돌아가는 것을 못 잡는다 — 함수는
    받은 대로 재기 때문이다. 사고가 난 자리가 바로 거기라 원문으로 고정한다.
    """
    s = open(SRC, encoding='utf-8').read()
    # ⚠️ `def _drop_incomplete(fetched, regions, name)` 정의부가 먼저 걸리므로
    #    'def '가 앞에 붙지 않은 것만 본다(이 시험을 쓰면서 실제로 걸렸다).
    m = re.search(r'(?<!def )_drop_incomplete\(fetched,\s*([A-Za-z_]+),', s)
    assert m, '_drop_incomplete 호출을 찾지 못했다 — 이름이 바뀌었으면 이 시험도 고칠 것'
    assert m.group(1) == 'SUPPLY_SIDO', (
        "완비 기준으로 '%s'를 넘기고 있다. 저장 계열 키에는 '기타광역시'·'기타지방'이 "
        "섞여 있어 모든 달이 제외된다 — SUPPLY_SIDO를 쓸 것." % m.group(1))


def test_batch_and_watchdog_measure_the_same_thing():
    """감시(rone_latest_complete)와 배치가 같은 집합으로 완비를 재는지.

    기준이 갈리면 배치는 일부러 안 받고 감시는 그걸 뒤처짐이라 하거나(오경보),
    반대로 배치가 멈춘 것을 감시가 못 본다(2026-09에 실제로 후자였다).
    """
    watchdog = {z for z in U.WEEKLY_REGIONS if z not in ('전국', '수도권', '지방')}
    assert set(U.SUPPLY_SIDO) == watchdog, \
        '배치와 감시의 시도 집합이 다르다: %s' % sorted(set(U.SUPPLY_SIDO) ^ watchdog)

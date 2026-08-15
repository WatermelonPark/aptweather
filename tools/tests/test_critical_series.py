# -*- coding: utf-8 -*-
"""핵심 계열(주간)을 못 봤으면 개수와 무관하게 실패해야 한다.

개수 게이트('SKIPPED×2 > len(fails)')는 계열의 값어치를 표현하지 못한다.
R-ONE 하나가 죽으면 주간·월간·분양·미분양이 함께 빠지는데 17계열 중 4개라
임계 아래여서, 주간이 미검증인 채로 초록불이 떴다(2026-08-15 주입 시험으로 재현).
연간 계열이 같은 수만큼 빠지는 건 무해하므로, 개수를 올리는 게 아니라 계열을
지목해서 막는다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import check_freshness as C


@pytest.fixture(autouse=True)
def _clean():
    """모듈 전역 목록을 매 시험마다 비운다 — 다른 시험이 남긴 값이 새면 안 된다."""
    C.SKIPPED[:] = []
    C.FETCH_FAIL[:] = []
    yield
    C.SKIPPED[:] = []
    C.FETCH_FAIL[:] = []


def _exit_code(fn):
    try:
        fn()
    except SystemExit as e:
        return e.code
    return 0


def test_weekly_is_critical():
    """주간은 목록에 있어야 한다 — 이 감시가 존재하는 이유다."""
    assert '주간' in C.CRITICAL_SERIES


def test_skipped_weekly_fails_even_under_count_threshold():
    """주간 포함 4/17이면 개수 게이트는 통과하지만 핵심 게이트가 잡는다."""
    C.SKIPPED[:] = ['주간', '월간', '분양', '미분양']
    fails = [None] * 17                      # 전부 통과 = 뒤처진 계열 없음
    assert len(C.SKIPPED) * 2 <= len(fails), '전제: 개수 게이트로는 안 걸리는 규모'
    assert _exit_code(lambda: C._gate(fails)) == C.EXIT_RETRYABLE


def test_skipped_non_critical_still_passes():
    """연간 4계열만 빠진 건 봐준다 — 1년에 한 번 바뀌는 값이다."""
    C.SKIPPED[:] = ['보급률', '아파트건설', '주택멸실', '노후주택30년']
    assert _exit_code(lambda: C._gate([None] * 17)) == 0


def test_critical_verdict_is_retryable_not_deterministic():
    """조회 실패이므로 새 IP로 다시 볼 값어치가 있다 — recheck로 가야 한다.

    EXIT_DETERMINISTIC(2)로 나가면 recheck를 건너뛰고 바로 경보한다. 원천이
    잠깐 죽은 밤에 그러면 오경보가 된다.
    """
    C.SKIPPED[:] = ['주간']
    assert _exit_code(lambda: C._gate([None] * 17)) == C.EXIT_RETRYABLE
    assert C.EXIT_RETRYABLE != C.EXIT_DETERMINISTIC

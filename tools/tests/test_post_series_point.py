# -*- coding: utf-8 -*-
"""발행 글의 값과 기준 시점은 **같은 원소**에서 나와야 한다.

2026-09-12 리뷰. `_series_last`가 값은 결측을 걸러낸 목록의 끝에서, 날짜는 원본
목록의 끝에서 뽑고 있었다. 꼬리가 None이면 지난달 값에 이번 달 날짜가 붙어
"전국 미분양은 6만 7천 호입니다(2026.07 기준)"처럼 **발행 글이 틀린 시점을 말한다.**

터지는 조건이 실재한다: merge_basic은 새 달 열을 전 지역 None으로 먼저 만들고
받아온 지역만 채운다. 전국이 아직 안 온 달에 정확히 이 모양이 된다. 발견 시점에는
네 계열 모두 꼬리 None이 0이라 겉으로는 멀쩡했다 — 그래서 주입해서 본다.

블로그가 사이트와 다른 숫자·시점을 말하면 '계산법을 공개한다'는 근거가 무너진다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_naver_post as P  # noqa: E402
import make_theory_post as T  # noqa: E402


def _st(tail):
    return {'미분양': {'dates': ['2026.05', '2026.06', '2026.07'],
                       'series': {'전국': [65000, 67464, tail]}}}


def test_point_matches_the_value_when_tail_is_missing():
    cur, prv, when = P._series_last(_st(None), '미분양')
    assert (cur, prv, when) == (67464, 65000, '2026.06'), \
        '꼬리가 비었는데 이번 달 날짜를 붙였다 — 발행 글이 틀린 시점을 말한다'


def test_normal_tail_still_reports_the_latest():
    cur, prv, when = P._series_last(_st(70000), '미분양')
    assert (cur, prv, when) == (70000, 67464, '2026.07')


def test_too_few_points_returns_nothing():
    """값이 하나뿐이면 '전월 대비'를 쓸 수 없다 — 섹션째 생략되어야 한다."""
    st = {'미분양': {'dates': ['2026.07'], 'series': {'전국': [70000]}}}
    assert P._series_last(st, '미분양') == (None, None, None)


def test_both_publishing_tools_say_the_same_region_count():
    """사이클 곳 수를 두 도구가 다르게 말하면 안 된다. 둘 다 정본을 읽는다."""
    from make_naver_post import CYCLE_SYNC_N as A
    assert A == T.CYCLE_SYNC_N
    descs = [m['desc'] for m in P.MORE_ROTATION if '개 시도' in m['desc']]
    assert descs, 'MORE_ROTATION 에서 곳 수 문장을 찾지 못했다'
    for s in descs:
        assert '%d개 시도' % T.CYCLE_SYNC_N in s, \
            '블로그 문구의 곳 수가 사이트와 다르다: %s' % s

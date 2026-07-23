# -*- coding: utf-8 -*-
"""verify_ref_scale.zone_done_avg 순수함수 스모크 (in-memory 픽스처, 네트워크 없음).

실행: python tools/test_verify_ref_scale.py
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_ref_scale as V


def _q(delta_from_current):
    """오늘 기준 delta_from_current분기 전 라벨('YYYYQn'). 0=이번 분기."""
    today = datetime.date.today()
    n = today.year * 4 + (today.month - 1) // 3 - delta_from_current
    y, qi = n // 4, n % 4 + 1
    return '%dQ%d' % (y, qi)


def test_zone_done_avg_aggregates_and_averages():
    hp = {
        'sgg': {
            'A1': {'done_q': {_q(0): 100, _q(1): 200}},   # 존X 소속
            'A2': {'done_q': {_q(0): 50}},                 # 존X 소속 (같은 존 합산)
            'B1': {'permit_q': {_q(0): 9999}},              # done_q 없음(구스키마) → 무시
            'C1': {'done_q': {_q(20): 10}},                 # 최근 3년(12분기) 창 밖 → 제외
            'D1': {'done_q': {_q(0): 5}},                   # z_of에 없는 코드 → 무시
        }
    }
    z_of = {'A1': '존X', 'A2': '존X', 'B1': '존Y', 'C1': '존Z'}   # D1은 매핑 없음(의도적)

    out = V.zone_done_avg(hp, z_of, n_years=3)

    assert '존X' in out, out
    avg, nq = out['존X']
    # 분기0: 100+50=150, 분기1: 200 → 평균 = (150+200)/2 = 175, 표본분기수=2
    assert nq == 2, nq
    assert abs(avg - 175.0) < 1e-9, avg
    assert '존Y' not in out    # done_q 없는 시군구만 있던 존은 방출되지 않음
    assert '존Z' not in out    # 최근 3년 창 밖 데이터만 있던 존은 방출되지 않음
    print('OK: test_zone_done_avg_aggregates_and_averages')


def test_zone_done_avg_empty_when_no_done_q():
    hp = {'sgg': {'X1': {'permit_q': {_q(0): 1}, 'start_q': {_q(0): 1}}}}
    z_of = {'X1': '존X'}
    out = V.zone_done_avg(hp, z_of, n_years=3)
    assert out == {}, out
    print('OK: test_zone_done_avg_empty_when_no_done_q')


def test_zone_region_and_refq_mirror_calc():
    # make_zone_pages.calc()의 ps 규칙: region=='수도권'이면 무조건 '수도권',
    # 아니면 psido, 그것도 없으면 '수도권' 폴백.
    assert V.zone_region({'region': '수도권', 'psido': '부산'}) == '수도권'
    assert V.zone_region({'region': '경상', 'psido': '부산'}) == '부산'
    assert V.zone_region({'region': '경상', 'psido': None}) == '수도권'

    O = {'ref': {'부산': 5000, '세종': None}, 'band': {'세종': [200, 300]}}
    assert V.zone_refq(O, '부산') == 5000
    assert V.zone_refq(O, '세종') == 250          # ref 없음 → band 중앙값 폴백
    assert V.zone_refq(O, '없는지역') is None
    print('OK: test_zone_region_and_refq_mirror_calc')


if __name__ == '__main__':
    test_zone_done_avg_aggregates_and_averages()
    test_zone_done_avg_empty_when_no_done_q()
    test_zone_region_and_refq_mirror_calc()
    print('all tests passed')

# -*- coding: utf-8 -*-
"""주택총조사 시군구 노후 재고(DT_1JU1521) 집계 규칙.

시도값 안분을 걷어내고 시군구 실측 합계로 바꾼 2026-08-04 작업의 안전장치.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U


def _row(c1, nm, dt):
    return {'C1': c1, 'C1_NM': nm, 'DT': dt, 'C2_NM': '30년 이상'}


def test_sgg_rows_drop_gu_of_merged_city():
    """통합시와 그 일반구가 둘 다 등재돼 있다(성남시 31020 + 분당구 31023).
    그대로 더하면 경기가 602,215 -> 989,206으로 64% 부푼다."""
    rows = [_row('31020', '성남시', '91614'), _row('31021', '수정구', '20000'),
            _row('31022', '중원구', '30000'), _row('31023', '분당구', '41614')]
    kept = U._aged30_sgg_rows(rows)
    assert [r['C1_NM'] for r in kept] == ['성남시']


def test_sgg_rows_drop_dong_eup_myeon_aggregates():
    """꼬리 003/004/005는 동부/읍부/면부 집계행이라 시군구가 아니다."""
    rows = [_row('31010', '수원시', '41022'), _row('31003', '동부', '569503'),
            _row('31004', '읍부', '25628'), _row('31005', '면부', '7084')]
    assert [r['C1_NM'] for r in U._aged30_sgg_rows(rows)] == ['수원시']


def test_sgg_rows_drop_sido_and_national_rows():
    rows = [_row('00', '전국', '2953380'), _row('31', '경기도', '602215'),
            _row('31010', '수원시', '41022')]
    assert [r['C1_NM'] for r in U._aged30_sgg_rows(rows)] == ['수원시']


def test_zone_of_resolves_across_sido_boundary():
    """생활권은 시도 경계를 넘는다 — 대구권은 경북 경산·칠곡을 문다."""
    assert U.lz_zone_of('대구', '수성구') == '대구권'
    assert U.lz_zone_of('경북', '경산시') == '대구권'
    assert U.lz_zone_of('경남', '양산시') == '부산권'


def test_zone_of_keeps_gyeonggi_gwangju_separate():
    """경기 광주시가 광주광역시에 합산된 전례가 있다(4,797세대)."""
    assert U.lz_zone_of('경기', '광주시') == '경기광주권'
    assert U.lz_zone_of('광주', '북구') == '광주권'


def test_zone_of_does_not_eat_middle_syllable():
    """replace('시','')를 쓰면 시흥시->흥권, 군포시->포권이 된다."""
    assert U.lz_zone_of('경기', '시흥시') == '시흥권'
    assert U.lz_zone_of('경기', '군포시') == '군포권'


def test_single_zone_assignment_rule():
    """배정 규칙 사본이 늘면 한쪽만 고치게 된다(같은 날 aged_stock에서 실제로 그랬다)."""
    import inspect
    src = inspect.getsource(U)
    assert src.count('def lz_zone_of') == 1
    assert src.count('def gg_zone') == 0, 'zone_of/gg_zone 사본이 다시 생겼다'

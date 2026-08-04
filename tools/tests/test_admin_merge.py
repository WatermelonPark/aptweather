# -*- coding: utf-8 -*-
"""2026-07 행정구역 개편(광주광역시+전라남도 -> 전남광주통합특별시) 대응."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U


def _rows():
    """실제 KOSIS 응답의 계층 순서를 축약 재현."""
    return [
        {'C1': '00', 'C1_NM': '전국', 'DT': '9999'},
        {'C1': '11', 'C1_NM': '서울특별시', 'DT': '4522718'},
        {'C1': '12', 'C1_NM': '전남광주통합특별시', 'DT': '1579042'},
        {'C1': '12110', 'C1_NM': '목포시', 'DT': '102499'},
        {'C1': '12170', 'C1_NM': '나주시', 'DT': '60241'},
        {'C1': '12210', 'C1_NM': '동구', 'DT': '55843'},      # 옛 광주 동구
        {'C1': '12240', 'C1_NM': '서구', 'DT': '133769'},
        {'C1': '12270', 'C1_NM': '남구', 'DT': '96316'},
        {'C1': '12300', 'C1_NM': '북구', 'DT': '203708'},
        {'C1': '12330', 'C1_NM': '광산구', 'DT': '173068'},
        {'C1': '12710', 'C1_NM': '담양군', 'DT': '23834'},
        {'C1': '41', 'C1_NM': '경기도', 'DT': '6181804'},
        {'C1': '41110', 'C1_NM': '수원시', 'DT': '500000'},
    ]


def _parse(monkeypatch):
    monkeypatch.setattr(U, 'http_json', lambda url: _rows())
    monkeypatch.setattr(U, 'KEY', 'x')
    return U._lz_region('DT_1B040B3', 'T1')


def test_merged_sido_is_split_back_into_gwangju_and_jeonnam(monkeypatch):
    """통합 시도를 그대로 흘리면 광주권·목포권·여순광권 3개 존(268만 명)이
    조용히 사라진다 — livezone 급감 가드는 44->41이라 안 걸린다."""
    sido, sgg = _parse(monkeypatch)
    assert sido['광주'] == 55843 + 133769 + 96316 + 203708 + 173068
    assert sido['전남'] == 1579042 - sido['광주']


def test_merged_children_land_in_jeonnam_sgg(monkeypatch):
    sido, sgg = _parse(monkeypatch)
    assert sgg[('전남', '목포시')] == 102499
    assert sgg[('전남', '나주시')] == 60241
    assert sgg[('전남', '담양군')] == 23834


def test_gwangju_gu_do_not_leak_into_sgg(monkeypatch):
    """광역시 구는 시도 단위로만 센다 — sgg에 들어가면 이중계상."""
    sido, sgg = _parse(monkeypatch)
    assert not [k for k in sgg if k[1].endswith('구')]


def test_other_sido_unaffected(monkeypatch):
    sido, sgg = _parse(monkeypatch)
    assert sido['서울'] == 4522718 and sido['경기'] == 6181804
    assert sgg[('경기', '수원시')] == 500000

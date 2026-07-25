import sys, os, io, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import import_demol_bulk as I


# ---------------------------------------------------------------------------
# parse_bulk_stream: 파싱 + 필터 + 분기화 (실제 34컬럼 파이프 포맷 미믹)
# ---------------------------------------------------------------------------

def _row(sgg='11680', bjdong='10100', strt='', end='', extng='', purps='공동주택', hhld='30'):
    """실제 mart_kcy_07.txt 34컬럼 레이아웃을 흉내낸 한 줄을 만든다.
    인덱스: [3]=sgg [4]=bjdong [13]=strt [14]=end [15]=extng [19]=purps [22]=hhld."""
    cols = [''] * 34
    cols[3] = sgg
    cols[4] = bjdong
    cols[13] = strt
    cols[14] = end
    cols[15] = extng
    cols[19] = purps
    cols[22] = hhld
    return '|'.join(cols)


def _write(tmp_path, lines):
    p = tmp_path / 'bulk.txt'
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(p)


def test_parse_filters_non_apt_and_zero_household(tmp_path):
    lines = [
        _row(sgg='11680', end='20240315', purps='공동주택', hhld='100'),
        _row(sgg='11680', end='20240315', purps='단독주택', hhld='50'),   # 유형 제외
        _row(sgg='11680', end='20240315', purps='공동주택', hhld='0'),    # 0세대 제외
    ]
    agg, seen, stats = I.parse_bulk_stream(_write(tmp_path, lines))
    assert agg == {'11680': {'2024Q1': 100}}
    assert stats['apt_positive_rows'] == 1


def test_parse_quarter_fallback_end_extng_strt():
    # to_quarter/fallback 순서는 hub_common.to_quarter + _aggregate_demol과 동일해야 함
    import hub_common as H
    assert H.to_quarter('20240315') == '2024Q1'


def test_parse_prefers_end_day_then_extng_then_strt(tmp_path):
    lines = [
        _row(sgg='11680', strt='20230101', end='20240315', extng='20230601'),  # end 우선
        _row(sgg='11680', strt='20220101', end='', extng='20230610'),           # end 없음 -> extng
        _row(sgg='11680', strt='20210905', end='', extng=''),                    # 둘 다 없음 -> strt
    ]
    agg, seen, stats = I.parse_bulk_stream(_write(tmp_path, lines))
    assert agg['11680'] == {'2024Q1': 30, '2023Q2': 30, '2021Q3': 30}


def test_parse_skips_row_with_no_date_at_all(tmp_path):
    lines = [_row(sgg='11680', strt='', end='', extng='')]
    agg, seen, stats = I.parse_bulk_stream(_write(tmp_path, lines))
    assert agg == {}
    assert stats['apt_positive_no_quarter_rows'] == 1


def test_parse_tracks_seen_codes_regardless_of_apt_filter(tmp_path):
    # seen_codes(커버리지 판정용)는 공동주택 필터와 무관하게 시군구코드 등장 여부만 봄
    lines = [_row(sgg='11680', purps='단독주택', hhld='1', end='20240101')]
    agg, seen, stats = I.parse_bulk_stream(_write(tmp_path, lines))
    assert '11680' in seen
    assert agg == {}   # 단독주택이라 집계 자체엔 안 들어감


def test_parse_skips_malformed_short_row(tmp_path):
    lines = ['a|b|c', _row(sgg='11680', end='20240101', hhld='10')]
    agg, seen, stats = I.parse_bulk_stream(_write(tmp_path, lines))
    assert stats['malformed_rows'] == 1
    assert agg == {'11680': {'2024Q1': 10}}


def test_parse_sums_multiple_rows_same_quarter(tmp_path):
    lines = [
        _row(sgg='11680', end='20240315', hhld='40'),
        _row(sgg='11680', end='20240320', hhld='60'),
    ]
    agg, seen, stats = I.parse_bulk_stream(_write(tmp_path, lines))
    assert agg['11680'] == {'2024Q1': 100}


# ---------------------------------------------------------------------------
# merge_into_hub_permits: rep 매핑 + 병합 정책(overwrite) + 완결성 워닝
# ---------------------------------------------------------------------------

def _fake_groups():
    # 강남(11680, 단일코드), 수원(41110 rep, 다구 분할 41111/41113 멤버 포함),
    # 부천(41190, legacy 불능 — excluded), 안동(37040, 파일에 전혀 없음 — warning 대상)
    return {
        '11680': {'name': '강남구', 'sido': '서울', 'members': ['11680'],
                   'bjdong': {'11680': ['10100']}, 'legacy': None},
        '41110': {'name': '수원시', 'sido': '경기', 'members': ['41110', '41111', '41113'],
                   'bjdong': {}, 'legacy': None},
        '41190': {'name': '부천시', 'sido': '경기', 'members': ['41190'],
                   'bjdong': {}, 'legacy': {'legacy_codes': ['41192', '41194', '41196'], 'enumerable': False}},
        '37040': {'name': '안동시', 'sido': '경북', 'members': ['37040'],
                   'bjdong': {}, 'legacy': None},
    }


def test_merge_maps_multi_gu_member_code_into_rep():
    groups = _fake_groups()
    raw_to_rep = {'11680': '11680', '41110': '41110', '41111': '41110', '41113': '41110',
                  '41190': '41190', '37040': '37040'}
    excluded_reps = {'41190'}
    agg = {'41111': {'2024Q1': 50}, '41110': {'2024Q1': 10}}   # 분당구 격 코드 + 본체 코드
    seen_codes = {'11680', '41110', '41111', '37040'}   # 안동(37040)은 universe엔 있음(공동주택 매치는 없음)

    hp = {'meta': {'scanned_demol': []}, 'sgg': {}}
    newly, warnings, zero_marked, total = I.merge_into_hub_permits(
        hp, agg, seen_codes, groups, raw_to_rep, excluded_reps)

    assert hp['sgg']['41110']['demol_q'] == {'2024Q1': 60}   # 41110+41111 rep 단위로 합산됨
    assert '41110' in hp['meta']['scanned_demol']


def test_merge_marks_zero_coverage_group_scanned_with_empty_demol_q():
    groups = _fake_groups()
    raw_to_rep = {'11680': '11680', '41110': '41110', '41111': '41110', '41113': '41110',
                  '41190': '41190', '37040': '37040'}
    excluded_reps = {'41190'}
    agg = {}   # 아무 매치도 없음
    seen_codes = {'37040'}   # 안동은 universe엔 있지만 실제 공동주택 멸실 매치가 0건

    hp = {'meta': {'scanned_demol': []}, 'sgg': {}}
    newly, warnings, zero_marked, total = I.merge_into_hub_permits(
        hp, agg, seen_codes, groups, raw_to_rep, excluded_reps)

    assert hp['sgg']['37040']['demol_q'] == {}
    assert '37040' in hp['meta']['scanned_demol']
    assert '37040' in zero_marked


def test_merge_warns_and_skips_scanned_demol_for_uncovered_group():
    groups = _fake_groups()
    raw_to_rep = {'11680': '11680', '41110': '41110', '41111': '41110', '41113': '41110',
                  '41190': '41190', '37040': '37040'}
    excluded_reps = {'41190'}
    agg = {}
    seen_codes = {'11680'}   # 안동(37040)은 파일 universe에 아예 없음

    hp = {'meta': {'scanned_demol': []}, 'sgg': {}}
    newly, warnings, zero_marked, total = I.merge_into_hub_permits(
        hp, agg, seen_codes, groups, raw_to_rep, excluded_reps)

    assert '37040' not in hp['meta']['scanned_demol']
    assert ('37040', '안동시') in warnings
    assert '37040' not in hp['sgg']   # 커버 안 된 그룹은 sgg 항목조차 안 건드림


def test_merge_excludes_legacy_group_entirely():
    groups = _fake_groups()
    raw_to_rep = {'11680': '11680', '41190': '41190'}
    excluded_reps = {'41190'}
    agg = {'41190': {'2024Q1': 999}}   # 벌크 파일엔 실제로 41190 행이 있음
    seen_codes = {'41190'}

    hp = {'meta': {'scanned_demol': []}, 'sgg': {}}
    newly, warnings, zero_marked, total = I.merge_into_hub_permits(
        hp, agg, seen_codes, groups, raw_to_rep, excluded_reps)

    # [SKIP legacy]와 동일 정책: 집계도 scanned_demol 등록도 전혀 안 함
    assert '41190' not in hp['sgg']
    assert '41190' not in hp['meta']['scanned_demol']
    assert not any(rep == '41190' for rep, name in warnings)   # warning 대상도 아님(의도적 제외라 별개)


def test_merge_overwrites_prior_demol_q_not_additive():
    groups = {'11680': {'name': '강남구', 'sido': '서울', 'members': ['11680'],
                          'bjdong': {'11680': ['10100']}, 'legacy': None}}
    raw_to_rep = {'11680': '11680'}
    excluded_reps = set()
    agg = {'11680': {'2024Q1': 200}}
    seen_codes = {'11680'}

    hp = {'meta': {'scanned_demol': ['11680']},
          'sgg': {'11680': {'name': '강남구', 'demol_q': {'2024Q1': 5, '2019Q1': 999}}}}
    newly, warnings, zero_marked, total = I.merge_into_hub_permits(
        hp, agg, seen_codes, groups, raw_to_rep, excluded_reps)

    # 더하기(205)가 아니라 통째로 덮어써 200이어야 함(overwrite 정책)
    assert hp['sgg']['11680']['demol_q'] == {'2024Q1': 200}
    assert newly == []   # 이미 scanned_demol에 있었으니 "신규" 아님


def test_merge_preserves_done_sched_units_fields():
    groups = {'11680': {'name': '강남구', 'sido': '서울', 'members': ['11680'],
                          'bjdong': {'11680': ['10100']}, 'legacy': None}}
    raw_to_rep = {'11680': '11680'}
    excluded_reps = set()
    agg = {'11680': {'2024Q1': 10}}
    seen_codes = {'11680'}

    hp = {'meta': {'scanned_demol': []},
          'sgg': {'11680': {'name': '강남구', 'done_q': {'2020Q1': 40}, 'sched_q': {}, 'units': [['x', 1, '2020-01', 'done']]}}}
    I.merge_into_hub_permits(hp, agg, seen_codes, groups, raw_to_rep, excluded_reps)

    assert hp['sgg']['11680']['done_q'] == {'2020Q1': 40}
    assert hp['sgg']['11680']['units'] == [['x', 1, '2020-01', 'done']]
    assert hp['sgg']['11680']['demol_q'] == {'2024Q1': 10}


def test_merge_total_seats_sums_across_reps():
    groups = _fake_groups()
    raw_to_rep = {'11680': '11680', '41110': '41110', '41111': '41110', '41113': '41110',
                  '41190': '41190', '37040': '37040'}
    excluded_reps = {'41190'}
    agg = {'11680': {'2024Q1': 30}, '41111': {'2024Q1': 20}}
    seen_codes = {'11680', '41111'}

    hp = {'meta': {'scanned_demol': []}, 'sgg': {}}
    newly, warnings, zero_marked, total = I.merge_into_hub_permits(
        hp, agg, seen_codes, groups, raw_to_rep, excluded_reps)
    assert total == 50


# ---------------------------------------------------------------------------
# build_rep_maps: fetch_hub_permits.build_targets() 재사용 확인(모킹)
# ---------------------------------------------------------------------------

def test_build_rep_maps_reuses_build_targets_and_flags_legacy(monkeypatch):
    import fetch_hub_permits as F
    fake_groups = {
        '41370': {'name': '오산시', 'sido': '경기', 'members': ['41370'],
                   'bjdong': {'41370': ['11300']}, 'legacy': None},
        '41190': {'name': '부천시', 'sido': '경기', 'members': ['41190'],
                   'bjdong': {'41190': ['10100']},
                   'legacy': {'legacy_codes': ['41192', '41194', '41196'], 'enumerable': False}},
    }
    monkeypatch.setattr(F, 'build_targets', lambda: (fake_groups, []))
    groups, raw_to_rep, excluded_reps = I.build_rep_maps()
    assert groups == fake_groups
    assert raw_to_rep['41370'] == '41370'
    assert raw_to_rep['41190'] == '41190'
    assert excluded_reps == {'41190'}

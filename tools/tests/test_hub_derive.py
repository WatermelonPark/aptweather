import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U

def _bdong(): return {'41370':('경기도','오산시'), '41131':('경기도','성남시 수정구')}

def test_hub_zone_map_leading_token():
    z = U._hub_zone_map(_bdong())
    assert z['41370'] == '오산권'
    assert z['41131'] == '성남권'

def test_hub_derive_inactive_emits_nothing(tmp_path, monkeypatch):
    # meta.activate=false → done/sched 미방출
    adv = {'permits': {}}
    hp = {'meta': {'activate': False, 'scanned': [], 'unresolved_legacy': []}, 'sgg': {}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)      # 아래 구현이 이 헬퍼를 씀
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert 'done' not in adv['permits'] and 'sched' not in adv['permits']

def test_hub_derive_active_complete_zone_only(tmp_path, monkeypatch):
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': ['41370'], 'unresolved_legacy': []},
          'sgg': {'41370': {'name':'오산시','done_q':{'2023Q1':100},'sched_q':{'2028Q2':200}}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert adv['permits']['done']['오산권'] == {'2023Q1':100}
    assert adv['permits']['sched']['오산권'] == {'2028Q2':200}


# ---------------------------------------------------------------------------
# Fix C1(FINAL review): 구가 나뉜 다구 도시(수원·성남·창원 등)는 fetch_hub_permits의
# fold_groups가 전부 대표(rep) 코드 하나로 접어 hub_permits.json에 저장한다
# (수원권 = 41110 본체 + 41111/41113/41115/41117 4개 구 -> rep=41110). 완결성 게이트가
# rep 환산 없이 원시 구 코드 전원을 scanned와 직접 비교하면, 대표가 아닌 구 코드는
# scanned에 결코 나타나지 않으므로 이런 다구 도시 존은 activate 이후에도 영원히
# 미완결(폴백)로 남는다 — 이 테스트는 실제 수원시 코드 구성(code_bdong.json 실측)으로
# 그 버그를 재현/검증한다.
# ---------------------------------------------------------------------------

def _bdong_suwon():
    """수원시 실제 코드 구성(2026-07 code_bdong.json 실측): 본체 41110 + 구 4개."""
    return {
        '41110': ('경기도', '수원시'),
        '41111': ('경기도', '수원시 장안구'),
        '41113': ('경기도', '수원시 권선구'),
        '41115': ('경기도', '수원시 팔달구'),
        '41117': ('경기도', '수원시 영통구'),
    }


def test_hub_group_reps_folds_multi_gu_codes_to_min_code():
    reps = U._hub_group_reps(_bdong_suwon())
    assert reps['41110'] == '41110'   # 본체(대표) 자기 자신
    assert reps['41111'] == '41110'
    assert reps['41113'] == '41110'
    assert reps['41115'] == '41110'
    assert reps['41117'] == '41110'


def test_hub_derive_multi_gu_zone_complete_when_rep_scanned(monkeypatch):
    # hub_permits.json의 sgg/scanned 키는 수집기가 접은 rep(41110)뿐이다 — 원시 구
    # 코드(41111 등)는 scanned에 결코 안 들어온다. rep만 scanned여도 존은 완결로
    # 방출돼야 한다(고치기 전엔 members<=scanned가 실패해 영원히 미완결이었다).
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': ['41110'], 'unresolved_legacy': []},
          'sgg': {'41110': {'name': '수원시', 'done_q': {'2023Q1': 1000},
                             'sched_q': {'2028Q2': 2000}}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong_suwon())
    U.hub_derive(adv)
    assert adv['permits']['done']['수원권'] == {'2023Q1': 1000}
    assert adv['permits']['sched']['수원권'] == {'2028Q2': 2000}


def test_hub_derive_multi_gu_zone_incomplete_when_rep_not_scanned(monkeypatch):
    # rep(41110)이 scanned에 없으면(아직 수집 안 됨) — sgg에 값이 있어도 미완결이라
    # 방출하면 안 된다.
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': [], 'unresolved_legacy': []},
          'sgg': {'41110': {'name': '수원시', 'done_q': {'2023Q1': 1000}, 'sched_q': {}}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong_suwon())
    U.hub_derive(adv)
    assert '수원권' not in adv['permits'].get('done', {})


# ---------------------------------------------------------------------------
# Task 7: permits['units'][zone] — 존 상세페이지 2섹션(앞으로 들어올 물량/
# 최근 들어온 물량) 렌더용 소량 단지 리스트
# ---------------------------------------------------------------------------

def test_hub_derive_injects_units_sorted_and_capped(tmp_path, monkeypatch):
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': ['41370'], 'unresolved_legacy': []},
          'sgg': {'41370': {
              'name': '오산시',
              'done_q': {'2023Q1': 300}, 'sched_q': {'2028Q2': 500, '2027Q1': 400},
              'units': [
                  ['오산자이', 300, '2023-01', 'done'],
                  ['오산푸르지오', 200, '2022-06', 'done'],
                  ['오산센트럴', 500, '2028-04', 'sched'],
                  ['오산더샵', 400, '2027-03', 'sched'],
              ]}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    u = adv['permits']['units']['오산권']
    # done: 준공 연월 내림차순(최신 먼저)
    assert u['done'] == [['오산자이', 300, '2023-01'], ['오산푸르지오', 200, '2022-06']]
    # sched: 준공예정 연월 오름차순(가까운 미래 먼저)
    assert u['sched'] == [['오산더샵', 400, '2027-03'], ['오산센트럴', 500, '2028-04']]


def test_hub_derive_units_caps_at_top_20_by_household(monkeypatch):
    adv = {'permits': {}}
    units = [['단지%d' % i, 100 + i, '2029-%02d' % ((i % 12) + 1), 'sched'] for i in range(30)]
    hp = {'meta': {'activate': True, 'scanned': ['41370'], 'unresolved_legacy': []},
          'sgg': {'41370': {'name': '오산시', 'done_q': {}, 'sched_q': {}, 'units': units}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    sched = adv['permits']['units']['오산권']['sched']
    assert len(sched) == 20
    # 상위 20은 세대 큰 순(100+10..100+29)으로 뽑힌 뒤 날짜순 재정렬됨
    assert set(u[1] for u in sched) == set(range(110, 130))


def test_hub_derive_units_missing_date_sorts_last(monkeypatch):
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': ['41370'], 'unresolved_legacy': []},
          'sgg': {'41370': {'name': '오산시', 'done_q': {}, 'sched_q': {}, 'units': [
              ['오산미정단지', 999, None, 'sched'],
              ['오산확정단지', 100, '2027-05', 'sched'],
          ]}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    sched = adv['permits']['units']['오산권']['sched']
    assert sched[0][0] == '오산확정단지'
    assert sched[1][0] == '오산미정단지'   # 연월 결측은 맨 뒤


def test_hub_derive_all_members_unresolved_zone_emits_nothing(monkeypatch):
    # 오산권의 유일한 멤버 41370이 통째로 unresolved_legacy면 members[존]가 populate
    # 자체가 안 되어(defaultdict라 add()가 한 번도 안 불림) complete 집합에 못 들어가야
    # 한다(hub_derive의 `if ms` 가드 — 빈 멤버 집합인 존은 방출 금지).
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': ['41370'], 'unresolved_legacy': ['41370']},
          'sgg': {'41370': {'name': '오산시', 'done_q': {'2023Q1': 100}, 'sched_q': {'2028Q2': 200},
                             'units': [['오산자이', 100, '2023-01', 'done']]}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert '오산권' not in adv['permits'].get('done', {})
    assert '오산권' not in adv['permits'].get('sched', {})
    assert '오산권' not in adv['permits'].get('units', {})


# ---------------------------------------------------------------------------
# Task B: permits['demol'][zone] — 멸실(demolition) 시계열, scanned_demol 게이트
# (done/sched의 scanned와 독립적인 별도 완결성 게이트)
# ---------------------------------------------------------------------------

def test_hub_derive_demol_emitted_when_zone_complete_in_scanned_demol(monkeypatch):
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': ['41370'], 'scanned_demol': ['41370'],
                   'unresolved_legacy': []},
          'sgg': {'41370': {'name': '오산시', 'done_q': {'2023Q1': 100},
                             'sched_q': {'2028Q2': 200},
                             'demol_q': {'2014Q1': 50, '2015Q2': 30}}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert adv['permits']['demol']['오산권'] == {'2014Q1': 50, '2015Q2': 30}


def test_hub_derive_demol_not_emitted_when_zone_incomplete_in_scanned_demol(monkeypatch):
    # done/sched는 완결(scanned에 있음)이어도 scanned_demol에 없으면 demol은 방출 안 함.
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': ['41370'], 'scanned_demol': [],
                   'unresolved_legacy': []},
          'sgg': {'41370': {'name': '오산시', 'done_q': {'2023Q1': 100},
                             'sched_q': {'2028Q2': 200},
                             'demol_q': {'2014Q1': 50}}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert '오산권' not in adv['permits'].get('demol', {})
    # done/sched는 영향받지 않아야 함
    assert adv['permits']['done']['오산권'] == {'2023Q1': 100}
    assert adv['permits']['sched']['오산권'] == {'2028Q2': 200}


def test_hub_derive_inactive_emits_no_demol(monkeypatch):
    adv = {'permits': {}}
    hp = {'meta': {'activate': False, 'scanned': [], 'scanned_demol': [],
                   'unresolved_legacy': []}, 'sgg': {}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert 'demol' not in adv['permits']


# ---------------------------------------------------------------------------
# 강원(42xxx->51xxx) 코드 정정: code_bdong.json이 원주/춘천/강릉권의 신 코드를
# 아예 갖고 있지 않은 실측 갭에 대한 _load_bdong_map()의 GANGWON_CODE_FIX
# RENAME 보정. 옛 코드를 남겨두면 _hub_group_reps가 신/구를 같은 (시도,이름)
# 그룹으로 묶어 rep이 다시 42xxx로 돌아가버리므로(문자열 정렬상 42<51),
# 그 회귀를 함께 방지한다.
#
# 강릉권은 LIVEZONE상 강릉시 외에 동해시(42170->51170)·속초시(42210->51210)도
# 멤버다. 이 둘은 fold_groups가 (시도,이름) 단위로 묶기 때문에 강릉시와 별개
# 그룹(각자가 자기 rep)이라, 애초 GANGWON_CODE_FIX(42110/42130/42150)가
# 강릉시만 고치고 이 둘은 놓쳤었다 — 동일 패턴(sigunguCd=51170/51210 실호출
# -> resultCode=00·item 존재; 42170/42210은 resultCode=00·item 0개)을 실측
# 확인(2026-07-25)해 GANGWON_CODE_FIX에 추가했다. 지금은 다섯 코드 전부가
# 정정 범위이므로, 강릉권의 완결성 게이트는 강릉시/동해시/속초시 3개 rep
# (51150/51170/51210) 전원이 scanned일 때만 통과한다.
# ---------------------------------------------------------------------------

def test_hub_zone_map_resolves_real_gangwon_51xxx_codes():
    # 실제 code_bdong.json(네트워크 없음) 기준 — 신 코드가 파일에 아예 없다는
    # 확인된 갭을 _load_bdong_map()의 정정이 메꾸는지 검증.
    bdong = U._load_bdong_map()
    z = U._hub_zone_map(bdong)
    assert z['51110'] == '춘천권'
    assert z['51130'] == '원주권'
    assert z['51150'] == '강릉권'
    assert z['51170'] == '강릉권'
    assert z['51210'] == '강릉권'
    for stale in ('42110', '42130', '42150', '42170', '42210'):
        assert stale not in bdong


def test_hub_group_reps_gangwon_51xxx_maps_to_itself_not_stale_42xxx():
    # rep이 42xxx로 되돌아가면(신/구가 같은 그룹으로 묶이는 회귀) 완결성 게이트가
    # hub_permits.json에 실제로 기록되는 51xxx scanned와 영영 안 맞아 미완결로 남는다.
    bdong = U._load_bdong_map()
    reps = U._hub_group_reps(bdong)
    assert reps['51110'] == '51110'
    assert reps['51130'] == '51130'
    assert reps['51150'] == '51150'
    assert reps['51170'] == '51170'
    assert reps['51210'] == '51210'


def test_hub_derive_gangwon_zones_populate_when_51xxx_scanned(monkeypatch):
    # 51xxx로 재시딩된 hub_permits.json을 가정하고, 춘천/원주/강릉권이 실제로
    # 방출되는지 end-to-end로 확인. 강릉권은 강릉시/동해시/속초시 3개 rep이
    # 모두 scanned여야 완결이라, done/sched/demol은 세 시군구 합계여야 한다.
    adv = {'permits': {}}
    bdong = {
        '51110': ('강원특별자치도', '춘천시'),
        '51130': ('강원특별자치도', '원주시'),
        '51150': ('강원특별자치도', '강릉시'),
        '51170': ('강원특별자치도', '동해시'),
        '51210': ('강원특별자치도', '속초시'),
    }
    hp = {'meta': {'activate': True,
                   'scanned': ['51110', '51130', '51150', '51170', '51210'],
                   'scanned_demol': ['51110', '51130', '51150', '51170', '51210'],
                   'unresolved_legacy': []},
          'sgg': {
              '51110': {'name': '춘천시', 'done_q': {'2024Q1': 100}, 'sched_q': {'2028Q2': 50},
                         'demol_q': {'2020Q1': 10}},
              '51130': {'name': '원주시', 'done_q': {'2024Q1': 200}, 'sched_q': {'2028Q2': 60},
                         'demol_q': {'2020Q1': 20}},
              '51150': {'name': '강릉시', 'done_q': {'2024Q1': 300}, 'sched_q': {'2028Q2': 70},
                         'demol_q': {'2020Q1': 30}},
              '51170': {'name': '동해시', 'done_q': {'2024Q1': 30}, 'sched_q': {'2028Q2': 7},
                         'demol_q': {'2020Q1': 3}},
              '51210': {'name': '속초시', 'done_q': {'2024Q1': 20}, 'sched_q': {'2028Q2': 5},
                         'demol_q': {'2020Q1': 2}},
          }}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: bdong)
    U.hub_derive(adv)
    assert adv['permits']['done']['춘천권'] == {'2024Q1': 100}
    assert adv['permits']['done']['원주권'] == {'2024Q1': 200}
    assert adv['permits']['done']['강릉권'] == {'2024Q1': 350}   # 강릉+동해+속초 합계
    assert adv['permits']['sched']['춘천권'] == {'2028Q2': 50}
    assert adv['permits']['sched']['강릉권'] == {'2028Q2': 82}
    assert adv['permits']['demol']['춘천권'] == {'2020Q1': 10}
    assert adv['permits']['demol']['원주권'] == {'2020Q1': 20}
    assert adv['permits']['demol']['강릉권'] == {'2020Q1': 35}


def test_hub_derive_gangneung_zone_incomplete_when_donghae_sokcho_not_scanned(monkeypatch):
    # 강릉시(51150)만 scanned고 동해/속초(51170/51210)가 아직이면, 강릉권 전체가
    # 미완결로 방출되면 안 된다(부분합이 전체인 척하면 안 됨 — 완결성 게이트).
    adv = {'permits': {}}
    bdong = {
        '51150': ('강원특별자치도', '강릉시'),
        '51170': ('강원특별자치도', '동해시'),
        '51210': ('강원특별자치도', '속초시'),
    }
    hp = {'meta': {'activate': True, 'scanned': ['51150'], 'unresolved_legacy': []},
          'sgg': {'51150': {'name': '강릉시', 'done_q': {'2024Q1': 300}, 'sched_q': {'2028Q2': 70}}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: bdong)
    U.hub_derive(adv)
    assert '강릉권' not in adv['permits'].get('done', {})
    assert '강릉권' not in adv['permits'].get('sched', {})


def test_hub_derive_units_excludes_incomplete_zone(monkeypatch):
    # done_q/sched_q와 동일한 완결성 게이트 — scanned에 없는 시군구가 섞이면
    # 그 존은 units도 전혀 방출되면 안 된다(부분 리스트가 전체인 척하면 안 됨).
    adv = {'permits': {}}
    hp = {'meta': {'activate': True, 'scanned': [], 'unresolved_legacy': []},   # 41370 미스캔
          'sgg': {'41370': {'name': '오산시', 'done_q': {'2023Q1': 100}, 'sched_q': {},
                             'units': [['오산자이', 100, '2023-01', 'done']]}}}
    monkeypatch.setattr(U, '_load_hub_permits', lambda: hp)
    monkeypatch.setattr(U, '_load_bdong_map', lambda: _bdong())
    U.hub_derive(adv)
    assert '오산권' not in adv['permits'].get('units', {})

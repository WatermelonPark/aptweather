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

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

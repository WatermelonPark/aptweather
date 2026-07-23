"""Task 5: 건축HUB 시군구 실측 -> 존별 permits['meas']/permits['fwd_far'] 집계기.

네트워크·10MB 원본 code_bdong.json 접근 없음: 전부 작은 인메모리/tmp_path 픽스처.
"""
import sys, os, io, json, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U


def _bdong_payload(rows):
    """rows: [(sgg_cd, sido_full, sgg_nm, era_or_None), ...] -> code_bdong.json 컬럼형."""
    nan = float('nan')
    sido, cd, nm, era = {}, {}, {}, {}
    for i, (c, sd, n, e) in enumerate(rows):
        k = str(i)
        sido[k] = sd; cd[k] = c; nm[k] = n; era[k] = nan if e is None else e
    return {'시도명': sido, '시군구코드': cd, '시군구명': nm, '말소일자': era}


def _write_bdong(tmp_path, rows):
    p = tmp_path / 'code_bdong.json'
    p.write_text(json.dumps(_bdong_payload(rows), ensure_ascii=False), encoding='utf-8')


def _write_hub(tmp_path, sgg, unresolved_legacy=None):
    p = tmp_path / 'hub_permits.json'
    payload = {'meta': {'unresolved_legacy': unresolved_legacy or []}, 'sgg': sgg}
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


# ---------------------------------------------------------------------------
# _hub_zone_map: sigunguCd -> zone, 존 규칙 재현 확인
# ---------------------------------------------------------------------------

def test_hub_zone_map_gyeonggi_dynamic_zone():
    bdong = {'41370': ('경기도', '오산시')}
    assert U._hub_zone_map(bdong) == {'41370': '오산권'}


def test_hub_zone_map_seoul_gu_falls_to_metro_zone():
    bdong = {'11680': ('서울특별시', '강남구')}
    assert U._hub_zone_map(bdong) == {'11680': '서울권'}


def test_hub_zone_map_changwon_gu_folds_to_si_named_zone():
    bdong = {'48125': ('경상남도', '창원시 마산합포구')}
    assert U._hub_zone_map(bdong) == {'48125': '창원권'}


def test_hub_zone_map_named_provincial_zone():
    bdong = {'48170': ('경상남도', '진주시')}
    assert U._hub_zone_map(bdong) == {'48170': '진주권'}


def test_hub_zone_map_unresolvable_sigungu_is_omitted():
    # LIVEZONE에도 없고 경기도 아닌 시군구는 매핑에서 빠져야(orphan 판정 재료) 함.
    bdong = {'42123': ('강원특별자치도', '정선군')}
    assert U._hub_zone_map(bdong) == {}


def test_hub_zone_map_gyeonggi_multi_gu_city_seongnam_bundang():
    # LZ_GU2SI에 없는 경기 다구 도시("시 구" 결합형) -> parts[-1](구)을 쓰면
    # gg_zone('분당구')가 존재하지 않는 '분당구권'을 만들어낸다(수정 전 버그).
    # 선두 토큰("성남시")을 취해야 정상적으로 성남권에 접힌다.
    bdong = {'41135': ('경기도', '성남시 분당구')}
    assert U._hub_zone_map(bdong) == {'41135': '성남권'}


def test_hub_zone_map_gyeonggi_multi_gu_city_suwon_yeongtong():
    bdong = {'41117': ('경기도', '수원시 영통구')}
    assert U._hub_zone_map(bdong) == {'41117': '수원권'}


def test_hub_zone_map_gyeonggi_multi_gu_city_goyang_deokyang():
    bdong = {'41281': ('경기도', '고양시 덕양구')}
    assert U._hub_zone_map(bdong) == {'41281': '고양권'}


def test_hub_zone_map_gyeonggi_multi_gu_city_yongin_giheung():
    bdong = {'41465': ('경기도', '용인시 기흥구')}
    assert U._hub_zone_map(bdong) == {'41465': '용인권'}


def test_hub_zone_map_changwon_gu_lz_gu2si_still_correct():
    # LZ_GU2SI에 등록된 구(창원)는 선두 토큰 방식으로도 여전히 올바르다.
    bdong = {'48125': ('경상남도', '창원시 마산합포구')}
    assert U._hub_zone_map(bdong) == {'48125': '창원권'}


def test_hub_zone_map_cheongju_gu_lz_gu2si_still_correct():
    bdong = {'43111': ('충청북도', '청주시 상당구')}
    assert U._hub_zone_map(bdong) == {'43111': '청주권'}


def test_hub_zone_map_gyeonggi_gwangju_name_collision_with_metro():
    # 경기 광주시는 '광주권'(광주광역시)과 이름이 겹쳐 '경기광주권'으로 분리된다.
    bdong = {'41610': ('경기도', '광주시')}
    assert U._hub_zone_map(bdong) == {'41610': '경기광주권'}


def test_hub_zone_map_gwangju_metro_maps_to_gwangju_zone():
    bdong = {'29155': ('광주광역시', '서구')}
    assert U._hub_zone_map(bdong) == {'29155': '광주권'}


def test_hub_zone_map_seoul_gu_single_token_falls_to_metro_zone():
    # 서울 등 광역시 구(1토큰, "구"만) -> zone_of(sd,'*')가 먼저 걸려 서울권.
    bdong = {'11650': ('서울특별시', '서초구')}
    assert U._hub_zone_map(bdong) == {'11650': '서울권'}


# ---------------------------------------------------------------------------
# hub_derive: meas 연평균 정규화(윈도우 밖 분기 제외) + fwd_far(착공+13분기 합산)
# ---------------------------------------------------------------------------

def test_hub_derive_meas_annualizes_and_excludes_out_of_window(tmp_path, monkeypatch, capsys):
    cur = datetime.date.today().year
    monkeypatch.setattr(U, 'TOOLS_DATA', str(tmp_path))
    _write_bdong(tmp_path, [('41370', '경기도', '오산시', None)])
    _write_hub(tmp_path, {
        '41370': {'name': '오산시', 'permit_q': {
            '%dQ1' % cur: 100, '%dQ2' % (cur - 1): 200, '%dQ3' % (cur - 2): 300,
            '%dQ1' % (cur - 4): 9999,   # 3년 윈도우 밖 -> 제외돼야 함
        }, 'start_q': {}},
    })
    adv = {'permits': {}}
    U.hub_derive(adv)
    assert adv['permits']['meas'] == {'오산권': round((100 + 200 + 300) / 3)}
    out = capsys.readouterr().out
    assert 'zones=1 orphan_sgg_ignored=0' in out


def test_hub_derive_fwd_far_shifts_quarter_by_13():
    import hub_common as H
    assert H.shift_quarter('2024Q1', 13) == '2027Q2'


def test_hub_derive_fwd_far_lands_in_shifted_quarter(tmp_path, monkeypatch):
    monkeypatch.setattr(U, 'TOOLS_DATA', str(tmp_path))
    _write_bdong(tmp_path, [('41370', '경기도', '오산시', None)])
    _write_hub(tmp_path, {
        '41370': {'name': '오산시', 'permit_q': {}, 'start_q': {'2024Q1': 500}},
    })
    adv = {'permits': {}}
    U.hub_derive(adv)
    assert adv['permits']['fwd_far'] == {'오산권': {'2027Q2': 500}}


def test_hub_derive_fwd_far_sums_multiple_sigungu_in_same_zone(tmp_path, monkeypatch):
    # 부산권 = ('부산','*') + ('경남','양산시') — 서로 다른 시군구가 한 생활권으로 합산돼야 함.
    monkeypatch.setattr(U, 'TOOLS_DATA', str(tmp_path))
    _write_bdong(tmp_path, [
        ('26470', '부산광역시', '연제구', None),
        ('48330', '경상남도', '양산시', None),
    ])
    _write_hub(tmp_path, {
        '26470': {'name': '연제구', 'permit_q': {}, 'start_q': {'2024Q1': 300}},
        '48330': {'name': '양산시', 'permit_q': {}, 'start_q': {'2024Q1': 200}},
    })
    adv = {'permits': {}}
    U.hub_derive(adv)
    assert adv['permits']['fwd_far'] == {'부산권': {'2027Q2': 500}}


# ---------------------------------------------------------------------------
# orphan 판정 + unresolved_legacy(부천 등) 스킵
# ---------------------------------------------------------------------------

def test_hub_derive_orphan_sigungu_counted_and_excluded_from_meas(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(U, 'TOOLS_DATA', str(tmp_path))
    _write_bdong(tmp_path, [('41370', '경기도', '오산시', None)])
    # '99999'는 code_bdong 픽스처에 아예 없음 -> zone 미해결 -> orphan
    _write_hub(tmp_path, {
        '41370': {'name': '오산시', 'permit_q': {'2024Q1': 10}, 'start_q': {}},
        '99999': {'name': '미상', 'permit_q': {'2024Q1': 10}, 'start_q': {}},
    })
    adv = {'permits': {}}
    U.hub_derive(adv)
    assert '99999' not in adv['permits']['meas']
    assert set(adv['permits']['meas'].keys()) == {'오산권'}
    out = capsys.readouterr().out
    assert 'orphan_sgg_ignored=1' in out


def test_hub_derive_skips_unresolved_legacy_sigungu(tmp_path, monkeypatch, capsys):
    # 부천(41190) 같은 옛 구코드 미해결 항목은 orphan으로도 세지 않고 조용히 건너뛴다
    # (Task 6이 dC 폴백으로 처리 — 여기서 집계 대상이 아님).
    monkeypatch.setattr(U, 'TOOLS_DATA', str(tmp_path))
    _write_bdong(tmp_path, [('41370', '경기도', '오산시', None)])
    _write_hub(tmp_path, {
        '41370': {'name': '오산시', 'permit_q': {'2024Q1': 10}, 'start_q': {}},
        '41190': {'name': '부천', 'permit_q': {'2024Q1': 999}, 'start_q': {}},
    }, unresolved_legacy=['41190'])
    adv = {'permits': {}}
    U.hub_derive(adv)
    assert set(adv['permits']['meas'].keys()) == {'오산권'}
    out = capsys.readouterr().out
    assert 'orphan_sgg_ignored=0' in out   # legacy는 orphan 카운트에 안 들어감


def test_hub_derive_missing_hub_permits_file_is_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(U, 'TOOLS_DATA', str(tmp_path))   # hub_permits.json 없음
    adv = {'permits': {'rows': []}}
    U.hub_derive(adv)
    assert 'meas' not in adv['permits']
    assert 'hub_derive skip' in capsys.readouterr().out

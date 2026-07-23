import sys, os, io, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import fetch_hub_permits as F


# ---------------------------------------------------------------------------
# 두 "무자료" 형태 분류기 (함정3)
# ---------------------------------------------------------------------------

def test_classify_empty_body_is_retryable():
    assert F.classify_response('') == 'empty'
    assert F.classify_response('   ') == 'empty'


def test_classify_json_no_data_param_missing():
    # 파라미터 누락/오류 시 HTTP 200 + JSON {"body":{}} (~69 bytes)
    assert F.classify_response('{"body":{},"header":{"resultCode":"00","resultMsg":"NORMAL SERVICE"}}') == 'no_data_json'


def test_classify_xml_zero_rows_is_normal_no_data():
    xml = ('<response><header><resultCode>00</resultCode></header><body>'
           '<items/><numOfRows>10</numOfRows><pageNo>1</pageNo><totalCount>0</totalCount>'
           '</body></response>')
    assert F.classify_response(xml) == 'no_data_xml'


def test_classify_real_data():
    xml = ('<response><body><items><item><platPlc>서울시 종로구</platPlc>'
           '<purpsCdNm>공동주택</purpsCdNm></item></items><totalCount>1</totalCount></body></response>')
    assert F.classify_response(xml) == 'data'


# ---------------------------------------------------------------------------
# Finding 1: 오류 봉투 XML도 <item> 없이 오지만 진짜 0건과 반드시 구분돼야 함
# ---------------------------------------------------------------------------

def test_classify_service_key_error_envelope_is_error_not_no_data():
    # data.go.kr 서비스키 미등록 오류: cmmMsgHeader 봉투, resultCode 없음
    xml = ('<OpenAPI_ServiceResponse><cmmMsgHeader>'
           '<errMsg>SERVICE ERROR</errMsg>'
           '<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>'
           '<returnReasonCode>30</returnReasonCode>'
           '</cmmMsgHeader></OpenAPI_ServiceResponse>')
    assert F.classify_response(xml) == 'error'


def test_classify_quota_exceeded_error_envelope_is_error_not_no_data():
    xml = ('<OpenAPI_ServiceResponse><cmmMsgHeader>'
           '<returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>'
           '<returnReasonCode>22</returnReasonCode>'
           '</cmmMsgHeader></OpenAPI_ServiceResponse>')
    assert F.classify_response(xml) == 'error'


def test_classify_non_zero_result_code_is_error_not_no_data():
    # header가 있어도 resultCode가 00이 아니면 무재시도 무자료로 취급하면 안 됨
    xml = ('<response><header><resultCode>04</resultCode>'
           '<resultMsg>HTTP ERROR</resultMsg></header><body></body></response>')
    assert F.classify_response(xml) == 'error'


def test_classify_xml_zero_rows_with_result_code_00_still_no_data_xml():
    # 회귀 방지: 정상 resultCode=00 + 빈 items는 여전히 진짜 0건으로 남아야 함
    xml = ('<response><header><resultCode>00</resultCode></header><body>'
           '<items/><numOfRows>10</numOfRows><pageNo>1</pageNo><totalCount>0</totalCount>'
           '</body></response>')
    assert F.classify_response(xml) == 'no_data_xml'


def test_extract_error_info_reads_reason_code_and_auth_msg():
    xml = ('<OpenAPI_ServiceResponse><cmmMsgHeader>'
           '<returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>'
           '<returnReasonCode>22</returnReasonCode>'
           '</cmmMsgHeader></OpenAPI_ServiceResponse>')
    code, msg = F._extract_error_info(xml)
    assert code == '22'
    assert msg == 'LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR'


def test_fetch_page_retries_on_error_and_logs(monkeypatch, capsys):
    # _curl_get을 스텁으로 대체해 네트워크 없이 error->재시도->소진 경로를 검증.
    calls = {'n': 0}
    err_xml = ('<OpenAPI_ServiceResponse><cmmMsgHeader>'
               '<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>'
               '<returnReasonCode>30</returnReasonCode>'
               '</cmmMsgHeader></OpenAPI_ServiceResponse>')

    def fake_curl_get(sigungu, bjdong, page):
        calls['n'] += 1
        return err_xml

    monkeypatch.setattr(F, '_curl_get', fake_curl_get)
    monkeypatch.setattr(F, 'PACE', 0)   # 테스트 속도: 페이싱 대기 제거
    body, cls = F.fetch_page('41370', '11300', 1)
    assert cls == 'error'
    assert calls['n'] == F.MAX_RETRY   # 재시도를 다 씀 — 조용히 empty/no_data로 안 빠짐
    out = capsys.readouterr().out
    assert 'ERROR' in out and 'SERVICE_KEY_IS_NOT_REGISTERED_ERROR' in out


# ---------------------------------------------------------------------------
# XML item 파싱
# ---------------------------------------------------------------------------

SAMPLE_XML = """<response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE</resultMsg></header>
<body><items>
<item><rnum>1</rnum><platPlc>경기도 오산시 세교동 123-4번지</platPlc><sigunguCd>41370</sigunguCd>
<bjdongCd>11300</bjdongCd><mgmHsrgstPk>PK-A</mgmHsrgstPk><bldNm>오산자이</bldNm>
<purpsCd>02001</purpsCd><purpsCdNm>공동주택</purpsCdNm><totHhldCnt>832</totHhldCnt>
<apprvDay>20240115</apprvDay><stcnsDay>20240320</stcnsDay><useInsptDay></useInsptDay></item>
<item><rnum>2</rnum><platPlc>경기도 오산시 세교동 55번지</platPlc><sigunguCd>41370</sigunguCd>
<bjdongCd>11300</bjdongCd><mgmHsrgstPk>PK-B</mgmHsrgstPk><bldNm>단독주택</bldNm>
<purpsCd>01001</purpsCd><purpsCdNm>단독주택</purpsCdNm><totHhldCnt>1</totHhldCnt>
<apprvDay>20240210</apprvDay><stcnsDay></stcnsDay><useInsptDay></useInsptDay></item>
</items>
<numOfRows>1000</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount></body></response>"""


def test_parse_items_extracts_all_tags():
    items = F.parse_items(SAMPLE_XML)
    assert len(items) == 2
    assert items[0]['mgmHsrgstPk'] == 'PK-A'
    assert items[0]['purpsCdNm'] == '공동주택'
    assert items[0]['totHhldCnt'] == '832'
    assert items[0]['apprvDay'] == '20240115'
    assert items[1]['purpsCdNm'] == '단독주택'


def test_parse_items_empty_tag_becomes_empty_string():
    items = F.parse_items(SAMPLE_XML)
    assert items[1]['stcnsDay'] == ''


def test_aggregate_filters_apt_only_and_sums_by_quarter():
    items = F.parse_items(SAMPLE_XML)
    permit_q, start_q = F._aggregate(items)
    # 단독주택(PK-B)은 apt_records에서 제외되어야 함
    assert permit_q == {'2024Q1': 832}
    assert start_q == {'2024Q1': 832}


# ---------------------------------------------------------------------------
# 대상 시군구/법정동 도출 (작은 픽스처)
# ---------------------------------------------------------------------------

LZ_SIDO_FULL_FIXTURE = {'경기도': '경기', '경상남도': '경남', '세종특별자치시': '세종'}

FIXTURE_ROWS = [
    # 시도 합계행(시군구명 결측, 코드 ...000) — 제외돼야 함
    {'sido': '경기도', 'sgg_cd': '41000', 'sgg_nm': float('nan'), 'bjd_cd': '4100000000', 'eup': float('nan')},
    # 오산시(구 분할 없음, 경기)
    {'sido': '경기도', 'sgg_cd': '41370', 'sgg_nm': '오산시', 'bjd_cd': '4137000000', 'eup': float('nan')},
    {'sido': '경기도', 'sgg_cd': '41370', 'sgg_nm': '오산시', 'bjd_cd': '4137011300', 'eup': '세교동'},
    # 성남시(구 분할: 본체 + 분당구)
    {'sido': '경기도', 'sgg_cd': '41130', 'sgg_nm': '성남시', 'bjd_cd': '4113000000', 'eup': float('nan')},
    {'sido': '경기도', 'sgg_cd': '41135', 'sgg_nm': '성남시 분당구', 'bjd_cd': '4113510100', 'eup': '정자동'},
    # 창원시(경남, LIVEZONE '*' 대상 아님 - 이름 매칭 대상)
    {'sido': '경상남도', 'sgg_cd': '48120', 'sgg_nm': '창원시', 'bjd_cd': '4812000000', 'eup': float('nan')},
    {'sido': '경상남도', 'sgg_cd': '48123', 'sgg_nm': '창원시 성산구', 'bjd_cd': '4812310100', 'eup': '상남동'},
    # 경남 다른 시군구('*' 확장용)
    {'sido': '경상남도', 'sgg_cd': '48250', 'sgg_nm': '김해시', 'bjd_cd': '4825010100', 'eup': '내외동'},
    # 세종(시군구명 언제나 결측, 구 계층 없음 — 코드가 ...000으로 안 끝나면 유효)
    {'sido': '세종특별자치시', 'sgg_cd': '36000', 'sgg_nm': float('nan'), 'bjd_cd': '3600000000', 'eup': float('nan')},
    {'sido': '세종특별자치시', 'sgg_cd': '36110', 'sgg_nm': float('nan'), 'bjd_cd': '3611010100', 'eup': '반곡동'},
]


def test_build_target_index_excludes_sido_aggregate_row():
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    assert '41000' not in sgg_name_by_code
    assert '41370' in sgg_name_by_code


def test_build_target_index_folds_sejong_blank_name_to_sido_short():
    _, _, sgg_name_by_code, _, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    assert sgg_name_by_code['36110'] == '세종'
    assert bjdong_by_sgg['36110'] == {'10100'}


def test_build_target_index_gu_split_name_matches_both_full_and_base():
    _, name_codes, _, _, _ = F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    assert '41135' in name_codes['성남시 분당구']
    assert '41135' in name_codes['성남시']   # base명으로도 매칭돼야 gu-folding 가능
    assert '41130' in name_codes['성남시']


def test_expand_livezone_wildcard_and_named():
    sido_codes, name_codes, sgg_name_by_code, _, _ = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    livezone = {'창원권': [('경남', '창원시')], '경남권': [('경남', '*')]}
    unresolved = []
    targets = F.expand_livezone(livezone, sido_codes, name_codes, sgg_name_by_code, unresolved)
    assert not unresolved
    # 이름 매칭: 창원시 본체+성산구 둘 다 포함
    assert '48120' in targets and '48123' in targets
    # '*' 확장: 경남 전체(김해시 포함)
    assert '48250' in targets
    # 경기는 LIVEZONE에 없어도 전체 시/군이 자동 추가됨
    assert '41370' in targets and '41130' in targets and '41135' in targets


def test_expand_livezone_unresolved_name_reported():
    sido_codes, name_codes, sgg_name_by_code, _, _ = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    livezone = {'없는권': [('경남', '없는시')]}
    unresolved = []
    F.expand_livezone(livezone, sido_codes, name_codes, sgg_name_by_code, unresolved)
    assert unresolved == [('없는권', '경남', '없는시')]


def test_fold_groups_folds_multi_gu_city_under_parent_code():
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    targets = {'41130': '성남시', '41135': '성남시 분당구', '41370': '오산시'}
    groups = F.fold_groups(targets, sido_by_code, bjdong_by_sgg, {})
    assert '41130' in groups                      # 부모 코드가 그룹 키
    assert set(groups['41130']['members']) == {'41130', '41135'}
    assert groups['41130']['name'] == '성남시'
    assert groups['41130']['bjdong']['41135'] == ['10100']
    assert '41370' in groups
    assert groups['41370']['members'] == ['41370']


def test_fold_groups_marks_unresolvable_legacy():
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    targets = {'41370': '오산시'}
    old_gu_map = {'41370': ['99999']}   # 존재하지 않는 옛코드
    groups = F.fold_groups(targets, sido_by_code, bjdong_by_sgg, old_gu_map)
    assert groups['41370']['legacy']['enumerable'] is False


def test_fold_groups_marks_resolvable_legacy():
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    targets = {'41370': '오산시'}
    old_gu_map = {'41370': ['41135']}   # 실제 bjdong(정자동)이 있는 코드를 옛코드로 가정
    groups = F.fold_groups(targets, sido_by_code, bjdong_by_sgg, old_gu_map)
    assert groups['41370']['legacy']['enumerable'] is True


# ---------------------------------------------------------------------------
# Finding 2: 기본(증분) 모드는 "아직 한 번도 스캔 안 된 그룹"을 거짓 0으로
# 쓰면 안 된다 — should_refresh_group()으로 판정을 순수함수화해서 검증.
# ---------------------------------------------------------------------------

def test_should_refresh_group_true_when_full_mode_regardless_of_cache():
    # --full/--only는 전량 스캔하므로 캐시가 비어 있어도 항상 True.
    assert F.should_refresh_group('41370', {'41370': ['11300']}, set(), True) is True


def test_should_refresh_group_false_when_never_scanned_in_default_mode():
    # 그룹 자기 법정동이 cached_productive에 하나도 없음 = 아직 한 번도 안 돌았음
    # -> 기본모드에서 건드리면 안 됨(거짓 0 방지).
    group_bjdong = {'48120': ['10100'], '48123': ['10200']}
    cached_productive = {'41370' + '11300'}   # 다른 그룹(오산시)만 캐시에 있음
    assert F.should_refresh_group('48120', group_bjdong, cached_productive, False) is False


def test_should_refresh_group_true_when_own_bjdong_previously_productive():
    # 자기 소속 법정동 중 하나라도 이전에 productive였다면(=이미 스캔된 그룹)
    # 기본모드에서 증분 재조회 대상이다.
    group_bjdong = {'41370': ['11300', '11400']}
    cached_productive = {'4137011300'}
    assert F.should_refresh_group('41370', group_bjdong, cached_productive, False) is True


def test_run_default_mode_does_not_stamp_false_zero_on_never_scanned_group(tmp_path, monkeypatch):
    # 통합 시나리오(네트워크 없음): 148개 중 1개 그룹만 seed된 상태에서 기본
    # 모드로 run()을 돌리면, 미스캔 그룹은 out['sgg']에 전혀 쓰이지 않아야
    # 한다(빈 dict로도 안 됨). fetch_group이 실제로 호출되지 않는지까지 확인.
    fake_groups = {
        '41370': {'name': '오산시', 'sido': '경기', 'members': ['41370'],
                   'bjdong': {'41370': ['11300']}, 'legacy': None},
        '48120': {'name': '창원시', 'sido': '경남', 'members': ['48120'],
                   'bjdong': {'48120': ['10100']}, 'legacy': None},
    }
    monkeypatch.setattr(F, 'build_targets', lambda: (fake_groups, []))
    monkeypatch.setattr(F, 'KEY', 'dummy-key')

    out_path = tmp_path / 'hub_permits.json'
    monkeypatch.setattr(F, 'OUT_PATH', str(out_path))
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': []},
              'sgg': {'41370': {'name': '오산시', 'permit_q': {'2024Q1': 5}, 'start_q': {}}},
              'productive_bjdong': ['4137011300']}
    io.open(str(out_path), 'w', encoding='utf-8').write(json.dumps(seeded))

    def fetch_group_stub(group, only_bjdong=None):
        # 41370(오산시)은 이미 스캔된 그룹(자기 bjdong이 캐시에 있음)이라
        # 정상적으로 호출된다. 48120(창원시)은 미스캔 그룹이라 should_refresh_group이
        # False를 반환해 run()이 아예 이 함수를 부르지 않아야 한다 — 호출되면 실패.
        if group['name'] == '창원시':
            raise AssertionError('never-scanned 그룹(창원시)에 fetch_group이 호출되면 안 됨')
        return {'2024Q1': 5}, {}, ['4137011300']

    monkeypatch.setattr(F, 'fetch_group', fetch_group_stub)

    F.run(mode_full=False, only_codes=None, list_targets_only=False)

    result = json.load(io.open(str(out_path), encoding='utf-8'))
    assert '48120' not in result['sgg']              # 거짓 0으로 찍히지 않음
    assert result['sgg']['41370']['permit_q'] == {'2024Q1': 5}   # 기존 항목 보존


# ---------------------------------------------------------------------------
# load_bdong_rows: 실제 파일 포맷(컬럼-딕셔너리) 파싱 + NaN 활성행 필터
# ---------------------------------------------------------------------------

def test_load_bdong_rows_filters_active_and_parses_columnar_json(tmp_path):
    nan = float('nan')
    payload = {
        '시도명': {'0': '경기도', '1': '경기도'},
        '시군구코드': {'0': '41370', '1': '41370'},
        '시군구명': {'0': '오산시', '1': '오산시'},
        '법정동코드': {'0': '4137000000', '1': '4137099900'},
        '읍면동명': {'0': nan, '1': '폐지동'},
        '동리명': {'0': nan, '1': nan},
        '생성일자': {'0': '19880423', '1': '19880423'},
        '말소일자': {'0': nan, '1': '20200101'},   # 두 번째 행은 말소(비활성) -> 제외돼야 함
    }
    # 실제 code_bdong.json 포맷 그대로: 결측은 JSON 비표준 NaN 리터럴(Python json 확장)로
    # 저장된다(위 hub_pilot_notes.md 확인) — json.dumps(allow_nan=True 기본값)로 재현.
    p = tmp_path / 'bdong_fixture.json'
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    rows = F.load_bdong_rows(str(p))
    assert len(rows) == 1
    assert rows[0]['sgg_cd'] == '41370'

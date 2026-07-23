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

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
<apprvDay>20240115</apprvDay><stcnsDay>20240320</stcnsDay><useInsptDay>20240310</useInsptDay></item>
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


def test_aggregate_filters_apt_only_and_classifies_by_stage():
    items = F.parse_items(SAMPLE_XML)
    done_q, sched_q, units = F._aggregate(items)
    # 단독주택(PK-B)은 apt_records에서 제외되어야 함
    assert done_q == {'2024Q1': 832}
    assert sched_q == {}
    assert units == [['오산자이', 832, '2024-03', 'done']]


def test_aggregate_classifies_latest_stage_once():
    import fetch_hub_permits as F
    items = [
        {'mgmHsrgstPk':'A','purpsCdNm':'공동주택','totHhldCnt':'100','useInsptDay':'20240310','useInsptSchedDay':'20231130','stcnsDay':'20210101','apprvDay':'20200101'},  # 준공됨→done 2024Q1
        {'mgmHsrgstPk':'B','purpsCdNm':'공동주택','totHhldCnt':'200','useInsptDay':'','useInsptSchedDay':'20291130','stcnsDay':'','apprvDay':'20230101'},                    # 미완공+예정→sched 2029Q4
        {'mgmHsrgstPk':'C','purpsCdNm':'공동주택','totHhldCnt':'50','useInsptDay':'','useInsptSchedDay':'','stcnsDay':'','apprvDay':'20240101'},                              # 미정→어디에도 안 감
        {'mgmHsrgstPk':'A','purpsCdNm':'공동주택','totHhldCnt':'100','useInsptDay':'20240310','useInsptSchedDay':'','stcnsDay':'','apprvDay':''},                             # A 중복→dedupe
    ]
    done, sched, units = F._aggregate(items)
    assert done == {'2024Q1': 100}
    assert sched == {'2029Q4': 200}
    # 세대 큰 순 정렬(B=200 sched 먼저) — bldNm 필드가 픽스처에 없어 빈 문자열
    assert units == [['', 200, '2029-11', 'sched'], ['', 100, '2024-03', 'done']]


def test_aggregate_caps_units_at_top_40_by_household():
    items = []
    for i in range(50):
        items.append({'mgmHsrgstPk': 'K%d' % i, 'purpsCdNm': '공동주택',
                       'totHhldCnt': str(100 + i), 'useInsptDay': '20240310',
                       'useInsptSchedDay': '', 'bldNm': '단지%d' % i})
    done_q, sched_q, units = F._aggregate(items)
    assert len(units) == F.UNITS_CAP
    assert units[0][1] == 149   # 세대 최댓값(100+49)이 먼저
    assert all(units[i][1] >= units[i + 1][1] for i in range(len(units) - 1))


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
              'sgg': {'41370': {'name': '오산시', 'done_q': {'2024Q1': 5}, 'sched_q': {}}},
              'productive_bjdong': ['4137011300']}
    io.open(str(out_path), 'w', encoding='utf-8').write(json.dumps(seeded))

    def fetch_group_stub(group, only_bjdong=None):
        # 41370(오산시)은 이미 스캔된 그룹(자기 bjdong이 캐시에 있음)이라
        # 정상적으로 호출된다. 48120(창원시)은 미스캔 그룹이라 should_refresh_group이
        # False를 반환해 run()이 아예 이 함수를 부르지 않아야 한다 — 호출되면 실패.
        if group['name'] == '창원시':
            raise AssertionError('never-scanned 그룹(창원시)에 fetch_group이 호출되면 안 됨')
        return {'2024Q1': 5}, {}, [], ['4137011300'], False

    monkeypatch.setattr(F, 'fetch_group', fetch_group_stub)

    F.run(mode_full=False, only_codes=None, list_targets_only=False)

    result = json.load(io.open(str(out_path), encoding='utf-8'))
    assert '48120' not in result['sgg']              # 거짓 0으로 찍히지 않음
    assert result['sgg']['41370']['done_q'] == {'2024Q1': 5}   # 기존 항목 보존
    assert result['meta']['scanned'] == ['41370']     # 깨끗하게 스캔된 그룹만 기록


# ---------------------------------------------------------------------------
# Fix pass 2 (Important): 지속 장애로 재시도 소진('error')된 그룹은
# out['sgg'][key]를 덮어쓰면 안 된다 — 진짜 카운트가 빈 값으로 clobber되는
# 것 방지. 같은 메커니즘으로 meta['scanned']를 도입해 Minor(never-scanned vs
# scanned-genuinely-zero 구분)도 함께 해결한다.
# ---------------------------------------------------------------------------

def test_fetch_bjdong_all_pages_reports_had_error_on_retry_exhaustion(monkeypatch):
    # fetch_page가 재시도를 다 쓰고도 'error'를 반환하면(=fetch_page가 이미
    # ERROR를 찍은 상태) had_error=True로 전달돼야 한다.
    monkeypatch.setattr(F, 'fetch_page', lambda sigungu, bjdong, page: ('', 'error'))
    items, had_error = F.fetch_bjdong_all_pages('41370', '11300')
    assert items == []
    assert had_error is True


def test_fetch_bjdong_all_pages_no_error_on_clean_no_data(monkeypatch):
    monkeypatch.setattr(F, 'fetch_page', lambda sigungu, bjdong, page: ('', 'no_data_xml'))
    items, had_error = F.fetch_bjdong_all_pages('41370', '11300')
    assert items == []
    assert had_error is False


def test_fetch_group_propagates_had_unresolved_error(monkeypatch):
    # 그룹 소속 법정동 중 하나라도 had_error면 그룹 전체가
    # had_unresolved_error=True로 올라와야 fetch_group 결과를 신뢰 안 함.
    group = {'name': '오산시', 'sido': '경기', 'members': ['41370'],
             'bjdong': {'41370': ['11300', '11400']}, 'legacy': None}

    def fake_fetch_bjdong_all_pages(sigungu, bjdong, log=None):
        if bjdong == '11400':
            return [], True   # 이 법정동만 재시도 소진 오류
        return [], False

    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', fake_fetch_bjdong_all_pages)
    done_q, sched_q, units, productive, had_unresolved_error = F.fetch_group(group)
    assert had_unresolved_error is True


def test_fetch_group_no_error_when_all_bjdong_clean(monkeypatch):
    group = {'name': '오산시', 'sido': '경기', 'members': ['41370'],
             'bjdong': {'41370': ['11300']}, 'legacy': None}
    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', lambda sigungu, bjdong, log=None: ([], False))
    done_q, sched_q, units, productive, had_unresolved_error = F.fetch_group(group)
    assert had_unresolved_error is False


def test_fetch_group_collects_units_across_bjdong(monkeypatch):
    group = {'name': '오산시', 'sido': '경기', 'members': ['41370'],
             'bjdong': {'41370': ['11300']}, 'legacy': None}
    items = [{'mgmHsrgstPk': 'X', 'purpsCdNm': '공동주택', 'totHhldCnt': '300',
              'useInsptDay': '20240310', 'useInsptSchedDay': '', 'bldNm': '오산자이'}]
    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', lambda sigungu, bjdong, log=None: (items, False))
    done_q, sched_q, units, productive, had_unresolved_error = F.fetch_group(group)
    assert units == [['오산자이', 300, '2024-03', 'done']]


def _run_with_stub(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub):
    monkeypatch.setattr(F, 'build_targets', lambda: (fake_groups, []))
    monkeypatch.setattr(F, 'KEY', 'dummy-key')
    out_path = tmp_path / 'hub_permits.json'
    monkeypatch.setattr(F, 'OUT_PATH', str(out_path))
    io.open(str(out_path), 'w', encoding='utf-8').write(json.dumps(seeded))
    monkeypatch.setattr(F, 'fetch_group', fetch_group_stub)
    F.run(mode_full=False, only_codes=None, list_targets_only=False)
    return json.load(io.open(str(out_path), encoding='utf-8'))


def test_run_does_not_clobber_prior_value_on_unresolved_error(tmp_path, monkeypatch):
    # Important: 41370은 이전에 실측된 진짜 값(done_q 5)이 있다. 이번 회차에
    # 지속 장애로 had_unresolved_error=True가 나면, 그 진짜 값을 절대
    # 덮어쓰면 안 된다(빈 dict로 clobber 금지).
    fake_groups = {
        '41370': {'name': '오산시', 'sido': '경기', 'members': ['41370'],
                   'bjdong': {'41370': ['11300']}, 'legacy': None},
    }
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': ['41370']},
              'sgg': {'41370': {'name': '오산시', 'done_q': {'2024Q1': 999}, 'sched_q': {'2024Q1': 999}}},
              'productive_bjdong': ['4137011300']}

    def fetch_group_stub(group, only_bjdong=None):
        return {}, {}, [], [], True   # 지속 장애: 재시도 소진, 결과 신뢰 불가

    result = _run_with_stub(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub)
    assert result['sgg']['41370']['done_q'] == {'2024Q1': 999}   # 이전 실측값 그대로 보존
    assert result['meta']['scanned'] == ['41370']   # 이번 회차엔 재확인 못 했으니 갱신 안 됨(기존 유지)


def test_run_does_not_write_empty_placeholder_on_unresolved_error_without_prior_value(tmp_path, monkeypatch):
    # 이전 값이 아예 없던 그룹이 첫 시도에서 바로 지속 장애를 만나면, 빈
    # placeholder({}) 조차 쓰지 않아야 한다(거짓 0과 동일한 오염이므로).
    fake_groups = {
        '48120': {'name': '창원시', 'sido': '경남', 'members': ['48120'],
                   'bjdong': {'48120': ['10100']}, 'legacy': None},
    }
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': []},
              'sgg': {}, 'productive_bjdong': ['4812010100']}   # 48120은 캐시상 이미 스캔된 것으로 세팅(should_refresh=True 유도)

    def fetch_group_stub(group, only_bjdong=None):
        return {}, {}, [], [], True

    result = _run_with_stub(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub)
    assert '48120' not in result['sgg']
    assert result['meta']['scanned'] == []


def test_run_clean_scan_writes_result_and_marks_scanned(tmp_path, monkeypatch):
    # 대조군: 깨끗하게(오류 없이) 스캔되면 정상적으로 기록되고 meta['scanned']에 추가된다.
    fake_groups = {
        '48120': {'name': '창원시', 'sido': '경남', 'members': ['48120'],
                   'bjdong': {'48120': ['10100']}, 'legacy': None},
    }
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': []},
              'sgg': {}, 'productive_bjdong': ['4812010100']}

    def fetch_group_stub(group, only_bjdong=None):
        return {'2024Q1': 3}, {}, [['창원자이', 300, '2024-03', 'done']], ['4812010100'], False

    result = _run_with_stub(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub)
    assert result['sgg']['48120']['done_q'] == {'2024Q1': 3}
    assert result['sgg']['48120']['units'] == [['창원자이', 300, '2024-03', 'done']]
    assert result['meta']['scanned'] == ['48120']


# ---------------------------------------------------------------------------
# Fix pass(resumability): GitHub 호스티드 러너 6시간 캡 때문에 --full 전량이
# 한 실행으로 안 끝난다 — 재트리거된 --full이 meta['scanned']를 보고 이어서
# 돌아야 한다(RESUME). --reseed는 이를 무시하고 진짜 처음부터 다시 돈다.
# ---------------------------------------------------------------------------

def test_full_resume_skips_already_scanned_groups(tmp_path, monkeypatch, capsys):
    # 41370은 이전 --full 실행에서 이미 깨끗하게 스캔 완료(scanned에 있음).
    # 48120은 scanned에 없음(이전 실행이 여기서 킬됐거나 아직 시도 안 함).
    fake_groups = {
        '41370': {'name': '오산시', 'sido': '경기', 'members': ['41370'],
                   'bjdong': {'41370': ['11300']}, 'legacy': None},
        '48120': {'name': '창원시', 'sido': '경남', 'members': ['48120'],
                   'bjdong': {'48120': ['10100']}, 'legacy': None},
    }
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': ['41370']},
              'sgg': {'41370': {'name': '오산시', 'done_q': {'2024Q1': 5}, 'sched_q': {}}},
              'productive_bjdong': ['4137011300']}

    called = []

    def fetch_group_stub(group, only_bjdong=None):
        called.append(group['name'])
        if group['name'] == '오산시':
            raise AssertionError('이미 scanned인 그룹(오산시)은 --full 재트리거에서 재호출되면 안 됨')
        return {'2024Q1': 7}, {}, [], ['4812010100'], False

    result = _run_with_stub_full(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub)

    assert called == ['창원시']                                  # 스캔 안 된 그룹만 실제 호출됨
    assert result['sgg']['41370']['done_q'] == {'2024Q1': 5}    # 기존 값 보존(재호출 없이 그대로)
    assert result['sgg']['48120']['done_q'] == {'2024Q1': 7}    # 미스캔 그룹은 새로 스캔됨
    assert set(result['meta']['scanned']) == {'41370', '48120'}   # 이어서 완료됨
    out = capsys.readouterr().out
    assert '[RESUME skip] 41370' in out


def test_full_resume_rescans_group_killed_mid_scan(tmp_path, monkeypatch):
    # "킬됨" 시뮬레이션: 48120은 scanned에 없다(직전 --full 실행이 이 그룹
    # 도중 죽어서 clean scan을 못 남겼다는 뜻) — 재트리거된 --full은 이 그룹을
    # 다시(처음부터) 스캔해야 한다. 41370은 이미 scanned라 재스캔 안 됨.
    fake_groups = {
        '41370': {'name': '오산시', 'sido': '경기', 'members': ['41370'],
                   'bjdong': {'41370': ['11300']}, 'legacy': None},
        '48120': {'name': '창원시', 'sido': '경남', 'members': ['48120'],
                   'bjdong': {'48120': ['10100']}, 'legacy': None},
    }
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': ['41370']},
              'sgg': {'41370': {'name': '오산시', 'done_q': {'2024Q1': 5}, 'sched_q': {}}},
              'productive_bjdong': ['4137011300']}

    called = []

    def fetch_group_stub(group, only_bjdong=None):
        called.append(group['name'])
        return {'2024Q1': 9}, {}, [], ['4812010100'], False

    result = _run_with_stub_full(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub)

    assert called == ['창원시']   # 킬되어 scanned 못 들어간 그룹만 재스캔
    assert result['sgg']['48120']['done_q'] == {'2024Q1': 9}
    assert set(result['meta']['scanned']) == {'41370', '48120'}


def test_reseed_forces_rescan_of_already_scanned_groups(tmp_path, monkeypatch):
    # --reseed는 meta['scanned']를 무시하고 전량(41370 포함)을 다시 스캔한다.
    fake_groups = {
        '41370': {'name': '오산시', 'sido': '경기', 'members': ['41370'],
                   'bjdong': {'41370': ['11300']}, 'legacy': None},
    }
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': ['41370']},
              'sgg': {'41370': {'name': '오산시', 'done_q': {'2024Q1': 5}, 'sched_q': {}}},
              'productive_bjdong': ['4137011300']}

    called = []

    def fetch_group_stub(group, only_bjdong=None):
        called.append(group['name'])
        return {'2024Q1': 42}, {}, [], ['4137011300'], False

    result = _run_with_stub_full(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub, reseed=True)

    assert called == ['오산시']                                    # --reseed는 재호출함
    assert result['sgg']['41370']['done_q'] == {'2024Q1': 42}    # 새로 스캔한 값으로 갱신됨
    assert result['meta']['scanned'] == ['41370']


def _run_with_stub_full(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub, reseed=False):
    monkeypatch.setattr(F, 'build_targets', lambda: (fake_groups, []))
    monkeypatch.setattr(F, 'KEY', 'dummy-key')
    out_path = tmp_path / 'hub_permits.json'
    monkeypatch.setattr(F, 'OUT_PATH', str(out_path))
    io.open(str(out_path), 'w', encoding='utf-8').write(json.dumps(seeded))
    monkeypatch.setattr(F, 'fetch_group', fetch_group_stub)
    F.run(mode_full=True, only_codes=None, list_targets_only=False, reseed=reseed)
    return json.load(io.open(str(out_path), encoding='utf-8'))


# ---------------------------------------------------------------------------
# Fix pass 2 (Minor): never-scanned vs scanned-genuinely-zero 구분
# ---------------------------------------------------------------------------

def test_skip_log_distinguishes_never_scanned_from_scanned_zero(tmp_path, monkeypatch, capsys):
    fake_groups = {
        '41370': {'name': '오산시(미스캔)', 'sido': '경기', 'members': ['41370'],
                   'bjdong': {'41370': ['11300']}, 'legacy': None},
        '48120': {'name': '창원시(스캔완료-0건)', 'sido': '경남', 'members': ['48120'],
                   'bjdong': {'48120': ['10100']}, 'legacy': None},
    }
    # 둘 다 cached_productive(productive_bjdong)와 자기 법정동이 하나도 안 겹쳐
    # should_refresh_group은 둘 다 False를 준다 — 로그로만 구분돼야 한다.
    # 48120은 meta['scanned']에 이미 들어있어(=이전에 깨끗하게 스캔해서 0건으로
    # 확정됨) '아직 스캔 안 함'이라고 오해를 부르면 안 된다.
    seeded = {'meta': {'fetched': '', 'mode': 'incr', 'unresolved_legacy': [], 'scanned': ['48120']},
              'sgg': {}, 'productive_bjdong': []}

    def fetch_group_stub(group, only_bjdong=None):
        raise AssertionError('should_refresh_group이 False인 그룹에 fetch_group이 호출되면 안 됨')

    _run_with_stub(tmp_path, monkeypatch, fake_groups, seeded, fetch_group_stub)
    out = capsys.readouterr().out
    assert '[SKIP not-yet-scanned] 41370' in out
    assert '[SKIP scanned-zero] 48120' in out
    assert '[SKIP not-yet-scanned] 48120' not in out   # 스캔완료-0건을 미스캔으로 오분류하면 안 됨


# ---------------------------------------------------------------------------
# Fix pass 2: load_existing 하위호환 — meta['scanned'] 없는 과거 파일도 로드 가능
# ---------------------------------------------------------------------------

def test_load_existing_backward_compat_missing_scanned_key(tmp_path, monkeypatch):
    out_path = tmp_path / 'hub_permits.json'
    legacy_state = {'meta': {'fetched': '2026-01-01', 'mode': 'full', 'unresolved_legacy': ['41190']},
                     'sgg': {'41370': {'name': '오산시', 'done_q': {'2024Q1': 5}, 'sched_q': {}}},
                     'productive_bjdong': ['4137011300']}
    io.open(str(out_path), 'w', encoding='utf-8').write(json.dumps(legacy_state, ensure_ascii=False))
    monkeypatch.setattr(F, 'OUT_PATH', str(out_path))

    loaded = F.load_existing()   # 과거엔 meta에 'scanned' 키가 아예 없었음 — 죽으면 안 됨
    assert loaded['meta']['scanned'] == []
    assert loaded['sgg']['41370']['done_q'] == {'2024Q1': 5}   # 기존 데이터는 그대로


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

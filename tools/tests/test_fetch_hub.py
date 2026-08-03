import sys, os, io, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import fetch_hub_permits as F
import hub_common as H


# ---------------------------------------------------------------------------
# 두 "무자료" 형태 분류기 (함정3)
# ---------------------------------------------------------------------------

def test_classify_empty_body_is_retryable():
    assert F.classify_response('') == 'empty'
    assert F.classify_response('   ') == 'empty'


def test_classify_json_no_data_param_missing():
    # 파라미터 누락/오류 시 HTTP 200 + JSON {"body":{}} (~69 bytes)
    assert F.classify_response('{"body":{},"header":{"resultCode":"00","resultMsg":"NORMAL SERVICE"}}') == 'no_data_json'


# ---------------------------------------------------------------------------
# 2026-08-03 실사고 회귀: 원천이 기본 응답 포맷을 XML->JSON으로 바꿨는데
# 분류기가 '{'로 시작하면 무조건 no_data_json(무자료)로 봐서 실데이터를 조용히
# 버렸다 — error가 아니라 clobber 방지도 안 타서 부산 8개 구 준공/준공예정이
# 0으로 소거된 채 라이브에 배포됐다.
# ---------------------------------------------------------------------------

JSON_WITH_DATA = ('{"header":{"resultCode":"00","resultMsg":"NORMAL SERVICE"},'
                  '"body":{"items":{"item":['
                  '{"rnum":1,"platPlc":"인천광역시 미추홀구 숭의동 5-17번지",'
                  '"mgmHsrgstPk":105616,"bldNm":"수봉아파트","purpsCdNm":"공동주택",'
                  '"totHhldCnt":52,"useInsptDay":"20070404","useInsptSchedDay":" "},'
                  '{"rnum":2,"platPlc":"인천광역시 미추홀구 숭의동 18번지",'
                  '"mgmHsrgstPk":1000000000000000063855,"bldNm":"숭의3 아파트",'
                  '"purpsCdNm":"공동주택","totHhldCnt":736,"useInsptDay":" ",'
                  '"useInsptSchedDay":"20300930"}]},'
                  '"numOfRows":100,"pageNo":1,"totalCount":157}}')

JSON_ZERO_ROWS = ('{"header":{"resultCode":"00","resultMsg":"NORMAL SERVICE"},'
                  '"body":{"items":"","numOfRows":100,"pageNo":1,"totalCount":0}}')


def test_classify_json_with_items_is_data_not_no_data():
    # 핵심 회귀: 실데이터가 든 JSON을 무자료로 버리면 안 된다.
    assert F.classify_response(JSON_WITH_DATA) == 'data'


def test_classify_json_zero_rows_is_normal_no_data():
    assert F.classify_response(JSON_ZERO_ROWS) == 'no_data_xml'


def test_classify_json_error_result_code_is_error():
    body = '{"header":{"resultCode":"04","resultMsg":"HTTP ERROR"},"body":{"items":""}}'
    assert F.classify_response(body) == 'error'


def test_classify_malformed_json_is_error_not_silent_no_data():
    assert F.classify_response('{"body": truncated...') == 'error'


def test_parse_items_reads_json_and_stringifies_values():
    # 숫자로 오는 JSON 값(PK/세대수)을 문자열로 정규화해야 XML 경로와 dedupe·
    # 집계·이중등재 접기가 동일하게 동작한다.
    items = F.parse_items(JSON_WITH_DATA)
    assert len(items) == 2
    assert items[0]['mgmHsrgstPk'] == '105616'
    assert items[0]['totHhldCnt'] == '52'
    assert items[1]['mgmHsrgstPk'] == '1000000000000000063855'
    assert items[1]['purpsCdNm'] == '공동주택'


def test_parse_items_json_single_item_is_dict_not_list():
    # data.go.kr JSON은 1건일 때 item을 리스트가 아니라 dict로 준다.
    body = ('{"header":{"resultCode":"00"},"body":{"items":{"item":'
            '{"mgmHsrgstPk":1,"purpsCdNm":"공동주택","totHhldCnt":10}},"totalCount":1}}')
    items = F.parse_items(body)
    assert len(items) == 1 and items[0]['totHhldCnt'] == '10'


def test_parse_items_json_zero_rows_is_empty_list():
    assert F.parse_items(JSON_ZERO_ROWS) == []


def test_parse_total_count_reads_json_total_count():
    assert F.parse_total_count(JSON_WITH_DATA) == 157
    assert F.parse_total_count(JSON_ZERO_ROWS) == 0
    assert F.parse_total_count('{"body":{}}') is None


def test_json_response_aggregates_same_as_xml():
    # 포맷이 뭐든 집계 결과가 같아야 한다(포맷 전환이 수치를 흔들면 안 됨).
    done_q, sched_q, units = F._aggregate(F.parse_items(JSON_WITH_DATA))
    assert done_q == {'2007Q2': 52}
    assert sched_q == {'2030Q3': 736}


def test_curl_get_forces_xml_format(monkeypatch):
    # 1차 방어: _type=xml을 빼면 08-02 사고가 재현된다.
    seen = {}

    class FakeResult:
        stdout = '<response/>'

    def fake_run(cmd, **kw):
        seen['cmd'] = cmd
        return FakeResult()

    monkeypatch.setattr(F.subprocess, 'run', fake_run)
    F._curl_get('28177', '10100', 1)
    assert '_type=xml' in seen['cmd']


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

    def fake_curl_get(sigungu, bjdong, page, endpoint=F.EP):
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
    # 저장 순서는 stage별 묶음(done 먼저) — 화면 순서는 렌더러가 날짜로 다시 정한다.
    assert sorted(units) == sorted([['', 200, '2029-11', 'sched'],
                                    ['', 100, '2024-03', 'done']])


def test_aggregate_counts_dual_registered_project_once():
    """PK만 다른 이중등재는 세대수를 두 번 세면 안 된다(2026-08-03 감사).

    실측 사례(제물포역 3,497세대): pk 220546/220547이 지번·연면적·예정일까지
    전 필드가 같은 채 두 번 등재돼 있어, 예전 집계는 sched에 6,994를 넣었다 —
    미래공급 과대 = 순부족 과소평가.
    """
    def rec(pk, rnum):
        return {'mgmHsrgstPk': pk, 'rnum': rnum, 'purpsCdNm': '공동주택',
                'bldNm': '제물포역 북측 도심 공공주택 복합지구 공동주택',
                'platPlc': '인천광역시 미추홀구 도화동 94-1번지',
                'totHhldCnt': '3497', 'totArea': '576352.0556',
                'useInsptDay': '', 'useInsptSchedDay': '20310930'}

    done_q, sched_q, units = F._aggregate([rec('1000000000000000220546', '3'),
                                           rec('1000000000000000220547', '4')])
    assert sched_q == {'2031Q3': 3497}     # 6994가 아니라 3497
    assert len(units) == 1                 # 목록에도 한 번만


def test_aggregate_keeps_every_unit_sorted_by_household():
    """캡 폐지(2026-08-02): 단지를 하나도 버리지 않는다.

    개수로 자르면 존 페이지의 '목록 합계'가 차트 총량과 안 맞아 사용자가 버그로
    읽는다(대구권 55,693 vs 15,020, 춘천권 2,852 vs 1,326). 무제한이면 units의
    세대 합이 done_q+sched_q 합과 정의상 같아진다 — 아래에서 그것도 확인한다.
    """
    items = []
    for i in range(50):
        items.append({'mgmHsrgstPk': 'K%d' % i, 'purpsCdNm': '공동주택',
                       'totHhldCnt': str(100 + i), 'useInsptDay': '20240310',
                       'useInsptSchedDay': '', 'bldNm': '단지%d' % i})
    done_q, sched_q, units = F._aggregate(items)
    assert F.UNITS_CAP is None, '캡을 되살리려면 합계 불일치 문제부터 풀 것'
    assert len(units) == 50
    assert units[0][1] == 149   # 세대 최댓값(100+49)이 먼저
    assert all(units[i][1] >= units[i + 1][1] for i in range(len(units) - 1))
    # 목록 세대 합 == 분기 집계 세대 합
    assert sum(u[1] for u in units) == sum(done_q.values()) + sum(sched_q.values())


# ---------------------------------------------------------------------------
# --demol (멸실/철거멸실관리대장): 준공과 필드명이 다른 별도 집계 경로.
# mainPurpsCdNm(주용도)/hhldCnt(세대수)/mgmPmsrgstPk(PK) — apt_records의
# purpsCdNm/totHhldCnt/mgmHsrgstPk와 완전히 다른 이름이므로 hub_common에
# demol_records()를 따로 두었다. 분기화는 demolEndDay -> demolExtngDay ->
# demolStrtDay 순 fallback(hub_common.to_quarter 재사용).
# ---------------------------------------------------------------------------

def test_demol_records_filters_gongdong_and_positive_hhldcnt():
    items = [
        {'mgmPmsrgstPk': 'A', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '30'},
        {'mgmPmsrgstPk': 'B', 'mainPurpsCdNm': '단독주택', 'hhldCnt': '1'},   # 유형 제외
        {'mgmPmsrgstPk': 'C', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '0'},   # 0세대 제외
    ]
    out = H.demol_records(items)
    assert [r['mgmPmsrgstPk'] for r in out] == ['A']


def test_demol_records_dedupes_by_mgmpmsrgstpk():
    items = [
        {'mgmPmsrgstPk': 'A', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '30'},
        {'mgmPmsrgstPk': 'A', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '30'},  # 중복 PK
    ]
    out = H.demol_records(items)
    assert len(out) == 1


def test_aggregate_demol_buckets_by_demol_end_day():
    items = [{'mgmPmsrgstPk': 'A', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '100',
              'demolEndDay': '20240315', 'demolExtngDay': '20240301', 'demolStrtDay': '20240101'}]
    demol_q = F._aggregate_demol(items)
    assert demol_q == {'2024Q1': 100}   # demolEndDay 우선


def test_aggregate_demol_falls_back_to_extng_day_then_strt_day():
    items_extng = [{'mgmPmsrgstPk': 'A', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '50',
                     'demolEndDay': '', 'demolExtngDay': '20230610', 'demolStrtDay': '20230101'}]
    assert F._aggregate_demol(items_extng) == {'2023Q2': 50}   # demolEndDay 없음 -> demolExtngDay

    items_strt = [{'mgmPmsrgstPk': 'B', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '20',
                   'demolEndDay': '', 'demolExtngDay': '', 'demolStrtDay': '20220905'}]
    assert F._aggregate_demol(items_strt) == {'2022Q3': 20}   # 둘 다 없음 -> demolStrtDay


def test_aggregate_demol_excludes_non_apt_and_dedupes():
    items = [
        {'mgmPmsrgstPk': 'A', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '100', 'demolEndDay': '20240315'},
        {'mgmPmsrgstPk': 'A', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '100', 'demolEndDay': '20240315'},  # 중복
        {'mgmPmsrgstPk': 'B', 'mainPurpsCdNm': '단독주택', 'hhldCnt': '5', 'demolEndDay': '20240315'},     # 유형 제외
    ]
    demol_q = F._aggregate_demol(items)
    assert demol_q == {'2024Q1': 100}


def test_aggregate_demol_sums_multiple_quarters():
    items = [
        {'mgmPmsrgstPk': 'A', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '100', 'demolEndDay': '20240315'},
        {'mgmPmsrgstPk': 'B', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '40', 'demolEndDay': '20240320'},
        {'mgmPmsrgstPk': 'C', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '10', 'demolEndDay': '20230715'},
    ]
    demol_q = F._aggregate_demol(items)
    assert demol_q == {'2024Q1': 140, '2023Q3': 10}


def test_fetch_group_demol_uses_demol_endpoint_and_aggregates(monkeypatch):
    group = {'name': '부산중구', 'sido': '부산', 'members': ['26110'],
              'bjdong': {'26110': ['10100']}, 'legacy': None}
    seen_endpoints = []

    def fake_fetch_bjdong_all_pages(sigungu, bjdong, log=None, endpoint=F.EP):
        seen_endpoints.append(endpoint)
        return [{'mgmPmsrgstPk': 'X', 'mainPurpsCdNm': '공동주택', 'hhldCnt': '80',
                  'demolEndDay': '20240315'}], False

    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', fake_fetch_bjdong_all_pages)
    demol_q, productive, had_unresolved_error = F.fetch_group_demol(group)
    assert seen_endpoints == [F.EP_DEMOL]   # 준공 EP가 아니라 멸실 EP로 호출됨
    assert demol_q == {'2024Q1': 80}
    assert productive == ['2611010100']
    assert had_unresolved_error is False


def test_fetch_group_demol_propagates_had_unresolved_error(monkeypatch):
    group = {'name': '오산시', 'sido': '경기', 'members': ['41370'],
              'bjdong': {'41370': ['11300', '11400']}, 'legacy': None}

    def fake_fetch_bjdong_all_pages(sigungu, bjdong, log=None, endpoint=F.EP):
        if bjdong == '11400':
            return [], True
        return [], False

    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', fake_fetch_bjdong_all_pages)
    demol_q, productive, had_unresolved_error = F.fetch_group_demol(group)
    assert had_unresolved_error is True


def test_run_demol_writes_demol_q_without_touching_permit_scanned(tmp_path, monkeypatch):
    # --demol이 별도 meta['scanned_demol']을 쓰고, 준공 meta['scanned']/
    # done_q/sched_q/units는 절대 건드리지 않아야 한다(Task 지시 핵심 제약).
    fake_groups = {
        '26110': {'name': '중구', 'sido': '부산', 'members': ['26110'],
                   'bjdong': {'26110': ['10100']}, 'legacy': None},
    }
    monkeypatch.setattr(F, 'build_targets', lambda: (fake_groups, []))
    monkeypatch.setattr(F, 'KEY', 'dummy-key')
    out_path = tmp_path / 'hub_permits.json'
    monkeypatch.setattr(F, 'OUT_PATH', str(out_path))
    seeded = {
        'meta': {'fetched': '2026-07-01', 'mode': 'full', 'unresolved_legacy': [], 'scanned': ['26110']},
        'sgg': {'26110': {'name': '중구', 'done_q': {'2020Q1': 40}, 'sched_q': {}, 'units': []}},
        'productive_bjdong': ['2611010100'],
    }
    io.open(str(out_path), 'w', encoding='utf-8').write(json.dumps(seeded, ensure_ascii=False))

    def fetch_group_demol_stub(group, only_bjdong=None):
        return {'2024Q1': 60}, ['2611010100'], False

    monkeypatch.setattr(F, 'fetch_group_demol', fetch_group_demol_stub)
    F.run_demol(mode_full=True, only_codes=None, reseed=False)

    result = json.load(io.open(str(out_path), encoding='utf-8'))
    # 멸실만 추가됨
    assert result['sgg']['26110']['demol_q'] == {'2024Q1': 60}
    assert result['meta']['scanned_demol'] == ['26110']
    # 준공 쪽은 완전히 그대로
    assert result['sgg']['26110']['done_q'] == {'2020Q1': 40}
    assert result['meta']['scanned'] == ['26110']
    assert result['productive_bjdong'] == ['2611010100']


def test_run_demol_does_not_clobber_prior_demol_q_on_unresolved_error(tmp_path, monkeypatch):
    fake_groups = {
        '26110': {'name': '중구', 'sido': '부산', 'members': ['26110'],
                   'bjdong': {'26110': ['10100']}, 'legacy': None},
    }
    monkeypatch.setattr(F, 'build_targets', lambda: (fake_groups, []))
    monkeypatch.setattr(F, 'KEY', 'dummy-key')
    out_path = tmp_path / 'hub_permits.json'
    monkeypatch.setattr(F, 'OUT_PATH', str(out_path))
    seeded = {
        'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': [], 'scanned_demol': ['26110']},
        'sgg': {'26110': {'name': '중구', 'demol_q': {'2024Q1': 999}}},
        'productive_bjdong': [], 'productive_bjdong_demol': ['2611010100'],
    }
    io.open(str(out_path), 'w', encoding='utf-8').write(json.dumps(seeded, ensure_ascii=False))

    def fetch_group_demol_stub(group, only_bjdong=None):
        return {}, [], True   # 지속 장애

    monkeypatch.setattr(F, 'fetch_group_demol', fetch_group_demol_stub)
    F.run_demol(mode_full=True, only_codes=None, reseed=False)

    result = json.load(io.open(str(out_path), encoding='utf-8'))
    assert result['sgg']['26110']['demol_q'] == {'2024Q1': 999}   # 보존됨


def test_run_permit_scan_preserves_prior_demol_q(tmp_path, monkeypatch):
    # 반대 방향: --demol이 먼저 demol_q를 써놓은 뒤 준공(run())이 그 그룹을
    # 재스캔해도 demol_q가 지워지면 안 된다(두 수집기 상호 clobber 방지).
    fake_groups = {
        '26110': {'name': '중구', 'sido': '부산', 'members': ['26110'],
                   'bjdong': {'26110': ['10100']}, 'legacy': None},
    }
    monkeypatch.setattr(F, 'build_targets', lambda: (fake_groups, []))
    monkeypatch.setattr(F, 'KEY', 'dummy-key')
    out_path = tmp_path / 'hub_permits.json'
    monkeypatch.setattr(F, 'OUT_PATH', str(out_path))
    seeded = {
        'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': [], 'scanned_demol': ['26110']},
        'sgg': {'26110': {'name': '중구', 'demol_q': {'2024Q1': 60}}},
        'productive_bjdong': ['2611010100'], 'productive_bjdong_demol': ['2611010100'],
    }
    io.open(str(out_path), 'w', encoding='utf-8').write(json.dumps(seeded, ensure_ascii=False))

    def fetch_group_stub(group, only_bjdong=None):
        return {'2020Q1': 40}, {}, [], ['2611010100'], False

    monkeypatch.setattr(F, 'fetch_group', fetch_group_stub)
    F.run(mode_full=True, only_codes=None, list_targets_only=False)

    result = json.load(io.open(str(out_path), encoding='utf-8'))
    assert result['sgg']['26110']['done_q'] == {'2020Q1': 40}
    assert result['sgg']['26110']['demol_q'] == {'2024Q1': 60}   # 준공 재스캔에도 보존됨


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


def test_fold_groups_marks_unresolvable_legacy_when_rep_itself_has_no_bjdong():
    # 실측(2026-07-27, 부천 팬아웃 배경): enumerable은 옛구코드 자신이 아니라
    # 대표(rep) 자신의 법정동 보유 여부로 판정한다 — 옛구코드는
    # code_bdong.json에 자기 행이 아예 없어(2016 구 폐지로 삭제) 예전 판정
    # (legacy code 자신의 bjdong 확인)은 항상 False였다. 이제는 대표가 없는
    # 극단적인 경우(픽스처에 아예 없는 코드)만 False다.
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    targets = {'99999': '없는시'}   # 픽스처에 전혀 없는 코드 -> 대표 자신도 법정동 없음
    old_gu_map = {'99999': ['41135']}   # 옛코드 자체가 실 bjdong을 가져도 이제 무관
    groups = F.fold_groups(targets, sido_by_code, bjdong_by_sgg, old_gu_map)
    assert groups['99999']['legacy']['enumerable'] is False


def test_fold_groups_marks_resolvable_legacy_based_on_rep_own_bjdong():
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    targets = {'41370': '오산시'}
    old_gu_map = {'41370': ['99999']}   # 옛코드 자체는 존재하지 않아도(법정동 없어도) 무관해짐
    groups = F.fold_groups(targets, sido_by_code, bjdong_by_sgg, old_gu_map)
    assert groups['41370']['legacy']['enumerable'] is True   # 대표(41370=오산시) 자신에 법정동(세교동) 있음


def test_apply_legacy_gu_fix_fans_out_rep_bjdong_across_legacy_codes():
    # 부천 실측(2026-07-27): 대표(41190) 자신의 법정동 목록을 옛구코드 여러개에
    # 그대로 재사용해 조회해야 한다(옛구마다 독립 번호체계라 하나만 물으면 누락).
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    targets = {'41370': '오산시'}
    old_gu_map = {'41370': ['41192', '41194']}
    groups = F.fold_groups(targets, sido_by_code, bjdong_by_sgg, old_gu_map)
    fixed = F.apply_legacy_gu_fix(groups)
    assert '41370' in fixed                                    # 대표 키는 안 바뀜(GANGWON_CODE_FIX와 차이점)
    assert set(fixed['41370']['bjdong'].keys()) == {'41192', '41194'}
    assert fixed['41370']['bjdong']['41192'] == ['11300']       # 대표의 법정동(세교동) 그대로 재사용
    assert fixed['41370']['bjdong']['41194'] == ['11300']


def test_apply_legacy_gu_fix_noop_when_no_legacy():
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        F.build_target_index(FIXTURE_ROWS, LZ_SIDO_FULL_FIXTURE)
    targets = {'41370': '오산시'}
    groups = F.fold_groups(targets, sido_by_code, bjdong_by_sgg, {})
    fixed = F.apply_legacy_gu_fix(groups)
    assert fixed['41370']['bjdong'] == groups['41370']['bjdong']


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
    monkeypatch.setattr(F, 'fetch_page', lambda sigungu, bjdong, page, endpoint=F.EP: ('', 'error'))
    items, had_error = F.fetch_bjdong_all_pages('41370', '11300')
    assert items == []
    assert had_error is True


def test_fetch_bjdong_all_pages_no_error_on_clean_no_data(monkeypatch):
    monkeypatch.setattr(F, 'fetch_page', lambda sigungu, bjdong, page, endpoint=F.EP: ('', 'no_data_xml'))
    items, had_error = F.fetch_bjdong_all_pages('41370', '11300')
    assert items == []
    assert had_error is False


def _fake_page_xml(n_items, total_count):
    items = ''.join('<item><mgmHsrgstPk>%d</mgmHsrgstPk></item>' % i for i in range(n_items))
    return ('<response><header><resultCode>00</resultCode></header><body><items>%s</items>'
            '<numOfRows>%d</numOfRows><pageNo>1</pageNo><totalCount>%d</totalCount>'
            '</body></response>') % (items, n_items, total_count)


def test_parse_total_count_reads_totalcount_tag():
    assert F.parse_total_count(_fake_page_xml(100, 1072)) == 1072
    assert F.parse_total_count('<response></response>') is None


def test_fetch_bjdong_all_pages_continues_past_server_page_cap(monkeypatch):
    # 회귀 테스트(2026-07-27 실측 버그): 서버가 요청한 numOfRows(1000)를
    # 무시하고 페이지당 100건만 돌려준다 — totalCount=1072인 법정동이면
    # 100건씩 10페이지 + 마지막 72건, 총 11페이지가 필요하다. 예전 로직
    # (이번 페이지 건수 < 요청한 NUM_ROWS)은 "100 < 1000"이 항상 참이라
    # 첫 페이지에서 멈췄다(강남 삼성동 실측: 1072건 중 100건만 수집됨).
    # 지금은 누적 items가 totalCount에 도달할 때까지 계속 페이징해야 한다.
    calls = []

    def fake_fetch_page(sigungu, bjdong, page, endpoint=F.EP):
        calls.append(page)
        if page <= 10:
            return _fake_page_xml(100, 1072), 'data'
        return _fake_page_xml(72, 1072), 'data'   # 마지막 페이지(11번째): 72건

    monkeypatch.setattr(F, 'fetch_page', fake_fetch_page)
    items, had_error = F.fetch_bjdong_all_pages('11680', '10500')
    assert had_error is False
    assert len(items) == 1072                  # 100*10 + 72, 총계와 정확히 일치
    assert calls == list(range(1, 12))          # 11페이지 전부 호출됨


def test_fetch_bjdong_all_pages_single_page_under_cap_stops_correctly(monkeypatch):
    # totalCount가 서버 페이지 상한(관측 100) 이하인 흔한 경우 — 1페이지에서
    # 정상 종료해야 한다(불필요한 추가 호출 없이).
    calls = []

    def fake_fetch_page(sigungu, bjdong, page, endpoint=F.EP):
        calls.append(page)
        return _fake_page_xml(7, 7), 'data'

    monkeypatch.setattr(F, 'fetch_page', fake_fetch_page)
    items, had_error = F.fetch_bjdong_all_pages('41370', '11300')
    assert len(items) == 7
    assert calls == [1]


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


def test_fetch_group_fans_out_legacy_codes_for_bucheon_style_group(monkeypatch):
    # 준공(HsPmsHubService) 전용 팬아웃: legacy 그룹은 대표코드(41190) 자체가
    # 아니라 옛구코드(41192/41194) 각각으로, 대표 자신의 법정동 목록을 그대로
    # 재사용해 조회해야 한다(실측 2026-07-27).
    group = {'name': '부천시', 'sido': '경기', 'members': ['41190'],
             'bjdong': {'41190': ['10100', '10200']},
             'legacy': {'legacy_codes': ['41192', '41194'], 'enumerable': True}}
    calls = []

    def fake_fetch_bjdong_all_pages(sigungu, bjdong, log=None):
        calls.append((sigungu, bjdong))
        return [], False

    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', fake_fetch_bjdong_all_pages)
    F.fetch_group(group)
    # 대표코드(41190) 자체로는 한 번도 호출되지 않고, 옛구코드 2개 x 법정동 2개
    # = 4콜이 나가야 한다(대표 자신의 법정동 목록이 옛구코드마다 재사용됨).
    assert ('41190', '10100') not in calls and ('41190', '10200') not in calls
    assert set(calls) == {('41192', '10100'), ('41192', '10200'),
                           ('41194', '10100'), ('41194', '10200')}


def test_fetch_group_demol_reverses_jeonbuk_code_for_query_only(monkeypatch):
    # 회귀(2026-07-31 실측): 멸실 API는 전북을 아직 구 코드(45xxx)로만 응답한다
    # (군산 45130 3개동 15건 vs 52130 0건). build_targets는 준공 기준 신 코드
    # (52130)를 주므로 멸실 조회 때만 구 코드로 되돌려야 한다. 단 저장 키
    # (productive)는 신 코드 그대로여야 준공 쪽과 체계가 맞는다.
    group = {'name': '군산시', 'sido': '전북', 'members': ['52130'],
             'bjdong': {'52130': ['10100', '10200']}, 'legacy': None}
    calls = []

    def fake_fetch(sigungu, bjdong, log=None, endpoint=None):
        calls.append((sigungu, bjdong))
        return [{'mainPurpsCdNm': '공동주택', 'hhldCnt': '10', 'demolEndDay': '20200315',
                 'mgmPmsrgstPk': 'PK' + bjdong}], False

    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', fake_fetch)
    demol_q, productive, had_err = F.fetch_group_demol(group)
    assert set(calls) == {('45130', '10100'), ('45130', '10200')}   # 조회는 구 코드로
    assert set(productive) == {'5213010100', '5213010200'}          # 저장은 신 코드로
    assert demol_q == {'2020Q1': 20}


def test_fetch_group_demol_does_not_reverse_gangwon(monkeypatch):
    # 강원은 멸실도 신 코드가 정상이다(원주 51130 68건 vs 42130 0건) — 역매핑을
    # 강원까지 적용하면 멀쩡한 데이터가 죽는다.
    group = {'name': '원주시', 'sido': '강원', 'members': ['51130'],
             'bjdong': {'51130': ['10100']}, 'legacy': None}
    calls = []

    def fake_fetch(sigungu, bjdong, log=None, endpoint=None):
        calls.append((sigungu, bjdong))
        return [], False

    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', fake_fetch)
    F.fetch_group_demol(group)
    assert calls == [('51130', '10100')]   # 신 코드 그대로


def test_fetch_group_demol_does_not_fan_out_legacy_codes(monkeypatch):
    # 멸실(ArchPmsHubService)은 대표코드 자체로 실데이터가 나온다(실측
    # 2026-07-27, 41190/10100->521건 등) — fetch_group_demol은 준공과 달리
    # legacy 팬아웃을 적용하지 않고 group['bjdong']를 원본(대표코드 키) 그대로
    # 써야 한다.
    group = {'name': '부천시', 'sido': '경기', 'members': ['41190'],
             'bjdong': {'41190': ['10100', '10200']},
             'legacy': {'legacy_codes': ['41192', '41194'], 'enumerable': True}}
    calls = []

    def fake_fetch_bjdong_all_pages(sigungu, bjdong, log=None, endpoint=None):
        calls.append((sigungu, bjdong))
        return [], False

    monkeypatch.setattr(F, 'fetch_bjdong_all_pages', fake_fetch_bjdong_all_pages)
    F.fetch_group_demol(group)
    assert set(calls) == {('41190', '10100'), ('41190', '10200')}   # 대표코드 그대로, 팬아웃 없음


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


# ---------------------------------------------------------------------------
# 재시딩 캠페인 재개(2026-08-03): --reseed는 라이브 게이트(meta['scanned'])를
# 건드리지 않으므로 진행 재개를 meta['reseed_done']이 담당한다. 이게 없으면
# 340분 캡에 걸린 샤드를 재트리거할 때마다 자기 그룹을 처음부터 다시 돈다.
# ---------------------------------------------------------------------------

RESEED_GROUPS = {
    '41370': {'name': '오산시', 'sido': '경기', 'members': ['41370'],
              'bjdong': {'41370': ['11300']}, 'legacy': None},
    '48120': {'name': '창원시', 'sido': '경남', 'members': ['48120'],
              'bjdong': {'48120': ['10100']}, 'legacy': None},
}


def test_reseed_records_progress_without_touching_live_scanned_gate(tmp_path, monkeypatch):
    # 핵심 제약: 재시딩 며칠 동안 meta['scanned']가 줄면 hub_derive의 존 완결성
    # 게이트가 닫혀 라이브가 통째로 pre-HUB로 되돌아간다. scanned는 그대로 두고
    # 진행분만 reseed_done에 쌓여야 한다.
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [],
                        'scanned': ['41370', '48120']},
              'sgg': {'41370': {'name': '오산시', 'done_q': {'2024Q1': 5}, 'sched_q': {}},
                      '48120': {'name': '창원시', 'done_q': {'2024Q1': 5}, 'sched_q': {}}},
              'productive_bjdong': ['4137011300']}

    def fetch_group_stub(group, only_bjdong=None):
        return {'2024Q1': 42}, {}, [], [], False

    result = _run_with_stub_full(tmp_path, monkeypatch, RESEED_GROUPS, seeded,
                                 fetch_group_stub, reseed=True)
    assert set(result['meta']['scanned']) == {'41370', '48120'}       # 게이트 그대로
    assert set(result['meta']['reseed_done']) == {'41370', '48120'}   # 진행분 기록


def test_reseed_resumes_from_campaign_progress_on_retrigger(tmp_path, monkeypatch, capsys):
    # 41370은 이번 캠페인에서 이미 재스캔 완료 -> 재트리거에서 건너뛰고
    # 48120만 이어서 돈다(캡에 걸려 죽은 샤드를 다시 던지는 상황).
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [],
                        'scanned': ['41370', '48120'], 'reseed_done': ['41370']},
              'sgg': {'41370': {'name': '오산시', 'done_q': {'2024Q1': 42}, 'sched_q': {}},
                      '48120': {'name': '창원시', 'done_q': {'2024Q1': 5}, 'sched_q': {}}},
              'productive_bjdong': []}

    called = []

    def fetch_group_stub(group, only_bjdong=None):
        called.append(group['name'])
        return {'2024Q1': 77}, {}, [], [], False

    result = _run_with_stub_full(tmp_path, monkeypatch, RESEED_GROUPS, seeded,
                                 fetch_group_stub, reseed=True)
    assert called == ['창원시']                                        # 41370은 재호출 안 됨
    assert result['sgg']['41370']['done_q'] == {'2024Q1': 42}         # 이번 캠페인 값 보존
    assert result['sgg']['48120']['done_q'] == {'2024Q1': 77}
    assert '[RESEED skip] 41370' in capsys.readouterr().out


def test_reseed_starts_fresh_campaign_when_previous_one_completed(tmp_path, monkeypatch, capsys):
    # 지난 캠페인이 전량 완료된 상태로 새 --reseed가 들어오면 전부 skip돼
    # 아무것도 안 도는 함정이 있다 — 자기 초기화로 새 캠페인을 연다.
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [],
                        'scanned': ['41370', '48120'],
                        'reseed_done': ['41370', '48120']},
              'sgg': {}, 'productive_bjdong': []}

    called = []

    def fetch_group_stub(group, only_bjdong=None):
        called.append(group['name'])
        return {'2024Q1': 1}, {}, [], [], False

    result = _run_with_stub_full(tmp_path, monkeypatch, RESEED_GROUPS, seeded,
                                 fetch_group_stub, reseed=True)
    assert sorted(called) == ['오산시', '창원시']
    assert '초기화하고 새 캠페인 시작' in capsys.readouterr().out
    assert set(result['meta']['reseed_done']) == {'41370', '48120'}


def test_plain_full_does_not_write_reseed_done(tmp_path, monkeypatch):
    # --reseed 없는 평범한 --full은 캠페인 키를 만들지 않는다(무관한 실행이
    # 캠페인 진행 상태를 조용히 바꾸면 안 된다).
    seeded = {'meta': {'fetched': '', 'mode': 'full', 'unresolved_legacy': [], 'scanned': []},
              'sgg': {}, 'productive_bjdong': []}

    def fetch_group_stub(group, only_bjdong=None):
        return {'2024Q1': 1}, {}, [], [], False

    result = _run_with_stub_full(tmp_path, monkeypatch, RESEED_GROUPS, seeded, fetch_group_stub)
    assert 'reseed_done' not in result['meta']


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

# ---------------------------------------------------------------------------
# 강원(42xxx->51xxx) 코드 정정: code_bdong.json이 원주/춘천/강릉권의 신 코드
# (51xxx) 행을 아예 갖고 있지 않고 스테일한 42xxx만 활성행으로 갖고 있는 실측
# 갭 대응(hub_common.GANGWON_CODE_FIX). apply_gangwon_fix()는 fold_groups가
# 뽑아낸 42xxx rep을 51xxx로 RENAME(옮김)한다 — bjdong 목록은 신/구 동일이라
# 그대로 재사용.
# ---------------------------------------------------------------------------

def test_apply_gangwon_fix_renames_rep_key_and_reuses_bjdong():
    groups = {
        '42110': {'name': '춘천시', 'sido': '강원', 'members': ['42110'],
                   'bjdong': {'42110': ['11200', '11300']}, 'legacy': None},
        '41370': {'name': '오산시', 'sido': '경기', 'members': ['41370'],
                   'bjdong': {'41370': ['11300']}, 'legacy': None},   # 무관 그룹, 영향 없어야 함
    }
    out = F.apply_gangwon_fix(groups)
    assert '42110' not in out
    assert '51110' in out
    assert out['51110']['members'] == ['51110']
    assert out['51110']['bjdong'] == {'51110': ['11200', '11300']}
    assert out['51110']['name'] == '춘천시'
    assert out['41370']['members'] == ['41370']   # 무관 그룹은 그대로


def test_apply_gangwon_fix_renames_all_member_codes_not_just_rep():
    # 회귀(2026-07-31 실측 버그): 전주는 구 분할 도시(본체 45110 + 완산구 45111 +
    # 덕진구 45113)라 rep뿐 아니라 멤버 코드도 전부 스테일이다. 예전 로직은
    # `m == old`로 rep만 갈아끼워 45111/45113이 남았고, 그 구들이 라이브 API에서
    # 0건이라 전주 준공이 통째로 비었다(전량 재시딩 "148/148 완료"인데도 done=0).
    # 이제 members/bjdong의 모든 코드에 매핑이 적용돼야 한다.
    groups = {
        '45110': {'name': '전주시', 'sido': '전북', 'members': ['45110', '45111', '45113'],
                   'bjdong': {'45110': ['10100'], '45111': ['10200'], '45113': ['10300']},
                   'legacy': None},
    }
    out = F.apply_gangwon_fix(groups)
    assert '45110' not in out
    assert out['52110']['members'] == ['52110', '52111', '52113']      # 구까지 전부 신코드
    assert set(out['52110']['bjdong'].keys()) == {'52110', '52111', '52113'}
    assert out['52110']['bjdong']['52111'] == ['10200']                 # bjdong 목록은 그대로 재사용
    assert out['52110']['name'] == '전주시'


def test_apply_gangwon_fix_covers_jeonbuk_single_code_cities():
    # 군산·익산·완주는 구 분할이 없는 단일 코드 — 45xxx -> 52xxx 치환만 되면 된다.
    groups = {
        '45130': {'name': '군산시', 'sido': '전북', 'members': ['45130'],
                   'bjdong': {'45130': ['10100']}, 'legacy': None},
        '45140': {'name': '익산시', 'sido': '전북', 'members': ['45140'],
                   'bjdong': {'45140': ['10100']}, 'legacy': None},
        '45710': {'name': '완주군', 'sido': '전북', 'members': ['45710'],
                   'bjdong': {'45710': ['10100']}, 'legacy': None},
    }
    out = F.apply_gangwon_fix(groups)
    assert set(out.keys()) == {'52130', '52140', '52710'}
    assert out['52130']['members'] == ['52130']
    assert out['52140']['bjdong'] == {'52140': ['10100']}


def test_apply_gangwon_fix_noop_when_old_codes_absent():
    groups = {'51110': {'name': '춘천시', 'sido': '강원', 'members': ['51110'],
                          'bjdong': {'51110': ['11200']}, 'legacy': None}}
    out = F.apply_gangwon_fix(groups)
    assert out == groups


def test_apply_gangwon_fix_renames_donghae_sokcho_independently_of_gangneung():
    # 강릉권은 LIVEZONE상 강릉시 외에 동해시(42170)·속초시(42210)도 멤버인데,
    # fold_groups는 (시도,이름) 단위로 그룹을 접기 때문에 이 둘은 강릉시와
    # 별개 그룹(각자가 자기 rep)이다 — 강릉시(42150)만 고치고 이 둘을 빠뜨리면
    # 계속 스테일 상태로 남는다(실측으로 확인한 갭). code_fix 표에 42170/42210이
    # 있으면 강릉시 항목 유무와 무관하게 독립적으로 51170/51210으로 옮겨져야 한다.
    groups = {
        '42170': {'name': '동해시', 'sido': '강원', 'members': ['42170'],
                   'bjdong': {'42170': ['10100', '10200']}, 'legacy': None},
        '42210': {'name': '속초시', 'sido': '강원', 'members': ['42210'],
                   'bjdong': {'42210': ['10100']}, 'legacy': None},
    }
    out = F.apply_gangwon_fix(groups)
    assert '42170' not in out and '42210' not in out
    assert out['51170']['bjdong'] == {'51170': ['10100', '10200']}
    assert out['51170']['name'] == '동해시'
    assert out['51210']['bjdong'] == {'51210': ['10100']}
    assert out['51210']['name'] == '속초시'


def test_build_targets_real_data_produces_gangwon_51xxx_reps_not_42xxx():
    # 실제 code_bdong.json(네트워크 없음)으로 전체 파이프라인을 돌려, 확인된
    # 데이터 갭(42xxx만 활성으로 남아있음)이 build_targets() 출력에서 51xxx로
    # 정정돼 나오는지 검증한다. 강릉권의 동해시/속초시(42170/42210->51170/51210)도
    # 강릉시(42150->51150)와 동일 패턴이라 함께 검증한다.
    groups, unresolved_names = F.build_targets()
    for stale in ('42110', '42130', '42150', '42170', '42210'):
        assert stale not in groups
    for rep, expect_name_substr in (('51110', '춘천'), ('51130', '원주'), ('51150', '강릉'),
                                     ('51170', '동해'), ('51210', '속초')):
        assert rep in groups, '%s(%s) 그룹이 build_targets() 출력에 없음' % (rep, expect_name_substr)
        g = groups[rep]
        assert rep in g['members']
        bjdong_list = g['bjdong'].get(rep, [])
        assert len(bjdong_list) > 0, '%s의 bjdong 목록이 비어 있음' % rep


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


def test_aggregate_units_cap_is_per_stage():
    """캡은 done/sched 각각 UNITS_CAP — 섞어서 자르면 옛 준공 대단지가 자리를 다
    차지해 '앞으로 들어올 단지' 목록이 비어버린다(2026-08-01 춘천권 사례)."""
    items = []
    # 준공(과거) 대단지 60개: 세대 2000~2059 — 섞어 자르면 이들이 상위를 독점
    for i in range(60):
        items.append({'purpsCdNm': '공동주택', 'totHhldCnt': 2000 + i,
                      'mgmHsrgstPk': 'D%d' % i, 'bldNm': '옛단지%d' % i,
                      'useInsptDay': '20200315'})
    # 준공예정(미래) 소단지 60개: 세대 100~159
    for i in range(60):
        items.append({'purpsCdNm': '공동주택', 'totHhldCnt': 100 + i,
                      'mgmHsrgstPk': 'S%d' % i, 'bldNm': '새단지%d' % i,
                      'useInsptSchedDay': '20281120'})
    _dq, _sq, units = F._aggregate(items)
    done = [u for u in units if u[3] == 'done']
    sched = [u for u in units if u[3] == 'sched']
    # 캡 폐지(2026-08-02) 후에도 stage 분리는 유지 — 화면이 done/sched 2섹션이라
    # 정렬이 stage 안에서 닫혀야 한다. 캡을 되살릴 때 이 구조가 그대로 쓰인다.
    assert len(done) == 60, 'done 전량이 남아야 한다'
    assert len(sched) == 60, 'sched가 옛 대단지에 밀리면 안 된다'
    # 각 stage 안에서는 세대 큰 순
    assert done[0][1] == 2059 and sched[0][1] == 159


# ---------------------------------------------------------------------------
# 샤드 분할 (2026-08-02) — merge_hub_shards.py가 같은 규칙으로 소유권을 재계산한다
# ---------------------------------------------------------------------------

def test_shard_keys_partition_is_exact():
    """N개 샤드가 전체를 정확히 한 번씩 덮어야 한다 — 겹치면 병합이 덮어쓰고
    빠지면 그 시군구가 영영 갱신 안 된다."""
    keys = ['%05d' % i for i in range(148)]
    for n in (1, 3, 6, 7):
        parts = [F.shard_keys(keys, (i, n)) for i in range(1, n + 1)]
        flat = [k for p in parts for k in p]
        assert sorted(flat) == sorted(keys), 'n=%d 분할이 전체를 안 덮는다' % n
        assert len(flat) == len(set(flat)), 'n=%d 샤드가 겹친다' % n
        # 인터리브라 크기 차가 1을 넘지 않는다
        assert max(map(len, parts)) - min(map(len, parts)) <= 1


def test_shard_keys_is_order_independent():
    """입력 순서가 달라도 같은 샤드가 나와야 한다(정렬 후 분할) — 수집기와 병합기가
    서로 다른 경로로 키 목록을 만들어도 소유권이 갈리면 안 된다."""
    keys = ['41110', '11110', '26110', '51110', '43110']
    a = F.shard_keys(keys, (2, 3))
    b = F.shard_keys(list(reversed(keys)), (2, 3))
    assert a == b


def test_should_refresh_group_true_for_legacy_gu_cached_under_old_codes():
    """부천 사각지대 회귀 방지(2026-08-03). fetch_group은 옛 구코드(41192/94/96)로
    팬아웃해 조회하므로 productive_bjdong도 옛 코드로 저장되는데, 문지기가 대표
    코드(41190)로만 교집합을 보면 항상 공집합 → --full 시딩이 멀쩡해도 증분이
    매달 부천을 건너뛰었다. legacy_codes까지 팬아웃해 검사해야 한다."""
    group_bjdong = {'41190': ['10100', '10200']}
    legacy = {'legacy_codes': ['41192', '41194', '41196'], 'enumerable': True}
    cached = {'4119210100', '4119410200'}          # 옛 코드로만 저장돼 있음
    assert F.should_refresh_group('41190', group_bjdong, cached, False,
                                  legacy=legacy) is True
    # legacy 정보를 안 넘기면(옛 버그 재현) 여전히 False — 인자 전달을 잊으면 잡힌다
    assert F.should_refresh_group('41190', group_bjdong, cached, False) is False

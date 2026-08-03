import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import hub_common as H

def test_to_quarter():
    assert H.to_quarter('20240315') == '2024Q1'
    assert H.to_quarter('2024-11-02') == '2024Q4'
    assert H.to_quarter('') is None
    assert H.to_quarter('bad') is None

def test_dedupe_keeps_one_per_pk():
    items = [{'mgmHsrgstPk':'A','totHhldCnt':'10'},
             {'mgmHsrgstPk':'A','totHhldCnt':'10'},
             {'mgmHsrgstPk':'B','totHhldCnt':'5'}]
    assert len(H.dedupe(items)) == 2

def test_apt_records_filters_and_dedupes():
    items = [{'mgmHsrgstPk':'A','purpsCdNm':'공동주택','totHhldCnt':'30'},
             {'mgmHsrgstPk':'A','purpsCdNm':'공동주택','totHhldCnt':'30'},  # 중복
             {'mgmHsrgstPk':'C','purpsCdNm':'단독주택','totHhldCnt':'1'},   # 유형 제외
             {'mgmHsrgstPk':'D','purpsCdNm':'공동주택','totHhldCnt':'0'}]   # 0세대 제외
    out = H.apt_records(items)
    assert [r['mgmHsrgstPk'] for r in out] == ['A']


# ---------------------------------------------------------------------------
# 이중등재 접기 (2026-08-03 감사): mgmHsrgstPk는 '단지' 키가 아니라 '대장' 키다.
# 같은 사업이 PK만 다른 채 두 번 등재된 사례가 전국 규모로 확인됐다.
# ---------------------------------------------------------------------------

def _reg(pk, **kw):
    """실제 응답에 가까운 대장 레코드 픽스처(제물포역 쌍 기준)."""
    base = {
        'mgmHsrgstPk': pk, 'rnum': '1',
        'platPlc': '인천광역시 미추홀구 도화동 94-1번지', 'purpsCdNm': '공동주택',
        'bldNm': '제물포역 북측 도심 공공주택 복합지구 공동주택', 'totHhldCnt': '3497',
        'totArea': '576352.0556', 'useInsptDay': '', 'useInsptSchedDay': '20310930',
        'apprvDay': '20240115', 'block': ' ', 'lot': ' ', 'crtnDay': '20260625',
    }
    base.update(kw)
    return base


def test_collapse_folds_pair_differing_only_by_pk_and_rnum():
    # 실측 쌍: pk=1000...220546 / 220547, rnum 3/4 — 나머지 전 필드 동일.
    items = [_reg('1000000000000000220546', rnum='3'),
             _reg('1000000000000000220547', rnum='4')]
    out = H.collapse_dup_registrations(items)
    assert len(out) == 1


def test_collapse_folds_old_and_new_pk_scheme_pair():
    # 달서 본리동 589세대: 구형 PK(1044...)와 신형 PK(1000...)로 이중 등재.
    items = [_reg('1000000000000000099016', bldNm='본리동 주상복합', totHhldCnt='589'),
             _reg('1044100006146', bldNm='본리동 주상복합', totHhldCnt='589')]
    assert len(H.collapse_dup_registrations(items)) == 1


def test_collapse_keeps_records_differing_in_any_substantive_field():
    # 세대수·지번·연면적·인허가일 등 실질 필드가 하나라도 다르면 별개로 남는다.
    items = [_reg('A'), _reg('B', totHhldCnt='3496')]
    assert len(H.collapse_dup_registrations(items)) == 2
    items = [_reg('A'), _reg('B', platPlc='인천광역시 미추홀구 도화동 95번지')]
    assert len(H.collapse_dup_registrations(items)) == 2
    items = [_reg('A'), _reg('B', apprvDay='20240116')]
    assert len(H.collapse_dup_registrations(items)) == 2


def test_collapse_does_not_fold_per_dong_registrations():
    """호별·동별 대장(F2)은 여기서 접히면 안 된다.

    신림현대 1,634세대는 block(동번호)·lot(호수)가 서로 다른 56개 대장에
    단지 총세대수가 복제된 유형이다. 이건 지번 단위 사업 계상으로 따로 풀
    문제고, 여기서 같이 접으면 '진짜 별동'까지 지워버릴 위험이 있다.
    """
    items = [_reg('1022233', block='106', lot='1410', apprvDay='20050809'),
             _reg('1022234', block='103', lot='1502', apprvDay='20050809'),
             _reg('1022235', block='110', lot='1505', apprvDay='20050812')]
    assert len(H.collapse_dup_registrations(items)) == 3


def test_collapse_treats_blank_and_space_as_same():
    # XML은 빈 필드를 ' '(공백)으로, 다른 경로는 ''로 준다 — 같은 값으로 본다.
    items = [_reg('A', splotNm=' '), _reg('B', splotNm='')]
    assert len(H.collapse_dup_registrations(items)) == 1


def test_apt_records_applies_collapse_by_default_and_can_opt_out():
    items = [_reg('1000000000000000220546', rnum='3'),
             _reg('1000000000000000220547', rnum='4')]
    assert len(H.apt_records(items)) == 1                    # 기본: 접힘
    assert len(H.apt_records(items, collapse=False)) == 2    # 로그용 비교치

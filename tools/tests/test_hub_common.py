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


# ---------------------------------------------------------------------------
# 사업 단위 계상 — 호별·동별 대장에 단지 총세대수가 복제된 유형(F2).
# 외부 실측: 봉화산 e편한세상(원주 단계동) 690세대 · 신림현대(관악) 1,634세대·14개동.
# ---------------------------------------------------------------------------

BONG = '강원특별자치도 원주시 단계동 1234번지'


def test_collapse_by_project_folds_replicated_complex_total():
    # 대장 105개가 각각 단지 총세대수 690을 달고 있는 실제 형태.
    units = [['봉화산 e-편한세상', 690, '2004-11', 'done', BONG] for _ in range(99)]
    units += [['봉화산e-편한세상', 690, '2004-12', 'done', BONG] for _ in range(3)]
    out = H.collapse_units_by_project(units)
    assert len(out) == 1
    assert sum(u[1] for u in out) == 690          # 72,450이 아니라 실제 690
    assert out[0][2] == '2004-11'                 # 최빈 연월(소수 이설 대장에 안 밀림)
    assert out[0][0] == '봉화산 e-편한세상'        # 최빈 표기


def test_collapse_by_project_keeps_genuinely_different_sizes_at_same_jibun():
    """같은 지번이라도 세대수가 다르면 진짜 동별 분할 — 합산돼야 한다.

    세대수를 키에 넣는 이유가 이것이다. 지번만으로 접으면 동별로 규모가 다른
    단지의 물량이 통째로 사라진다.
    """
    units = [['A동', 60, '2020-01', 'done', BONG],
             ['B동', 80, '2020-01', 'done', BONG],
             ['C동', 100, '2020-01', 'done', BONG]]
    out = H.collapse_units_by_project(units)
    assert sum(u[1] for u in out) == 240


def test_collapse_by_project_prefers_done_over_sched():
    # 이미 준공된 단지를 미래공급으로도 세면 재고·미래공급 이중계상이 된다.
    units = [['신림현대', 1634, '2006-11', 'sched', BONG],
             ['신림현대', 1634, '1993-05', 'done', BONG],
             ['신림현대', 1634, '2007-02', 'sched', BONG]]
    out = H.collapse_units_by_project(units)
    assert len(out) == 1
    assert out[0][3] == 'done' and out[0][2] == '1993-05'


def test_collapse_by_project_leaves_units_without_jibun_untouched():
    # 지번은 2026-08-03부터 수집한다 — 없는 항목을 근거 없이 접으면 안 된다.
    units = [['옛항목', 500, '2019-03', 'done'],
             ['옛항목', 500, '2019-04', 'done', '   ']]
    out = H.collapse_units_by_project(units)
    assert len(out) == 2
    assert sum(u[1] for u in out) == 1000


def test_collapse_by_project_is_idempotent():
    """두 번 접어도 값이 같아야 한다.

    재시딩 도중 코드가 갱신되면 일부 시군구는 수집기가 이미 접은 상태로,
    나머지는 대장 그대로 저장된다 — 소급 스크립트(rebuild_hub_projects)가 그
    섞인 파일에 다시 돌아도 이미 접힌 쪽을 망가뜨리면 안 된다.
    """
    units = [['봉화산 e-편한세상', 690, '2004-11', 'done', BONG] for _ in range(5)]
    once = H.collapse_units_by_project(units)
    twice = H.collapse_units_by_project(once)
    assert once == twice


def test_collapse_by_project_separates_different_jibun():
    units = [['1단지', 500, '2020-01', 'done', BONG],
             ['2단지', 500, '2020-01', 'done', BONG.replace('1234', '5678')]]
    assert len(H.collapse_units_by_project(units)) == 2


def test_apt_records_applies_collapse_by_default_and_can_opt_out():
    items = [_reg('1000000000000000220546', rnum='3'),
             _reg('1000000000000000220547', rnum='4')]
    assert len(H.apt_records(items)) == 1                    # 기본: 접힘
    assert len(H.apt_records(items, collapse=False)) == 2    # 로그용 비교치


def test_collapse_preserves_and_picks_earliest_stcns():
    """착공연월(6번째)은 접힌 뒤에도 남아야 한다 — 안 챙기면 수집만 하고 못 쓴다.

    같은 사업의 대장들이 서로 다른 착공일을 달고 있으면 가장 이른 값이 그 사업이
    실제로 삽을 뜬 시점이다. 옛 5필드 데이터와 섞여도 깨지면 안 된다(하위호환).
    """
    P = '서울특별시 강북구 번동 1-1번지'
    got = H.collapse_units_by_project([
        ['A동', 500, '2026-03', 'sched', P, '2023-05'],
        ['B동', 500, '2026-03', 'sched', P, '2023-02'],
        ['C동', 500, '2026-03', 'sched', P, None]])
    assert len(got) == 1 and got[0][5] == '2023-02'

    # 옛 형식(5필드)만 있으면 None으로 채워 형태를 통일한다.
    old = H.collapse_units_by_project([
        ['A동', 500, '2026-03', 'sched', P],
        ['B동', 500, '2026-03', 'sched', P]])
    assert len(old) == 1 and old[0][5] is None

    # 혼재해도 있는 값을 쓴다.
    mix = H.collapse_units_by_project([
        ['A동', 500, '2026-03', 'sched', P],
        ['B동', 500, '2026-03', 'sched', P, '2023-02']])
    assert mix[0][5] == '2023-02'

    # done 우선 규칙은 그대로.
    d = H.collapse_units_by_project([
        ['A', 300, '2024-01', 'sched', P, '2021-01'],
        ['A', 300, '2024-06', 'done', P, '2021-01']])
    assert d[0][3] == 'done' and d[0][5] == '2021-01'

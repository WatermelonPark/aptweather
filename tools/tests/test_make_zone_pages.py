import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_zone_pages as M


# ---------------------------------------------------------------------------
# Task 7: render_units_2sec — 존 상세페이지 "앞으로 들어올 물량"/"최근 들어온
# 물량" 2섹션 순수 렌더 헬퍼
# ---------------------------------------------------------------------------

TODAY = datetime.date(2026, 7, 24)


def test_render_units_2sec_empty_units_returns_empty_string():
    assert M.render_units_2sec({}, TODAY) == ''
    assert M.render_units_2sec(None, TODAY) == ''
    assert M.render_units_2sec({'sched': [], 'done': []}, TODAY) == ''


def test_render_units_2sec_renders_both_sections_with_markers():
    units = {
        'sched': [
            ['오산더샵', 400, '2027-03'],           # 8개월 뒤 — 정상
            ['오산센트럴', 999, None],                # 연월 결측 — "미정"
            ['오산레이크', 300, '2031-01'],           # ~4.5년 뒤 — 지연 가능
        ],
        'done': [
            ['오산자이', 832, '2024-03'],
        ],
    }
    html = M.render_units_2sec(units, TODAY)
    assert '앞으로 들어올 물량' in html
    assert '최근 들어온 물량' in html
    assert '오산더샵' in html and '2027.03 예정' in html
    assert '오산센트럴' in html and '미정' in html
    assert '오산레이크' in html and '지연 가능' in html
    assert '오산자이' in html and '2024.03 준공' in html
    assert '832' in html and '400' in html


def test_render_units_2sec_far_future_gets_muted_class_and_hint():
    units = {'sched': [['오산레이크', 300, '2031-01']], 'done': []}
    html = M.render_units_2sec(units, TODAY)
    assert 'class="far"' in html
    assert '지연 가능' in html


def test_render_units_2sec_near_future_no_hint():
    units = {'sched': [['오산더샵', 400, '2027-03']], 'done': []}
    html = M.render_units_2sec(units, TODAY)
    assert '지연 가능' not in html
    assert 'class="far"' not in html


def test_render_units_2sec_sched_only_omits_done_section():
    units = {'sched': [['오산더샵', 400, '2027-03']], 'done': []}
    html = M.render_units_2sec(units, TODAY)
    assert '앞으로 들어올 물량' in html
    assert '최근 들어온 물량' not in html


def test_render_units_2sec_done_only_omits_sched_section():
    units = {'sched': [], 'done': [['오산자이', 832, '2024-03']]}
    html = M.render_units_2sec(units, TODAY)
    assert '최근 들어온 물량' in html
    assert '앞으로 들어올 물량' not in html


# ---------------------------------------------------------------------------
# build_page 통합: permits.units가 있는 존은 2섹션, 없는 존은 기존 odcloud
# 폴백 렌더가 그대로 나가야 한다(에러 없이).
# ---------------------------------------------------------------------------

def _fake_row(nm='테스트권', units_field=None, subs=None):
    z = {'z': nm, 'region': '충북', 'psido': '충북', 'pop': 100000, 'supply': 500,
         'sgg': [('테스트시', 500)], 'q0': '', 'q1': '', 'span': 0}
    if units_field is not None:
        z['units'] = units_field
    r = dict(z=z, ps='충북', share=0.1, need=1000, dA=100, dB=10, dC=20, tot=130,
             fsup=900, fq=4, flag=None, lo=None, hi=None, loan=None, pv=None, plo=None,
             dY=0, refq=1000, band=None, inv_path=False, tot_fallback=130)
    if subs is not None:
        r['subs'] = subs
    return r


def test_build_page_renders_2sections_when_zone_has_permits_units():
    r = _fake_row('테스트권')
    punits = {'테스트권': {
        'sched': [['새아파트', 500, '2027-06']],
        'done': [['헌아파트', 300, '2024-01']],
    }}
    html = M.build_page(r, [r], '2026-07', '2026-07-24', punits)
    assert '앞으로 들어올 물량' in html
    assert '최근 들어온 물량' in html
    assert '새아파트' in html and '2027.06 예정' in html
    assert '헌아파트' in html and '2024.01 준공' in html


def test_build_page_falls_back_to_odcloud_list_when_no_permits_units():
    # permits.units에 이 존이 아예 없으면(커버 안 됨) 새 2섹션은 안 나가고,
    # 기존 odcloud 기반 z['units'](입주예정 단지 목록)로 폴백해야 한다(에러 없이).
    future_ym = '%04d-%02d' % (
        datetime.date.today().year + 2, ((datetime.date.today().month) % 12) + 1)
    r = _fake_row('테스트권', units_field=[['테스트시', '옛아파트', 200, future_ym]])
    html = M.build_page(r, [r], '2026-07', '2026-07-24', punits={})
    assert '입주 예정 단지' in html
    assert '옛아파트' in html
    assert '앞으로 들어올 물량' not in html
    assert '최근 들어온 물량' not in html


def test_build_page_no_permits_units_and_no_odcloud_units_does_not_error():
    r = _fake_row('테스트권')   # z['units'] 아예 없음, punits도 없음
    html = M.build_page(r, [r], '2026-07', '2026-07-24', punits=None)
    assert '<html' in html
    assert '앞으로 들어올 물량' not in html


# ---------------------------------------------------------------------------
# Fix I2(FINAL review): inv_path(러닝재고) 존은 히어로 tot가 running_shortage()에서
# 나오는데, 페이지가 여전히 dA/dB/dC 가중합(구 폴백 산식) 기반 breakdown 표·카드·
# note("...인구 비중으로 배분한 추정치...")를 보여주면 두 숫자가 안 맞아 사용자가
# 모순을 본다. inv_path 존은 이 breakdown을 숨기고, 폴백 존은 기존 그대로 유지돼야
# 한다.
# ---------------------------------------------------------------------------

def test_build_page_inv_path_zone_suppresses_fallback_breakdown():
    r = _fake_row('테스트권')
    r['inv_path'] = True
    html = M.build_page(r, [r], '2026-07', '2026-07-24', punits=None)
    assert '인허가 — 3~4년 뒤 입주' not in html          # 구 폴백 표 행
    assert '인구 비중으로 배분한 추정치' not in html      # 시도-배분 note
    assert '세 값을 더한 것이 맨 위의' not in html         # trio 합계=tot 주장
    assert '러닝재고' in html                             # 정직한 대체 요약은 남는다


def test_build_page_fallback_zone_still_shows_breakdown():
    r = _fake_row('테스트권')   # inv_path=False (기본)
    html = M.build_page(r, [r], '2026-07', '2026-07-24', punits=None)
    assert '인허가 — 3~4년 뒤 입주' in html
    assert '인구 비중으로 배분한 추정치' in html
    assert '세 값을 더한 것이 맨 위의' in html

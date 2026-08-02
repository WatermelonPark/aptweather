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


def test_render_units_2sec_renders_both_sections():
    units = {
        'sched': [
            ['오산더샵', 400, '2027-03'],           # 8개월 뒤 — 창 안
            ['오산센트럴', 999, None],                # 연월 결측 — "미정"으로 유지
        ],
        'done': [
            ['오산자이', 832, '2024-03'],            # 28개월 전 — 창 안
        ],
    }
    html = M.render_units_2sec(units, TODAY)
    assert '앞으로 들어올 단지' in html
    assert '최근 들어온 단지' in html
    assert '오산더샵' in html and '2027.03 예정' in html
    assert '오산센트럴' in html and '미정' in html
    assert '오산자이' in html and '2024.03 준공' in html
    assert '832' in html and '400' in html
    # 2026-07-31: 지연/지연 가능 태그 제거 결정
    assert '지연' not in html


def test_render_units_2sec_window_drops_far_and_old():
    # UNIT_WINDOW(±48개월) 밖은 목록에서 제외: 4.5년 뒤 예정, 10년+ 전 준공,
    # 이미 지난 예정일(스테일)도 빠진다.
    units = {'sched': [
        ['오산레이크', 300, '2031-01'],     # +54개월 — 제외
        ['오산지난예정', 250, '2026-01'],   # 예정일 경과 — 제외
        ['오산더샵', 400, '2027-03'],       # 창 안 — 유지
    ], 'done': [
        ['오산옛단지', 500, '2005-06'],     # 21년 전 — 제외
        ['오산자이', 832, '2024-03'],       # 창 안 — 유지
    ]}
    html = M.render_units_2sec(units, TODAY)
    assert '오산더샵' in html and '오산자이' in html
    assert '오산레이크' not in html
    assert '오산지난예정' not in html
    assert '오산옛단지' not in html


def test_render_units_2sec_all_outside_window_returns_empty():
    units = {'sched': [['오산레이크', 300, '2031-01']],
             'done': [['오산옛단지', 500, '2005-06']]}
    assert M.render_units_2sec(units, TODAY) == ''


def test_render_units_2sec_sched_only_omits_done_section():
    units = {'sched': [['오산더샵', 400, '2027-03']], 'done': []}
    html = M.render_units_2sec(units, TODAY)
    assert '앞으로 들어올 단지' in html
    assert '최근 들어온 단지' not in html


def test_render_units_2sec_done_only_omits_sched_section():
    units = {'sched': [], 'done': [['오산자이', 832, '2024-03']]}
    html = M.render_units_2sec(units, TODAY)
    assert '최근 들어온 단지' in html
    assert '앞으로 들어올 단지' not in html


# ---------------------------------------------------------------------------
# build_page 통합: permits.units가 있는 존은 2섹션, 없는 존은 기존 odcloud
# 폴백 렌더가 그대로 나가야 한다(에러 없이).
# ---------------------------------------------------------------------------

def _fake_row(nm='테스트권', units_field=None, subs=None):
    z = {'z': nm, 'region': '충북', 'psido': '충북', 'pop': 100000, 'supply': 500,
         'sgg': [('테스트시', 500)], 'q0': '', 'q1': '', 'span': 0}
    if units_field is not None:
        z['units'] = units_field
    need4 = 1000.0
    fsupw = 900.0
    inow = need4 - fsupw - 130   # tot == need4 - fsupw - inow 항등식 유지
    r = dict(z=z, ps='충북', share=0.1, need=1000, dA=100, dB=10, dC=20, tot=130,
             fsup=900, fq=4, flag=None, lo=None, hi=None, loan=None, pv=None, plo=None,
             dY=0, refq=1000, band=None, inv_path=False, tot_fallback=130,
             need4=need4, inow=inow, fsupw=fsupw, gr=M.grade(130, need4))
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
    assert '앞으로 들어올 단지' in html
    assert '최근 들어온 단지' in html
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
    assert '앞으로 들어올 단지' not in html
    assert '최근 들어온 단지' not in html


def test_build_page_no_permits_units_and_no_odcloud_units_does_not_error():
    r = _fake_row('테스트권')   # z['units'] 아예 없음, punits도 없음
    html = M.build_page(r, [r], '2026-07', '2026-07-24', punits=None)
    assert '<html' in html
    assert '앞으로 들어올 단지' not in html


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


# ---------------------------------------------------------------------------
# M4(deferred minor): 수도권 같은 롤업 존이 자체 permits.units는 없지만 subs(멤버
# 생활권)가 있을 때, punits를 subs 각각의 생활권 이름으로 조회해 sched/done을
# 합산하는 분기(build_page의 `if subs and not (zone_units.get('sched') or ...)`)
# — 지금까지 테스트가 없었다.
# ---------------------------------------------------------------------------

def test_build_page_rollup_aggregates_subs_units_when_own_missing():
    sub1 = _fake_row('서울권')
    sub2 = _fake_row('인천권')
    rollup = _fake_row('수도권', subs=[sub1, sub2])
    # punits는 롤업 이름('수도권')이 아니라 서브존 이름으로만 키가 있다.
    punits = {
        '서울권': {'sched': [['서울단지', 100, '2027-01']], 'done': []},
        '인천권': {'sched': [], 'done': [['인천단지', 200, '2024-05']]},
    }
    html = M.build_page(rollup, [rollup, sub1, sub2], '2026-07', '2026-07-24', punits)
    assert '앞으로 들어올 단지' in html
    assert '최근 들어온 단지' in html
    assert '서울단지' in html and '2027.01 예정' in html
    assert '인천단지' in html and '2024.05 준공' in html


# ---------------------------------------------------------------------------
# 회귀 테스트(FINAL review C1 재발 방지): '주변과 비교하면'(near) 섹션이 비면
# near_html=''로 처리했는데, 44존 nav(zlist)와 /#score CTA가 그 안에 함께
# 있어서 같이 사라졌다 — 시도에 존이 하나뿐인 7곳(부산·대구·대전세종·광주·
# 울산·청주·제주권)이 5섹션+아웃바운드 /zone/ 링크 0짜리 고아 페이지가 됐다.
# 이제 nav/zlist/CTA는 near와 무관한 독립 섹션(항상 렌더)이고, near는 같은
# 시도 → 같은 region → 전국 순으로 최대 4곳을 채우는 3단 폴백을 쓴다.
# 전체 45장을 매번 생성하는 대신 대표 존 3곳(서울권·평택권·제주권) + 수도권
# 합계로 build_page를 직접 호출하되, 링크 검증은 그 결과를 실제로 파일에
# 쓰고 다시 읽은 내용(실제 생성물)으로 한다.
# ---------------------------------------------------------------------------

def _real_pages(tmp_path):
    adv, sts = M.load()
    rows = M.calc(adv, sts)
    cap = M.make_capital(rows)
    punits = (adv.get('permits') or {}).get('units') or {}
    prd = adv['livezone'].get('prd', '')
    today = datetime.date.today().isoformat()
    by_name = {row['z']['z']: row for row in rows}
    picks = [by_name[nm] for nm in ('서울권', '평택권', '제주권') if nm in by_name]
    if cap:
        picks.append(cap)
    out = {}
    for row in picks:
        nm = row['z']['z']
        html = M.build_page(row, rows, prd, today, punits)
        d = tmp_path / 'zone' / nm
        d.mkdir(parents=True, exist_ok=True)
        fp = d / 'index.html'
        fp.write_text(html, encoding='utf-8')
        out[nm] = fp.read_text(encoding='utf-8')
    return out


def test_regression_representative_zones_have_required_h2_sections(tmp_path):
    pages = _real_pages(tmp_path)
    assert pages, "대표 존을 하나도 못 찾았다 — data.js 생활권 이름이 바뀌었는지 확인할 것"
    for nm, html in pages.items():
        assert '왜 이 판정인가' in html, nm
        assert '언제 들어오나' in html, nm
        assert '이 숫자의 한계' in html, nm


def test_regression_outbound_zone_links_at_least_40(tmp_path):
    # C1 핵심 가드: nav가 near와 분리돼 항상 렌더되므로, 시도에 존이 하나뿐인
    # 7곳을 포함해 모든 페이지가 44개 생활권 전체로 나가는 링크를 가져야 한다.
    pages = _real_pages(tmp_path)
    for nm, html in pages.items():
        n_links = html.count('href="/zone/')
        assert n_links >= 40, '%s: /zone/ 링크 %d개뿐 (>=40 기대)' % (nm, n_links)


def test_regression_near_section_absent_when_truly_empty():
    # 근처 비교 카드가 진짜로 하나도 없는(같은 시도·region·전국 어디에도 다른
    # 존이 없는) 극단적 단일-존 상황에서는 '주변과 비교하면' 섹션이 나가면
    # 안 된다 — 반면 nav(다른 생활권도 보기)는 이런 상황에서도 항상 남아야 한다.
    r = _fake_row('테스트권')
    html = M.build_page(r, [r], '2026-07', '2026-07-24', punits=None)
    assert '주변과 비교하면' not in html
    assert '다른 생활권도 보기' in html


def test_regression_near_section_present_with_real_data(tmp_path):
    # 실제 데이터에서는 3단계 폴백(같은 시도 → 같은 region → 전국) 덕에
    # region에도 혼자인 극단 케이스(제주권)까지 카드가 채워져야 한다.
    pages = _real_pages(tmp_path)
    for nm, html in pages.items():
        assert '주변과 비교하면' in html, '%s: 주변 카드가 비었다' % nm


def test_render_units_2sec_dedupes_same_project():
    """같은 단지가 동·블록별 별도 PK로 두 번 오면(대구금호워터폴리스 D2블록 사례)
    화면에선 한 줄로 접는다."""
    units = {'sched': [
        ['대구금호워터폴리스 D2블록', 1334, '2028-10'],
        ['대구금호워터폴리스 D2블록', 1334, '2028-10'],   # 중복
        ['다른단지', 500, '2028-10'],
    ], 'done': []}
    html = M.render_units_2sec(units, TODAY)
    assert html.count('대구금호워터폴리스 D2블록</td>') == 1
    assert '세대 큰 순 2곳' in html


def test_render_units_2sec_total_is_labelled_as_list_sum():
    """합계는 쓰되 반드시 '목록 합계'로 라벨링한다(2026-08-02 사용자 요청).

    목록은 수집기 캡(시군구당 40)이 걸린 부분집합이라 존 전체 물량과 다르다.
    라벨을 떼고 그냥 'N세대'로 쓰면 '언제 들어오나' 차트의 총량과 나란히 놓였을
    때 버그로 읽힌다(2026-08-01 대구권 차트 55,693 vs 목록 15,020 보고).
    """
    units = {'sched': [['오산더샵', 400, '2027-03'], ['오산자이', 600, '2028-01']], 'done': []}
    html = M.render_units_2sec(units, TODAY)
    assert '목록 합계 1,000세대' in html
    assert '세대 큰 순 2곳' in html
    # 라벨 없는 맨 합계가 새어나가면 안 된다
    assert '· 1,000세대' not in html


def test_render_units_2sec_escapes_quotes_in_name():
    """단지명이 title="..." 속성에 들어가므로 따옴표를 이스케이프해야 한다 —
    HUB 원자료에 '일신 "에일린의 뜰" 아파트'가 실재(2026-08-01 리뷰 M3)."""
    ym = _ym_off(8) if '_ym_off' in globals() else '2027-03'
    units = {'sched': [['일신 "에일린의 뜰" 아파트', 300, ym]], 'done': []}
    html = M.render_units_2sec(units, TODAY)
    assert 'title="일신 &quot;에일린의 뜰&quot; 아파트"' in html
    # 속성이 조기 종료돼 깨진 마크업이 나오면 안 된다
    assert 'title="일신 "' not in html


# ---------------------------------------------------------------------------
# 미래 공급 신뢰감쇠 폐지 (2026-08-02) — 잠금
# ---------------------------------------------------------------------------

def test_conf_is_flat():
    """_conf는 지평선 전 구간에서 1.0이어야 한다.

    옛 감쇠(1-(k-1)/20)는 근거가 없었고 수요만 100%인 비대칭 탓에 순부족을
    구조적으로 부풀렸다(등급 12/44곳이 이 상수 하나에 좌우됐다). 되살리려면
    make_zone_pages._conf docstring의 반증 3건을 먼저 반박할 것.
    """
    for k in range(1, M.FUT_HORIZON + 1):
        assert M._conf(k) == 1.0, 'k=%d에서 감쇠가 되살아났다' % k


def test_running_shortage_counts_future_supply_at_face_value():
    """감쇠가 없으므로 미래 공급은 액면 그대로 순부족에서 빠진다."""
    cur = M.ANCHOR                      # 과거 재고 루프를 1분기로 짧게
    sched = {M._qkey(cur + k): 100 for k in range(1, M.FUT_HORIZON + 1)}
    r = M.running_shortage({}, sched, {}, refq=100, cur_q=cur,
                           weight_demand=False, full=True)
    assert r['supplyw'] == 100 * M.FUT_HORIZON   # 가중 없이 전량
    assert r['demand'] == 100 * M.FUT_HORIZON
    assert r['tot'] == r['demand'] - r['supplyw'] - r['inow']


def test_zone_page_copy_has_no_decay_claim():
    """화면 카피가 모델에 없는 감쇠를 말하면 안 된다."""
    import io
    src = io.open(M.__file__.replace('.pyc', '.py'), encoding='utf-8').read()
    body = src.split('def _conf', 1)[1].split('\n    """', 2)[-1]  # docstring 제외
    assert '먼 미래는 낮춰 반영' not in body
    assert '먼 미래를 낮춰 반영하면' not in body

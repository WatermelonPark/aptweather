# -*- coding: utf-8 -*-
"""Task 6: calc() dC 시군구 실측 교체 + forward 4년(분기 배타분할) 단위 테스트.

네트워크·실제 data.js 접근 없음: 전부 작은 인메모리 ADV/STATS 픽스처.
"""
import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_zone_pages as M


def _cur_q(today=None):
    today = today or datetime.date.today()
    return today.year * 4 + (today.month - 1) // 3


def _qlabel(idx):
    return '%dQ%d' % (idx // 4, idx % 4 + 1)


# ---------------------------------------------------------------------------
# forward 창 exclusive partition: near=byq(<=2년), far=fwd_far(2~4년), 겹침 없음
# ---------------------------------------------------------------------------

def test_fut_window_hq_is_fixed_at_4_years():
    LZ = {'zones': [{'z': '존A', 'byq': {}}]}
    NEARQ, FARQ, HQ, cur_q = M.fut_window(LZ)
    assert HQ == 16 == M.FUT_FAR
    assert len(FARQ) == M.FUT_FAR - M.FUT_NEAR == 8


def test_zone_fut_supply_near_from_byq_far_from_fwd_far_no_double_count():
    today = datetime.date.today()
    cur_q = _cur_q(today)
    near_q = _qlabel(cur_q + 1)          # ≤2년 창 안(첫 미래 분기)
    far_q = _qlabel(cur_q + 9)           # 2~4년 창 안(첫 원거리 분기)
    z = {'z': '존A', 'byq': {near_q: 100}}
    LZ = {'zones': [z]}
    # fwd_far에 근분기 라벨로도 하나 심어둔다 — near는 byq만 보므로 이 값은
    # fsup에 반영되면 안 된다(이중집계/오분류 검증).
    P = {'fwd_far': {'존A': {far_q: 50, near_q: 999}}}
    NEARQ, FARQ, HQ, cq = M.fut_window(LZ, today)
    assert near_q in NEARQ
    assert far_q in FARQ
    assert near_q not in FARQ            # 배타분할: 근/원 라벨이 겹치면 안 됨
    fsup, H = M.zone_fut_supply(z, P, NEARQ, FARQ, HQ)
    assert H == 16
    assert fsup == 150                   # 100(near·byq) + 50(far·fwd_far) — 999는 제외


def test_zone_fut_supply_ignores_fwd_far_when_zone_absent():
    today = datetime.date.today()
    cur_q = _cur_q(today)
    near_q = _qlabel(cur_q + 1)
    z = {'z': '존B', 'byq': {near_q: 40}}
    LZ = {'zones': [z]}
    P = {'fwd_far': {}}                  # 이 존은 착공파생 데이터가 아직 없음
    NEARQ, FARQ, HQ, cq = M.fut_window(LZ, today)
    fsup, H = M.zone_fut_supply(z, P, NEARQ, FARQ, HQ)
    assert fsup == 40                    # far 기여 0, near만 반영


# ---------------------------------------------------------------------------
# calc_dc: meas(건축HUB 실측) 경로 vs fallback(시도 인구배분) 경로
# ---------------------------------------------------------------------------

def test_calc_dc_meas_path_uses_zone_measured_permits():
    P = {'meas': {'존A': 900}, 'regions': ['시도A'], 'ref': {'시도A': [5000, 1]}}
    ph = [{'v': [1000]}, {'v': [1200]}]   # meas가 있으면 이 값은 아예 안 쓰임
    dC, plo, pv, src = M.calc_dc(P, ph, '시도A', {'z': '존A'}, refq=1000, share=0.5, dY=400)
    # plo(base) = refq*4*share = 1000*4*0.5 = 2000
    # pv = perm_z - dY*share = 900 - 400*0.5 = 700
    # dC = plo - pv = 2000 - 700 = 1300
    assert src == 'meas'
    assert plo == 2000
    assert pv == 700
    assert dC == 1300


def test_calc_dc_fallback_path_when_no_measured_zone():
    P = {'meas': {}, 'regions': ['시도A'], 'ref': {'시도A': [5000, 1]}}
    ph = [{'v': [1000]}, {'v': [1200]}]   # sido 인허가 실적 2개 반기/분기 합
    dC, plo, pv, src = M.calc_dc(P, ph, '시도A', {'z': '존B'}, refq=1000, share=0.5, dY=400)
    # pv_sido = 1000+1200 = 2200, plo_sido = 5000
    # dC = (5000 - (2200-400)) * 0.5 = (5000-1800)*0.5 = 1600
    # plo(disp) = 5000*0.5 = 2500, pv(disp) = (2200-400)*0.5 = 900
    assert src == 'fallback'
    assert plo == 2500
    assert pv == 900
    assert dC == 1600


def test_calc_dc_fallback_path_skipped_when_any_value_missing():
    P = {'meas': {}, 'regions': ['시도A'], 'ref': {'시도A': [5000, 1]}}
    ph = [{'v': [1000]}, {'v': [None]}]   # 최근 반기 값 결측 -> 폴백도 계산 불가
    dC, plo, pv, src = M.calc_dc(P, ph, '시도A', {'z': '존B'}, refq=1000, share=0.5, dY=400)
    assert src is None
    assert plo is None and pv is None
    assert dC == 0


def test_calc_dc_no_meas_and_region_unknown_yields_zero():
    P = {'meas': {}, 'regions': [], 'ref': {}}
    dC, plo, pv, src = M.calc_dc(P, [], '시도Z', {'z': '존Z'}, refq=1000, share=0.5, dY=0)
    assert (dC, plo, pv, src) == (0, None, None, None)


# ---------------------------------------------------------------------------
# calc() 통합: 작은 ADV/STATS로 전체 파이프라인이 need=refq*16*share, dC(meas
# 경로) 를 동시에 정확히 산출하는지 확인 — 회귀 없이 dC 교체·forward 4년이
# 함께 맞물려 동작함을 검증.
# ---------------------------------------------------------------------------

def _tiny_adv_sts(byq, fwd_far, meas):
    zone = {'z': '존A', 'region': '기타', 'psido': '테스트시', 'pop': 10000, 'byq': byq}
    adv = {
        'livezone': {'zones': [zone], 'sidopop': {'테스트시': 20000}},
        'occupancy': {
            'regions': ['테스트시'], 'rows': [], 'band': {}, 'ref': {'테스트시': 1000},
        },
        'permits': {
            'regions': ['테스트시'], 'ref': {'테스트시': [5000, 1]}, 'rows': [],
            'meas': meas, 'fwd_far': fwd_far,
        },
        'bubble': {},
    }
    sts = {
        '전세가율': {'series': {}},
        '주택멸실': {'series': {'테스트시': [400]}},
    }
    return adv, sts


def test_fut_window_near_far_overlap_is_deduped_favor_near():
    """NEARQ(odcloud 실측 라벨)와 FARQ(산술 생성 라벨)가 우연히 같은 분기 문자열로
    겹치는 경우(원자료 결측으로 FUTQ가 예상보다 먼 분기까지 뻗을 때) 겹친 라벨은
    near 쪽에만 남고 far에서는 빠져야 한다 — 이중집계 방지 가드가 구조적으로
    동작하는지 확인."""
    today = datetime.date.today()
    cur_q = _cur_q(today)
    overlap_q = _qlabel(cur_q + 9)   # FARQ가 산술로 만드는 첫 라벨(offset=FUT_NEAR)과 동일
    LZ = {'zones': [{'z': '존A', 'byq': {overlap_q: 500}}]}
    NEARQ, FARQ, HQ, cq = M.fut_window(LZ, today)
    assert overlap_q in NEARQ
    assert overlap_q not in FARQ         # 가드가 far 쪽에서 중복 라벨을 제거함

    # fwd_far에도 같은 라벨로 값이 있어도(공급원이 다름) 가드 덕에 near만 반영된다.
    P = {'fwd_far': {'존A': {overlap_q: 999}}}
    zz = LZ['zones'][0]
    fsup, H = M.zone_fut_supply(zz, P, NEARQ, FARQ, HQ)
    assert fsup == 500                   # 999(far)는 FARQ에서 빠졌으니 합산 안 됨


# ---------------------------------------------------------------------------
# make_capital: 수도권 rollup의 dcsrc — 혼합 출처를 단일 실측처럼 주장하면 안 됨
# ---------------------------------------------------------------------------

def _cap_row(z, dcsrc, tot=1000):
    return dict(
        z={'z': z, 'region': '수도권', 'pop': 1000, 'supply': 500,
           'sgg': [], 'q0': '2026-01', 'q1': '2026-12', 'span': 1},
        ps='수도권', share=0.1, need=1000, dA=100, dB=10, dC=50, tot=tot, fsup=900, fq=16,
        flag=None, lo=None, hi=None, loan=None, pv=700, plo=800, dcsrc=dcsrc, dY=0, refq=100, band=None,
    )


def test_make_capital_mixed_sources_yields_dcsrc_mixed():
    rows = [_cap_row('성남권', 'meas', tot=2000), _cap_row('오산권', 'meas', tot=1500),
            _cap_row('안양권', 'fallback', tot=1000)]
    agg = M.make_capital(rows)
    assert agg['dcsrc'] == 'mixed'


def test_make_capital_all_fallback_stays_fallback():
    rows = [_cap_row('안양권', 'fallback', tot=1000), _cap_row('부천권', 'fallback', tot=900)]
    agg = M.make_capital(rows)
    assert agg['dcsrc'] == 'fallback'


def test_make_capital_all_meas_stays_meas():
    rows = [_cap_row('성남권', 'meas', tot=2000), _cap_row('오산권', 'meas', tot=1500)]
    agg = M.make_capital(rows)
    assert agg['dcsrc'] == 'meas'


def test_calc_integration_need_uses_16q_and_dc_uses_meas_when_present():
    today = datetime.date.today()
    cur_q = _cur_q(today)
    near_q = _qlabel(cur_q + 1)
    far_q = _qlabel(cur_q + 9)
    byq = {near_q: 100}
    fwd_far = {'존A': {far_q: 50}}
    meas = {'존A': 900}
    adv, sts = _tiny_adv_sts(byq, fwd_far, meas)
    rows = M.calc(adv, sts)
    assert len(rows) == 1
    r = rows[0]
    share = 10000 / 20000  # 0.5
    assert r['fq'] == 16
    assert r['need'] == 1000 * 16 * share
    assert r['fsup'] == 150
    assert r['dA'] == r['need'] - 150
    assert r['dcsrc'] == 'meas'
    assert r['dC'] == 1300   # 같은 값을 calc_dc 단위 테스트에서도 검증함
    assert r['tot'] == M.W[0] * r['dA'] + M.W[1] * r['dC'] + M.W[2] * r['dB']

# -*- coding: utf-8 -*-
"""판정기준 대표 결정(2026-09-13) — 세 줄·인허가 참고 신호·추정 표기.

지키는 것:
① 인허가는 누계를 풀어 월별로 쓰고, 24개월 연평균 × 지역 착공 전환율로 잰다.
② 인허가는 판정을 움직이지 않는다(참고로만).
③ 세 번째 줄은 경보가 아니라 참고 형태다 — 빨간 경고 박스가 돌아오지 않는다.
④ 추정 표기 목록은 EST에서 파생한다.

⚠️ 생성된 페이지를 라이브 데이터로 단정하지 않는다(배치는 pytest를 페이지 생성보다
먼저 돌린다). 렌더러는 합성 입력으로, 데이터는 저장된 값끼리의 일치로 본다.
"""
import copy
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sido_zones as SZ  # noqa: E402
import make_sido_pages as P  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')


def _data():
    src = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    st = json.loads(re.search(r'const STATS\s*=\s*(\{.*?\});?\s*(?:/\*|const |$)', src, re.S).group(1))
    adv = json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S).group(1))
    return st, adv


def _stats(dates, permit_cum, starts):
    return {'인허가': {'dates': dates, 'series': {'X': permit_cum}},
            '착공': {'dates': dates, 'series': {'X': starts}}}


def test_permit_is_de_cumulated_before_use():
    dates = ['2024.01', '2024.02', '2024.03']
    m = SZ.permit_monthly(_stats(dates, [10, 25, 45], [0, 0, 0]), 'X')
    assert m == {'2024.01': 10, '2024.02': 15, '2024.03': 20}, '누계를 풀지 않았다'


def test_conversion_is_same_year_starts_over_permits():
    dates = ['%d.%02d' % (y, mm) for y in (2012, 2013) for mm in range(1, 13)]
    cum = [100.0 * mm for mm in range(1, 13)] * 2           # 해마다 12월 누계 1,200
    starts = [60.0] * 24                                     # 해마다 720
    conv = SZ.permit_start_conv(_stats(dates, cum, starts), 'X')
    assert abs(conv - 0.6) < 1e-9


def test_signal_uses_24_month_average_times_conversion():
    dates = ['%d.%02d' % (y, mm) for y in (2012, 2013) for mm in range(1, 13)]
    cum = [100.0 * mm for mm in range(1, 13)] * 2           # 월 100호
    starts = [50.0] * 24                                     # 전환율 0.5
    sig = SZ.permit_signal(_stats(dates, cum, starts), 'X', ref_q=150)
    # 연평균 1,200 × 0.5 ÷ (150 × 4) = 1.0
    assert abs(sig['pbr'] - 1.0) < 1e-9
    assert abs(sig['pdec'] - 1.0 / 12) < 1e-9


def test_permits_do_not_move_the_verdict():
    """인허가를 10배로 부풀려도 판정·비율은 그대로여야 한다 — 참고로만 쓴다."""
    st, _ = _data()
    base = {z['z']: (z['grade'], z['ratio']) for z in SZ.calc(st)['zones']}
    st2 = copy.deepcopy(st)
    for r, v in st2['인허가']['series'].items():
        st2['인허가']['series'][r] = [None if x is None else x * 10 for x in v]
    after = SZ.calc(st2)['zones']
    assert {z['z']: (z['grade'], z['ratio']) for z in after} == base, '인허가가 판정에 샜다'
    assert any(z['pbr'] for z in after), '신호가 계산되지 않았다 — 시험이 헛돈다'


def test_warning_follows_the_new_signal_not_the_raw_12_months():
    _, adv = _data()
    for z in adv['sido']['zones']:
        if z.get('pbr') is not None:
            assert z['pwarn'] == (z['pbr'] < SZ.PWARN_CUT), z['z']


def test_estimate_flag_is_derived_from_the_model():
    _, adv = _data()
    for z in adv['sido']['zones']:
        assert z['est'] == (z['z'] in SZ.EST), z['z']
        assert bool(z['split']['est_note']) == z['est'], '%s 추정 표기가 est와 다르다' % z['z']
    src = io.open(os.path.join(ROOT, 'tools', 'make_sido_pages.py'), encoding='utf-8').read()
    assert not re.search(r"\(\s*'서울'\s*,\s*'경기'", src), '생성기에 추정 지역 목록을 손으로 적었다'


def test_stored_split_matches_the_function():
    st, adv = _data()
    fresh = {z['z']: z['split'] for z in SZ.calc(st)['zones']}
    stored = {z['z']: z['split'] for z in adv['sido']['zones']}
    norm = lambda d: json.loads(json.dumps(d, ensure_ascii=False))
    assert norm(fresh) == norm(stored), '저장된 세 줄이 산식과 다르다 — --seed-sido를 다시 돌릴 것'


def _sp(thin, est=True, dec=True):
    # 지난 4년 재고 −120 ÷ (분기 250 × 16) = −3%, 앞으로 3년 880 ÷ 1,000 = 88%
    return SZ.split_text(inow=-120, fut=880, need=1000, ref=250,
                         sig={'pbr': 0.9 if thin else 1.26, 'pdec': 0.49 if dec else None, 'pconv': 0.87},
                         est=est)


def test_reference_line_looks_like_a_reference_not_an_alarm():
    html = P.split_block(_sp(thin=True))
    assert '<em class="zchip">참고</em>' in html
    assert '참고로만 봅니다' in html and '판정에는 넣지 않습니다' in html
    assert '12월 한 달' in html
    assert 'zwarn' not in html and '⚠' not in html, '인허가를 경보처럼 보여준다'
    assert '<strong>' in html, '필요량에 못 미칠 때 참고 줄 안에서 강조하지 않는다'
    assert '<strong>' not in P.split_block(_sp(thin=False))


def test_old_red_permit_box_is_gone():
    src = io.open(os.path.join(ROOT, 'tools', 'make_sido_pages.py'), encoding='utf-8').read()
    assert '3년 너머는 더 얇습니다' not in src


def test_estimate_note_only_where_estimated():
    assert '<em class="zchip">추정</em>' in P.split_block(_sp(thin=False, est=True))
    assert '추정' not in P.split_block(_sp(thin=False, est=False))


def test_three_lines_state_numbers_only():
    sp = _sp(thin=False)
    (l1, t1), (l2, t2) = sp['rows']
    assert '3%' in t1 and '덜 지었습니다' in t1
    assert '88%' in t2
    for word in ('충분', '넉넉', '크게 모자람'):
        assert word not in json.dumps(sp, ensure_ascii=False), '단계 말이 들어갔다'

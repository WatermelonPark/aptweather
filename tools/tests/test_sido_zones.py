# -*- coding: utf-8 -*-
"""시도 공급 지표 산식 — sido_zones.calc의 계약을 못 박는다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sido_zones as M


def _months(y0, m0, n):
    out = []
    y, m = y0, m0
    for _ in range(n):
        out.append('%04d.%02d' % (y, m))
        m += 1
        if m > 12:
            y += 1; m = 1
    return out


def _stats(done, start, regions=('전국', '서울'), y0=2010, m0=1, demol=None):
    """월별 시리즈를 만든다. done/start는 지역별 월 값 리스트."""
    n = len(done[regions[0]])
    dates = _months(y0, m0, n)
    mk = lambda src: {'dates': dates, 'series': {r: list(src[r]) for r in regions}}
    s = {'준공': mk(done), '착공': mk(start)}
    if demol:
        s['아파트멸실'] = {'dates': [str(y0)], 'series': {r: [demol.get(r, 0)] for r in regions}}
    return s


def test_none은_결측이_아니라_0이다():
    """KOSIS가 값 0을 '-'로 준다 — 건너뛰면 그 분기가 사라져 창이 어긋난다."""
    q = M._series({'준공': {'dates': ['2020.01', '2020.02', '2020.03'],
                            'series': {'서울': [100, None, 50]}}}, '준공', '서울')
    i = M.qidx(2020, 1)
    assert q[i] == (150, 3), 'None을 0으로 세고 월 수는 3으로 잡아야 한다'


def test_덜_찬_분기는_실적에서_빠진다():
    """4·5월만 있는 분기를 실적으로 쓰면 그 지역만 공급이 낮게 잡힌다."""
    s = {'준공': {'dates': ['2020.04', '2020.05'], 'series': {'서울': [10, 20]}}}
    assert M.quarterly(s, '준공', '서울') == {}
    assert M.quarterly(s, '준공', '서울', full_only=False) == {M.qidx(2020, 2): 30}


def test_적정물량_합이_맞는다():
    loc = sum(v for k, v in M.REF_Q.items()
              if k not in M.AGG and k not in ('서울', '경기', '인천'))
    assert M.REF_Q['서울'] + M.REF_Q['경기'] + M.REF_Q['인천'] == M.REF_Q['수도권'] == 50000
    assert loc == M.REF_Q['지방'] == 45000
    assert M.REF_Q['수도권'] + M.REF_Q['지방'] == M.REF_Q['전국'] == 95000


def test_미래공급은_3년전_착공에_전환율을_곱한다():
    # 2011.01 ~ 2026.12 = 192개월. 준공은 2026.06까지만 채워 L=2026Q2를 만든다.
    n = (2026 - 2011) * 12 + 12
    done = {'전국': [0] * n, '서울': [0] * n}
    start = {'전국': [0] * n, '서울': [0] * n}
    # 착공 2023Q3(=2023.07~09)에 서울 300 → 준공 2026Q3에 300*0.958이 잡혀야 한다
    for k, ym in enumerate(_months(2011, 1, n)):
        if ym in ('2023.07', '2023.08', '2023.09'):
            start['서울'][k] = 100
            start['전국'][k] = 100
    # 준공·착공 모두 2026.06까지만 유효하게 자른다
    cut = (2026 - 2011) * 12 + 6
    s = _stats({k: v[:cut] for k, v in done.items()},
               {k: v[:cut] for k, v in start.items()}, y0=2011, m0=1)
    r = M.calc(s)
    seoul = [z for z in r['zones'] if z['z'] == '서울'][0]
    assert r['L'] == '2026Q2' and r['S'] == '2026Q2'
    assert r['H'] == 12, '착공 끝 + 12분기 − 준공 끝 = 12분기(3년)'
    assert seoul['fut'] == round(300 * M.CONV)


def test_재고창은_오늘이_아니라_준공_마지막_분기_기준():
    """오늘을 기준점으로 삼으면 아직 안 끝난 분기의 준공 0이 들어가 재고가 깎인다."""
    cut = (2026 - 2011) * 12 + 6
    z = [0] * cut
    s = _stats({'전국': list(z), '서울': list(z)},
               {'전국': list(z), '서울': list(z)}, y0=2011, m0=1)
    r = M.calc(s)
    seoul = [x for x in r['zones'] if x['z'] == '서울'][0]
    # 준공 0, 멸실 0이면 재고는 정확히 −(적정 × 16분기)
    assert seoul['inow'] == -M.REF_Q['서울'] * M.BACKLOG_WINDOW
    # 미래공급 0이면 순부족은 적정 × H − 0 − 재고
    assert seoul['tot'] == M.REF_Q['서울'] * r['H'] - seoul['inow']


def test_등급_경계():
    assert M.grade(1.5) == 'g4' and M.grade(1.4999) == 'g3'
    assert M.grade(1.0) == 'g3' and M.grade(0.9999) == 'g2'
    assert M.grade(0.5) == 'g2' and M.grade(0.4999) == 'g1'
    assert M.grade(-0.5) == 'g1' and M.grade(-0.5001) == 'g0'


def test_순서는_등급_먼저_그다음_순부족():
    rows = [
        {'z': 'A', 'grade': 'g2', 'tot': 100, 'agg': False},
        {'z': 'B', 'grade': 'g3', 'tot': 10, 'agg': False},
        {'z': 'C', 'grade': 'g2', 'tot': 200, 'agg': False},
        {'z': '전국', 'grade': 'g4', 'tot': 999, 'agg': True},
    ]
    assert [x['z'] for x in M.zone_order(rows)] == ['B', 'C', 'A'], '집계는 빠지고 등급이 먼저'


def test_기간_표기():
    assert M.qlabel(M.qidx(2017, 4)) == '17Q4'
    assert M.qlabel(M.qidx(2017, 4), 'y') == '2017'
    assert M.mlabel(2017, 1) == '17.1'


def test_실데이터가_있으면_모든_지역이_나온다():
    try:
        s = M._load_stats()
    except Exception:
        return   # 데이터 파일 없는 환경(CI 초기)에서는 건너뛴다
    r = M.calc(s)
    got = {z['z'] for z in r['zones']}
    assert got == set(M.ORDER), '빠진 지역: %s' % (set(M.ORDER) - got)
    assert r['H'] > 0

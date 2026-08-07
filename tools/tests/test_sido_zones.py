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
    assert M.grade(0.0) == "g1" and M.grade(-0.0001) == "g0"


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
    # ⚠️ 이름 집합과 H만 보면 손상된 데이터가 그대로 통과한다 — 감사에서 세 가지
    # 손상 주입이 전부 PASS했다(2026-08-07). 프로젝트가 핵심 불변식으로 못 박은
    # '전국 = Σ17시도'를 **calc 출력**에 대해서도 본다.
    assert r['missing'] == [], '실데이터에 빠진 지역이 있다: %s' % r['missing']
    assert r['agg_warn'] == [], '집계 항등식이 깨졌다: %s' % r['agg_warn']
    byz = {z['z']: z for z in r['zones']}
    cap = sum(byz[z]['inow'] for z in ('서울', '경기', '인천'))
    assert abs(cap - byz['수도권']['inow']) <= 3, '수도권 ≠ 서울+경기+인천'
    assert abs((byz['전국']['inow'] - byz['수도권']['inow']) - byz['지방']['inow']) <= 3


def test_미분양은_점수에_안_들어간다():
    """미분양은 결과값이라 재고에서 차감하면 부호가 반대고 이중계상된다.
    맥락으로만 싣는지 — 같은 통계를 넣고 빼도 tot가 흔들리지 않아야 한다."""
    cut = (2026 - 2011) * 12 + 6
    z = [0] * cut
    base = _stats({'전국': list(z), '서울': list(z)},
                  {'전국': list(z), '서울': list(z)}, y0=2011, m0=1)
    a = M.calc(base)
    with_un = dict(base)
    with_un['미분양'] = {'dates': ['2026.06'], 'series': {'전국': [9999], '서울': [9999]}}
    b = M.calc(with_un)
    ga = [x for x in a['zones'] if x['z'] == '서울'][0]
    gb = [x for x in b['zones'] if x['z'] == '서울'][0]
    assert ga['tot'] == gb['tot'] and ga['grade'] == gb['grade'], '미분양이 점수를 바꿨다'
    assert gb['unsold'] == 9999 and ga['unsold'] is None


def test_모순_표시는_부족_판정에만_붙는다():
    """공급 여유인데 미분양이 많은 건 모순이 아니라 일관이다(충남)."""
    cut = (2026 - 2011) * 12 + 6
    z = [0] * cut
    s = _stats({'전국': list(z), '서울': list(z)},
               {'전국': list(z), '서울': list(z)}, y0=2011, m0=1)
    ref = M.REF_Q['서울']
    s['미분양'] = {'dates': ['2026.06'], 'series': {'전국': [0], '서울': [ref]}}
    row = [x for x in M.calc(s)['zones'] if x['z'] == '서울'][0]
    assert row['grade'] in ('g4', 'g3', 'g2') and row['um'] == 1.0
    assert row['uwarn'] is True, '부족 + 미분양 1배면 모순 표시'
    s['미분양']['series']['서울'] = [ref - 1]
    row2 = [x for x in M.calc(s)['zones'] if x['z'] == '서울'][0]
    assert row2['uwarn'] is False, '1배 미만이면 표시하지 않는다'


def test_전_기간_None인_지역은_missing으로_빠진다():
    """quarterly()가 비어 있지 않다는 것만으로는 부족하다 — 전 기간 None이어도
    분기 키는 생기므로 그 지역이 준공 0 = 완전 공급절벽으로 1위가 된다."""
    cut = (2026 - 2011) * 12 + 6
    z = [0] * cut
    s = _stats({'전국': list(z), '서울': list(z)},
               {'전국': list(z), '서울': list(z)}, y0=2011, m0=1)
    assert '서울' not in M.calc(s)['missing']
    s['준공']['series']['서울'] = [None] * cut
    r = M.calc(s)
    assert '서울' in r['missing'], '전 기간 None을 못 잡았다'
    assert not [x for x in r['zones'] if x['z'] == '서울']


def _full_stats(per_sido=10000):
    """20개 지역이 전부 있고 전국 = Σ시도가 성립하는 합성 STATS.

    집계 항등식 검사를 시험하려면 애초에 항등식이 성립하는 fixture가 있어야 한다.
    """
    cut = (2026 - 2011) * 12 + 6
    sido = [z for z in M.ORDER if z not in M.AGG]
    cap = ('서울', '경기', '인천')
    def mk(v):
        d = {z: [v] * cut for z in sido}
        d['전국'] = [v * len(sido)] * cut
        d['수도권'] = [v * len(cap)] * cut
        d['지방'] = [v * (len(sido) - len(cap))] * cut
        return d
    return _stats(mk(per_sido), mk(0), regions=tuple(M.ORDER), y0=2011, m0=1)


def test_부분_결측은_집계_항등식_경고로_드러난다():
    """한 지역의 특정 월만 None이면 missing에 안 걸리지만 Σ시도 ≠ 전국이 된다."""
    s = _full_stats()
    assert M.calc(s)['agg_warn'] == [], '정상 fixture에서는 항등식이 성립해야 한다'
    # 허용오차가 |전국|의 0.1%라, 결측분이 그보다 커야 경고가 뜬다.
    # per_sido=10,000이면 3개월 결측 = 30,000 > 6,640(0.1%)이다.
    s['준공']['series']['경기'][-3:] = [None, None, None]
    r = M.calc(s)
    assert r['missing'] == [], '부분 결측은 missing이 아니다'
    assert r['agg_warn'], '집계 항등식 경고가 안 떴다'
    assert any('inow' in w for w in r['agg_warn'])


def test_멸실은_분기의_연도에_맞춘다():
    """최신 1개 연도를 창 전체에 쓰면 창 안의 실측을 버린다."""
    cut = (2026 - 2011) * 12 + 6
    z = [0] * cut
    s = _stats({'전국': list(z), '서울': list(z)},
               {'전국': list(z), '서울': list(z)}, y0=2011, m0=1)
    s['아파트멸실'] = {'dates': ['2023', '2024'],
                    'series': {'전국': [0, 0], '서울': [40000, 0]}}
    by = M.demol_q(s, '서울')
    assert by == {2023: 10000.0, 2024: 0.0}
    assert M.demol_of(by, 2023) == 10000.0, '그 해 값을 써야 한다'
    assert M.demol_of(by, 2026) == 0.0, '창 밖은 가장 가까운 해로 채운다'
    row = [x for x in M.calc(s)['zones'] if x['z'] == '서울'][0]
    # 창 2022Q3~2026Q2 = 16분기: 2022(2) 2023(4) 2024(4) 2025(4) 2026(2).
    # 2022는 가장 가까운 2023 값(10,000), 2025·2026은 2024 값(0)으로 채운다.
    # → 2×10,000 + 4×10,000 = 60,000이 재고에서 빠진다.
    assert row['inow'] == -M.REF_Q['서울'] * M.BACKLOG_WINDOW - 60000

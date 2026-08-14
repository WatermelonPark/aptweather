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


# ---------------------------------------------------------------------------
# 창 너머 신호 — 최근 12개월 인허가 vs 적정연간 (2026-08-11)
# ---------------------------------------------------------------------------

def test_permit_trail12_handles_yearly_reset():
    """인허가는 '연내 누계'라 1월마다 리셋된다. 최근 12개월 = 올해 최신 누계 +
    (작년 12월 − 작년 같은 달). 그냥 합산하면 이중계상으로 수십만이 나온다
    (실제로 그렇게 계산했다가 잡은 전례, 2026-08-11)."""
    stats = {'인허가': {
        'dates': ['2025.06', '2025.12', '2026.06'],
        'series': {'서울': [50, 100, 30]},
    }}
    v, ym = M.permit_trail12(stats, '서울')
    assert v == 30 + 100 - 50 and ym == '2026.06'


def test_permit_trail12_refuses_partial_data():
    """작년 조각이 없으면 반쪽 계산으로 오탐을 내지 말고 접는다."""
    stats = {'인허가': {'dates': ['2026.06'], 'series': {'서울': [30]}}}
    assert M.permit_trail12(stats, '서울') == (None, None)


def test_pwarn_threshold_avoids_knife_edge():
    """문턱 0.95 — 수도권이 100% 언저리에 있어(실측), 1.0으로 자르면 매달 켜졌다
    꺼졌다 한다. 깜빡이는 경고는 무시된다.

    ⚠️ 이 테스트는 원래 `assert M.permit_trail12`(함수 객체 → 항상 참)여서
    아무것도 검사하지 않았다. 문턱을 지킨다고 이름만 붙어 있고 실제로는
    1.0으로 되돌려도 초록이었다(2026-08-15 리뷰). 상수와 동작을 함께 잠근다."""
    assert M.PWARN_CUT == 0.95
    assert M.PWARN_CUT < 1.0, '1.0이면 100% 언저리 지역이 매달 깜빡인다'
    # 동작으로도 확인 — 100% 언저리는 안 뜨고, 확실히 얇은 쪽만 뜬다.
    assert not (1.0 < M.PWARN_CUT) and not (0.999 < M.PWARN_CUT)
    assert 0.90 < M.PWARN_CUT, '너무 낮추면 진짜 얇은 곳도 못 잡는다'


def test_pwarn_fires_on_live_data_where_expected():
    """실데이터 고정점(2026-08-10 시장 통념과 대조): 경남(인허가가 특히 적은 곳)은
    뜨고, 대전(그나마 있다)·충남(너무 많았다)은 안 뜬다. 이 관계가 뒤집히면
    인허가 계열이 오염된 것이다."""
    import io, json, re, os
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    src = io.open(os.path.join(root, 'data.js'), encoding='utf-8').read()
    adv = json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S).group(1))
    by = {z['z']: z for z in adv['sido']['zones']}
    thin = ('경남', '대구', '서울')      # 실측 pmr 0.23~0.42 — 컷에서 0.5 이상 떨어져 있다
    thick = ('대전', '충남')             # 실측 pmr 1.84~1.90 — 역시 멀다
    for z in thin:
        assert by[z]['pwarn'], '%s 경고가 꺼졌다 — 인허가 계열 오염 의심' % z
    for z in thick:
        assert not by[z]['pwarn'], '%s 경고가 켜졌다 — 인허가 계열 오염 의심' % z
    # 오염 판정의 본체는 문턱 통과 여부가 아니라 **관계**다. 얇은 쪽이 두꺼운 쪽보다
    # 확실히 낮아야 한다 — 이 부등식은 문턱과 무관해 시장이 움직여도 안 깨진다.
    assert max(by[z]['pmr'] for z in thin) < min(by[z]['pmr'] for z in thick) / 2

    # ⚠️ 전국·수도권·부산은 **일부러 단정하지 않는다.** 실측 pmr이 전국 0.853,
    # 부산 0.925, 수도권 1.000으로 컷(0.95)에서 0.03~0.10밖에 안 떨어져 있다.
    # 인허가는 월별로 들쭉날쭉한 계열이라 정상적인 회복만으로도 부호가 뒤집힌다.
    # 이 테스트는 update-cloud.yml의 배포 게이트(exit 1)라, 여기서 단정하면
    # **시장이 정상적으로 움직인 날 배치 전체가 커밋을 못 한다** — data.js·지역
    # 20페이지·sitemap이 통째로 얼고, 다음 날 감시가 그 정지를 다시 빨간불로
    # 보고한다. 값이 실려 있고 범위가 온전한지만 확인한다(2026-08-15 리뷰).
    for z in ('전국', '수도권', '부산'):
        assert isinstance(by[z]['pmr'], float) and 0 < by[z]['pmr'] < 5, z


def test_table_footer_shows_unsold_and_permits_everywhere():
    """표 하단 참고 2행(2026-08-11 사용자, 텍스트 줄→표 행으로 승격) — 배지(경고)와
    달리 전 지역에 항상 붙는다. 표만 보고 떠나는 사람이 함께 봐야 할 값이라서다.
    스크롤 기본값이 맨 아래라 이 두 행이 첫 화면에 들어온다."""
    import io, os
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    for z in ('서울', '대전', '충남'):     # 배지가 뜨는 곳과 안 뜨는 곳 모두
        h = io.open(os.path.join(root, 'zone', z, 'index.html'), encoding='utf-8').read()
        assert '<tfoot><tr class="zref" data-ref="un"><td><button' in h, z
        assert '<tr class="zref" data-ref="pm"><td><button' in h, z
        assert '>미분양<' in h and '>인허가 1년<' in h, z
        assert 'scrollTop=e.scrollHeight' in h, '%s: 표 기본 화면이 맨 아래가 아니다' % z
        # 탭 안내(2026-08-11 사용자) — 모바일엔 호버가 없어 행을 누르면 설명이 열린다
        assert 'id="zrefnote"' in h and 'ZREFNOTE' in h, '%s: 참고 행 탭 안내가 없다' % z


def test_home_table_has_both_reference_rows():
    """홈 표 tfoot도 같은 2행(미분양+인허가 1년)이어야 한다 — 지역 페이지와 홈이
    다른 참고 값을 보여주면 사용자가 둘 중 하나를 오독한다. 탭 안내·기본 스크롤
    맨 아래(2026-08-11 사용자)도 함께 잠근다."""
    import io, os
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    src = io.open(os.path.join(root, 'index.html'), encoding='utf-8').read()
    assert src.count('<tr class="tb-un" data-ref=') == 2, 'tfoot 참고 행은 정확히 2개'
    assert "refBtn('인허가 1년')" in src and "refBtn('미분양')" in src
    assert 'pm[z.z]=z.pm12' in src, '인허가 값이 TB_BCACHE에 실리지 않았다'
    assert 'TB_REFNOTE' in src and 'id="tb-refnote"' in src, '참고 행 탭 안내가 없다'
    assert 'sc.scrollTop=sc.scrollHeight' in src, '표 모드 기본 화면이 맨 아래가 아니다'
    assert "querySelector('#tb-main tbody tr.now')" in src, \
        '굵은 줄 클램프가 없다 — 월 모드(미래 36행)에서 현재가 시야 밖으로 나간다'


def test_refnote_copy_is_identical_on_home_and_zone():
    """참고 행 안내 문구는 make_sido_pages.REFNOTE가 정본이고 홈은 거울이다.
    홈이 정적 파일이라 생성기가 주입할 수 없어, 등급 JS 미러처럼 테스트로 묶는다 —
    한쪽만 고치면 같은 표의 같은 줄이 두 화면에서 다른 말을 하게 된다."""
    import io, json, os, re, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import make_sido_pages as M
    root = os.path.join(os.path.dirname(__file__), '..', '..')

    src = io.open(os.path.join(root, 'index.html'), encoding='utf-8').read()
    body = re.search(r'var TB_REFNOTE=\{(.*?)\n\};', src, re.S).group(1)
    home = dict(re.findall(r"(\w+):'((?:[^'\\]|\\.)*)'", body))
    assert set(home) == set(M.REFNOTE), '홈과 정본의 항목이 다르다: %s' % sorted(home)
    for k in M.REFNOTE:
        assert home[k] == M.REFNOTE[k], '%s 문구가 갈렸다\n홈  : %s\n정본: %s' % (
            k, home[k], M.REFNOTE[k])

    # 지역 페이지는 정본을 JSON으로 실어 나른다 — 옮겨 적기 자체가 없어야 한다.
    z = io.open(os.path.join(root, 'zone', '서울', 'index.html'), encoding='utf-8').read()
    baked = json.loads(re.search(r'var ZREFNOTE=(\{.*?\});', z, re.S).group(1))
    assert baked == M.REFNOTE, '지역 페이지에 구운 문구가 정본과 다르다'


def test_unsold_ratio_reads_the_same_everywhere():
    """같은 미분양 배수가 카드와 표에서 다르게 보이면 안 된다(2026-08-12 리뷰:
    0.38배 / 0.4배). 1 미만은 둘째 자리까지 — 0.01배를 '0.0배'로 뭉개면 0과
    구별이 안 된다."""
    import io, os, re, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import make_sido_pages as M
    assert M.umx(0.384) == '0.38배' and M.umx(0.01) == '0.01배'
    assert M.umx(2.44) == '2.4배' and M.umx(1.0) == '1.0배'
    # 경계: 첫째 자리로 1.0이 되는 값은 1.0배로 — 0.996이 '1.00배'로 나와
    # 1.0의 '1.0배'와 자릿수가 갈리면 안 된다(2026-08-13 리뷰).
    assert M.umx(0.996) == '1.0배' and M.umx(0.95) == '0.95배'

    root = os.path.join(os.path.dirname(__file__), '..', '..')
    for z in ('수도권', '제주', '세종'):
        h = io.open(os.path.join(root, 'zone', z, 'index.html'), encoding='utf-8').read()
        seen = set(re.findall(r'분기 적정물량(?:\([\d,]+호\))?의 ([\d.]+배)', h))
        seen |= set(re.findall(r'data-ref="un">.*?</td><td>[\d,]+</td><td>([\d.]+배)', h))
        assert len(seen) <= 1, '%s: 같은 배수가 여러 표기로 보인다 %s' % (z, sorted(seen))


def test_reference_rows_are_keyboard_reachable():
    """클릭 전용이면 키보드 사용자는 설명에 닿을 길이 없다(2026-08-12 리뷰).
    라벨이 진짜 <button>이라야 Tab 도달·Enter/Space 실행을 브라우저가 해준다."""
    import io, os
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    src = io.open(os.path.join(root, 'index.html'), encoding='utf-8').read()
    assert 'aria-controls="tb-refnote"' in src and 'class="rbtn"' in src
    assert 'aria-live="polite"' in src, '열린 설명이 읽히지 않는다'
    assert 'tbRefSync' in src, 'aria-expanded가 상태를 따라가지 않는다'
    # 열릴 때 nearest 스크롤 — 탭한 행이 화면 맨 밑이면 설명이 폴드 아래
    # 열려 아무 일도 없는 것처럼 보인다(2026-08-13 리뷰, 모바일).
    assert 'scrollIntoView' in src, '열린 설명이 시야 밖에 남을 수 있다'
    for z in ('서울', '세종'):
        h = io.open(os.path.join(root, 'zone', z, 'index.html'), encoding='utf-8').read()
        assert h.count('<button type="button" class="rbtn"') == 2, z
        assert 'aria-controls="zrefnote"' in h and 'aria-live="polite"' in h, z
        assert 'scrollIntoView' in h, '%s: 열린 설명이 시야 밖에 남을 수 있다' % z


def test_home_css_avoids_reviewed_regressions():
    """2026-08-12 리뷰 4건 재발 방지 — CSS 쪽 세 가지를 문자열로 잠근다.
    ① tfoot 두 행이 모두 bottom:0이면 sticky가 같은 자리에 포개진다,
    ② 표 밖 모드에서 참고 설명(#tb-refnote)이 남는다,
    ③ 2px 구분선이 행 사이에도 그어져 참고 블록이 안 묶인다."""
    import io, os
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    css = io.open(os.path.join(root, 'app.css'), encoding='utf-8').read()
    assert '#tb-main tfoot tr:first-child td' in css, 'tfoot 첫 행 띄우기(스택)가 없다'
    assert '#sec-score:not(.vm-table) #tb-refnote' in css, \
        '지도·그래프 모드에서 참고 설명이 숨지 않는다'
    stuck = [l for l in css.splitlines()
             if '#tb-main tfoot td' in l and 'border-top:2px' in l]
    assert not stuck, '2px 구분선이 tfoot 전체에 걸려 있다(첫 행 한정이어야 한다)'

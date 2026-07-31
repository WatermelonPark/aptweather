import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_zone_pages as M

def test_grade_cuts_and_boundaries():
    # 컷: (1.5, 1.0, 0.5, -0.5), 경계는 상위 등급 포함(>=)
    assert M.grade(150, 100)['k'] == 'g4'      # 정확히 150% -> 매우 부족
    assert M.grade(149, 100)['k'] == 'g3'
    assert M.grade(100, 100)['k'] == 'g3'      # 정확히 100% -> 부족
    assert M.grade(99, 100)['k'] == 'g2'
    assert M.grade(50, 100)['k'] == 'g2'       # 정확히 50% -> 다소 부족
    assert M.grade(49, 100)['k'] == 'g1'
    assert M.grade(-50, 100)['k'] == 'g1'      # 정확히 -50% -> 균형
    assert M.grade(-51, 100)['k'] == 'g0'      # 그 미만 -> 공급 여유
    assert M.grade(0, 0)['k'] == 'g1'          # need4=0 방어: ratio 0 -> 균형

def test_grade_labels_and_colors():
    g = M.grade(200, 100)
    assert g['label'] == '매우 부족' and g['color'] == '#a93226'
    assert abs(g['ratio'] - 2.0) < 1e-9
    assert M.grade(-100, 100)['label'] == '공급 여유'

def test_running_shortage_full_breakdown():
    # full=True: 분해값 dict. 세 항의 재조합이 tot과 정확히 일치해야 한다
    # (존 페이지 근거 3줄 = 필요 - 들어올것 - 재고, 합이 히어로 숫자와 같아야 신뢰 유지)
    cur = 2026 * 4 + 2
    refq = 50
    sched = {'2026Q4': 50}
    d = M.running_shortage({}, sched, {}, refq, cur, horizon=16,
                           weight_demand=False, full=True)
    assert set(d) == {'tot', 'inow', 'demand', 'supplyw'}
    assert d['demand'] == 16 * refq                      # 800
    assert d['supplyw'] == 50.0                          # conf(1)*50
    assert d['inow'] == -M.DEFICIT_CAP * refq            # 하한 -800
    assert d['tot'] == d['demand'] - d['supplyw'] - d['inow'] == 1550.0
    # full 생략 시 기존과 동일한 float
    s = M.running_shortage({}, sched, {}, refq, cur, horizon=16, weight_demand=False)
    assert s == d['tot']

def test_calc_rows_carry_grade_fields():
    adv, sts = M.load()
    rows = M.calc(adv, sts)
    r = rows[0]
    for k in ('need4', 'inow', 'fsupw', 'gr'):
        assert k in r, k
    assert abs(r['need4'] - r['refq'] * r['share'] * 16) < 1e-6
    # 재조합 정합: tot = demand(=need4) - supplyw - inow
    assert abs(r['tot'] - (r['need4'] - r['fsupw'] - r['inow'])) < 1e-6
    assert r['gr']['k'] in ('g0', 'g1', 'g2', 'g3', 'g4')
    hub = [x for x in rows if x.get('subs')]
    if hub:
        assert 'gr' in hub[0] and abs(
            hub[0]['need4'] - sum(c['need4'] for c in hub[0]['subs'])) < 1e-6

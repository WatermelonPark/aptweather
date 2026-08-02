import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_zone_pages as M

def test_running_shortage_window_counts_only_last_4y():
    """과거 재고는 최근 BACKLOG_WINDOW분기(4년)만 0에서 누적한다(2026-08-02).

    앵커(2010Q1)+상한 방식에서 창 방식으로 바꿨다. 창 안이면 언제 준공됐든
    같은 값이고, 창 밖이면 아예 안 세는 게 핵심 — 예전엔 상한에 눌려 옛 준공이
    조용히 사라지거나 남거나 했다.
    """
    cur = 2026 * 4 + 2                     # 2026Q3 → 창 = 2022Q4~2026Q3
    refq = 100
    # 준공 전무: I_now = -16*100 = -1600, 미래수요 4*100 = 400 → 2000
    assert M.running_shortage({}, {}, {}, refq, cur, horizon=4) == 2000.0

    # 창 안(2025Q1)에 400 준공 → I_now = 400-1600 = -1200 → 1600
    s_in = M.running_shortage({'2025Q1': 400}, {}, {}, refq, cur, horizon=4)
    assert s_in == 1600.0, s_in

    # 창 안이면 시점은 무관하다 — 2026Q2도 같은 값
    s_late = M.running_shortage({'2026Q2': 400}, {}, {}, refq, cur, horizon=4)
    assert s_late == s_in

    # 창 밖(2022Q3, 창 시작 한 분기 전)은 아예 안 센다
    s_out = M.running_shortage({'2022Q3': 400}, {}, {}, refq, cur, horizon=4)
    assert s_out == 2000.0, s_out
    assert s_out > s_in, '창 안 준공만 부족을 줄여야 한다'


def test_running_shortage_window_bounds_deficit_structurally():
    """창이 곧 상한이다 — 별도 클램프 없이 부족은 16*refq를 넘지 못한다.

    옛 DEFICIT_CAP이 하던 일을 구조가 대신하므로 파라미터가 하나 줄었다.
    """
    cur = 2026 * 4 + 2
    refq = 100
    fut = sum(M._conf(k) * refq for k in range(1, 5))
    s = M.running_shortage({}, {}, {}, refq, cur, horizon=4)
    assert s == fut + M.BACKLOG_WINDOW * refq

    # refq에 비례
    s2 = M.running_shortage({}, {}, {}, refq * 2, cur, horizon=4)
    assert s2 == fut * 2 + M.BACKLOG_WINDOW * refq * 2

    # 창은 cur_q에만 걸리고 ANCHOR와 무관하다(앵커 방식의 잔재가 없는지)
    old = M.running_shortage({}, {}, {}, refq, M.ANCHOR + 3, horizon=4)
    assert old == fut + M.BACKLOG_WINDOW * refq


def test_running_shortage_demol_reduces_inventory():
    """멸실은 재고를 그만큼 정확히 줄인다 — 창 방식엔 하한 포화가 없다.

    앵커+하한 시절엔 오래된 존이 하한에 붙어 멸실 유무가 상쇄돼 보였다.
    """
    cur = 2026 * 4 + 2
    refq = 100
    done = {'2025Q1': 400}
    s = M.running_shortage(done, {}, {'2025Q1': 100}, refq, cur, horizon=4)
    s_no = M.running_shortage(done, {}, {}, refq, cur, horizon=4)
    assert s - s_no == 100.0, (s, s_no)
    assert s > s_no, '멸실을 반영하면 재고가 줄어 순부족이 커야 한다'

    # 창 밖 멸실은 무시된다
    s_out = M.running_shortage(done, {}, {'2022Q3': 100}, refq, cur, horizon=4)
    assert s_out == s_no


def test_running_shortage_ab_agree_without_decay():
    # Issue #4의 A안/B안은 conf가 있을 때만 갈렸다. 감쇠 폐지(2026-08-02)로
    # conf≡1.0이 되면서 Σconf*(refq-s) == Σrefq - Σconf*s 가 항등식이 된다.
    # 이 테스트는 그 동치를 못박는다 — 둘이 갈리면 conf가 되살아났다는 뜻이다.
    # done={}이라 I_now는 하한 -BACKLOG_WINDOW*refq = -1600으로 같아, 차이가 생긴다면
    # 그건 순수하게 미래 항에서 온다.
    cur = 2026*4 + 2                       # 2026Q3
    refq = 100
    sched = {'2026Q4': 40, '2027Q1': 60, '2027Q2': 20, '2027Q3': 0}
    CAP = M.BACKLOG_WINDOW * refq             # 1600
    # A안: Σ (refq-sched) = 60 + 40 + 80 + 100 = 280 → s = 280 + 1600 = 1880
    s_a = M.running_shortage({}, sched, {}, refq, cur, horizon=4, weight_demand=True)
    assert s_a == 280.0 + CAP, f"Expected s_a == {280.0 + CAP}, got {s_a}"
    # B안: Σrefq - Σsched = 400 - (40 + 60 + 20 + 0) = 400 - 120 = 280 → 같은 값
    s_b = M.running_shortage({}, sched, {}, refq, cur, horizon=4, weight_demand=False)
    assert s_b == 280.0 + CAP, f"Expected s_b == {280.0 + CAP}, got {s_b}"
    assert s_b == s_a, "감쇠가 없으면 A안과 B안은 같아야 한다 — 갈리면 conf 부활"
    # 기본값(weight_demand 생략)은 A안 경로 — 라이브 산식이 안 바뀌었는지 확인
    s_default = M.running_shortage({}, sched, {}, refq, cur, horizon=4)
    assert s_default == s_a


def test_running_shortage_b_horizon16_hand_verified():
    # B4 결정(2026-07-25, 기준표 「기본의 기본 3」 근거): B안(weight_demand=False) +
    # 4년 지평(horizon=16). done={} → I_now는 하한 -BACKLOG_WINDOW*refq = -800으로
    # 단순화되고, sched는 미래 1분기(k=1)에만 넣어 나머지 15분기는 공급 0으로 둔다.
    cur = 2026 * 4 + 2                     # 2026Q3
    refq = 50
    sched = {'2026Q4': 50}                 # k=1만 공급 있음, k=2..16은 0
    s = M.running_shortage({}, sched, {}, refq, cur, horizon=16, weight_demand=False)
    # demand_sum = 16*refq = 800 (conf(k)>0 for all k=1..16, break never hits)
    # supply_weighted = conf(1)*50 = 1.0*50 = 50 (k=2..16의 sched=0이라 기여 없음)
    # fut = 800 - 50 = 750; I_now = -800 → s = 750 + 800 = 1550
    assert s == 750.0 + M.BACKLOG_WINDOW * refq, f"Expected s == 1550.0, got {s}"


def test_calc_live_path_uses_b_and_horizon16():
    # B4 결정: calc()를 override 없이(라이브 경로 그대로) 호출하면 inv_path 존은
    # weight_demand=False + horizon=FUT_HORIZON(16)으로 계산돼야 한다.
    today = datetime.date.today()
    cur_q = today.year * 4 + (today.month - 1) // 3
    sched_key = M._qkey(cur_q + 1)
    adv = {
        'livezone': {
            'zones': [{'z': '테스트권', 'region': '충북', 'psido': '충북',
                       'pop': 100000, 'hh': 50000, 'byq': {}}],
            'sidohh': {'충북': 100000},
        },
        'occupancy': {
            'regions': ['충북'],
            'rows': [{'v': [50], 'e': False}],
            'band': {'충북': [90, 110]},
            'ref': {'충북': 100},
        },
        'permits': {
            'regions': ['충북'],
            'rows': [{'v': [10]}, {'v': [10]}],
            'ref': {'충북': [80]},
            'done': {},
            'sched': {'테스트권': {sched_key: 50}},
        },
    }
    sts = {'전세가율': {'series': {}}, '주택멸실': {'series': {}}}

    assert M.calc.__defaults__ == (False, 16), (
        "calc()의 기본값이 (weight_demand=False, horizon=16=FUT_HORIZON)이어야 한다")

    rows = M.calc(adv, sts)          # override 없음 = 라이브 경로
    r = rows[0]
    assert r['inv_path'] is True
    expected = M.running_shortage({}, {sched_key: 50}, {}, 100 * 0.5, cur_q,
                                   horizon=16, weight_demand=False)
    # refq = 100*share(0.5) = 50 → 미래항 750 + 하한 BACKLOG_WINDOW*50 = 800 → 1550
    assert r['tot'] == expected == 750.0 + M.BACKLOG_WINDOW * 50


def test_calc_demol_not_share_scaled():
    # demol은 done/sched처럼 이미 zone-level 절대값(멸실 세대)이다 — refq만 share를
    # 곱해 region 적정을 zone 적정으로 맞추고, done/sched/demol은 원값 그대로 써야
    # 한다. share=0.5인 존에서 calc()가 zdemol을 그대로(비스케일) 넘기는지,
    # running_shortage({},{},{'2025Q1':100}*share...) 처럼 잘못 스케일한 값과
    # 달라지는지로 검증한다.
    today = datetime.date.today()
    cur_q = today.year * 4 + (today.month - 1) // 3
    done_key = M._qkey(cur_q - 4)          # 1년 전 분기(재고에 아직 남아 있게)
    adv = {
        'livezone': {
            'zones': [{'z': '테스트권', 'region': '충북', 'psido': '충북',
                       'pop': 100000, 'hh': 50000, 'byq': {}}],
            'sidohh': {'충북': 100000},           # share = 50000/100000 = 0.5
        },
        'occupancy': {
            'regions': ['충북'],
            'rows': [{'v': [50], 'e': False}],
            'band': {'충북': [90, 110]},
            'ref': {'충북': 100},
        },
        'permits': {
            'regions': ['충북'],
            'rows': [{'v': [10]}, {'v': [10]}],
            'ref': {'충북': [80]},
            'done': {'테스트권': {done_key: 400}},
            'sched': {},
            'demol': {'테스트권': {done_key: 100}},
        },
    }
    sts = {'전세가율': {'series': {}}, '주택멸실': {'series': {}}}

    rows = M.calc(adv, sts)
    r = rows[0]
    share = 0.5
    # calc()가 zdemol을 비스케일(원값 100)로 넘겼다면 이 값과 일치해야 한다.
    expected_raw = M.running_shortage({done_key: 400}, {}, {done_key: 100},
                                       100 * share, cur_q, horizon=16, weight_demand=False)
    # 만약 (잘못) demol에도 share를 곱했다면 나올 값 — 위와 달라야 한다(회귀 가드).
    expected_wrongly_scaled = M.running_shortage({done_key: 400}, {}, {done_key: 100 * share},
                                                  100 * share, cur_q, horizon=16, weight_demand=False)
    assert r['tot'] == expected_raw
    assert expected_raw != expected_wrongly_scaled, (
        "이 테스트가 의미 있으려면 두 경로가 실제로 갈라져야 한다")

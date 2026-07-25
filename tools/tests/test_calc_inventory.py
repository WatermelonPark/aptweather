import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_zone_pages as M

def test_running_shortage_buffer_and_decay():
    # cur_q 기준 미래 1분기 sched 부족, 과거 준공으로 재고 버퍼
    cur = 2026*4 + 2                       # 2026Q3 인덱스(년*4+분기-1)
    done = {'2025Q1': 400}                 # 과거 준공
    sched = {'2026Q4': 0}                  # 미래 공급 0
    refq = 100
    # I_now: 앵커~cur, 2025Q1에 +400-100=300, 이후 분기마다 -100 소진 → cur까지 몇 분기 소진
    s = M.running_shortage(done, sched, refq, cur, horizon=4)
    # 미래수요 Σconf*refq - (I_now + Σconf*sched). 값이 유한·부호 정상인지
    assert s == 370.0, f"Expected s == 370.0, got {s}"
    
    # 최근 준공의 재고 버퍼가 부족을 경감하는지 검증
    s_recent = M.running_shortage({'2026Q2': 400}, {}, refq, cur, horizon=4)
    assert s_recent == 170.0, f"Expected s_recent == 170.0, got {s_recent}"
    assert s_recent < s, f"Expected recent buffer to reduce shortage: {s_recent} < {s}"

def test_running_shortage_no_negative_inventory():
    cur = 2026*4 + 2
    # 과거 준공 전무 → I_now=0, 미래 공급 0 → 순부족 = Σconf*refq > 0 (부족)
    s = M.running_shortage({}, {}, 100, cur, horizon=4)
    assert s > 0

def test_running_shortage_weight_demand_false():
    # Issue #4 B안(스펙 원문): 수요는 비가중(Σrefq), 공급만 conf 가중(Σconf*sched).
    # A안(가중, 기본값)과 다른 산식임을 손계산으로 증명 — done={} → I_now=0으로 단순화.
    cur = 2026*4 + 2                       # 2026Q3
    refq = 100
    sched = {'2026Q4': 40, '2027Q1': 60, '2027Q2': 20, '2027Q3': 0}
    # conf(1..4) = 1.0, 0.95, 0.9, 0.85
    # A안: Σ conf(k)*(refq-sched) = 1.0*60 + 0.95*40 + 0.9*80 + 0.85*100
    #     = 60 + 38 + 72 + 85 = 255
    s_a = M.running_shortage({}, sched, refq, cur, horizon=4, weight_demand=True)
    assert s_a == 255.0, f"Expected s_a == 255.0, got {s_a}"
    # B안: Σrefq - Σ conf(k)*sched = 400 - (1.0*40 + 0.95*60 + 0.9*20 + 0.85*0)
    #     = 400 - (40 + 57 + 18 + 0) = 400 - 115 = 285
    s_b = M.running_shortage({}, sched, refq, cur, horizon=4, weight_demand=False)
    assert s_b == 285.0, f"Expected s_b == 285.0, got {s_b}"
    assert s_b != s_a, "A안과 B안은 서로 다른 산식이어야 한다"
    # 기본값(weight_demand 생략)은 A안과 동치 — 라이브 산식이 안 바뀌었는지 확인
    s_default = M.running_shortage({}, sched, refq, cur, horizon=4)
    assert s_default == s_a


def test_running_shortage_b_horizon16_hand_verified():
    # B4 결정(2026-07-25, 기준표 「기본의 기본 3」 근거): B안(weight_demand=False) +
    # 4년 지평(horizon=16). done={} → I_now=0으로 단순화하고, sched는 미래 1분기
    # (k=1)에만 넣어 나머지 15분기는 공급 0으로 손계산 가능하게 한다.
    cur = 2026 * 4 + 2                     # 2026Q3
    refq = 50
    sched = {'2026Q4': 50}                 # k=1만 공급 있음, k=2..16은 0
    s = M.running_shortage({}, sched, refq, cur, horizon=16, weight_demand=False)
    # demand_sum = 16*refq = 800 (conf(k)>0 for all k=1..16, break never hits)
    # supply_weighted = conf(1)*50 = 1.0*50 = 50 (k=2..16의 sched=0이라 기여 없음)
    # fut = 800 - 50 = 750; I_now = 0 → s = 750
    assert s == 750.0, f"Expected s == 750.0, got {s}"


def test_calc_live_path_uses_b_and_horizon16():
    # B4 결정: calc()를 override 없이(라이브 경로 그대로) 호출하면 inv_path 존은
    # weight_demand=False + horizon=FUT_HORIZON(16)으로 계산돼야 한다.
    today = datetime.date.today()
    cur_q = today.year * 4 + (today.month - 1) // 3
    sched_key = M._qkey(cur_q + 1)
    adv = {
        'livezone': {
            'zones': [{'z': '테스트권', 'region': '충북', 'psido': '충북',
                       'pop': 100000, 'byq': {}}],
            'sidopop': {'충북': 200000},
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
    expected = M.running_shortage({}, {sched_key: 50}, 100 * 0.5, cur_q,
                                   horizon=16, weight_demand=False)
    assert r['tot'] == expected == 750.0

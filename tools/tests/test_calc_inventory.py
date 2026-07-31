import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_zone_pages as M

def test_running_shortage_buffer_and_decay():
    # cur_q 기준 미래 1분기 sched 부족, 과거 준공으로 재고 버퍼
    cur = 2026*4 + 2                       # 2026Q3 인덱스(년*4+분기-1)
    done = {'2025Q1': 400}                 # 과거 준공
    sched = {'2026Q4': 0}                  # 미래 공급 0
    refq = 100
    # 2026-07-31: 재고 하한이 0 → -DEFICIT_CAP*refq(=-1600)로 바뀌었다.
    # I_now: 앵커(2010Q1)~2025Q1 직전까지 준공이 없어 분기마다 -100씩 쌓이다 16분기째
    # -1600에서 멈춘다. 2025Q1에 max(-1600, -1600+400-100) = -1300으로 회복하고,
    # 2025Q2~2026Q3(6분기) 동안 -1400,-1500,-1600, 이후 하한 유지 → I_now = -1600.
    s = M.running_shortage(done, sched, {}, refq, cur, horizon=4)
    # 미래수요 Σconf*refq = (1.0+0.95+0.9+0.85)*100 = 370; s = 370 - (-1600) = 1970
    assert s == 1970.0, f"Expected s == 1970.0, got {s}"

    # 최근 준공의 재고 버퍼가 부족을 경감하는지 검증
    # 2026Q2에 400 → max(-1600,-1600+400-100) = -1300, 2026Q3에 -1400 → I_now = -1400
    s_recent = M.running_shortage({'2026Q2': 400}, {}, {}, refq, cur, horizon=4)
    assert s_recent == 1770.0, f"Expected s_recent == 1770.0, got {s_recent}"
    assert s_recent < s, f"Expected recent buffer to reduce shortage: {s_recent} < {s}"

def test_running_shortage_deficit_cap():
    # 2026-07-31: 재고 하한이 0 → -DEFICIT_CAP*refq. 부족도 쌓이되 4년치가 상한이다.
    # (옛 max(0,·)는 만성부족 존의 재고를 늘 0에 붙여 "이번 분기부터 모자란 곳"과
    #  "16년째 모자란 곳"을 구분하지 못했다 — 서울권 재고>0 분기가 6%뿐이었다.)
    cur = 2026*4 + 2
    refq = 100
    # 과거 준공 전무 → 앵커부터 매 분기 -refq, DEFICIT_CAP분기에서 하한 도달 후 고정
    s = M.running_shortage({}, {}, {}, refq, cur, horizon=4)
    fut = sum(M._conf(k) * refq for k in range(1, 5))
    assert s == fut + M.DEFICIT_CAP * refq, (
        f"I_now가 정확히 -DEFICIT_CAP*refq에서 멈춰야 한다 (got s={s})")
    assert s > 0

    # 하한이 refq에 비례하는지 — refq를 2배로 하면 하한도 2배
    s2 = M.running_shortage({}, {}, {}, refq * 2, cur, horizon=4)
    assert s2 == fut * 2 + M.DEFICIT_CAP * refq * 2

    # 앵커에서 DEFICIT_CAP분기밖에 안 지난 시점이면 아직 하한에 안 닿는다(=하한이
    # 무조건 걸리는 상수가 아니라 실제로 굴러가는 값인지 확인)
    near = M.ANCHOR + 3                       # 앵커 포함 4분기만 경과
    s_near = M.running_shortage({}, {}, {}, refq, near, horizon=4)
    assert s_near == fut + 4 * refq, f"4분기치(-400)만 쌓여야 한다 (got {s_near})"


def test_running_shortage_demol_reduces_inventory():
    # 멸실 보정: 순공급=준공−멸실. 과거 2025Q1에 준공 400 + 멸실 100 → 재고에 실린
    # 순증은 300세대뿐이어야 한다(기준표: 재건축 준공은 순공급을 부풀린다).
    cur = 2026 * 4 + 2                     # 2026Q3
    refq = 100
    done = {'2025Q1': 400}
    demol = {'2025Q1': 100}
    sched = {'2026Q4': 0}
    # I_now(멸실 있음): 앵커~2024Q4에 하한 -1600 도달. 2025Q1에
    # max(-1600, -1600+400-100-100) = -1400, 이후 2025Q2~2026Q3(6분기) -100씩 →
    # -1500, -1600, 이후 하한 유지 → I_now = -1600.
    # (증거용 대조군) 멸실 없으면: 2025Q1에 -1300 → -1400 → -1500 → -1600 → 하한 유지.
    # 두 경로 모두 cur_q(2026Q3)까지 하한으로 수렴하므로, 이 손계산으로는 s와
    # s_no_demol이 같아진다. 재고가 하한에 안 닿은 구간(cur을 앞당겨)을 별도 검증한다.
    s = M.running_shortage(done, sched, demol, refq, cur, horizon=4)
    s_no_demol = M.running_shortage(done, sched, {}, refq, cur, horizon=4)
    assert s == s_no_demol, (
        "이 시나리오는 cur_q까지 재고가 완전 소진되므로 멸실 유무와 무관하게 같다")

    # 하한에 안 닿은 시점(cur을 done 직후로 당김)에서는 멸실이 I_now를 정확히
    # 줄여야 한다: done 400, demol 100 in 2025Q1, refq=100, cur=2025Q1
    # → I_now = max(-1600, -1600+400-100-100) = -1400 (멸실 없으면 -1300).
    cur_near = 2025 * 4 + 0                # 2025Q1
    fut = 0.0
    for k in range(1, 5):
        w = M._conf(k)
        fut += w * refq
    s_near = M.running_shortage(done, sched, demol, refq, cur_near, horizon=4)
    s_near_no_demol = M.running_shortage(done, sched, {}, refq, cur_near, horizon=4)
    assert s_near == fut + 1400.0, f"Expected s_near == {fut + 1400.0}, got {s_near}"
    assert s_near_no_demol == fut + 1300.0, (
        f"Expected s_near_no_demol == {fut + 1300.0}, got {s_near_no_demol}")
    assert s_near > s_near_no_demol, (
        "멸실을 반영하면 재고(I_now)가 줄어 순부족(s)이 더 커야 한다(+100)")
    assert s_near - s_near_no_demol == 100.0

def test_running_shortage_weight_demand_false():
    # Issue #4 B안(스펙 원문): 수요는 비가중(Σrefq), 공급만 conf 가중(Σconf*sched).
    # A안(가중, 기본값)과 다른 산식임을 손계산으로 증명 — done={}이라 I_now는 두 안
    # 모두 하한 -DEFICIT_CAP*refq = -1600으로 같아, 차이는 순수하게 미래 항에서만 온다.
    cur = 2026*4 + 2                       # 2026Q3
    refq = 100
    sched = {'2026Q4': 40, '2027Q1': 60, '2027Q2': 20, '2027Q3': 0}
    CAP = M.DEFICIT_CAP * refq             # 1600
    # conf(1..4) = 1.0, 0.95, 0.9, 0.85
    # A안: Σ conf(k)*(refq-sched) = 1.0*60 + 0.95*40 + 0.9*80 + 0.85*100
    #     = 60 + 38 + 72 + 85 = 255 → s = 255 + 1600 = 1855
    s_a = M.running_shortage({}, sched, {}, refq, cur, horizon=4, weight_demand=True)
    assert s_a == 255.0 + CAP, f"Expected s_a == {255.0 + CAP}, got {s_a}"
    # B안: Σrefq - Σ conf(k)*sched = 400 - (1.0*40 + 0.95*60 + 0.9*20 + 0.85*0)
    #     = 400 - (40 + 57 + 18 + 0) = 400 - 115 = 285 → s = 285 + 1600 = 1885
    s_b = M.running_shortage({}, sched, {}, refq, cur, horizon=4, weight_demand=False)
    assert s_b == 285.0 + CAP, f"Expected s_b == {285.0 + CAP}, got {s_b}"
    assert s_b != s_a, "A안과 B안은 서로 다른 산식이어야 한다"
    # 기본값(weight_demand 생략)은 A안과 동치 — 라이브 산식이 안 바뀌었는지 확인
    s_default = M.running_shortage({}, sched, {}, refq, cur, horizon=4)
    assert s_default == s_a


def test_running_shortage_b_horizon16_hand_verified():
    # B4 결정(2026-07-25, 기준표 「기본의 기본 3」 근거): B안(weight_demand=False) +
    # 4년 지평(horizon=16). done={} → I_now는 하한 -DEFICIT_CAP*refq = -800으로
    # 단순화되고, sched는 미래 1분기(k=1)에만 넣어 나머지 15분기는 공급 0으로 둔다.
    cur = 2026 * 4 + 2                     # 2026Q3
    refq = 50
    sched = {'2026Q4': 50}                 # k=1만 공급 있음, k=2..16은 0
    s = M.running_shortage({}, sched, {}, refq, cur, horizon=16, weight_demand=False)
    # demand_sum = 16*refq = 800 (conf(k)>0 for all k=1..16, break never hits)
    # supply_weighted = conf(1)*50 = 1.0*50 = 50 (k=2..16의 sched=0이라 기여 없음)
    # fut = 800 - 50 = 750; I_now = -800 → s = 750 + 800 = 1550
    assert s == 750.0 + M.DEFICIT_CAP * refq, f"Expected s == 1550.0, got {s}"


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
    expected = M.running_shortage({}, {sched_key: 50}, {}, 100 * 0.5, cur_q,
                                   horizon=16, weight_demand=False)
    # refq = 100*share(0.5) = 50 → 미래항 750 + 하한 DEFICIT_CAP*50 = 800 → 1550
    assert r['tot'] == expected == 750.0 + M.DEFICIT_CAP * 50


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
                       'pop': 100000, 'byq': {}}],
            'sidopop': {'충북': 200000},          # share = 100000/200000 = 0.5
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

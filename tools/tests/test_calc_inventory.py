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
    s = M.running_shortage(done, sched, {}, refq, cur, horizon=4)
    # 미래수요 Σconf*refq - (I_now + Σconf*sched). 값이 유한·부호 정상인지
    assert s == 370.0, f"Expected s == 370.0, got {s}"

    # 최근 준공의 재고 버퍼가 부족을 경감하는지 검증
    s_recent = M.running_shortage({'2026Q2': 400}, {}, {}, refq, cur, horizon=4)
    assert s_recent == 170.0, f"Expected s_recent == 170.0, got {s_recent}"
    assert s_recent < s, f"Expected recent buffer to reduce shortage: {s_recent} < {s}"

def test_running_shortage_no_negative_inventory():
    cur = 2026*4 + 2
    # 과거 준공 전무 → I_now=0, 미래 공급 0 → 순부족 = Σconf*refq > 0 (부족)
    s = M.running_shortage({}, {}, {}, 100, cur, horizon=4)
    assert s > 0


def test_running_shortage_demol_reduces_inventory():
    # 멸실 보정: 순공급=준공−멸실. 과거 2025Q1에 준공 400 + 멸실 100 → 재고에 실린
    # 순증은 300세대뿐이어야 한다(기준표: 재건축 준공은 순공급을 부풀린다).
    cur = 2026 * 4 + 2                     # 2026Q3
    refq = 100
    done = {'2025Q1': 400}
    demol = {'2025Q1': 100}
    sched = {'2026Q4': 0}
    # I_now(멸실 있음): 2025Q1에 I=max(0,0+400-100-100)=200, 이후 2025Q2~2026Q3
    # (6분기)마다 refq=100씩 소진 → I가 6번의 -100을 버틸 수 없어 2025Q2에서
    # max(0,200-100)=100, 2025Q3에서 max(0,100-100)=0, 이후 0 유지 → I_now=0.
    # (증거용 대조군) 멸실 없으면: 2025Q1에 I=max(0,400-100)=300 → 2025Q2 200 →
    # 2025Q3 100 → 2025Q4 0 → 이후 0. 두 경로 모두 cur_q(2026Q3)까지 재고가
    # 소진돼 I_now=0으로 수렴하므로, 이 손계산으로는 s와 s_no_demol이 같아진다.
    # 재고가 남는 구간(cur을 앞당겨) 쪽을 별도로 검증한다.
    s = M.running_shortage(done, sched, demol, refq, cur, horizon=4)
    s_no_demol = M.running_shortage(done, sched, {}, refq, cur, horizon=4)
    assert s == s_no_demol, (
        "이 시나리오는 cur_q까지 재고가 완전 소진되므로 멸실 유무와 무관하게 같다")

    # 재고가 아직 남아 있는 시점(cur을 done 직후로 당김)에서는 멸실이 I_now를
    # 정확히 줄여야 한다: done 400, demol 100 in 2025Q1, refq=100, cur=2025Q1
    # → I_now = max(0, 0+400-100-100) = 200 (멸실 없으면 300).
    cur_near = 2025 * 4 + 0                # 2025Q1
    fut = 0.0
    for k in range(1, 5):
        w = M._conf(k)
        fut += w * refq
    s_near = M.running_shortage(done, sched, demol, refq, cur_near, horizon=4)
    s_near_no_demol = M.running_shortage(done, sched, {}, refq, cur_near, horizon=4)
    assert s_near == fut - 200.0, f"Expected s_near == {fut - 200.0}, got {s_near}"
    assert s_near_no_demol == fut - 300.0, (
        f"Expected s_near_no_demol == {fut - 300.0}, got {s_near_no_demol}")
    assert s_near > s_near_no_demol, (
        "멸실을 반영하면 재고(I_now)가 줄어 순부족(s)이 더 커야 한다(+100)")
    assert s_near - s_near_no_demol == 100.0

def test_running_shortage_weight_demand_false():
    # Issue #4 B안(스펙 원문): 수요는 비가중(Σrefq), 공급만 conf 가중(Σconf*sched).
    # A안(가중, 기본값)과 다른 산식임을 손계산으로 증명 — done={} → I_now=0으로 단순화.
    cur = 2026*4 + 2                       # 2026Q3
    refq = 100
    sched = {'2026Q4': 40, '2027Q1': 60, '2027Q2': 20, '2027Q3': 0}
    # conf(1..4) = 1.0, 0.95, 0.9, 0.85
    # A안: Σ conf(k)*(refq-sched) = 1.0*60 + 0.95*40 + 0.9*80 + 0.85*100
    #     = 60 + 38 + 72 + 85 = 255
    s_a = M.running_shortage({}, sched, {}, refq, cur, horizon=4, weight_demand=True)
    assert s_a == 255.0, f"Expected s_a == 255.0, got {s_a}"
    # B안: Σrefq - Σ conf(k)*sched = 400 - (1.0*40 + 0.95*60 + 0.9*20 + 0.85*0)
    #     = 400 - (40 + 57 + 18 + 0) = 400 - 115 = 285
    s_b = M.running_shortage({}, sched, {}, refq, cur, horizon=4, weight_demand=False)
    assert s_b == 285.0, f"Expected s_b == 285.0, got {s_b}"
    assert s_b != s_a, "A안과 B안은 서로 다른 산식이어야 한다"
    # 기본값(weight_demand 생략)은 A안과 동치 — 라이브 산식이 안 바뀌었는지 확인
    s_default = M.running_shortage({}, sched, {}, refq, cur, horizon=4)
    assert s_default == s_a


def test_running_shortage_b_horizon16_hand_verified():
    # B4 결정(2026-07-25, 기준표 「기본의 기본 3」 근거): B안(weight_demand=False) +
    # 4년 지평(horizon=16). done={} → I_now=0으로 단순화하고, sched는 미래 1분기
    # (k=1)에만 넣어 나머지 15분기는 공급 0으로 손계산 가능하게 한다.
    cur = 2026 * 4 + 2                     # 2026Q3
    refq = 50
    sched = {'2026Q4': 50}                 # k=1만 공급 있음, k=2..16은 0
    s = M.running_shortage({}, sched, {}, refq, cur, horizon=16, weight_demand=False)
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
    expected = M.running_shortage({}, {sched_key: 50}, {}, 100 * 0.5, cur_q,
                                   horizon=16, weight_demand=False)
    assert r['tot'] == expected == 750.0


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

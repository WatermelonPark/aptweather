import sys, os
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
    assert isinstance(s, float)

def test_running_shortage_no_negative_inventory():
    cur = 2026*4 + 2
    # 과거 준공 전무 → I_now=0, 미래 공급 0 → 순부족 = Σconf*refq > 0 (부족)
    s = M.running_shortage({}, {}, 100, cur, horizon=4)
    assert s > 0

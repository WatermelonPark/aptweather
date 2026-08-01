import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _stat(vs):
    """verify_ref_scale.main()의 _stat과 같은 계산(모집단 표준편차)."""
    n = len(vs)
    if not n:
        return 0.0, 0.0, float('inf'), 0
    m = sum(vs) / n
    sd = (sum((x - m) ** 2 for x in vs) / n) ** 0.5
    return m, sd, (sd / m if m else float('inf')), n


def _verdict(full_ratios, all_ratios):
    """2026-08-01 재정의된 판정 규칙 — 안분 없는 존 평균이 1.00 ±0.15 안인가."""
    fm, _, _, fn = _stat(full_ratios)
    if fn < 4:
        return 'hold'
    return 'ok' if abs(fm - 1.0) <= 0.15 else 'skew'


def test_high_cv_alone_is_not_a_scale_problem():
    """전체 CV가 커도(존별 과잉/부족 차이) 안분 없는 존 평균이 1 근처면 정상.
    옛 기준(CV>=0.3 -> 부적합)은 정상 상태에서도 경고를 냈다."""
    full = [1.01, 0.97, 1.12, 0.75, 1.05, 0.98]      # 평균 0.98
    allr = full + [2.61, 2.59, 0.12, 0.17, 0.20]     # 안분 존이 CV를 키움
    _, _, cv, _ = _stat(allr)
    assert cv >= 0.3, '이 표본은 CV가 커야 테스트가 의미 있다'
    assert _verdict(full, allr) == 'ok'


def test_systematic_offset_is_flagged():
    """척도가 어긋나면 흩어짐이 아니라 치우침으로 나타난다 — 그때만 경고."""
    full = [1.9, 2.0, 2.1, 1.95, 2.05, 2.0]          # 평균 ~2.0
    assert _verdict(full, full) == 'skew'


def test_too_few_unapportioned_zones_holds_judgment():
    assert _verdict([1.0, 1.0, 1.0], [1.0] * 3) == 'hold'


def test_verify_ref_scale_runs_clean():
    """실데이터로 끝까지 돌고 exit 0 (읽기 전용 도구)."""
    import verify_ref_scale as V
    assert V.main() == 0

# ---------------------------------------------------------------------------
# zone_done_avg 순수함수 스모크 — tools/test_verify_ref_scale.py(2026-07-24)에서
# 옮겨왔다. 두 파일의 basename이 같아 `pytest tools/`가 import mismatch로 수집
# 자체에 실패했고, 그래서 구 파일의 실패가 `pytest tools/tests/` 기준 "140 passed"에
# 가려져 있었다(2026-08-01 개발 세션 발견). 파일을 하나로 합쳐 충돌을 없앤다.
# ---------------------------------------------------------------------------
import datetime


def _q(delta_from_current):
    """오늘 기준 delta분기 전 라벨('YYYYQn'). 0=이번 분기."""
    today = datetime.date.today()
    n = today.year * 4 + (today.month - 1) // 3 - delta_from_current
    return '%dQ%d' % (n // 4, n % 4 + 1)


def test_zone_done_avg_aggregates_and_averages():
    import verify_ref_scale as V
    hp = {'sgg': {
        'A1': {'done_q': {_q(0): 100, _q(1): 200}},   # 존X 소속
        'A2': {'done_q': {_q(0): 50}},                # 존X 소속(같은 존 합산)
        'B1': {'permit_q': {_q(0): 9999}},            # done_q 없음(구스키마) → 무시
        'C1': {'done_q': {_q(20): 10}},               # 최근 3년 창 밖 → 제외
        'D1': {'done_q': {_q(0): 5}},                 # z_of에 없는 코드 → 무시
    }}
    z_of = {'A1': '존X', 'A2': '존X', 'B1': '존Y', 'C1': '존Z'}
    out = V.zone_done_avg(hp, z_of, n_years=3)
    assert '존X' in out, out
    avg, nq = out['존X']
    # 분기0: 100+50=150, 분기1: 200 → 평균 175, 표본분기 2
    assert nq == 2 and abs(avg - 175.0) < 1e-9, (avg, nq)
    assert '존Y' not in out    # done_q 없는 시군구만 있던 존은 방출 안 함
    assert '존Z' not in out    # 창 밖 데이터만 있던 존도 방출 안 함


def test_zone_done_avg_empty_when_no_done_q():
    import verify_ref_scale as V
    hp = {'sgg': {'X1': {'permit_q': {_q(0): 1}, 'start_q': {_q(0): 1}}}}
    assert V.zone_done_avg(hp, {'X1': '존X'}, n_years=3) == {}


def test_zone_refq_logic_lives_in_calc_now():
    """옛 미러 가드(zone_region/zone_refq가 calc()의 ps 규칙과 같은지)는 되살리지
    않는다 — 2026-08-01에 verify_ref_scale이 자체 계산을 버리고 calc()의 zrefq를
    그대로 쓰도록 위임해서, **드리프트할 중복 자체가 사라졌기** 때문이다.
    가드 대신 '중복이 다시 생기지 않았는지'를 지킨다."""
    import verify_ref_scale as V
    for gone in ('zone_region', 'zone_refq', 'zone_share', 'load_adv'):
        assert not hasattr(V, gone), (
            '%s가 되살아났다 — 존 적정 계산을 자체 구현하면 calc()와 조용히 어긋난다'
            '(수요 풀 재배선·세대수 안분 때 실제로 어긋났던 이력). calc()의 zrefq를 쓸 것.' % gone)

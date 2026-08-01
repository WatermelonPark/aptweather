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

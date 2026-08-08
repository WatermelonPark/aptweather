# -*- coding: utf-8 -*-
"""저장분 정합 검사(17시도 합 == 전국) — 굳은 과거를 잡는 유일한 장치.

나이·원천 대조는 **최신 시점 하나**만 본다. 모든 수집이 '최근 N개'만 다시 받으므로
그 창 밖 과거는 최초 시딩 판본이 영구히 굳는데, 2026-08-08 감사에서 전세가율
2,593셀·매매지수 6,041셀·주간 시세 360행이 그렇게 굳어 있던 게 드러났다. 그때까지
감시는 매일 OK였다. 이 검사가 그 사각지대를 덮는다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import check_freshness as C


def _stats(nat, sido_rows, dates=None, name='준공'):
    """전국 행 + 시도 행들로 최소 STATS를 만든다."""
    ser = {'전국': list(nat)}
    for r, v in sido_rows.items():
        ser[r] = list(v)
    return {name: {'dates': dates or ['2011.0%d' % (i + 1) for i in range(len(nat))],
                   'series': ser}}


def test_clean_data_passes():
    st = _stats([30, 40], {'서울': [10, 15], '경기': [20, 25]})
    assert C.check_sido_sum(st) == []


def test_catches_a_corrupted_past_cell():
    """창 밖 과거가 굳어 원천과 갈라진 상황 — 정확히 이걸 잡으려고 만들었다."""
    st = _stats([30, 40], {'서울': [10 + 5000, 15], '경기': [20, 25]})
    fails = C.check_sido_sum(st)
    assert len(fails) == 1
    assert '2011.01' in fails[0], fails[0]
    assert '--heal-basic' in fails[0], '교정 방법을 안내해야 한다'


def test_null_counts_as_zero():
    """KOSIS의 null은 결측이 아니라 0이다(시도합÷전국이 모든 연도 1.00으로 증명).
    None을 건너뛰면 합이 모자라 오탐이 난다."""
    st = _stats([30], {'서울': [30], '경기': [None]})
    assert C.check_sido_sum(st) == []


def test_skips_periods_before_a_series_starts():
    """계열이 시작되기 전 구간은 전국 행도 None이다 — 0이 아니므로 판정에서 뺀다
    (세종 2012.07 출범 같은 경우)."""
    st = _stats([None, 40], {'서울': [None, 15], '경기': [None, 25]})
    assert C.check_sido_sum(st) == []


def test_rounding_slack_does_not_alarm():
    """소수 계열은 반올림으로 1 미만 차가 생긴다 — 그걸로 매일 red를 만들면 안 된다."""
    st = _stats([30.0], {'서울': [10.4], '경기': [19.9]})   # 합 30.3
    assert C.check_sido_sum(st) == []


def test_runs_on_the_series_that_have_a_national_row():
    """대상 계열이 조용히 줄어들면 검사가 꺼진 줄 모른다."""
    assert set(C.SUM_SERIES) == {'준공', '착공', '인허가', '분양', '미분양'}
    assert len(C.SIDO17) == 17


def test_live_data_satisfies_the_invariant():
    """실제 저장분에서 성립하는지 — 여기서 깨지면 데이터가 오염된 것이다."""
    import io
    import json
    import re
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    src = io.open(os.path.join(root, 'data.js'), encoding='utf-8').read()
    st = json.loads(re.search(r'const STATS\s*=\s*(\{.*?\});?\s*(?:/\*|const |$)',
                              src, re.S).group(1))
    assert C.check_sido_sum(st) == []

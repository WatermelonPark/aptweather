# -*- coding: utf-8 -*-
"""갱신이 멈춘 것을 시점만으로는 못 잡는다.

2026-09-08~12 실사고: 배치의 완비 기준이 원천에 없는 이름(`기타광역시`·`기타지방`)을
요구해 받은 달을 **전부** 버렸다. 저장분은 멈춘 채 남았는데 원천도 새 달을 내지
않아 시점은 계속 같았고, 감시는 닷새 내내 초록이었다. 기준을 고친 것과 별개로,
같은 모양의 정지가 다른 이유로 또 생길 수 있으니 두 자리를 지킨다.

① 배치: 받은 달을 전부 버리면 개별 달의 결측이 아니라 기준이 틀린 것이다.
② 감시: 시점이 같아도 그 달의 시도 합이 원천과 같은지 본다.

지역 이름은 여기에 적지 않고 `SUPPLY_SIDO`에서 가져온다 — 픽스처에 모델을 박으면
지역이 바뀔 때 이 시험이 배치를 막는다(2026-09-11에 실제로 그랬다).
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U  # noqa: E402
import check_freshness as C  # noqa: E402


def _months(n=2):
    """완비된 달 n개. 값은 지역마다 1로 둬서 시도 합이 곧 지역 수가 되게 한다."""
    return {(2026, 6 - i): {r: 1.0 for r in U.SUPPLY_SIDO} for i in range(n)}


def test_all_dropped_is_announced(capsys):
    """전부 버려지는 것은 평범한 제외와 다르게 보여야 한다."""
    U._drop_incomplete(_months(), set(U.SUPPLY_SIDO) | {'있을 수 없는 이름'}, '분양')
    out = capsys.readouterr().out
    assert '전부 버렸다' in out, '모든 달을 버렸는데 평범한 제외 줄만 찍혔다'
    assert '::warning::' in out, '워크플로 로그에서 눈에 띄지 않는다'


def test_normal_drop_stays_quiet(capsys):
    """한 달만 빠지는 것은 정상 동작이라 경고까지 올리지 않는다."""
    got = _months()
    ym = max(got)
    got[ym].pop(U.SUPPLY_SIDO[0])
    kept = U._drop_incomplete(got, set(U.SUPPLY_SIDO), '분양')
    out = capsys.readouterr().out
    assert len(kept) == 1, '멀쩡한 달까지 버렸다'
    assert '전부 버렸다' not in out and '::warning::' not in out


def _series(dates, per_region):
    return {'dates': list(dates),
            'series': {r: [per_region] * len(dates) for r in U.SUPPLY_SIDO}}


def test_value_check_passes_when_totals_agree(monkeypatch, capsys):
    n = len(U.SUPPLY_SIDO)
    monkeypatch.setitem(C._COMPLETE_CACHE, ('T', '202605'), ('202606', float(n)))
    assert C.check_supply_value('분양', _series(['2026.05', '2026.06'], 1.0),
                                'T', '202605') is None


def test_value_check_catches_a_frozen_series(monkeypatch):
    """시점은 같은데 값이 다르면 잡아야 한다 — 조용한 정지가 이 모양이다."""
    n = len(U.SUPPLY_SIDO)
    monkeypatch.setitem(C._COMPLETE_CACHE, ('T', '202605'), ('202606', float(n) + 500))
    why = C.check_supply_value('분양', _series(['2026.05', '2026.06'], 1.0),
                               'T', '202605')
    assert why and '값이 다르다' in why, '시도 합이 어긋났는데 통과시켰다'


def test_value_check_is_silent_when_the_month_is_missing(monkeypatch):
    """저장분에 그 달이 아예 없으면 나이 검사 몫이다. 여기서 두 번 세지 않는다."""
    monkeypatch.setitem(C._COMPLETE_CACHE, ('T', '202605'), ('202607', 1.0))
    assert C.check_supply_value('분양', _series(['2026.05', '2026.06'], 1.0),
                                'T', '202605') is None


def test_value_check_survives_a_fetch_failure(monkeypatch):
    """조회 실패는 check()가 SKIPPED로 분류한다. 여기서 또 실패를 세면 게이트 산수가 틀어진다."""
    def boom(*a, **k):
        raise RuntimeError('원천 응답 없음')
    monkeypatch.setattr(C, 'rone_latest_complete', boom)
    assert C.check_supply_value('분양', _series(['2026.06'], 1.0), 'T', '202605') is None


def test_watchdog_reuses_the_lookup_instead_of_calling_twice():
    """값 대조 때문에 원천 호출이 늘면 감시 타임아웃 예산이 어긋난다."""
    src = io.open(os.path.join(os.path.dirname(__file__), '..', 'check_freshness.py'),
                  encoding='utf-8').read()
    assert '_COMPLETE_CACHE' in src, '조회 결과를 재사용하지 않는다'
    assert 'want_total' in src, '합계를 같은 조회에서 받지 않는다'

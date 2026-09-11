# -*- coding: utf-8 -*-
"""원천이 시도를 합쳐 내는 달은 받지 않는다.

2026-09 실사고: 국토교통부 주택건설실적통계가 2026.07분부터 '광주'와 '전남'을
'전남광주' 한 행으로 합쳐 내기 시작했다(원천 최종변경일 2026-08-31). 수집기는
개별 시도 행을 기대하므로 두 지역이 None으로 남았고, 저장분 정합 검사가 null을
0으로 세면서 17시도 합이 전국보다 작아졌다. 그 검사는 배포 게이트라 배치가
9/8·9/9·9/10 세 회차 연속 멈췄다.

같은 날 모델이 광주·전남을 '전남광주' 한 판정 단위로 통합했다(e2ba8eb). 그 뒤로
'전남광주'는 병합이 아니라 **정상 지역**이고 탐지기도 그렇게 본다. 이 가드가 지키는
것은 그 특정 이름이 아니라 "다음에 또 다른 조합이 합쳐졌을 때"다.

⚠️ 첫 판은 '전남광주'와 17시도 목록을 하드코딩했다가, 모델이 바뀌면서 그대로
빨개져 **9/10 14:52 배치를 막았다** — 고치려던 바로 그 게이트를 이 시험이 다시
막은 것이다. 그래서 지금은 지역 목록을 모델(sido_zones.ORDER)에서 파생하고, 병합
이름도 현재 지역 둘을 붙여 합성한다. 모델이 다시 바뀌어도 이 시험은 유효하다.

⚠️ 초록불만 보고 넘기지 말 것. 가드를 빼고 돌려서 빨개지는지 확인해야 한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U  # noqa: E402
import sido_zones as SZ      # noqa: E402

# 현재 모델의 판정 단위(집계 제외). 손 목록을 두면 모델 재편 때 이 시험만 낡는다.
ZONES = [z for z in SZ.ORDER if z not in SZ.AGG]
AGG_ROWS = ['총계', '수도권소계', '지방소계', '기타광역시', '기타지방']


def _pair():
    """현재 지역 둘을 골라 합친 이름을 만든다. 합성 이름이 실제 지역과 겹치면 안 된다."""
    a, b = ZONES[0], ZONES[1]
    merged = a + b
    assert merged not in ZONES, '합성 이름이 실제 지역과 겹친다 — 다른 쌍을 골라야 한다'
    return a, b, merged


def test_detects_a_merged_row_built_from_current_zones():
    a, b, merged = _pair()
    names = AGG_ROWS + [z for z in ZONES if z not in (a, b)] + [merged]
    assert U.merged_sido_rows(names) == {merged: [a, b]}


def test_current_zone_names_are_never_flagged():
    """모델에 있는 이름은 그 자체로 정상이다 — '전남광주'가 통합 뒤 여기에 들어온다."""
    assert U.merged_sido_rows(ZONES + AGG_ROWS) == {}


def test_no_false_positive_on_sigungu_names():
    """시군구 이름은 시도 이름을 하나만 품으므로 병합이 아니다."""
    assert U.merged_sido_rows(['광주시', '제주시', '남양주시', '전주시', '성남시']) == {}


def test_generalizes_beyond_one_pair():
    """다음에 다른 조합을 합쳐도 잡혀야 한다 — 이름을 박아 두지 않았다."""
    c, d = ZONES[2], ZONES[3]
    e, f = ZONES[4], ZONES[5]
    got = U.merged_sido_rows([c + d, e + f])
    assert got == {c + d: [c, d], e + f: [e, f]}


def test_merged_month_is_dropped_and_others_survive():
    a, b, merged = _pair()
    out = {
        (2026, 6): dict({z: 100 for z in ZONES}, 전국=100 * len(ZONES)),
        (2026, 7): dict({z: 100 for z in ZONES if z not in (a, b)},
                        전국=100 * len(ZONES), **{merged: 200}),
    }
    dropped = U.drop_unsplittable_months('준공', out)
    assert dropped == [(2026, 7)], '병합된 달을 버리지 않았다'
    assert sorted(out) == [(2026, 6)], '정상인 달까지 버렸다'


def test_kept_when_source_keeps_children_under_the_merged_name():
    """상위 묶음만 새로 생기고 하위 지역이 함께 오면 분해가 가능하므로 받는다.

    R-ONE이 2026-07에 '전남광주>광주' 형태로 그렇게 했다. 그 경우까지 버리면
    멀쩡한 달을 잃는다.
    """
    a, b, merged = _pair()
    out = {(2026, 7): dict({z: 100 for z in ZONES}, 전국=100 * len(ZONES), **{merged: 200})}
    assert U.drop_unsplittable_months('준공', out) == []
    assert sorted(out) == [(2026, 7)]

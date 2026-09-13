# -*- coding: utf-8 -*-
"""판정 옆 비율 문구 (2026-09-13 PM 요청 ①).

경기 리포트가 판정은 '균형'인데 바로 아래 '누적 순부족 50,579세대'라 반대로 읽혔다.
등급은 '앞으로 H분기 필요량 대비 누적 순부족의 비율'로 자르는데 화면에 그 비율이
없었다. 비율을 판정 옆에 보여줘서 푼다. 이 시험이 지키는 것은 셋이다.

① 문구의 숫자는 ratio에서만 나온다.
② 문구는 한 곳(sido_zones)에서만 만든다 — 홈 JS가 다시 만들지 않는다.
③ 판정 규칙 문장의 숫자는 GRADE_CUTS에서 나온다.

⚠️ 생성된 페이지 내용을 라이브 데이터로 단정하지 않는다. 배치는 pytest를 페이지 생성보다
먼저 돌리므로 그 시점의 페이지는 지난 회차 것이다. 그렇게 짜면 비율이 바뀌는 주마다
배치가 멈춘다.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sido_zones as SZ  # noqa: E402
import make_sido_pages as P  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')


def _adv():
    src = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    return json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S).group(1))


def test_percent_is_the_ratio_itself():
    for r in (0.02, 0.165, 0.49, 0.6, 0.97, 1.01, 1.79):
        t = SZ.ratio_text(r)
        assert ('%d%%' % int(round(r * 100))) in t, '%s → %s: 비율과 다른 숫자' % (r, t)
        assert '부족' in t


def test_shortfall_beyond_need_stays_in_percent():
    """'1.0배'는 '딱 같다'로 읽힌다(울산 1.012). 규칙 문장과 단위도 맞춘다."""
    assert '139%' in SZ.ratio_text(1.389) and '배' not in SZ.ratio_text(1.389)
    assert '101%' in SZ.ratio_text(1.012)


def test_surplus_reads_as_surplus():
    t = SZ.ratio_text(-0.19)
    assert '19%' in t and '여유' in t and '부족' not in t


def test_near_zero_does_not_invent_a_direction():
    t = SZ.ratio_text(0.004)
    assert '거의 같' in t and '부족' not in t and '여유' not in t


def test_sign_word_matches_sign_everywhere():
    for i in range(-150, 250):
        r = i / 100.0
        t = SZ.ratio_text(r)
        pct = int(round(r * 100))
        assert ('부족' in t) == (pct >= 1), '%s → %s' % (r, t)
        assert ('여유' in t) == (pct <= -1), '%s → %s' % (r, t)


def test_horizon_follows_H_instead_of_saying_three_years():
    """착공표가 한 달 늦으면 H가 11이 된다. 그때 '3년'이라고 쓰면 거짓이다."""
    assert '3년' in SZ.ratio_text(0.2, SZ.LEAD_Q)
    assert '3년' not in SZ.ratio_text(0.2, SZ.LEAD_Q - 1)


def test_stored_rows_carry_the_text_for_their_own_ratio():
    adv = _adv()
    H = adv['sido']['H']
    for z in adv['sido']['zones']:
        assert z.get('rtxt') == SZ.ratio_text(z['ratio'], H), \
            '%s: 저장된 문구가 저장된 비율과 다르다 — --seed-sido를 다시 돌릴 것' % z['z']


def _mid(lo, hi):
    return (lo + hi) / 2.0


def test_rule_sentence_numbers_come_from_the_cuts(monkeypatch):
    c = SZ.GRADE_CUTS
    for r in (c[0] + 0.3, _mid(c[1], c[0]), _mid(c[2], c[1]), _mid(c[3], c[2]), c[3] - 0.3):
        row = {'ratio': r, 'grade': SZ.grade(r)}
        line = P.verdict_line(row, SZ.LEAD_Q)
        assert SZ.ratio_text(r, SZ.LEAD_Q, full=True) in line
        assert P.GRADE_TXT[row['grade']][0] in line, '판정 문장에 등급 이름이 없다'
    # 컷을 옮기면 문장이 따라 바뀌어야 한다 — 숫자가 박혀 있지 않다는 증거
    monkeypatch.setattr(SZ, 'GRADE_CUTS', (2.0, 1.2, 0.6, 0.0))
    assert '60%' in P.verdict_line({'ratio': 0.3, 'grade': 'g1'}, SZ.LEAD_Q)


def test_balance_line_no_longer_says_enough_is_coming():
    """모순의 원문. g1에 '필요한 만큼 들어오고 있습니다'가 붙어 있었다."""
    r = 0.165
    line = P.verdict_line({'ratio': r, 'grade': SZ.grade(r)}, SZ.LEAD_Q)
    assert '필요한 만큼' not in line
    assert '%d%%' % int(round(r * 100)) in line and '균형' in line


def test_home_reads_the_baked_text_instead_of_rebuilding_it():
    src = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    assert 'z.rtxt' in src, '홈 요약 카드가 비율 문구를 읽지 않는다'
    assert not re.search(r'z\.ratio\s*\*', src), '홈이 비율 문구를 따로 계산한다 — 이중 구현'


def test_inner_spread_exemptions_are_real_regions():
    for z in P.NO_INNER_UNITS:
        assert z in SZ.ORDER and z not in SZ.AGG, '%s는 모델에 없는 지역이다' % z

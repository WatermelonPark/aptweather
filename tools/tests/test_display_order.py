# -*- coding: utf-8 -*-
"""시도 목록 표시 순서를 정본 하나(sido_zones.DISPLAY_ORDER)로 묶고, 모델과의 일치를 고정한다.

대표 결정(2026-09-13): 시도 목록은 부족 순이 아니라 관심 지역 순으로 고정한다. 부족한 곳이
지방·제주일 수 있는데 그곳이 곧 관심 지역은 아니다.

  목록 표시(허브·'다른 지역' 격자·홈 표 모드)  → DISPLAY_ORDER
  순위(블로그 공급 부족 순위표)                 → zone_order()
  정부 표와 대조하는 화면(/monthly/)            → ORDER (발표 원천 순서)

손으로 적은 목록이라 모델이 바뀌면 따라오지 않는다. 9/10 광주·전남 통합 같은 변경이 오면
여기가 먼저 빨개져야 한다.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sido_zones as SZ  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def test_display_order_covers_the_model_exactly():
    assert sorted(SZ.DISPLAY_ORDER) == sorted(SZ.ORDER), (
        'DISPLAY_ORDER 가 모델 지역과 다르다: %s' % sorted(set(SZ.DISPLAY_ORDER) ^ set(SZ.ORDER)))
    assert len(set(SZ.DISPLAY_ORDER)) == len(SZ.DISPLAY_ORDER), '중복 지역이 있다'


def test_aggregates_come_first():
    assert SZ.DISPLAY_ORDER[:3] == list(SZ.AGG), '집계 3곳이 맨 위가 아니다'


def test_calc_emits_zones_in_display_order():
    """홈 표 모드와 '다른 지역' 격자는 calc() 가 낸 zones 순서를 그대로 쓴다."""
    st = SZ._load_stats()
    got = [z['z'] for z in SZ.calc(st)['zones']]
    want = [z for z in SZ.DISPLAY_ORDER if z in got]
    assert got == want, 'calc() zones 가 표시 순서가 아니다: %s' % got


def test_live_payload_uses_display_order():
    """배포되는 페이로드가 표시 순서인가 — 홈 표 모드가 이 순서를 그린다."""
    s = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    adv = json.loads(re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});', s, re.S).group(1))
    got = [z['z'] for z in adv['sido']['zones']]
    assert got == [z for z in SZ.DISPLAY_ORDER if z in got], '페이로드 zones 순서가 표시 순서가 아니다: %s' % got


def test_hub_lists_sido_in_display_order_without_sort_toggle():
    h = io.open(os.path.join(ROOT, 'zone', 'index.html'), encoding='utf-8').read()
    assert 'sido-sort' not in h, '허브에 정렬 토글이 남아 있다 — 목록은 순위가 아니다'
    m = re.search(r'<div class="zlinks" id="sido-list">(.*?)</div>', h, re.S)
    assert m, '허브 시도 목록을 찾지 못했다'
    got = re.findall(r'<b>([^<]+)</b>', m.group(1))
    sido = [z for z in SZ.DISPLAY_ORDER if z not in SZ.AGG]
    assert got == sido, '허브 시도 순서가 표시 순서가 아니다: %s' % got


def test_ranking_still_uses_zone_order():
    """목록과 순위는 다른 질문이다 — 블로그 순위표까지 고정 순서로 바뀌면 안 된다."""
    src = io.open(os.path.join(ROOT, 'tools', 'make_naver_post.py'), encoding='utf-8').read()
    assert 'SZ.zone_order(' in src, '블로그 순위가 zone_order() 를 쓰지 않는다'


def test_monthly_keeps_source_order():
    """정부 표와 대조하는 화면은 발표 원천 순서(ORDER)를 유지한다."""
    src = io.open(os.path.join(ROOT, 'tools', 'make_monthly_page.py'), encoding='utf-8').read()
    assert 'ORDER = list(SZ.ORDER)' in src, '/monthly/ 가 원천 순서를 쓰지 않는다'


def test_no_ranking_wording_on_the_list_link():
    for rel in ('index.html', os.path.join('tools', 'make_naver_post.py')):
        s = io.open(os.path.join(ROOT, rel), encoding='utf-8').read()
        assert '시도별 공급 순위' not in s and '시도 공급 순위' not in s, (
            '%s: 목록 링크에 "순위"가 남아 있다' % rel)

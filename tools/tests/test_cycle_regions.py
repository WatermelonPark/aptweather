# -*- coding: utf-8 -*-
"""/cycle/의 재생성 차트가 모델의 지역을 다 담는가.

2026-09-12 실사고: `refresh_cycle_data.SIDO17`이 옛 손 목록(광주·전남)을 들고
있었고, 전세가율 차트를 만드는 `build_jratio`가 **모르는 지역을 조용히 건너뛰는**
구조였다. 통합 뒤 '전남광주'가 목록에 없으니 그대로 빠진 채 배포됐다 — 차트에
지역 하나가 통째로 없는데 아무도 빨개지지 않았다.

⚠️ 이 시험은 **재생성되는 것만** 본다. 고리 검증(sync·link3_regional 등)은 통합
이전에 한 번 돌린 붙박이 값이라 광주·전남이 따로 들어 있는 게 정상이다. 그건
'그때 그랬다'는 기록이므로 바꾸지 않는다.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sido_zones as SZ  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
PAGE = os.path.join(ROOT, 'cycle', 'index.html')


def _D():
    s = io.open(PAGE, encoding='utf-8').read()
    return json.loads(re.search(r'const D=(\{.*?\});', s, re.S).group(1)), s


def test_regenerated_chart_covers_every_model_region():
    D, _ = _D()
    want = {z for z in SZ.ORDER if z not in SZ.AGG}
    got = {r['region'] for r in D['jratio_level']}
    missing = want - got
    assert not missing, '전세가율 차트에 빠진 지역: %s' % ', '.join(sorted(missing))


def test_generator_does_not_hardcode_regions():
    """손 목록이 다시 들어오면 같은 사고가 반복된다."""
    src = io.open(os.path.join(ROOT, 'tools', 'refresh_cycle_data.py'), encoding='utf-8').read()
    assert 'SZ.ORDER' in src, '지역 목록이 모델에서 오지 않는다'
    hard = re.findall(r"SIDO\w*\s*=\s*\[\s*'", src)
    assert not hard, '지역을 손으로 나열한 자리가 있다'


def test_headline_counts_match_the_model():
    """머리글의 '시도 N개'는 현재 모델 수여야 한다. 본문의 고리 검증 15곳은
    통합 이전 표본이라 그대로 두되, 그 사실을 밝히고 있어야 한다."""
    _, s = _D()
    n = len([z for z in SZ.ORDER if z not in SZ.AGG])
    assert '%d개 시도 · 지역 4곳' % n in s, '머리글 시도 수가 모델과 다르다'
    assert '합치기 전 기준' in s, '고리 검증 표본이 통합 이전이라는 표시가 없다'

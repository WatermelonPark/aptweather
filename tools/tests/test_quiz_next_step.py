# -*- coding: utf-8 -*-
"""퀴즈 결과 화면이 공급 지도로 이어지고, 지키지 않는 출처 약속을 하지 않는지 잠근다.

대표 결정(요청서 2026-09-13).
  1. 퀴즈가 데려온 사람이 핵심 상품(공급 지도)으로 넘어가게 한다. 전에는 세 결과
     화면의 다음 단계가 다른 퀴즈·사이클·통계뿐이었다.
  2. 해설 대부분에 기관명이 없는데 화면이 "근거가 붙는다", "데이터로 검증"을 약속했다.
     출처를 붙이는 쪽이 아니라 **약속을 지우는 쪽**으로 정했다.

⚠️ 사이클 리포트를 설명하는 "데이터로 검증한 아파트 사이클 6개 고리"는 남긴다. 리포트는
   실제로 데이터 검증을 싣고 있어서 지킬 수 있는 약속이다.
"""
import io
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def _read(*parts):
    return io.open(os.path.join(ROOT, *parts), encoding='utf-8').read()


def _next_step_blocks():
    """nextStepHTML() 안의 세트별 블록. 순서: beginner, calc, investor(기본)."""
    s = _read('index.html')
    i = s.index('function nextStepHTML(){')
    j = s.index('function showResult(){', i)
    body = s[i:j]
    return re.findall(r'<div class="nextstep">(.*?)</div>`;', body, re.S)


def test_each_result_screen_leads_to_the_map_first():
    blocks = _next_step_blocks()
    assert len(blocks) == 3, '결과 화면 블록을 %d개 찾았다 — 구조가 바뀌었으면 이 시험도 고칠 것' % len(blocks)
    for frm, blk in zip(('beginner', 'calc', 'investor'), blocks):
        first = re.search(r'<(a|button) class="ns-btn(?: ghost)?"[^>]*>', blk)
        assert first, '%s: 버튼이 없다' % frm
        tag = first.group(0)
        assert tag.startswith('<a class="ns-btn"'), (
            '%s: 첫 버튼이 진한 <a> 가 아니다 — 인앱 브라우저에서 길게 눌러 열 수 있어야 한다' % frm)
        assert 'href="/#score"' in tag, '%s: 첫 버튼이 공급 지도(/#score)로 가지 않는다' % frm
        assert "to:'map'" in tag and "from:'%s'" % frm in tag, '%s: next_step 측정이 빠졌다' % frm
        assert "tbView('map')" in tag, (
            '%s: 지도 모드로 되돌리지 않는다 — 표로 보다 온 사람은 표로 도착한다' % frm)


def test_only_one_dark_button_per_result_screen():
    """진한 버튼이 둘이면 '첫 번째가 다음 단계'라는 위계가 사라진다."""
    for blk in _next_step_blocks():
        dark = re.findall(r'class="ns-btn"', blk)
        assert len(dark) == 1, '진한 버튼이 %d개다' % len(dark)


def test_link_button_is_styled_like_a_button():
    css = _read('app.css')
    assert re.search(r'a\.ns-btn\{[^}]*text-align:center', css), 'a.ns-btn 가운데 정렬이 없다'
    assert re.search(r'a\.ns-btn\{[^}]*text-decoration:none', css), 'a.ns-btn 밑줄이 남는다'


PROMISES = (
    ('index.html', 'KOSIS·한국은행·국토부 데이터로 검증한'),
    ('index.html', '근거를 직접 확인해보자'),
    ('burini-test/index.html', '국토부 데이터로 검증한 진짜 답'),
    ('investor-test/index.html', '문항마다 근거가 붙는다'),
    ('redev-test/index.html', '정답마다 근거가 붙는다'),
)


def test_unkept_source_promises_are_gone():
    left = ['%s: %s' % (f, t) for f, t in PROMISES if t in _read(*f.split('/'))]
    assert not left, '지키지 않는 출처 약속이 남았다: %s' % '; '.join(left)


def test_cycle_report_description_is_kept():
    """리포트 설명은 지킬 수 있는 약속이라 남긴다 — 과하게 지워지지 않았는지."""
    for f in ('burini-test', 'investor-test', 'redev-test'):
        assert '데이터로 검증한 아파트 사이클 6개 고리' in _read(f, 'index.html'), (
            '%s: 사이클 리포트 설명까지 지워졌다' % f)

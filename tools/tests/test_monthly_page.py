# -*- coding: utf-8 -*-
"""/monthly/ — '이달의 공급 통계' 화면의 계약을 못 박는다.

이 화면의 값어치는 **순서와 기준월 표시**에 있다(PM 요청서 2026-08-26).
순서는 제품 그 자체라 재량으로 바꾸면 안 되고, 기준월이 없으면 "지금 보는 게
이번 달 발표분"이라는 확신을 못 준다 — 그게 이 화면의 존재 이유다.
광주·전남 분리도 마찬가지다. 정부 화면이 통합으로 내보내는 구간이 있어서
우리가 원자료의 시도 단위 값을 그대로 꺼내 보여주는 것이 이 화면의 약속이다.
"""
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
PAGE = os.path.join(ROOT, 'monthly', 'index.html')

# 요청서가 못 박은 순서. 이 배열을 고치는 건 제품 결정이지 리팩터링이 아니다.
ORDER = ['price', 'permits', 'moveins', 'unsold', 'jeonse']


@pytest.fixture(scope='module')
def html():
    if not os.path.exists(PAGE):
        pytest.skip('/monthly/ 아직 생성 전')
    return io.open(PAGE, encoding='utf-8').read()


def _sections(h):
    return re.findall(r'<section id="([a-z]+)"', h)


def test_five_indicators_in_fixed_order(html):
    assert _sections(html) == ORDER, (
        '지표 순서가 바뀌었다. 이 순서는 요청서가 못 박은 제품 정의다 — '
        '바꾸려면 PM 합의가 먼저다.')


def test_every_indicator_shows_its_basis_month_and_source(html):
    """기준월·원천이 빠지면 '이번 달 발표분'이라는 확신이 사라진다."""
    for sid in ORDER:
        seg = html.split('id="%s"' % sid, 1)[1].split('</section>', 1)[0]
        m = re.search(r'<p class="basis"><b>([^<]+)</b> 기준 · ([^<]+)</p>', seg)
        assert m, '%s: 기준월·원천 줄이 없다' % sid
        assert m.group(1).strip(), '%s: 기준월이 비었다' % sid
        assert len(m.group(2).strip()) > 3, '%s: 원천이 비었다' % sid


def test_gwangju_and_jeonnam_are_separate(html):
    """정부 화면의 통합 표기('전남광주')를 따라가지 않는다."""
    seg = html.split('id="price"', 1)[1].split('</section>', 1)[0]
    names = re.findall(r'<tr[^>]*><td>([^<]+)</td>', seg)
    assert '광주' in names and '전남' in names, '광주·전남이 분리로 안 나온다'
    merged = [n for n in names if re.search(r'전남광주|광주전남', n)]
    assert not merged, '통합 표기가 섞였다: %s' % merged


def test_no_person_or_lecture_reference(html):
    """공개 통계의 편한 뷰까지가 우리 선이다(하드 룰)."""
    for bad in ('신쌤', '신성철', 'shinssam', '강의', '커뮤니티'):
        assert bad not in html, '금지된 표현이 들어 있다: %s' % bad


def test_entry_is_measured(html):
    """진입이 GA에 안 잡히면 이 화면의 효과를 잴 수 없다."""
    assert "screen_name:'monthly'" in html, '진입 측정이 없다'


def test_linked_from_sitemap_and_home():
    sm = io.open(os.path.join(ROOT, 'sitemap.xml'), encoding='utf-8').read()
    assert '/monthly/</loc>' in sm, 'sitemap에 없다 — 색인이 안 된다'
    home = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    assert 'href="/monthly/"' in home, '홈에서 도달할 수 없다'


def test_batch_generates_and_commits_it():
    """생성기를 배치에 걸어도 커밋 대상(TARGETS)에 없으면 라이브에 안 나간다.

    같은 함정이 실재했다 — 산출물이 만들어지는데 git add 목록에 없어 매 회차
    조용히 버려지는 구조다. 둘을 함께 잠근다.
    """
    y = io.open(os.path.join(ROOT, '.github', 'workflows', 'update-cloud.yml'),
                encoding='utf-8').read()
    assert 'tools/make_monthly_page.py' in y, '배치가 이 화면을 만들지 않는다'
    m = re.search(r'TARGETS="([^"]+)"', y)
    assert m and 'monthly' in m.group(1).split(), 'TARGETS에 monthly가 없다'

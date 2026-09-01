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
    # 행 머리는 <th scope="row">다 — 20열 표에서 스크린리더가 '어느 지역'인지
    # 말하게 하려고 td에서 승격시켰다(2026-09-02). 마크업이 또 바뀌면 여기도 같이.
    names = re.findall(r'<tr[^>]*><th scope="row">([^<]+)</th>', seg)
    assert '광주' in names and '전남' in names, '광주·전남이 분리로 안 나온다'
    merged = [n for n in names if re.search(r'전남광주|광주전남', n)]
    assert not merged, '통합 표기가 섞였다: %s' % merged


def test_no_person_or_lecture_reference(html):
    """공개 통계의 편한 뷰까지가 우리 선이다(하드 룰).

    ⚠️ 특정 인명은 **여기에 적지 않는다.** 저장소가 PUBLIC이고 tools/까지
    서빙되므로, 금지어 목록에 이름을 박는 것 자체가 그 이름을 공개하는 일이다
    (이 파일이 실제로 그랬다 — 2026-09-01에 걷어냈다). 인명은 릴리스 게이트인
    저장소 전체 grep이 맡고, 여기서는 이 화면에 들어오면 안 되는 **표현 유형**을
    막는다. 사람 이름을 쓰면 대개 이 단어들이 함께 붙는다.
    """
    for bad in ('강의', '강사', '커뮤니티', '수강'):
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


def test_no_dead_sort_affordances(html):
    """누르면 아무 일도 없는 버튼을 탭 순서에 두지 않는다.

    SHELL의 정렬 스크립트는 `getElementById('utable')` 하나에만 붙는데 이 페이지엔
    그 id가 없다. 그런데 표두에 tabindex/role="button"/aria-sort를 달아 두면
    스크린리더는 '버튼'이라 읽고 키보드는 17번 멈추는데 눌러도 아무 일이 없다
    (2026-09-02 리뷰). 정렬을 넣으려면 id와 함께 붙일 것.
    """
    body = html.split('</head>', 1)[1]
    for attr in ('tabindex', 'role="button"', 'aria-sort'):
        bad = [m for m in re.findall(r'<th[^>]*>', body) if attr in m]
        assert not bad, '표두에 %s가 달렸는데 정렬 스크립트가 안 붙는다: %s' % (attr, bad[:2])


def test_moveins_columns_name_the_actual_quarters(html):
    """'이번/다음 분기' 같은 상대 표현은 한 칸씩 밀린다.

    act[-1]은 끝난 분기, fut[0]이 지금 진행 중인 분기라 상대 표현을 쓰면
    진행 중인 분기가 '다음'이 되고 그 번호는 화면에 아예 안 나왔다.
    """
    seg = html.split('id="moveins"', 1)[1].split('</section>', 1)[0]
    heads = re.findall(r'<th scope="col">([^<]*)</th>', seg)
    quarters = [h for h in heads if re.search(r'\d{4}Q[1-4]', h)]
    assert len(quarters) >= 2, '분기명이 열 이름에 없다: %s' % heads
    assert not [h for h in heads if '이번 분기' in h or '다음 분기' in h],         '상대 표현이 남아 있다: %s' % heads


def test_page_has_its_own_publication_date(html):
    """make_indicator_pages.PUBLISHED를 물려쓰면 URL이 없던 날짜로 발행됐다고 선언한다."""
    m = re.search(r'"datePublished": "([0-9-]+)"', html)
    assert m, 'datePublished가 없다'
    assert m.group(1) >= '2026-09-01', (
        'datePublished가 %s다 — 이 URL이 생기기 전이다(다른 페이지 날짜를 물려썼다)'
        % m.group(1))


def test_basis_sort_key_orders_months_numerically():
    """한글 라벨 어휘 비교는 10월을 9월보다 작다고 본다.

    max()가 그걸 그대로 쓰면 10월부터 dateModified와 sitemap lastmod가 9월에
    얼어붙는데 표는 계속 바뀌므로 아무도 못 알아챈다(2026-09-02 리뷰).
    """
    import sys, os as _os
    sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..'))
    import make_monthly_page as M

    # 사고 재현: 라벨끼리 비교하면 9월이 이긴다
    assert max(['2026년 10월', '2026년 9월']) == '2026년 9월'
    # sort_key를 끼우면 바로잡힌다
    assert max(['2026.09', '2026.10'], key=M.sort_key) == '2026.10'
    assert M.sort_key('2026.9') == '2026-09'
    assert M.sort_key('2026Q3') == '2026-09', '분기는 그 분기 마지막 달로'
    assert M.sort_key('2026Q4') > M.sort_key('2026.09')

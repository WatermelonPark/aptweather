# -*- coding: utf-8 -*-
"""사이클 '검증 대상 곳 수'를 말하는 세 자리가 같은 값을 말하는지 고정한다.

같은 대상을 재는 코드가 셋이다.
  · 정본      make_naver_post.CYCLE_SYNC_N  (데이터에서 세어 나온다)
  · 리포트    cycle/index.html              (생성물)
  · 홈 배너   index.html                    (손으로 관리하는 파일)

홈은 생성 대상이 아니라 파생을 걸 수 없다. 손으로 적을 수밖에 없으니 대신 여기서
일치를 잠근다. 2026-09-13 까지 홈만 15로 남아 있었고, 그 배너를 눌러 들어간
/cycle/ 은 14라고 말했다 — 클릭 한 번에 모순이 보이는 상태였다.

⚠️ /cycle/ 에는 성격이 다른 두 수가 있다. 섞으면 안 된다.
     커버리지  16개 시도  = 사이트가 다루는 시도 전체(sido_zones 기준)
     검증 대상 14개 시도  = 고리 검증에 쓴 표본(세종·제주 제외)
   한 괄호에 섞어 '16 중 15'처럼 쓰면 둘 다 틀려 보인다. 데이터 세션이 2026-09-12 에
   그 괄호를 풀어 둘을 갈라놨다(355d767).
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sido_zones as SZ  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
COVERAGE = len([z for z in SZ.ORDER if z not in SZ.AGG])   # 16 — 섞이면 안 되는 다른 수


def _canon():
    """정본 곳 수. 데이터에서 세어 나오므로 import 로만 얻는다."""
    import make_theory_post as M
    return M.CYCLE_SYNC_N


def _counts(rel):
    """파일 안의 'N개 시도' 를 전부 뽑는다."""
    s = io.open(os.path.join(ROOT, rel), encoding='utf-8', errors='replace').read()
    return [int(x) for x in re.findall(r'(\d+)개 시도', s)]


def test_canon_is_derived_not_hardcoded():
    """정본이 상수로 박혀 있으면 이 시험 전체가 무의미해진다."""
    s = io.open(os.path.join(ROOT, 'tools', 'make_naver_post.py'), encoding='utf-8').read()
    assert re.search(r'CYCLE_SYNC_N\s*=\s*len\(', s), (
        'CYCLE_SYNC_N 이 len() 파생이 아니다 — 데이터에서 세어야 한다')
    assert _canon() >= 2, '곳 수가 비정상이다'


def test_home_banner_matches_the_canon():
    """홈 배너가 정본과 다르면, 배너를 눌러 들어간 리포트와 말이 갈린다."""
    n = _canon()
    s = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    m = re.search(r'<div class="hs-kicker">(\d+)개 시도 · 20년</div>', s)
    assert m, '홈 사이클 배너를 찾지 못했다 — 문구가 바뀌었으면 이 시험도 고칠 것'
    assert int(m.group(1)) == n, (
        '홈 배너 %s개 ≠ 정본 %d개' % (m.group(1), n))


def test_cycle_page_says_one_number_for_the_sample():
    """리포트의 '검증 대상' 수가 전부 정본과 같아야 한다.

    커버리지(%d개)는 성격이 다른 수라 제외한다. 그 둘을 뺀 나머지가 여러 값이면
    한 페이지 안에서 표본 크기가 갈리고 있는 것이다.
    """ % COVERAGE
    n = _canon()
    got = [c for c in _counts(os.path.join('cycle', 'index.html')) if c != COVERAGE]
    assert got, '/cycle/ 에서 검증 대상 곳 수를 찾지 못했다'
    bad = sorted(set(c for c in got if c != n))
    assert not bad, '/cycle/ 이 정본 %d 말고 %s 도 말한다' % (n, bad)


def test_theory_post_never_hardcodes_the_sample_size():
    """원고 생성기는 같은 파일 안에서도 빠짐없이 정본을 써야 한다.

    2026-09-13 이전에는 제목만 정본을 쓰고 본문 세 자리가 15로 박혀 있었다.
    발행하면 제목은 14, 본문은 15라고 말하는 글이 나간다.
    """
    s = io.open(os.path.join(ROOT, 'tools', 'make_theory_post.py'), encoding='utf-8').read()
    # 문자열 안에 박힌 'N개 시도'. %(sync_n)d / %d 로 쓴 자리는 잡히지 않는다.
    hard = sorted(set(re.findall(r'(\d+)개 시도', s)))
    allowed = {str(COVERAGE)}       # 커버리지 문장은 다른 수라 허용
    bad = [h for h in hard if h not in allowed]
    assert not bad, (
        '원고에 곳 수가 박혀 있다: %s — CYCLE_SYNC_N(%%(sync_n)d)로 바꿀 것' % bad)


def test_the_two_numbers_are_not_the_same():
    """커버리지와 표본이 같은 값이면 이 시험들이 서로를 못 가른다.

    지금은 16 vs 14 라 갈리는데, 언젠가 같아지면 위 검사들이 조용히 무의미해진다.
    그때는 이 시험이 먼저 깨져서 알려 준다.
    """
    assert _canon() != COVERAGE, (
        '검증 대상(%d)과 커버리지(%d)가 같아졌다 — 위 검사들의 전제가 무너졌으니 '
        '구분 방법을 다시 정할 것' % (_canon(), COVERAGE))

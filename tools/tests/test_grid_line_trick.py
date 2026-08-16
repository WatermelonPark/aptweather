# -*- coding: utf-8 -*-
"""그리드에서 '컨테이너 배경 = 선 색' 트릭을 금지한다.

이 트릭은 컨테이너에 `background: var(--line)`을 깔고 `gap: 1px`로 그 색을 1px씩
드러내 격자선을 만든다. flex에서는 멀쩡하다 — 항목이 줄을 꽉 채우지 않아도 남는
자리에 트랙이 생기지 않기 때문이다. **grid에서는 다르다.** 항목 수가 열 수의
배수가 아니면 마지막 줄에 셀이 없는 자리가 남고, 그 자리를 덮을 셀이 없으니
컨테이너 배경(=선 색)이 큰 덩어리로 그대로 보인다.

같은 결함이 두 번 나왔다:
  · `.zgrid`  — 카드 5개가 4열에 들어가 둘째 줄 빈 칸 3개 (2026-08-15 수정)
  · `.zlinks` — 항목 19개가 5열에 들어가 마지막 줄 빈 칸 1개 (2026-08-16 수정)

대안은 셀이 스스로 선을 그리는 것이다(`box-shadow: 0 0 0 1px var(--line)`) —
레이아웃을 밀지 않아 auto-fit/auto-fill 열 계산에도 영향이 없고, 빈 자리에는
아무것도 안 그려진다.

⚠️ 이 파일의 첫 판(2026-08-16)은 **세 가지 방법으로 그냥 뚫렸다**(같은 날 리뷰):
`display: grid`처럼 콜론 뒤에 공백만 넣어도, 미디어쿼리로 나중에 배경을 덮어써도,
`background-color`로 쓰기만 해도 통과했다. 선언을 정규화하지 않고 첫 규칙만 봤기
때문이다. 이 저장소가 반복해 겪은 '안 도는 방어선'이라, 아래는 셋 다 주입해
실패하는 것을 확인하고 고친 판이다. 손볼 일이 생기면 같은 주입을 다시 해볼 것.
"""
import glob
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
CSS = os.path.join(ROOT, 'app.css')

# `background` 또는 `background-color`의 값에 선 색 토큰이 들어간 선언.
# 단축 표기(background: var(--line) no-repeat)도 잡으려고 값 전체를 본다.
LINE_BG = re.compile(r'background(?:-color)?:[^;]*var\(--line\)')
GRID = re.compile(r'display:(?:inline-)?grid\b')
CELL_LINE = re.compile(r'box-shadow:[^;]*0 0 0 1px var\(--line\)')


def _norm(decls):
    """콜론·세미콜론 주변 공백만 걷는다.

    값 안의 공백은 의미가 있어(`0 0 0 1px`) 통째로 지우면 안 된다. 첫 판은
    `display:grid`를 원문 그대로 찾아서 `display: grid` 한 칸에 뚫렸다.
    """
    d = re.sub(r'\s*([:;])\s*', r'\1', decls)
    return re.sub(r'\s+', ' ', d).strip()


def _sources():
    """(라벨, CSS 텍스트) — app.css와 HTML 안의 인라인 <style>을 모두 본다.

    지역 20장을 비롯한 생성 페이지가 인라인 스타일을 갖는다. app.css만 보면
    거기에 같은 트릭을 새로 쓰는 걸 못 잡는다.
    """
    out = [('app.css', io.open(CSS, encoding='utf-8').read())]
    for pat in ('*.html', '*/index.html', 'zone/*/index.html'):
        for p in glob.glob(os.path.join(ROOT, pat)):
            if os.sep + 'drafts' + os.sep in p or os.sep + 'art_raw' + os.sep in p:
                continue
            t = io.open(p, encoding='utf-8').read()
            for m in re.finditer(r'<style[^>]*>(.*?)</style>', t, re.S):
                out.append((os.path.relpath(p, ROOT).replace(os.sep, '/'), m.group(1)))
    return out


def _rules(css):
    """(선택자, 정규화된 선언부). 주석은 걷는다 — 예시 코드가 걸리면 안 된다.

    `@media(...){ .x{...} }`의 안쪽 규칙도 그대로 잡힌다(중괄호가 없는 덩어리만
    선택자로 보므로). 미디어쿼리 안에서 배경을 되살리는 우회를 막으려면 필요하다.
    """
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return [(m.group(1).strip(), _norm(m.group(2)))
            for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css)]


def _all_rules():
    out = []
    for label, css in _sources():
        for sel, body in _rules(css):
            out.append((label, sel, body))
    return out


def _decls_for(selector):
    """그 선택자에 붙는 **모든** 규칙의 선언부.

    첫 판은 `next(...)`로 첫 규칙만 봐서, 뒤에 미디어쿼리로 덮어쓰면 못 잡았다.
    """
    return [(lab, body) for lab, sel, body in _all_rules()
            if selector in [s.strip() for s in sel.split(',')]]


def test_no_grid_paints_lines_with_container_background():
    bad = [(lab, sel, body) for lab, sel, body in _all_rules()
           if GRID.search(body) and LINE_BG.search(body)]
    assert not bad, (
        '그리드 컨테이너가 배경으로 격자선을 그린다 — 항목이 열 수로 안 떨어지면 '
        '마지막 줄 빈 칸에 선 색이 덩어리로 드러난다. 셀에 '
        'box-shadow:0 0 0 1px var(--line)를 주고 컨테이너 background는 뺄 것.\n  '
        + '\n  '.join('%s: %s { %s }' % (l, s, b[:80]) for l, s, b in bad))


@pytest.mark.parametrize('sel', ['.zgrid', '.zlinks'])
def test_known_grid_containers_never_get_line_background(sel):
    """미디어쿼리·나중 규칙으로 되살리는 것까지 막는다."""
    rules = _decls_for(sel)
    assert rules, '%s 규칙이 사라졌다' % sel
    bad = [(lab, b) for lab, b in rules if LINE_BG.search(b)]
    assert not bad, '%s가 다시 배경으로 선을 그린다: %s' % (sel, bad)


@pytest.mark.parametrize('sel', ['.zcell', '.zlinks a'])
def test_known_grid_cells_draw_their_own_line(sel):
    """배경만 지우면 격자선이 통째로 사라진다 — 셀이 실제로 선을 그리는지 본다."""
    rules = _decls_for(sel)
    assert rules, '%s 규칙이 사라졌다' % sel
    assert any(CELL_LINE.search(b) for _, b in rules), \
        '%s가 스스로 선을 안 그린다 — 격자선이 사라졌을 수 있다' % sel


def test_guard_actually_sees_the_known_grids():
    """대상이 0건이면 위 시험들이 통과해도 아무것도 안 지킨 것이다."""
    assert len(_all_rules()) > 100, '규칙을 거의 못 읽었다 — 파서가 깨졌다'
    for sel in ('.zgrid', '.zlinks', '.zcell', '.zlinks a'):
        assert _decls_for(sel), '%s를 못 찾는다' % sel

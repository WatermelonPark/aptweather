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

세 번째를 막으려고 조합 자체를 금지한다. 대안은 셀이 스스로 선을 그리는 것이다
(`box-shadow: 0 0 0 1px var(--line)`) — 레이아웃을 밀지 않아 auto-fit/auto-fill
열 계산에도 영향이 없고, 빈 자리에는 아무것도 안 그려진다.

flex는 예외로 둔다(`.map-agg`가 그 경우다). 다만 flex라도 `flex-wrap: wrap`으로
줄바꿈이 일어나면 뒤쪽 여백에 같은 문제가 생길 수 있으니, 그때는 눈으로 확인할 것.
"""
import io
import os
import re

import pytest

CSS = os.path.join(os.path.dirname(__file__), '..', '..', 'app.css')
LINE_BG = 'background:var(--line)'


def _rules():
    """(선택자, 선언부) 목록. 주석은 걷어낸다 — 예시 코드가 걸리면 안 된다."""
    css = io.open(CSS, encoding='utf-8').read()
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    css = re.sub(r'\s*\n\s*', ' ', css)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css)]


def _grid_rules_with_line_bg():
    return [(sel, body) for sel, body in _rules()
            if 'display:grid' in body and LINE_BG in body.replace(' ', '')]


def test_no_grid_paints_lines_with_container_background():
    bad = _grid_rules_with_line_bg()
    assert not bad, (
        '그리드 컨테이너가 배경으로 격자선을 그린다 — 항목이 열 수로 안 떨어지면 '
        '마지막 줄 빈 칸에 선 색이 덩어리로 드러난다. 셀에 '
        'box-shadow:0 0 0 1px var(--line)를 주고 컨테이너 background는 뺄 것.\n  '
        + '\n  '.join('%s { %s }' % (s, b.strip()[:90]) for s, b in bad))


def test_the_two_known_grids_use_cell_shadows():
    """수정한 둘이 되돌아가지 않았는지 직접 확인한다.

    위 금지 규칙만으로는 '컨테이너 배경을 뺐다'까지만 보장하고, 선이 실제로
    그려지는지는 안 본다 — 배경만 지우면 격자선이 통째로 사라진다.
    """
    for sel in ('.zcell', '.zlinks a'):
        got = next((b for s, b in _rules() if s == sel), None)
        assert got is not None, '%s 규칙이 사라졌다' % sel
        # 값 안의 공백은 의미가 있어(0 0 0 1px) 통째로 지우면 안 된다.
        # 선언 사이 공백만 접어 비교한다.
        flat = re.sub(r'\s+', ' ', got).replace('; ', ';')
        assert 'box-shadow:0 0 0 1px var(--line)' in flat, \
            '%s가 스스로 선을 안 그린다 — 격자선이 사라졌을 수 있다' % sel


@pytest.mark.parametrize('sel', ['.zgrid', '.zlinks'])
def test_known_grid_containers_have_no_line_background(sel):
    got = next((b for s, b in _rules() if s == sel), None)
    assert got is not None, '%s 규칙이 사라졌다' % sel
    assert LINE_BG not in got.replace(' ', ''), \
        '%s가 다시 배경으로 선을 그린다' % sel

# -*- coding: utf-8 -*-
"""/cycle/이 싣고 다니는 값이 실제로 쓰이는가, 본문과 어긋나지 않는가.

2026-09-12: `const D`의 키 22개 중 12개를 페이지 어디서도 읽지 않았다. 한때
차트가 있었다가 사라진 자리, 분석만 하고 싣기만 한 값, 배치가 매일 갱신하는데
아무도 보지 않는 평균이 뒤섞여 있었다. 눈에 띄지 않은 이유는 간단하다. 쓰이지
않는 데이터는 틀려도 화면이 멀쩡하기 때문이다. 실제로 그중 하나는 광주·전남
통합 뒤에도 옛 지역명을 안고 있었다.

그래서 두 가지를 지킨다.

1. D에 들어간 키는 페이지 코드가 읽어야 한다. 안 읽을 값이면 싣지 말고
   `tools/data/cycle_analysis.json`에 남긴다.
2. 본문에 글자로 박은 수치는 그 분석 결과와 같아야 한다. 재산정한 뒤 본문을
   고치지 않으면 여기서 걸린다.
"""
import io
import json
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
PAGE = os.path.join(ROOT, 'cycle', 'index.html')
ANALYSIS = os.path.join(ROOT, 'tools', 'data', 'cycle_analysis.json')


def _page():
    s = io.open(PAGE, encoding='utf-8').read()
    m = re.search(r'const D=(\{.*?\});\n', s, re.S)
    assert m, 'cycle 페이지에서 const D를 찾지 못했다'
    return json.loads(m.group(1)), s[:m.start()] + s[m.end():], s


def _analysis():
    if not os.path.exists(ANALYSIS):
        pytest.skip('분석 결과 파일이 없다(rebuild_cycle_analysis.py --write로 만든다)')
    return json.load(io.open(ANALYSIS, encoding='utf-8'))


def test_every_payload_key_is_read_by_the_page():
    D, code, _ = _page()
    dead = [k for k in D
            if not re.search(r'D\.%s\b|D\[.%s.\]' % (re.escape(k), re.escape(k)), code)]
    assert not dead, ('페이지가 읽지 않는 키를 싣고 있다: %s — 차트가 쓰지 않을 값이면 '
                      'tools/data/cycle_analysis.json에 남긴다' % ', '.join(sorted(dead)))


def test_archived_analysis_is_not_also_shipped():
    """같은 숫자를 두 곳에 두면 한쪽만 고쳐질 때 둘이 어긋난다."""
    D, _, _ = _page()
    A = _analysis()
    both = sorted(set(D) & set(A) - {'_extra'})
    shipped = {'sync', 'link1_new', 'link3_regional', 'link6_regional', 'cycle_strength'}
    stray = [k for k in both if k not in shipped]
    assert not stray, '보관용 값이 페이지에도 실려 있다: %s' % ', '.join(stray)


def _minus(v):
    """본문은 음수에 유니코드 빼기표(−)를 쓴다."""
    return ('%.2f' % v).replace('-', '−')


def test_prose_figures_match_the_analysis():
    """본문에 박은 수치가 재산정 결과와 같은가."""
    _, _, s = _page()
    A = _analysis()
    x = A['_extra']
    want = [
        ('검증 지역 수', '%d개 시도' % len(A['sync'])),
        ('동조성 평균', '평균 r %.2f' % x['sync_mean']),
        ('서울 동조성', '서울은 %.2f로 가장 느슨' % x['seoul']['sync']),
        ('고리1 상관', 'r %s · 약 1분기 시차' % _minus(A['link1_new']['r'])),
        ('고리3 강한 지역 평균', '강한 지역 평균 r %.2f' % A['link3_split']['strong_mean']),
        ('리드타임', '과거 %d개월 → 최근 %d개월'
         % (A['leadtime']['old_months'], A['leadtime']['new_months'])),
        ('착공→준공 상관', '가장 단단하다(r %.2f)' % A['leadtime']['all_r']),
        ('인허가→착공 상관', '거의 동시에 움직인다(r %.2f)' % x['l4']['r']),
        ('고리6 유의 지역', '시도 %d/%d 음(-) 유의' % (x['l6_sig'], x['l6_total'])),
        ('고리6 평균', '평균 r %s' % _minus(A['cycle_links'][5]['r'])),
        ('광역시 평균', '광역시는 평균 %s' % _minus(x['l6_scale']['metro'])),
        ('도 평균', '섞인 도는 %s' % _minus(x['l6_scale']['province'])),
        ('금리 상관', '수도권 분기 %d개 · r %s' % (x['rate']['n'], _minus(x['rate']['r']))),
        ('서울 입주 효과', '%s → %s' % (_minus(x['seoul']['l6']),
                                     _minus(x['l6_sudo']['r']))),
    ]
    missing = [(name, txt) for name, txt in want if txt not in s]
    assert not missing, ('본문이 분석 결과와 어긋난다(재산정 뒤 본문을 고치지 않았다):\n'
                         + '\n'.join('  %s: "%s"를 찾지 못했다' % m for m in missing))

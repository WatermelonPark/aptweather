# -*- coding: utf-8 -*-
"""투자자 테스트의 규제 문항 두 개가 호재·악재 이분법으로 되돌아가지 않는지 고정한다.

대표 판단(2026-09-13): 문항 내용은 공급론과 맞는데 형식이 문제였다. 투기과열지구는 단기엔
악재지만 공급을 줄여 상승장을 길게 만든다 — 정답이 **보는 기간**에 따라 갈린다. 취득세 중과는
핵심지 보유자에게 버팀목, 외곽 보유자에게 부담 — 정답이 **지역**에 따라 갈린다. "호재냐 악재냐"
둘 중 하나를 고르게 하면 그 축이 지워진다.

⚠️ 보기 문구는 모바일 카드(폭 약 162px) 두 줄 안으로 줄였다. 원안은 세 줄까지 접혔다. 정답과
   오답 길이를 비슷하게 둔 것도 의도다 — 한쪽만 길면 긴 쪽이 정답이라는 신호가 된다.
"""
import io
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def _items():
    s = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    out = []
    for m in re.finditer(r"\{q:'(.*?)',\s*opts:\[(.*?)\],\s*answer:(\d+),\s*exp:'(.*?)'\}", s, re.S):
        opts = re.findall(r"'([^']*)'", m.group(2))
        out.append({'q': m.group(1), 'opts': opts, 'answer': int(m.group(3)), 'exp': m.group(4)})
    assert len(out) >= 20, '퀴즈 문항을 %d개밖에 못 읽었다 — 형식이 바뀌었으면 이 시험도 고칠 것' % len(out)
    return out


def _find(key):
    hit = [x for x in _items() if key in x['q']]
    assert len(hit) == 1, '%r 문항을 %d개 찾았다' % (key, len(hit))
    return hit[0]


def test_speculation_zone_item_is_about_time_horizon():
    x = _find('투기과열지구 지정')
    assert x['opts'][x['answer']] == '단기엔 누르고 길게는 올린다', '정답이 기간 축 보기가 아니다: %s' % x['opts']
    assert '호재' not in x['q'] and '악재' not in x['q'], '질문이 다시 호재·악재를 묻는다'
    assert '보는 기간' in x['exp'], '해설이 기간에 따라 갈린다는 설명을 잃었다'


def test_acquisition_tax_item_is_about_region():
    x = _find('취득세 중과')
    assert x['opts'][x['answer']] == '핵심지는 쏠리고 외곽은 부담', '정답이 지역 축 보기가 아니다: %s' % x['opts']
    assert '호재' not in x['q'] and '악재' not in x['q'], '질문이 다시 호재·악재를 묻는다'
    assert '핵심지' in x['exp'] and '외곽' in x['exp'], '해설이 지역별로 갈린다는 설명을 잃었다'


def test_no_binary_good_bad_options_remain():
    for x in _items():
        pair = ' '.join(x['opts'])
        assert not ('호재' in pair and '악재' in pair and len(x['opts']) == 2 and
                    ('규제' in x['q'] or '중과' in x['q'] or '투기과열' in x['q'])), (
            '규제 문항이 다시 호재·악재 이분법이다: %s' % x['q'])


def test_option_lengths_are_balanced():
    """정답만 길면 답이 드러난다. 두 보기 글자 수 차이를 작게 둔다."""
    for key in ('투기과열지구 지정', '취득세 중과'):
        a, b = (len(o) for o in _find(key)['opts'])
        assert abs(a - b) <= 6, '%s 보기 길이 차이가 크다(%d vs %d)' % (key, a, b)

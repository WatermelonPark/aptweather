# -*- coding: utf-8 -*-
"""인허가 부풀림을 '1.3~1.7배'로 말하지 않는다 (2026-09-13 정정).

'착공 기반 대비 1.29~1.68배 과대'는 2026-08-06 건축HUB 준공예정을 걷어낼 때 잰
수치다. 8/11에 KOSIS 인허가 설명으로 옮겨지면서 뜻이 바뀌어 리포트 19장·홈·소개
페이지·블로그 생성기에 퍼졌고, PM이 그 계수로 경기 인허가를 할인해 '대략 균형'이라는
오판까지 이어졌다. KOSIS 인허가를 누계를 풀어 직접 재면 같은 해 착공 대비 약 1.15배다.

HUB 이야기로서의 1.29~1.68은 사실이라 주석·설계 문서에서는 남는다. 여기서는
화면에 나가는 원본(생성기와 손으로 쓴 페이지)에 인허가 부풀림으로 다시 들어오는 것만 막는다.
"""
import io
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
PUBLIC_SOURCES = ('index.html', 'about/index.html', 'tools/make_sido_pages.py',
                  'tools/make_theory_post.py', 'tools/make_naver_post.py')


def test_public_text_does_not_carry_the_hub_factor_as_permit_inflation():
    bad = []
    for rel in PUBLIC_SOURCES:
        src = io.open(os.path.join(ROOT, rel), encoding='utf-8').read()
        for m in re.finditer(r'1\.3\s*[~–-]\s*1\.7\s*배', src):
            bad.append('%s: …%s…' % (rel, src[max(0, m.start() - 30):m.end() + 10].replace('\n', ' ')))
    assert not bad, '인허가 부풀림을 HUB 수치로 말한다:\n' + '\n'.join(bad)

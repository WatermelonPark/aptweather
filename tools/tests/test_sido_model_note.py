# -*- coding: utf-8 -*-
"""산식이 구조적으로 안 맞는 지역의 공시 — 세종.

역검증(2026-08-08, 저점 3개 전수): 과거 가격 저점 직전 3년 공급이 적정의
5.7·5.9·2.2배. 당시 세대수로 재도 10.7·6.8·2.1배로 더 나빠진다 — 도시가
공급으로 만들어져 세대가 공급을 따라 들어온 곳이라 전제의 인과가 반대다.
대전 통합안은 실측 후 기각(세종을 못 고치고 대전 보정 0.90·0.93만 망친다).
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import make_sido_pages as M

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')


def _page(z):
    return io.open(os.path.join(ROOT, 'zone', z, 'index.html'), encoding='utf-8').read()


def test_sejong_page_carries_the_model_limit_note():
    h = _page('세종')
    assert '계획도시' in h and '참고로만 보세요' in h


def test_note_stays_scoped_to_sejong():
    """산식이 잘 맞는 곳(대전 0.90·0.93)에 이 공시가 번지면 지표 전체가
    못 미더워 보인다 — 세종 한정이어야 한다."""
    assert set(M.MODEL_LIMIT_NOTE) == {'세종'}
    for z in ('대전', '서울', '제주'):
        assert '계획도시' not in _page(z), z


def test_note_is_a_fact_not_methodology():
    """'기준표에 없어 추정' 같은 내부 방법론 서술은 싣지 않기로 했다(2026-08-08
    사용자). 이 공시는 그 결정을 어기지 않아야 한다 — 방법이 아니라 판정 정보만."""
    t = M.MODEL_LIMIT_NOTE['세종']
    for banned in ('추정', '원단위', '세대수 비중', '기준표'):
        assert banned not in t, banned

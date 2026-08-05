# -*- coding: utf-8 -*-
"""홈 페이로드(data-core.js)에 빌드 전용 데이터가 새지 않는지."""
import io, json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import split_data as S

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')


def _core():
    p = os.path.join(ROOT, 'data-core.js')
    return json.loads(re.search(r'const ADV=(\{.*?\});', io.open(p, encoding='utf-8').read(), re.S).group(1))


def test_build_only_keys_are_not_shipped_to_browser():
    """CORE_ADV가 'permits'를 통째로 복사하므로 permits에 새 하위 키를 넣으면
    아무도 안 막아준 채 홈 페이로드가 커진다 — permits.city(150KB)가 실제로 그렇게
    새어 data-core가 131KB -> 311KB가 됐다(2026-08-05)."""
    adv = _core()
    for k in S.BUILD_ONLY_PERMITS:
        assert k not in (adv.get('permits') or {}), 'permits.%s가 홈 페이로드에 있다' % k
    for k in S.BUILD_ONLY_LIVEZONE:
        assert k not in (adv.get('livezone') or {}), 'livezone.%s가 홈 페이로드에 있다' % k
    assert 'aged30' not in adv, 'aged30은 존 페이지 빌드 전용이다'


def test_home_payload_stays_small():
    """분리 구조의 존재 이유가 홈 전송량이다. 상한을 눈에 보이게 박아둔다."""
    n = os.path.getsize(os.path.join(ROOT, 'data-core.js'))
    assert n < 180_000, 'data-core.js %d bytes — 빌드 전용 데이터가 샜는지 확인할 것' % n


def test_strip_units_is_idempotent_and_non_mutating():
    src = {'permits': {'done': {'a': 1}, 'city': {'x': 1}, 'units': {'y': 1}},
           'livezone': {'sgghh': {'k': 1}, 'zones': [{'z': 'A', 'units': [1]}]}}
    out = S_strip(src)
    assert 'city' not in out['permits'] and 'done' in out['permits']
    assert 'sgghh' not in out['livezone']
    assert 'units' not in out['livezone']['zones'][0]
    assert src['permits']['city'] == {'x': 1}, '원본을 건드렸다'
    assert S_strip(out) == out, '두 번 돌리면 달라진다'


def S_strip(a):
    """split_data.main() 안의 클로저를 밖에서 부를 수 없어 같은 규칙을 재현한다."""
    a = dict(a)
    lz = a.get('livezone')
    if lz:
        lz = dict(lz)
        if lz.get('zones'):
            lz['zones'] = [{k: v for k, v in z.items() if k != 'units'} for z in lz['zones']]
        for k in S.BUILD_ONLY_LIVEZONE:
            lz.pop(k, None)
        a['livezone'] = lz
    p = a.get('permits')
    if p:
        p = dict(p)
        for k in S.BUILD_ONLY_PERMITS:
            p.pop(k, None)
        a['permits'] = p
    return a

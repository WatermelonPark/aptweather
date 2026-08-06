# -*- coding: utf-8 -*-
"""홈 페이로드(data-core.js)에 빌드 전용 데이터가 새지 않는지."""
import io, json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import split_data as S

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')


def _core():
    p = os.path.join(ROOT, 'data-core.js')
    src = io.open(p, encoding='utf-8').read()
    adv = json.loads(re.search(r'const ADV=(\{.*?\});\nconst STATS', src, re.S).group(1))
    stats = json.loads(re.search(r'const STATS=(\{.*?\});\nwindow', src, re.S).group(1))
    return adv, stats


def test_build_only_keys_are_not_shipped_to_browser():
    """CORE_ADV가 'permits'를 통째로 복사하므로 permits에 새 하위 키를 넣으면
    아무도 안 막아준 채 홈 페이로드가 커진다 — permits.city(150KB)가 실제로 그렇게
    새어 data-core가 131KB -> 311KB가 됐다(2026-08-05).
    done/sched/demol은 건축HUB 파생분으로, 2026-08-06 산식 교체로 점수에서 빠졌다."""
    adv, _ = _core()
    for k in S.BUILD_ONLY_PERMITS:
        assert k not in (adv.get('permits') or {}), 'permits.%s가 홈 페이로드에 있다' % k
    assert 'livezone' not in adv, '생활권 31곳 체제 잔재 — ADV.sido로 대체됐다'
    assert 'aged30' not in adv, 'aged30은 폐기된 지표다'


def test_home_payload_stays_small():
    """분리 구조의 존재 이유가 홈 전송량이다. 상한을 눈에 보이게 박아둔다."""
    n = os.path.getsize(os.path.join(ROOT, 'data-core.js'))
    assert n < 180_000, 'data-core.js %d bytes — 빌드 전용 데이터가 샜는지 확인할 것' % n


def test_table_stats_are_trimmed_to_the_table_window():
    """준공·착공은 표가 그리는 구간·지역만 실어야 한다. 전 구간 22개 지역이면
    65KB인데 잘라 쓰면 절반 아래다. 점수(ADV.sido)는 이미 계산돼 있으므로 홈이
    옛 구간을 다시 읽을 일이 없다."""
    _, stats = _core()
    for k in S.TABLE_STATS:
        s = stats.get(k)
        assert s, '홈 표가 쓰는 %s가 core에 없다' % k
        assert s['dates'][0] >= S.TABLE_FROM, '%s가 %s 이전까지 실렸다' % (k, S.TABLE_FROM)
        extra = set(s['series']) - S.TABLE_REGIONS
        assert not extra, '%s에 표에 없는 지역이 실렸다: %s' % (k, sorted(extra))


def test_core_carries_price_rows_for_the_table():
    """표의 과거 칸 3등분(매매·전세·월세)이 이 데이터로 칠해진다.
    통계 탭이 열리면 loadFullData가 전체 monthly로 덮어쓴다(상위 키 통째 교체)."""
    adv, _ = _core()
    mo = adv.get('monthly') or {}
    assert mo.get('rows'), 'monthly가 core에 없다 — 표의 가격 색이 전부 빠진다'
    assert len(mo.get('regions') or []) == 20, '표는 20개 지역을 그린다'
    for f in ('ma', 'je', 'wo'):
        assert f in mo['rows'][0], 'monthly.rows에 %s가 없다' % f
    for heavy in ('seoul', 'sgg'):
        assert heavy not in mo, 'monthly.%s는 홈이 안 쓴다(합쳐 694KB)' % heavy
    # ⚠️ monthly는 '2017-01', STATS는 '2017.01'로 구분자가 다르다. 그대로 비교하면
    # '-'(0x2D) < '.'(0x2E)라 2017년이 통째로 잘린다(2026-08-06 실제로 그랬다).
    assert mo['rows'][0]['p'].replace('-', '.') >= S.TABLE_FROM


def test_strip_units_is_idempotent_and_non_mutating():
    src = {'permits': {'done': {'a': 1}, 'city': {'x': 1}, 'units': {'y': 1},
                       'rows': [1, 2]}}
    out = S_strip(src)
    assert 'city' not in out['permits'] and 'done' not in out['permits']
    assert out['permits']['rows'] == [1, 2], '인허가 시계열은 남아야 한다'
    assert src['permits']['city'] == {'x': 1}, '원본을 건드렸다'
    assert S_strip(out) == out, '두 번 돌리면 달라진다'


def S_strip(a):
    """split_data.main() 안의 클로저를 밖에서 부를 수 없어 같은 규칙을 재현한다."""
    a = dict(a)
    p = a.get('permits')
    if p:
        p = dict(p)
        for k in S.BUILD_ONLY_PERMITS:
            p.pop(k, None)
        a['permits'] = p
    return a

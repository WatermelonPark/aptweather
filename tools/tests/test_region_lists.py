# -*- coding: utf-8 -*-
"""화면에 지역을 뿌리는 자리가 **모델과 같은 집합**을 들고 있는지 잠근다.

2026-09-12 하루에 같은 유형이 네 군데서 나왔다. 전부 '모르는 지역을 조용히
건너뛰는' 구조라 지역 하나가 통째로 빠졌는데도 아무것도 빨개지지 않았다.

  · 사이클 전세가율 차트   refresh_cycle_data 가 옛 손 목록(광주·전남)을 들고 있었다
  · 홈 PC 표 모드          MATRIX_REGIONS.filter 가 전남광주를 걸러냈다
  · 홈 주간 시세 타일      TILE 배치표에 전남광주 좌표가 없어 흐름 배치로 떨어졌다
  · 공유 PNG               (이쪽은 통합 때 고쳐져 있었다 — 그래서 홈만 어긋나 보였다)

빠지는 쪽이 조용하다는 게 이 유형의 본질이다. 개수가 줄어도 표는 멀쩡해 보이고,
합계만 그만큼 작아진다. 그래서 '값이 맞는가'가 아니라 '집합이 같은가'를 잠근다.

⚠️ 순서는 잠그지 않는다. 표시 순서는 디자인 결정이라 모델 순서와 달라도 된다.
   여기서 보는 것은 **빠진 지역이 있는가** 하나다.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sido_zones as SZ  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
MODEL = set(SZ.ORDER)                                   # 집계 3 + 시도
SIDO = set(z for z in SZ.ORDER if z not in SZ.AGG)      # 시도만


def _read(*parts):
    return io.open(os.path.join(ROOT, *parts), encoding='utf-8').read()


# ── 홈: PC 표 모드 ────────────────────────────────────────────────────────

def test_matrix_regions_covers_the_model():
    """표에서 지역이 빠지면 그 줄만 사라진다. filter 가 조용히 걸러내기 때문이다."""
    s = _read('index.html')
    m = re.search(r'const MATRIX_REGIONS=(\[[^\]]*\])', s)
    assert m, 'MATRIX_REGIONS 를 찾지 못했다 — 이름이 바뀌었으면 이 시험도 고칠 것'
    got = set(json.loads(m.group(1).replace("'", '"')))
    assert got == MODEL, '표 지역이 모델과 다르다: %s' % sorted(got ^ MODEL)


def test_matrix_keeps_the_silent_drop_guard():
    """목록을 고치는 것만으로는 다음 변경을 못 막는다 — 런타임 경고가 남아 있어야 한다."""
    s = _read('index.html')
    assert 'MATRIX_REGIONS에 없는 지역이 데이터에 있다' in s, (
        '데이터에만 있는 지역을 알리는 경고가 사라졌다')


# ── 홈: 주간 시세 타일 ────────────────────────────────────────────────────

def test_home_weekly_tile_has_every_sido():
    """좌표가 없는 지역은 흐름 배치로 떨어져 지도 밖에 붙는다."""
    s = _read('index.html')
    m = re.search(r'const TILE=\{(.*?)\};', s, re.S)
    assert m, 'TILE 배치표를 찾지 못했다'
    got = set(re.findall(r"'([가-힣]+)':\[", m.group(1)))
    assert got == SIDO, '주간 타일 지역이 모델과 다르다: %s' % sorted(got ^ SIDO)


def test_home_tile_matches_the_share_png():
    """같은 지도가 매체마다 달라 보이면 안 된다 — 공유 PNG 와 같은 집합이어야 한다."""
    h = _read('index.html')
    p = _read('tools', 'make_weekly_share.py')
    home = set(re.findall(r"'([가-힣]+)':\[", re.search(r'const TILE=\{(.*?)\};', h, re.S).group(1)))
    png = set(re.findall(r"\('([가-힣]+)',", re.search(r'TILE = \[(.*?)\]\s*\n', p, re.S).group(1)))
    assert home == png - set(SZ.AGG), (
        '홈 타일과 공유 PNG 의 지역이 다르다: %s' % sorted(home ^ (png - set(SZ.AGG))))


# ── 생성기: 손 목록을 두더라도 어긋나면 죽어야 한다 ──────────────────────

def test_indicator_generator_guards_its_region_list():
    """SIDO17 이 한 곳 빠지면 전국 합계(nat26/nat27)가 조용히 작아진다."""
    s = _read('tools', 'make_indicator_pages.py')
    assert 'sido_zones' in s, '모델을 안 읽으면 대조할 수가 없다'
    assert 'SIDO17이 모델과 다르다' in s, '집합 대조 가드가 사라졌다'
    m = re.search(r'SIDO17 = \[(.*?)\]', s, re.S)
    got = set(re.findall(r"'([가-힣]+)'", m.group(1)))
    assert got == SIDO, '지표 생성기 지역이 모델과 다르다: %s' % sorted(got ^ SIDO)


def test_weekly_share_generator_guards_its_tile():
    s = _read('tools', 'make_weekly_share.py')
    assert 'TILE에 빠진 지역' in s, '공유 PNG 타일 가드가 사라졌다'
    m = re.search(r'TILE = \[(.*?)\]\s*\n', s, re.S)
    got = set(re.findall(r"\('([가-힣]+)',", m.group(1)))
    assert got == MODEL, '공유 PNG 지역이 모델과 다르다: %s' % sorted(got ^ MODEL)


def test_no_generator_still_carries_the_old_split_names():
    """통합 이전 이름을 판정에 쓰는 생성기가 남아 있으면 안 된다.

    ⚠️ 정당한 자리는 뺀다 — 지리 도형(gen_sido_geo)은 두 경계를 그대로 두고,
       시군구 매핑(gen_sgg_rone_map)은 광주 5개 구 때문에 개별 이름이 필요하며,
       원천 수집(update_adv_data)은 원천이 아직 옛 이름으로 주기 때문에 쓴다.
       안내 페이지(make_sido_pages)는 '광주를 찾아온 사람'을 보내 주는 자리다.
    """
    ok = ('gen_sido_geo.py', 'gen_sgg_rone_map.py', 'update_adv_data.py',
          'make_sido_pages.py', 'merge_regions.py')
    bad = []
    tools = os.path.join(ROOT, 'tools')
    for fn in os.listdir(tools):
        if not fn.endswith('.py') or fn in ok:
            continue
        s = io.open(os.path.join(tools, fn), encoding='utf-8', errors='replace').read()
        # 따옴표에 감싸인 옛 이름만 본다(주석의 산문 언급은 기록이라 허용)
        for name in ("'광주'", "'전남'", '"광주"', '"전남"'):
            if name in s:
                bad.append('%s(%s)' % (fn, name))
    assert not bad, '통합 이전 이름을 들고 있는 생성기: %s' % ', '.join(bad)

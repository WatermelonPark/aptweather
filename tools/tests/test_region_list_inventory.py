# -*- coding: utf-8 -*-
"""지역 목록을 **전수로 훑어** 분류되지 않은 것이 있으면 실패한다.

왜 또 만드나. test_region_lists.py 는 목록을 하나씩 이름으로 적어 검사한다. 그
방식은 **적어 둔 것만** 지키므로, 새 목록이 생기거나 내가 못 본 목록이 있으면 그냥
빠진다. 실제로 그렇게 됐다 — 2026-09-12 에 지역 누락 셋을 고치며 그 시험을 만들었는데
BUBBLE_REGIONS 를 빠뜨렸고, 리뷰 세션이 전남광주를 지우고 전체 시험을 돌려도 200개가
전부 통과하는 것을 보여 줬다. 버블밴드에서 그 지역이 라이브에서 빠져 있었다. 네 번째
누락이었다.

내 판정이 틀린 구조도 같이 남긴다. 파일 단위로 훑고 파일 하나를 통과시키면, 그 파일
안의 **다른 목록**을 안 보게 된다. update_adv_data.py 는 지역명이 가장 많이 나오는
파일이라 1위로 걸렸는데, _GJ_OLD 주석 하나를 읽고 '원천이 옛 이름으로 주니 정당하다'며
파일 전체를 넘겼다. BUBBLE_REGIONS 는 그 안에 있었다.

그래서 이 시험은 **식별자 단위**로 본다. 그리고 목록마다 시험을 붙이는 대신, 목록이
둘 중 하나로 분류돼 있는지만 확인한다.

  FULL    모델 전체를 담아야 하는 것 — 집합이 sido_zones 와 같아야 한다
  PARTIAL 의도적으로 일부만 담는 것 — 이유를 적어 두고 검사에서 뺀다

어느 쪽도 아닌 이름이 나오면 실패한다. 새 목록을 만든 사람이 '이건 전부인가 일부인가'를
한 번 답하게 하는 것이 목적이다. 답을 적는 비용은 한 줄이고, 안 적었을 때 치르는 값은
지역 하나가 화면에서 조용히 사라지는 것이다.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sido_zones as SZ  # noqa: E402

# ⚠️ normpath 필수. 정규화하지 않으면 모든 경로가 'tools/tests/../..' 로 시작해
# 아래 SKIP_DIR 의 'tools/tests/' 에 걸려 **전부 스킵**된다 — 스캐너가 빈 목록을
# 돌려주고 위 두 시험이 조용히 통과한다. 만들자마자 그렇게 됐고 자기 확인 시험이
# 잡았다(2026-09-12).
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
MODEL = set(SZ.ORDER)
SIDO = set(z for z in SZ.ORDER if z not in SZ.AGG)
OLD = {'광주', '전남'}

# 모델 전체를 담아야 하는 목록. 여기 있는 것은 집합 일치를 강제한다.
FULL = {
    'MATRIX_REGIONS': MODEL,   # 홈 PC 표 모드 (2026-09-12 전남광주 누락)
    'WEEKLY_REGIONS': MODEL,   # 주간 시세 수집
    'BUBBLE_REGIONS': MODEL,   # 버블밴드 (2026-09-12 누락, 리뷰 세션 발견)
    'SIDO17': SIDO,            # 지표 페이지 (이름은 이력상 17)
    'DISPLAY_ORDER': MODEL,    # 시도 목록 표시 순서 정본 (2026-09-13 대표 결정)
}

# 일부만 담는 것이 의도인 목록. 왜 일부인지를 값으로 적는다.
PARTIAL = {
    'AGG': '집계 3곳(전국·수도권·지방)',
    'CAP': '수도권 3곳',
    'SUDO': '수도권',
    'REG_AGG': '집계 행',
    'METRO': '사이클 분석의 광역시 묶음',
    'PROVINCE': '사이클 분석의 도 묶음',
    'PRIORITY': '발행 순서를 앞당길 지역(나머지는 순부족 순)',
    'ZONE_REGIONS': '사이클 차트에 세울 대표 4곳',
    'REG15': '원천 조회용 — KOSIS 규모별표가 계속 쓴다',
    'PERMIT_REGIONS': 'REG15 에서 파생(리터럴만 세면 일부로 보인다)',
    'SUPPLY_SIDO': 'WEEKLY_REGIONS 에서 파생(리터럴만 세면 일부로 보인다)',
}

# ⚠️ drafts/ 와 logs/ 는 **gitignore 대상인 로컬 산출물**이다. 초안은 발행 직전마다
# 다시 만들어지고 사람이 손으로 고치기도 하므로, 훑으면 이 시험의 결과가 '지금 로컬에
# 어떤 초안이 있느냐'에 따라 흔들린다. 저장소의 코드를 보는 시험이 로컬 파일에 기대면
# 안 된다(2026-09-12 마케팅 세션 제보 — 그 세션에서 한 번 실패한 뒤 재현되지 않았다).
SKIP_DIR = ('zone/', 'monthly/', 'moveins/', 'jeonse-ratio/', 'weekly/', 'cycle/',
            'share/', 'docs/', 'tools/data/', 'tools/cache/', 'tools/tests/',
            'drafts/', 'logs/')
SKIP_FILE = ('data.js', 'data-core.js', 'sido-geo.js')

DECL = re.compile(
    r'(?:const\s+|var\s+|let\s+)?([A-Z_][A-Z0-9_]{2,})\s*=\s*[\[\(]([^\]\)]{0,4000})[\]\)]', re.S)


def _scan():
    """(파일, 식별자, 리터럴로 들어 있는 지역명 집합) 목록."""
    out = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != '.git' and (not d.startswith('.') or d == '.github')]
        for fn in files:
            p = (root + '/' + fn).replace(os.sep, '/')
            i = p.find('/aptweather/')
            rel = p[i + len('/aptweather/'):] if i >= 0 else p
            if not rel.endswith(('.py', '.html', '.js')):
                continue
            if any(rel.startswith(d) for d in SKIP_DIR) or os.path.basename(rel) in SKIP_FILE:
                continue
            try:
                s = io.open(p, encoding='utf-8', errors='replace').read()
            except Exception:
                continue
            for m in DECL.finditer(s):
                names = set(re.findall(r"['\"]([가-힣]{2,4})['\"]", m.group(2)))
                if len(names & (MODEL | OLD)) >= 3:
                    out.append((rel, m.group(1), names))
    return out


def test_every_region_list_is_classified():
    """분류에 없는 지역 목록이 나타나면 멈춘다 — 전부인지 일부인지 한 번 답할 것."""
    unknown = sorted({(n, f) for f, n, _ in _scan() if n not in FULL and n not in PARTIAL})
    assert not unknown, (
        '분류되지 않은 지역 목록: %s\n'
        '  전체를 담아야 하면 FULL 에, 일부만 담는 것이 의도면 PARTIAL 에 이유와 함께 넣을 것.'
        % ', '.join('%s(%s)' % (n, f) for n, f in unknown))


def test_full_lists_match_the_model():
    """FULL 로 분류한 목록은 모델과 집합이 같아야 한다."""
    bad = []
    for f, n, names in _scan():
        if n not in FULL:
            continue
        want = FULL[n]
        got = names & (MODEL | OLD)
        if got != want:
            bad.append('%s(%s) 차이 %s' % (n, f, sorted(got ^ want)))
    assert not bad, '모델과 어긋난 목록: %s' % '; '.join(bad)


def test_scanner_actually_sees_the_known_lists():
    """스캐너가 죽으면 위 두 시험이 조용히 통과한다 — 아는 것을 실제로 잡는지 본다.

    정규식 하나 어긋나면 _scan() 이 빈 목록을 돌려주고, 그러면 '분류 안 된 것 없음'과
    '어긋난 것 없음'이 둘 다 참이 된다. 이 저장소가 가장 자주 당한 '안 도는 방어선'이
    정확히 그 모양이라, 스캐너 자신을 먼저 확인한다.
    """
    seen = {n for _, n, _ in _scan()}
    for must in ('MATRIX_REGIONS', 'WEEKLY_REGIONS', 'BUBBLE_REGIONS', 'SIDO17'):
        assert must in seen, '스캐너가 %s 를 놓쳤다 — 정규식이 깨졌을 수 있다' % must

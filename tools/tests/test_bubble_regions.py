# -*- coding: utf-8 -*-
"""버블밴드도 모델의 모든 지역을 실어야 한다.

2026-09-12 발견. 광주·전남 통합(2026-09-10) 뒤 `BUBBLE_SHORT`가 여전히 옛 이름으로
매핑했고(`광주광역시→광주`, `전라남도→전남`), 바로 다음 줄의 `if rg not in
BUBBLE_REGIONS: continue`가 **둘 다 버렸다.** 그래서 전월세전환율 conv가 18곳이 되고
전남광주가 통째로 빠진 채 라이브에 나갔다(통계 → 투자지표 → 버블밴드).

같은 날 고친 세 건(사이클 전세가율 차트·홈 표 모드·홈 주간 타일)과 **같은 유형의
네 번째**다. 셋을 고치면서 `test_region_lists.py`를 만들었는데 거기에 BUBBLE_REGIONS가
빠져 있었다 — 전남광주를 지우고 전체 시험을 돌려도 전부 통과했다.

누락이 조용했던 이유는 payload가 `'regions': [r for r in BUBBLE_REGIONS if r in conv]`로
걸러 나가기 때문이다. 데이터에 없으면 목록에서도 사라지므로 화면은 멀쩡해 보인다.

⚠️ 전환율은 **비율(%)이라 합산하면 안 된다.** 가중평균이고 가중치는
merge_regions.W_GJ 정본을 쓴다(merge_regions.WEIGHTED와 같은 근거).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U  # noqa: E402
import sido_zones as SZ      # noqa: E402
from merge_regions import W_GJ  # noqa: E402

MODEL = [z for z in SZ.ORDER]


def test_bubble_regions_covers_the_model():
    assert set(U.BUBBLE_REGIONS) == set(MODEL), \
        '버블밴드 지역이 모델과 다르다: %s' % sorted(set(U.BUBBLE_REGIONS) ^ set(MODEL))


def test_short_map_never_yields_a_name_outside_the_model():
    """축약 결과가 모델 밖 이름이면 그 지역은 필터에서 조용히 버려진다.

    옛 이름(광주·전남)은 예외다 — 수집 단계에서 합쳐 전남광주를 만들기 때문이다.
    그 둘 말고 다른 이름이 새로 생기면 여기서 걸린다.
    """
    allowed = set(MODEL) | set(U._GJ_OLD)
    bad = sorted({v for v in U.BUBBLE_SHORT.values() if v not in allowed})
    assert not bad, '축약 결과가 모델에도 병합 대상에도 없다: %s' % bad


def test_old_names_are_merged_not_dropped():
    """옛 이름이 필터를 통과해 병합 대상이 되는지. 이게 깨지면 지역이 통째로 빠진다."""
    src = open(os.path.join(os.path.dirname(__file__), '..', 'update_adv_data.py'),
               encoding='utf-8').read()
    assert 'rg not in BUBBLE_REGIONS and rg not in _GJ_OLD' in src, (
        '옛 이름을 통과시키는 조건이 사라졌다 — 광주·전남이 버려져 전남광주가 빈다')


def test_rate_is_weighted_not_summed():
    """**생산 코드**(_merge_gj_rate)를 돌려서 확인한다.

    ⚠️ 처음엔 시험 안에서 `g*W_GJ + j*(1-W_GJ)`를 다시 계산해 비교했는데, 그건
    시험이 자기 산식을 검사하는 것이라 생산 코드를 합산으로 바꿔도 통과했다
    (2026-09-12 깨뜨리기에서 드러남). 그래서 함수를 분리해 직접 부른다.
    """
    got = U._merge_gj_rate({'202606': {'광주': 5.0, '전남': 8.0}})
    v = got['202606']['전남광주']
    assert 5.0 <= v <= 8.0, '가중평균 결과가 두 값 사이에 없다 — 합산했을 가능성'
    assert v != 13.0, '비율을 합산하고 있다'
    assert v == 6.2, '가중치가 바뀌었다 — merge_regions.W_GJ 정본을 볼 것'
    assert '광주' not in got['202606'] and '전남' not in got['202606'],         '옛 이름이 남아 있다 — 필터에서 버려지거나 중복 집계된다'


def test_rate_merge_keeps_the_single_side():
    """한쪽만 온 달. 없는 값을 0으로 세면 비율이 절반으로 내려앉는다."""
    got = U._merge_gj_rate({'202606': {'광주': 5.0}})
    assert got['202606']['전남광주'] == 5.0

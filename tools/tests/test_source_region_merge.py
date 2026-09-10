# -*- coding: utf-8 -*-
"""원천이 시도를 합쳐 내는 달은 받지 않는다.

2026-09 실사고: 국토교통부 주택건설실적통계가 2026.07분부터 '광주'와 '전남'을
'전남광주' 한 행으로 합쳐 내기 시작했다(원천 최종변경일 2026-08-31). 2026.05·06에는
두 지역이 따로 있었다. 소계도 함께 바뀌어 '기타광역시'에서 광주가, '기타지방'에서
전남이 빠졌다.

수집기는 17개 시도의 개별 행을 기대하므로 두 지역이 None으로 남았고, 저장분 정합
검사가 null을 0으로 세면서(KOSIS 규약) 17시도 합이 전국보다 작아졌다. 그 검사는
update-cloud의 배포 게이트라 **배치 전체가 멈췄다** — 9/8·9/9·9/10 세 회차 연속
실패, 마지막 데이터 커밋 9/5, 라이브 주간 기준일 8/31 정지. 주간 시세는 R-ONE
소스라 이 문제와 무관한데도 함께 묶였다.

이 시험이 지키는 것은 두 가지다.
 ① 병합을 **감지**한다(시군구 이름 등에 오탐이 없어야 한다).
 ② 감지한 달을 **버린다**. 안분해 채우지 않는다 — 합친 값을 비율로 쪼개면
    '숫자를 원천에서 그대로 가져온다'는 이 서비스의 근거가 그 자리에서 무너진다.

⚠️ 초록불만 보고 넘기지 말 것. 가드를 빼고 돌려서 빨개지는지 확인해야 한다.
이 저장소의 최다 결함 유형이 '있다고 적혀 있으나 안 도는 방어선'이다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import update_adv_data as U  # noqa: E402

# 2026.07 원천이 실제로 준 행 이름(실측)
REAL_202607 = ['총계', '수도권소계', '서울', '인천', '경기', '지방소계', '기타광역시',
               '전남광주', '부산', '대구', '대전', '울산', '기타지방', '세종', '강원',
               '충북', '충남', '전북', '경북', '경남', '제주']
# 2026.06까지의 정상 시도 목록
NORMAL17 = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기',
            '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']


def test_detects_the_real_merged_row():
    assert U.merged_sido_rows(REAL_202607) == {'전남광주': ['전남', '광주']}


def test_no_false_positive_on_normal_or_sigungu_names():
    """시군구 이름은 시도 이름을 하나만 품으므로 병합이 아니다."""
    assert U.merged_sido_rows(NORMAL17) == {}
    assert U.merged_sido_rows(['광주시', '제주시', '남양주시', '전주시', '성남시']) == {}
    assert U.merged_sido_rows(['총계', '수도권소계', '지방소계',
                               '기타광역시', '기타지방']) == {}


def test_generalizes_beyond_this_one_pair():
    """다음에 다른 조합을 합쳐도 잡혀야 한다 — 이름을 박아 두지 않았다."""
    got = U.merged_sido_rows(['대전세종', '충북충남'])
    assert got == {'대전세종': ['대전', '세종'], '충북충남': ['충북', '충남']}


def test_merged_month_is_dropped_and_others_survive():
    out = {
        (2026, 6): dict({z: 100 for z in NORMAL17}, 전국=1700),
        (2026, 7): dict({z: 100 for z in NORMAL17 if z not in ('광주', '전남')},
                        전국=1700, 전남광주=200),
    }
    dropped = U.drop_unsplittable_months('준공', out)
    assert dropped == [(2026, 7)], '병합된 달을 버리지 않았다'
    assert sorted(out) == [(2026, 6)], '정상인 달까지 버렸다'


def test_kept_when_source_keeps_children_under_the_merged_name():
    """상위 묶음만 새로 생기고 하위 시도가 함께 오면 분해가 가능하므로 받는다.

    R-ONE이 2026-07에 '전남광주>광주' 형태로 그렇게 했다. 그 경우까지 버리면
    멀쩡한 달을 잃는다.
    """
    out = {(2026, 7): dict({z: 100 for z in NORMAL17}, 전국=1700, 전남광주=200)}
    assert U.drop_unsplittable_months('준공', out) == []
    assert sorted(out) == [(2026, 7)]

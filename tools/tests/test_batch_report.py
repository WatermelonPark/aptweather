# -*- coding: utf-8 -*-
"""배치 알림 본문 — 받는 사람 기준으로 쓰였는지 잠근다.

이 시험이 지키는 것은 '동작'이 아니라 **전달**이다. 감시가 아무리 정확해도 사람이
못 읽으면 마지막 1미터에서 실패한다(PM 요청서 2026-09-12: 대표가 "무슨 뜻인지
모르겠다"고 한 것이 발단이다).

⚠️ 문구를 손볼 때 이 시험이 깨지면, 시험을 고치기 전에 **바뀐 문구가 받는 사람에게
   읽히는지** 먼저 보라. 여기서 잠그는 건 표현이 아니라 세 가지 성질이다.
     · 정상이면 읽을 것이 없다(항목 나열 금지, 멘션 금지 = 메일 안 감)
     · 실패는 무엇이 안 됐는지 이름을 밝힌다
     · 내부 용어가 새어 나가지 않는다
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import format_batch_report as F  # noqa: E402

RUN = 'https://github.com/x/y/actions/runs/1'
KST = '2026-09-12 21:52'

CLEAN = """✅ 러너 3/3 clean · 채택 주간 2026-09-07 / 월간 2026-07 / 공급 2026Q2
✅ 테스트
✅ 지역페이지
✅ 지표페이지
✅ 이달의 통계
✅ 사이클 리포트
✅ 공유카드
✅ 커밋·푸시 (5개 파일)
✅ IndexNow 제출
✅ 감시 최근 실행 09-11 01:57 KST (19시간 전)
"""

FAILED = """✅ 러너 2/3 clean · 채택 주간 2026-09-07 / 월간 2026-07 / 공급 2026Q2
❌ 테스트 실패 — 배포 중단(코드 회귀). 데이터 커밋 안 함
"""

WARNED = CLEAN.replace('✅ 공유카드\n',
                       '⚠️ 공유카드 실패 — /weekly/ og:image가 옛 주차에 고정된다\n')


def _b(raw, weekday=2):
    return F.build(raw, KST, RUN, 'OWNER', weekday)


# ── ③ 정상 회차에는 메일이 가지 않는다 ────────────────────────────────────

def test_clean_run_sends_no_mail():
    """멘션이 없어야 메일이 안 간다 — 이게 이번 개편의 핵심이다."""
    body, mention = _b(CLEAN)
    assert mention is False
    assert '@OWNER' not in body


def test_failed_run_sends_mail():
    body, mention = _b(FAILED)
    assert mention is True
    assert '@OWNER' in body


def test_warning_run_sends_mail():
    """곁가지 실패(⚠️)도 사람이 알아야 하므로 메일이 간다."""
    body, mention = _b(WARNED)
    assert mention is True and '@OWNER' in body


def test_monday_sends_a_reassurance_mail_even_when_clean():
    """침묵이 길면 도는지 의심하게 된다 — 월요일 1회는 살아 있다는 신호를 보낸다."""
    body, mention = _b(CLEAN, weekday=0)
    assert mention is True and '@OWNER' in body
    assert '월요일' in body


def test_watchdog_gap_sends_mail():
    """점검 작업이 안 돌면 데이터가 뒤처져도 모른다 — 조용히 넘기면 안 된다."""
    body, mention = _b(CLEAN + '⚠️ 감시가 41시간째 안 돌았다(마지막 09-10 03:00 KST) — 크론 누락 의심\n')
    assert mention is True
    assert '점검 작업' in body


# ── ② 받는 사람의 말로 쓴다 ──────────────────────────────────────────────

def test_clean_run_lists_nothing():
    """정상이면 확인된 항목을 나열하지 않는다. 읽을 것이 없어야 정상이다."""
    body, _ = _b(CLEAN)
    for gone in ('테스트', '지역페이지', '지표페이지', '사이클 리포트', '공유카드'):
        assert gone not in body, '정상인데 %s 를 나열했다' % gone
    assert body.count('\n- ') == 0, '정상 본문에 항목 목록이 있다'


def test_no_internal_jargon_leaks():
    """러너·clean·채택·IndexNow·감시는 우리끼리 쓰는 말이다."""
    for raw in (CLEAN, FAILED, WARNED):
        body, _ = _b(raw)
        for word in ('러너', 'clean', '채택', 'IndexNow', '커밋', '푸시', '아티팩트'):
            assert word not in body, '%r 가 본문에 남았다' % word


def test_failure_names_what_broke():
    """'일부 단계 실패'는 알림이 아니다 — 무엇이 안 됐는지 밝혀야 한다."""
    body, _ = _b(FAILED)
    assert '새 코드가 검사를 통과하지 못해' in body
    assert '고장 난 것이 아닙니다' in body, '막은 것과 고장 난 것을 구별해 줘야 한다'


def test_first_lines_are_conclusion_then_todo():
    """첫 줄이 결론, 그 다음이 할 일."""
    for raw, head in ((CLEAN, '✅'), (FAILED, '⚠️')):
        body, _ = _b(raw)
        assert body.splitlines()[0].startswith('### ' + head)
    fb, _ = _b(FAILED)
    assert '**사이트는 정상입니다.**' in fb, '사이트 영향이 먼저 와야 한다'
    assert '**하실 일: 없습니다.**' in fb, '할 일이 없으면 없다고 적어야 한다'
    cb, _ = _b(CLEAN)
    assert '하실 일 없습니다' in cb


def test_basis_is_written_in_human_dates():
    body, _ = _b(CLEAN)
    assert '주간 시세 9월 7일' in body
    assert '월간 통계 2026년 7월' in body
    assert '공급 2026년 2분기' in body
    for raw_form in ('2026-09-07', '2026Q2', '2026-07'):
        assert raw_form not in body, '%s 원형이 그대로 남았다' % raw_form


def test_no_change_run_says_so_plainly():
    """바뀐 게 없는 회차도 정상이다 — 사람에게는 그렇게 읽혀야 한다."""
    body, mention = _b(CLEAN.replace('✅ 커밋·푸시 (5개 파일)',
                                     '➖ 커밋 없음 — 원천이 그대로라 바뀐 파일이 없다(정상)'))
    assert mention is False
    assert '바뀐 내용이 없습니다' in body


# ── 항상 지켜야 하는 것 ──────────────────────────────────────────────────

def test_run_log_link_always_survives():
    """단계 나열을 지우더라도 파고들 입구는 남아야 한다."""
    for raw in (CLEAN, FAILED, WARNED):
        body, _ = _b(raw)
        assert RUN in body, '실행 로그 링크가 사라졌다'


def test_report_missing_is_reported_not_swallowed():
    """기록 파일조차 없는 회차 — 침묵이 가장 나쁘다."""
    body, mention = _b('❌ 배치가 보고 지점 전에 중단됨 — 러너 로그 확인 필요\n')
    assert mention is True
    assert '도중에 멈춰' in body


def test_unknown_line_is_kept_not_dropped():
    """대응표에 없는 실패도 삼키지 않는다 — 모르는 것을 지우면 조용한 정지가 된다."""
    body, mention = _b('❌ 처음 보는 실패 문구 XYZ\n')
    assert mention is True
    assert 'XYZ' in body

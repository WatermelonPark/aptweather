# -*- coding: utf-8 -*-
"""배치 0/3 전멸의 재시도 판정 — '시간이 바꿀 수 있는 실패'만 재시도한다.

재시도는 '35분 뒤 새 IP·새 시각이면 결과가 달라질 수 있다'는 가정 위에 서 있다.
시크릿 만료와 코드 크래시는 그 가정이 틀린 실패다 — 3회를 돌아도 똑같이 실패하고,
105분을 태우며 경보만 늦춘다. 감시가 결정론적 실패를 즉시 red로 보내는 것과 같은
원칙이다(check_freshness rc=2 → alert).

워크플로 셸 분기는 pytest가 실행할 수 없으므로, **판정의 뼈대(분류표와 안전
기본값)를 여기서 재현해 잠그고**, YAML에 그 뼈대가 실재하는지 함께 본다.
"""
import io
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
WF = os.path.join(ROOT, '.github', 'workflows', 'update-cloud.yml')

# 워크플로의 case 문과 같은 분류. 여기 없는 사유는 전부 '재시도'로 떨어진다.
DETERMINISTIC = ('nosecret', 'crash')


def decide(reasons):
    """True면 재시도, False면 즉시 red. 셸 분기와 같은 규칙."""
    words = [w for w in ' '.join(reasons).split() if w]
    if not words:
        return True                     # 사유를 못 읽으면 예전처럼 행동한다
    return any(w not in DETERMINISTIC for w in words)


def test_deterministic_failures_do_not_retry():
    assert decide(['nosecret'] * 3) is False
    assert decide(['crash'] * 3) is False
    assert decide(['nosecret', 'crash', 'crash']) is False


def test_transient_failures_still_retry():
    assert decide(['badip'] * 3) is True
    assert decide(['source'] * 3) is True


def test_one_healable_runner_is_enough_to_retry():
    """섞이면 재시도 쪽이다 — 하나라도 시간이 바꿀 여지가 있으면 그 여지를 쓴다."""
    assert decide(['badip', 'crash', 'crash']) is True


def test_unknown_reason_defaults_to_retrying():
    """판정 장치 자체가 고장났을 때(아티팩트 누락 등) 조용히 재시도를 꺼버리면,
    고칠 수 있었던 회차까지 같이 죽는다. 모르면 예전처럼 재시도한다."""
    assert decide([]) is True
    assert decide(['pending']) is True   # 갱신 스텝이 사유를 확정하기 전에 죽은 경우


def test_workflow_actually_carries_this_policy():
    """위 표는 워크플로의 거울일 뿐이다 — 셸에서 사라지면 여기만 초록으로 남는다."""
    y = io.open(WF, encoding='utf-8').read()
    assert 'reason-${{ matrix.n }}' in y, '러너가 사유를 안 올린다'
    assert re.search(r'pattern:\s*reason-\*', y), '커밋 잡이 사유를 안 받는다'
    assert 'nosecret|crash' in y, '분류표가 셸에서 사라졌다'
    assert re.search(r'HEALABLE.*=.*0.*\n.*then', y) or 'HEALABLE" = "0"' in y
    # 결정론적 실패는 재시도가 아니라 red여야 한다 — need_retry로 새지 않는지.
    det = y.index('HEALABLE" = "0"')
    nxt = y.index('need_retry=true', det)
    assert 'exit 1' in y[det:nxt], '결정론적 실패가 red 없이 지나간다'


def test_exhausted_retries_turn_the_run_red():
    """재시도 3회를 다 쓰고도 0/3이면 red다. 예전엔 exit 0이라 워크플로가 초록으로
    끝났고 이슈 코멘트의 ❌만 남아 **실패 메일이 오지 않았다**(2026-08-15 사용자
    결정). 감시가 5시간 뒤 뒤처짐으로 잡아주긴 하지만, 그만큼 늦게 아는 것이다."""
    y = io.open(WF, encoding='utf-8').read()
    blk = y[y.index('시도 3/3 소진'):]
    end = blk.index('\n          fi')
    assert 'exit 1' in blk[:end], '재시도 소진이 초록으로 끝난다'


def test_pending_retry_must_not_turn_red():
    """반대로 '재시도 대기' 분기는 초록이어야 한다 — retry 잡의 if가 커스텀 조건이라
    커밋 잡이 실패하면 GitHub이 그 잡을 건너뛴다. red로 만들면 재시도를 걸어놓고
    재시도를 못 돌게 하는 꼴이 된다."""
    y = io.open(WF, encoding='utf-8').read()
    blk = y[y.index('need_retry=true'):y.index('시도 3/3 소진')]
    assert 'exit 0' in blk, '재시도 대기 분기가 red가 되면 retry 잡이 건너뛰어진다'
    # retry 잡 조건이 always()/!cancelled() 없이 needs.commit에 걸려 있다는 전제.
    assert re.search(r"if:\s*needs\.commit\.outputs\.need_retry\s*==\s*'true'", y), \
        'retry 잡 조건이 바뀌었다 — 위 전제를 다시 확인할 것'


def test_reason_is_uploaded_even_when_the_runner_fails():
    """실패한 러너의 사유가 정보다. clean 산출물처럼 성공 때만 올리면 0/3 회차엔
    판정 근거가 하나도 없다."""
    y = io.open(WF, encoding='utf-8').read()
    # ⚠️ '산출물 업로드'는 앞선 echo 줄에도 있다 — 스텝 경계는 '- name:'으로 잡는다.
    blk = y[y.index('- name: 실패 사유 업로드'):y.index('- name: 산출물 업로드')]
    assert blk.strip(), '스텝 순서가 바뀌었다 — 슬라이스가 비었다'
    assert 'if: always()' in blk, '사유 업로드가 성공 러너에만 걸려 있다'

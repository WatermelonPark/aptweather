# -*- coding: utf-8 -*-
"""서비스워커 버전은 앞으로만 간다.

2026-08-15 실사고: 등급 라벨 작업에서 `sed`로 `const VERSION = 'v[0-9]*'`를 잡아
**기억한 값(v102)** 으로 치환했는데, 그 사이 다른 세션들이 v107까지 올려둔 상태였다.
버전이 5칸 뒤로 돌아간 채 배포됐다. 캐시 이름이 바뀌긴 해서 갱신 자체는 동작했지만
① 배포 이력이 읽히지 않게 되고 ② 다음 사람이 v103~v107을 재사용하게 된다.

여러 세션이 같은 파일을 번갈아 올리는 저장소라 '기억한 숫자를 박는' 실수가 반복된다.
사람의 주의력 대신 여기서 막는다 — git 이력의 최대값보다 큰지 본다.

⚠️ **이 가드는 로컬에서만 판정한다.** CI(actions/checkout 기본값)는 얕은 클론이라
sw.js 이력이 커밋 1개뿐이고, 그러면 이력 최대값 = 현재 값이 되어 어떤 값을 넣어도
통과한다. 배치가 sw.js를 건드리지 않으니 실질 위험은 없지만, **'CI가 막아준다'고
믿으면 안 된다** — 세션이 푸시 전에 pytest를 돌리는 것이 유일한 방어선이다.
그래서 이력을 못 읽으면 조용히 통과시키지 않고 skip으로 드러낸다(2026-08-15 리뷰).
"""
import io
import os
import re
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
SW = os.path.join(ROOT, 'sw.js')
PAT = re.compile(r"const VERSION = 'v(\d+)'")
# 이력에서 뽑을 때는 diff 줄(+/-)까지 본다 — 아래 _history() 주석 참조.
DIFF_PAT = re.compile(r"^[+-]const VERSION = 'v(\d+)'", re.M)
HISTORY_DEPTH = 60      # 버전은 시간순 증가라 최대값은 늘 최근 구간에 있다


def _current():
    m = PAT.search(io.open(SW, encoding='utf-8').read())
    assert m, 'sw.js에서 VERSION을 못 찾았다 — 형식이 바뀌었으면 이 테스트도 고칠 것'
    return int(m.group(1))


def _history():
    """git 이력에 등장한 모든 버전. 읽지 못하면 None(판정 불가).

    ⚠️ `git log`로 SHA를 받아 커밋마다 `git show`를 도는 방식이었는데, 프로세스를
    61번 띄워 3.56초가 걸렸다 — 나머지 135개 테스트 전부(4.73초)와 맞먹었다.
    `git log -p` 한 번이면 같은 정보가 0.07초에 나온다(2026-08-15 리뷰, 50배).
    diff에서 뽑으므로 `+`(새 값)와 `-`(옛 값)를 모두 세는데, 어느 쪽이든 '한때
    이 저장소에 있던 번호'라 재사용 판정에는 양쪽이 다 필요하다.

    ⚠️ text=True만 쓰면 Windows 기본 코덱(cp949)으로 디코딩하다 sw.js의 한글
    주석에서 깨져 stdout이 None으로 온다 — 인코딩을 명시한다.
    """
    try:
        out = subprocess.run(
            ['git', 'log', '-%d' % HISTORY_DEPTH, '-p', '--format=%h', '--', 'sw.js'],
            cwd=ROOT, capture_output=True, timeout=60,
            encoding='utf-8', errors='replace')
    except Exception:
        return None
    if out.returncode != 0:
        return None
    found = {int(v) for v in DIFF_PAT.findall(out.stdout or '')}
    return found or None


def test_sw_version_never_goes_below_the_highest_ever_shipped():
    """작업 트리의 VERSION은 **이력 최대값 이상**이어야 한다.

    이 한 줄이 역행과 번호 재사용을 동시에 막는다 — 둘 다 'cur < 최대값'이라는
    같은 모양이기 때문이다. 같을 때(cur == 최대값)는 통과시킨다: 아직 안 올린
    상태에서 테스트를 돌리는 정상적인 경우와 구분할 방법이 없고, 구분하려면
    '다른 파일이 바뀌었는지'를 알아야 하는데 그건 이 테스트의 일이 아니다.

    ⚠️ 처음엔 '재사용 금지'를 별도 테스트로 뒀는데, 비교 집합에서 자기 값을 빼는
    바람에 **조건이 항상 참**이라 영영 실패할 수 없었다(2026-08-15, 같은 날 만든
    테스트에서 바로 나왔다). 초록불로는 안 보이니 일부러 깨뜨려 확인할 것 —
    v102·v103은 실패하고 v108은 통과해야 한다.
    """
    cur = _current()
    hist = _history()
    if hist is None:
        pytest.skip('sw.js 이력을 읽지 못했다(얕은 클론 등) — 이번엔 버전을 못 본다')
    top = max(hist)
    # 얕은 클론이면 이력이 현재 값 하나뿐이라 비교가 자기 자신과의 비교가 된다.
    # 통과시키되 '봤다'고 말하지는 않는다.
    if hist == {cur}:
        pytest.skip('sw.js 이력에 현재 값(v%d)뿐이다 — 얕은 클론으로 보인다' % cur)
    assert cur >= top, (
        'sw.js VERSION이 뒤로 갔거나 이미 쓴 번호다: 현재 v%d, 이력 최대 v%d. '
        '기억한 숫자를 박지 말고 현재 값을 읽어 +1 할 것.' % (cur, top))

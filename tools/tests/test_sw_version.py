# -*- coding: utf-8 -*-
"""서비스워커 버전은 앞으로만 간다.

2026-08-15 실사고: 등급 라벨 작업에서 `sed`로 `const VERSION = 'v[0-9]*'`를 잡아
**기억한 값(v102)** 으로 치환했는데, 그 사이 다른 세션들이 v107까지 올려둔 상태였다.
버전이 5칸 뒤로 돌아간 채 배포됐다. 캐시 이름이 바뀌긴 해서 갱신 자체는 동작했지만
① 배포 이력이 읽히지 않게 되고 ② 다음 사람이 v103~v107을 재사용하게 된다.

여러 세션이 같은 파일을 번갈아 올리는 저장소라 '기억한 숫자를 박는' 실수가 반복된다.
사람의 주의력 대신 여기서 막는다 — git 이력의 최대값보다 큰지 본다.
"""
import io
import os
import re
import subprocess

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
SW = os.path.join(ROOT, 'sw.js')
PAT = re.compile(r"const VERSION = 'v(\d+)'")


def _current():
    m = PAT.search(io.open(SW, encoding='utf-8').read())
    assert m, 'sw.js에서 VERSION을 못 찾았다 — 형식이 바뀌었으면 이 테스트도 고칠 것'
    return int(m.group(1))


def _history(limit=60):
    """git 이력에 등장한 모든 버전. 저장소가 아니거나 이력이 없으면 빈 집합."""
    try:
        # ⚠️ text=True만 쓰면 Windows 기본 코덱(cp949)으로 디코딩하다 sw.js의
        # 한글 주석에서 깨지고, stdout이 None으로 와서 엉뚱한 TypeError가 난다.
        # 인코딩을 명시한다(2026-08-15에 실제로 이걸로 한 번 넘어졌다).
        out = subprocess.run(['git', 'log', '--format=%h', '-%d' % limit, '--', 'sw.js'],
                             cwd=ROOT, capture_output=True, timeout=60,
                             encoding='utf-8', errors='replace')
        shas = [s for s in (out.stdout or '').split() if s]
    except Exception:
        return set()
    seen = set()
    for sha in shas:
        try:
            blob = subprocess.run(['git', 'show', '%s:sw.js' % sha],
                                  cwd=ROOT, capture_output=True, timeout=60,
                                  encoding='utf-8', errors='replace').stdout or ''
        except Exception:
            continue
        m = PAT.search(blob)
        if m:
            seen.add(int(m.group(1)))
    return seen


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
    if not hist:
        return                      # 얕은 클론 등 — 이력을 못 읽으면 판정하지 않는다
    top = max(hist)
    assert cur >= top, (
        'sw.js VERSION이 뒤로 갔거나 이미 쓴 번호다: 현재 v%d, 이력 최대 v%d. '
        '기억한 숫자를 박지 말고 현재 값을 읽어 +1 할 것.' % (cur, top))

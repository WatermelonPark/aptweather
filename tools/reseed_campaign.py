# -*- coding: utf-8 -*-
"""전국 재시딩 캠페인 러너 — 시간 제한·락·자동 커밋으로 나눠 돌린다.

왜 필요한가: 전량 재수집은 12~14시간이라 한 번에 못 끝낸다. fetch_hub_permits는
`--full --reseed`에 재개(meta['reseed_done'])가 있지만 **시간 제한도 동시 실행
방지도 없다**. 두 프로세스가 hub_permits.json을 같이 쓰면 나중에 쓴 쪽이 앞의
수집분을 통째로 덮는다(로스트 업데이트). 이 러너가 그 둘을 채운다.

무엇을 하나:
  1) 락 파일로 중복 실행을 막는다(죽은 락은 자동 해제).
  2) 남은 그룹을 시간 예산 안에서 --only 덩어리로 나눠 돌린다.
  3) 덩어리마다 hub_permits.json을 커밋(+옵션 푸시)해 중단돼도 진행분이 남는다.
  4) 캠페인이 전량 완료되면 멈춘다 — fetch_hub_permits는 전량 완료 시
     reseed_done을 비우고 **처음부터 다시 돌므로**, 여기서 끊지 않으면 무한히 돈다.

사용:
  python tools/reseed_campaign.py --minutes 120            # 2시간치 돌리고 종료
  python tools/reseed_campaign.py --minutes 120 --push     # 커밋 후 푸시까지
  python tools/reseed_campaign.py --status                 # 진행률만 출력

⚠️ DATA_GO_KR_KEY 환경변수가 필요하다(~/.aptweather_keys.bat).
⚠️ update-hub 워크플로와 겹치지 않게 — 그쪽은 매월 1일 18:00 UTC에 돈다.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, 'data', 'hub_permits.json')
LOCK = os.path.join(HERE, 'data', '.reseed.lock')
LOCK_STALE_SEC = 3 * 3600      # 3시간 넘은 락은 죽은 것으로 본다(덩어리 최대치보다 넉넉히)

sys.path.insert(0, HERE)


def load():
    return json.load(io.open(DATA, encoding='utf-8'))


def has_stcns(entry):
    """이 그룹의 units가 착공연월(6번째)을 담고 있나 — 필드 도입 이후 수집분인지 판별.

    ⚠️ units가 비어 있으면(수집했는데 공동주택이 0건인 시군구) 판정 불가라 True로
    본다. 아니면 매번 재수집 대상으로 잡혀 캠페인이 끝나지 않는다.
    """
    u = entry.get('units') or []
    if not u:
        return True
    return any(len(x) > 5 and x[5] for x in u)


def progress():
    """(완료 그룹 수, 전체 그룹 수, 남은 코드 목록).

    ⚠️ reseed_done에 있어도 **착공연월이 없으면 다시 대상**으로 잡는다.
    착공일 수집(2026-08-04)보다 먼저 돌아간 캠페인 진행분이 25곳 있는데, 수집기는
    reseed_done만 보고 건너뛰므로 그대로 두면 그 시군구는 영영 착공일 없이 남는다.
    착공 여부가 이번 재수집의 목적이라 그러면 캠페인이 목적을 못 이룬다.
    """
    import fetch_hub_permits as F
    groups, _ = F.build_targets()
    keys = list(groups.keys())
    d = load()
    done = set((d.get('meta') or {}).get('reseed_done') or [])
    sgg = d.get('sgg') or {}
    remain = [k for k in keys
              if k not in done or not has_stcns(sgg.get(k) or {})]
    return len(keys) - len(remain), len(keys), remain


def take_lock():
    if os.path.exists(LOCK):
        age = time.time() - os.path.getmtime(LOCK)
        if age < LOCK_STALE_SEC:
            who = ''
            try:
                who = io.open(LOCK, encoding='utf-8').read().strip()
            except Exception:
                pass
            print('다른 수집이 진행 중이다(%.0f분 전 시작). 중복 실행하면 수집분이 유실된다.'
                  % (age / 60))
            if who:
                print('  락 내용: %s' % who)
            return False
        print('오래된 락(%.1f시간) — 죽은 것으로 보고 해제한다.' % (age / 3600))
    io.open(LOCK, 'w', encoding='utf-8').write(
        'pid=%d started=%s' % (os.getpid(), time.strftime('%Y-%m-%d %H:%M:%S')))
    return True


def drop_lock():
    try:
        os.remove(LOCK)
    except OSError:
        pass


def git(*args, **kw):
    return subprocess.run(('git',) + args, cwd=ROOT, capture_output=True,
                          text=True, encoding='utf-8', errors='replace', **kw)


def commit(msg, push):
    if git('diff', '--quiet', '--', DATA).returncode == 0:
        print('  (변경 없음 — 커밋 생략)')
        return
    git('add', '--', DATA)
    r = git('commit', '-q', '-m', msg)
    if r.returncode:
        print('  커밋 실패:', (r.stderr or '')[:200]); return
    print('  커밋 완료')
    if push:
        for i in (1, 2, 3):
            if git('pull', '--rebase', '-q', 'origin', 'main').returncode == 0 \
               and git('push', '-q', 'origin', 'main').returncode == 0:
                print('  푸시 완료'); return
            git('rebase', '--abort')
            time.sleep(3)
        print('  ⚠️ 푸시 3회 실패 — 로컬 커밋은 남아 있다')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=int, default=120, help='이번 실행의 시간 예산(분)')
    ap.add_argument('--chunk', type=int, default=6, help='한 덩어리에 넣을 그룹 수')
    ap.add_argument('--push', action='store_true', help='덩어리마다 푸시까지')
    ap.add_argument('--status', action='store_true', help='진행률만 출력하고 종료')
    args = ap.parse_args()

    done, total, remain = progress()
    print('재시딩 진행: %d/%d 그룹 (남은 %d곳)' % (done, total, len(remain)))
    if args.status:
        return 0
    if not remain:
        print('전량 완료 — 더 돌리지 않는다.')
        print('⚠️ 여기서 --reseed를 또 돌리면 fetch_hub_permits가 reseed_done을 비우고 '
              '처음부터 다시 시작한다.')
        return 0
    if not os.environ.get('DATA_GO_KR_KEY'):
        print('ERROR: DATA_GO_KR_KEY 없음 — 실호출 불가')
        return 2
    if not take_lock():
        return 3

    deadline = time.time() + args.minutes * 60
    n_chunk = 0
    try:
        while remain and time.time() < deadline:
            batch = remain[:args.chunk]
            n_chunk += 1
            left = (deadline - time.time()) / 60
            print()
            print('[덩어리 %d] %d곳 수집 (남은 예산 %.0f분): %s'
                  % (n_chunk, len(batch), left, ','.join(batch)))
            # ⚠️ 수집기는 reseed_done에 있는 그룹을 건너뛴다. 착공일이 없어서 다시
            # 대상으로 잡은 그룹은 그 표시를 지워야 실제로 재수집된다 — 안 그러면
            # 러너는 계속 대상으로 잡고 수집기는 계속 건너뛰어 무한루프가 된다.
            stale = [k for k in batch if not has_stcns((load().get('sgg') or {}).get(k) or {})]
            if stale:
                d = load()
                rd = set((d.get('meta') or {}).get('reseed_done') or []) - set(stale)
                d.setdefault('meta', {})['reseed_done'] = sorted(rd)
                io.open(DATA, 'w', encoding='utf-8').write(
                    json.dumps(d, ensure_ascii=False, separators=(',', ':')))
                print('  착공일 없는 %d곳의 완료 표시를 해제해 재수집시킨다: %s'
                      % (len(stale), ','.join(stale)))
            r = subprocess.run(
                [sys.executable, '-u', os.path.join(HERE, 'fetch_hub_permits.py'),
                 '--full', '--reseed', '--only', ','.join(batch)],
                cwd=ROOT, encoding='utf-8', errors='replace')
            if r.returncode != 0:
                print('  수집기가 종료코드 %d로 끝났다 — 이번 실행을 멈춘다'
                      '(한도 소진이면 내일 이어서).' % r.returncode)
                commit('data: HUB 재시딩 진행분(중단 시점까지)', args.push)
                break
            commit('data: HUB 재시딩 진행분 (%s)' % ','.join(batch), args.push)
            done, total, remain = progress()
            print('  누적 %d/%d' % (done, total))
    finally:
        drop_lock()

    done, total, remain = progress()
    print()
    print('이번 실행 종료 — 누적 %d/%d 그룹, 남은 %d곳' % (done, total, len(remain)))
    if remain:
        print('이어서 돌리려면 같은 명령을 다시 실행하면 된다(재개됨).')
    return 0


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""샤드 병렬 수집 결과를 hub_permits.json 하나로 합친다.

왜 필요한가: 증분 수집은 매번 생산적 법정동 2,646곳을 전부 다시 훑는다.
원천(건축HUB)이 불안정한 날엔 재시도가 붙어 GitHub 러너의 340분 스텝 캡을
넘긴다(2026-08-02 실사고: 5시간 40분 돌다 서울 강동구에서 타임아웃, 148곳 중
33곳만 갱신). 증분은 `--full`과 달리 meta['scanned']를 건너뛰지 않으므로
재실행해도 항상 같은 순서로 처음부터 돌아 서울만 반복 갱신된다 — 재시도로는
영원히 못 끝낸다. 그래서 잡을 쪼개 병렬로 돌리고 여기서 합친다.

소유권 규칙: fetch_hub_permits.shard_keys()를 그대로 재사용한다. 각 샤드는
자기 그룹만 갱신했고 나머지는 베이스 그대로이므로, 샤드 i의 파일에서 샤드 i가
소유한 키만 뽑아 베이스에 얹으면 된다. 규칙이 갈리면 병합이 조용히 어긋난다.

사용: python tools/merge_hub_shards.py --base BASE.json --out OUT.json \
          --shards s1.json s2.json ... (순서 = 샤드 1..N)
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_hub_permits as F  # noqa: E402


def shard_spec_of(d, pos, fallback_n, path=''):
    """샤드 산출물이 스스로 밝힌 (i, n). 없으면 (인자 위치, fallback_n)로 폴백.

    ⚠️ 예전엔 언제나 (인자 위치, len(files))로 계산했다. 그런데 소유권은 수집
    시점의 분할 수(--shard i/6)로 정해진다 — 6샤드 중 2개만 넘기면 n=2가 되어
    파티션이 통째로 달라지고, 그 회차 수집분이 소유권 밖으로 밀려 조용히
    버려진다(2026-08-04 감사: '하루 2샤드씩' 운용에서 하루치가 통째로 폐기).
    total>0이라 merge의 안전장치(반영 0건)도 안 걸린다.
    그래서 수집기가 meta['shard']에 기록한 값을 정본으로 쓴다.
    """
    sp = (d.get('meta') or {}).get('shard')
    if isinstance(sp, (list, tuple)) and len(sp) == 2:
        try:
            i, n = int(sp[0]), int(sp[1])
            if 1 <= i <= n:
                return i, n, True
        except (TypeError, ValueError):
            pass
    print('  ⚠️ %s: meta.shard 없음 — 인자 순서(%d/%d)로 추정한다. 수집 시점 분할 수와'
          ' 다르면 이 샤드의 갱신분이 통째로 버려진다.' % (path or '샤드', pos, fallback_n))
    return pos, fallback_n, False


def merge(base, shard_files, total=None):
    n = total or len(shard_files)
    groups, _ = F.build_targets()
    keys = list(groups.keys())
    out = json.loads(json.dumps(base))       # 깊은 복사 — 베이스를 건드리지 않는다
    out.setdefault('sgg', {})
    out.setdefault('meta', {})
    scanned = set(out['meta'].get('scanned') or [])
    # 재시딩 캠페인 진행분도 scanned와 같은 소유권 규칙으로 합친다 — 이게 빠지면
    # 샤드가 캡에 걸려 재트리거될 때마다 자기 그룹을 처음부터 다시 돈다.
    reseed_done = set(out['meta'].get('reseed_done') or [])
    productive = set(out.get('productive_bjdong') or [])
    stats = []
    for pos, path in enumerate(shard_files, 1):
        d = json.load(io.open(path, encoding='utf-8'))
        i, sn, declared = shard_spec_of(d, pos, n, os.path.basename(path))
        owned = set(F.shard_keys(keys, (i, sn)))
        took = 0
        for k in owned:
            ent = (d.get('sgg') or {}).get(k)
            if ent is None:
                continue                      # 그 샤드가 못 건드린 그룹 — 베이스 유지
            out['sgg'][k] = ent
            took += 1
        # scanned는 소유 키에 한해서만 반영한다. 샤드 파일의 scanned에는 베이스에서
        # 물려받은 남의 키가 그대로 들어 있어, 통째로 합치면 이번에 실패한 그룹까지
        # '깨끗하게 스캔 완료'로 표시돼 다음 --full이 그 그룹을 영영 건너뛴다.
        scanned |= (set((d.get('meta') or {}).get('scanned') or []) & owned)
        reseed_done |= (set((d.get('meta') or {}).get('reseed_done') or []) & owned)
        productive |= set(d.get('productive_bjdong') or [])
        stats.append((i, sn, len(owned), took, declared))
    # 병합 결과는 어느 한 샤드의 산출물이 아니다 — 샤드 꼬리표를 지워 다음 회차의
    # base로 커밋됐을 때 엉뚱한 소유권으로 읽히지 않게 한다.
    out['meta'].pop('shard', None)
    out['meta']['scanned'] = sorted(scanned)
    if reseed_done:
        out['meta']['reseed_done'] = sorted(reseed_done)
    out['productive_bjdong'] = sorted(productive)
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, help='병합 기준(수집 전 커밋된 hub_permits.json)')
    ap.add_argument('--shards', nargs='+', required=True,
                    help='샤드 산출 파일들. 소유권은 각 파일의 meta.shard로 판정하므로 '
                         '순서·개수가 달라도 안전하다(meta.shard가 없는 옛 파일만 순서 폴백).')
    ap.add_argument('--total', type=int, default=None,
                    help='meta.shard가 없는 옛 산출물의 폴백 분할 수(예: 6). '
                         '생략하면 넘긴 파일 개수를 쓴다 — 일부만 넘길 땐 반드시 지정할 것.')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    base = json.load(io.open(args.base, encoding='utf-8'))
    out, stats = merge(base, args.shards, total=args.total)
    for i, sn, owned, took, declared in stats:
        print('  샤드 %d/%d%s: 소유 %3d곳 중 %3d곳 반영'
              % (i, sn, '' if declared else '(추정)', owned, took))
    total = sum(t for _, _, _, t, _ in stats)
    print('총 %d/%d 그룹 갱신 · sgg %d곳 · productive_bjdong %d곳'
          % (total, sum(o for _, _, o, _, _ in stats), len(out['sgg']),
             len(out['productive_bjdong'])))
    if total == 0:
        raise SystemExit('ERROR: 반영된 그룹이 하나도 없다 — 샤드 산출물을 확인할 것')
    with io.open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main()

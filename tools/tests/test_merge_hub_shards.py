"""샤드 병합 — 소유권 규칙과 진행상태(scanned/reseed_done) 합류 검증.

병합이 조용히 어긋나면 "그 그룹은 갱신됐다"고 표시된 채 옛 값이 남거나,
반대로 이번에 실패한 그룹이 완료로 찍혀 다음 실행이 영영 건너뛴다 — 둘 다
로그 외엔 흔적이 없어 사후에 알아채기 어렵다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import fetch_hub_permits as F  # noqa: E402
import merge_hub_shards as M  # noqa: E402


FAKE_GROUPS = {c: {'name': c, 'sido': '경기', 'members': [c],
                   'bjdong': {c: ['10100']}, 'legacy': None}
               for c in ['41110', '41130', '41190', '41210', '41270', '41370']}


def _patch_groups(monkeypatch):
    monkeypatch.setattr(F, 'build_targets', lambda: (FAKE_GROUPS, []))
    return F.shard_keys(list(FAKE_GROUPS.keys()), (1, 2)), \
        F.shard_keys(list(FAKE_GROUPS.keys()), (2, 2))


def _write(tmp_path, name, d):
    import io
    import json
    p = tmp_path / name
    io.open(str(p), 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False))
    return str(p)


def test_merge_takes_only_owned_keys_from_each_shard(tmp_path, monkeypatch):
    own1, own2 = _patch_groups(monkeypatch)
    base = {'meta': {'scanned': []}, 'sgg': {}, 'productive_bjdong': []}
    # 각 샤드 파일에는 자기 소유가 아닌 키의 옛 값도 들어 있다(베이스에서 물려받음).
    # 남의 키까지 가져오면 다른 샤드의 새 값이 옛 값으로 덮인다.
    s1 = {'meta': {'scanned': list(FAKE_GROUPS)},
          'sgg': {k: {'name': k, 'done_q': {'2024Q1': 1 if k in own1 else 999}}
                  for k in FAKE_GROUPS},
          'productive_bjdong': []}
    s2 = {'meta': {'scanned': list(FAKE_GROUPS)},
          'sgg': {k: {'name': k, 'done_q': {'2024Q1': 2 if k in own2 else 999}}
                  for k in FAKE_GROUPS},
          'productive_bjdong': []}
    out, _ = M.merge(base, [_write(tmp_path, 's1.json', s1),
                            _write(tmp_path, 's2.json', s2)])
    for k in own1:
        assert out['sgg'][k]['done_q'] == {'2024Q1': 1}
    for k in own2:
        assert out['sgg'][k]['done_q'] == {'2024Q1': 2}


def test_merge_carries_reseed_progress_scoped_to_ownership(tmp_path, monkeypatch):
    """재시딩 캠페인 진행분도 소유 키에 한해 합류해야 한다.

    이게 빠지면 340분 캡에 걸린 샤드를 재트리거할 때마다 자기 그룹을 처음부터
    다시 돌아 캠페인이 영영 안 끝난다. 반대로 소유권 범위를 안 씌우면, 샤드
    파일이 베이스에서 물려받은 남의 키까지 '재스캔 완료'로 찍혀 실제로는 옛
    데이터인 그룹이 건너뛰어진다.
    """
    own1, own2 = _patch_groups(monkeypatch)
    base = {'meta': {'scanned': list(FAKE_GROUPS)}, 'sgg': {}, 'productive_bjdong': []}
    s1 = {'meta': {'scanned': list(FAKE_GROUPS), 'reseed_done': list(FAKE_GROUPS)},
          'sgg': {}, 'productive_bjdong': []}
    s2 = {'meta': {'scanned': list(FAKE_GROUPS), 'reseed_done': own2[:1]},
          'sgg': {}, 'productive_bjdong': []}
    out, _ = M.merge(base, [_write(tmp_path, 's1.json', s1),
                            _write(tmp_path, 's2.json', s2)])
    # 샤드1은 자기 소유 전부 완료, 샤드2는 1곳만 완료 — 나머지는 다음 재트리거 몫.
    assert set(out['meta']['reseed_done']) == set(own1) | set(own2[:1])


def test_merge_keeps_live_gate_intact_during_reseed(tmp_path, monkeypatch):
    # 재시딩 중에도 meta['scanned']는 줄지 않아야 한다 — 줄면 hub_derive의
    # 존 완결성 게이트가 닫혀 라이브가 pre-HUB로 되돌아간다.
    _patch_groups(monkeypatch)
    base = {'meta': {'scanned': list(FAKE_GROUPS)}, 'sgg': {}, 'productive_bjdong': []}
    s = {'meta': {'scanned': list(FAKE_GROUPS), 'reseed_done': []},
         'sgg': {}, 'productive_bjdong': []}
    out, _ = M.merge(base, [_write(tmp_path, 's1.json', s),
                            _write(tmp_path, 's2.json', s)])
    assert set(out['meta']['scanned']) == set(FAKE_GROUPS)


def test_merge_omits_reseed_key_when_no_campaign_running(tmp_path, monkeypatch):
    _patch_groups(monkeypatch)
    base = {'meta': {'scanned': []}, 'sgg': {}, 'productive_bjdong': []}
    s = {'meta': {'scanned': []}, 'sgg': {'41110': {'name': 'x'}}, 'productive_bjdong': []}
    out, _ = M.merge(base, [_write(tmp_path, 's1.json', s),
                            _write(tmp_path, 's2.json', s)])
    assert 'reseed_done' not in out['meta']

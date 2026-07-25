# -*- coding: utf-8 -*-
"""국토교통부 철거멸실관리대장 전국 벌크 파일 1회성 임포트.

배경: `tools/fetch_hub_permits.py --demol --full`이 시군구/법정동 단위로
data.go.kr(ArchPmsHubService)를 페이싱 호출해 `hub_permits.json`의
`sgg[rep]['demol_q']`를 채우는 전국 수집은 ~13시간급이다. 국토부가 별도로
배포하는 전국 철거멸실관리대장 벌크 파일(2026년 06월 스냅샷, 파이프 구분,
헤더 없음, 34컬럼, 462,774행, 296개 시군구코드 커버)을 읽어 그 결과를
API 경로 없이 재현한다.

컬럼 인덱스(0-based, 실측 확인 — Task 지시의 확정치와 동일):
  [3]=sigunguCd, [4]=bjdongCd, [13]=demolStrtDay(철거시작일),
  [14]=demolEndDay(철거완료일), [15]=demolExtngDay(멸실일),
  [19]=mainPurpsCdNm(주용도명), [22]=세대수(hhldCnt와 동등 — 11680 강남
  2018Q3 분기합 실측 대조로 검증됨, tools/fetch_hub_permits.py의
  ArchPmsHubService <hhldCnt> 필드와 동일 의미).

필터·분기화 규칙은 `fetch_hub_permits._aggregate_demol`
(및 `hub_common.demol_records`)과 완전히 동일하게 맞춘다:
  - mainPurpsCdNm.strip() == '공동주택'
  - int(float(hhldCnt or 0)) > 0
  - 분기 = to_quarter(demolEndDay or demolExtngDay or demolStrtDay),
    셋 다 없으면(quarter=None) 미반영(skip) — API 경로의 "철거일 3종
    모두 없으면 미정" 정책과 동일.
이 벌크 레이아웃에는 PK/dedupe 컬럼이 없다 — 페이지 재조회로 생기는 중복이
구조적으로 없는 flat ledger export라서, 행 하나를 그대로 레코드 하나로
취급한다(demol_records의 mgmPmsrgstPk dedupe에 대응하는 처리 불필요).

시군구코드 -> 대표(rep) 코드 매핑은 `fetch_hub_permits.build_targets()`가
파생하는 것과 완전히 동일한 그룹(148개 논리 시군구, 180개 원자 코드)을
그대로 재사용한다 — 별도로 다시 구현하지 않는다(구 분할 도시의 rep 폴딩
규칙이 어긋나면 hub_derive의 완결성 게이트가 깨진다).

병합 정책(OVERWRITE, 명시적 선택 — Additive 아님):
  이 파일은 2026-06 전국 스냅샷 전량이라, 기존에 부분적으로(3개 rep만)
  쌓여있던 API발 demol_q보다 항상 더 완전하다. rep이 이 파일에서 커버되면
  (= rep 소속 원자 코드 중 하나 이상이 파일의 296개 시군구코드 전체
  집합에 등장하면) 그 rep의 demol_q를 이 파일의 집계값으로 통째로
  덮어쓴다. 기존 부분합과 병합(더하기)하면 같은 분기를 이중 카운트할
  위험이 있고, 이 벌크 파일이 이미 API가 만들어냈을 결과의 상위집합이므로
  덮어쓰기가 더 정확하다.

scanned_demol 갱신 정책:
  - rep이 커버됨(멤버 코드가 296개 시군구코드 universe에 있음): 실제
    철거멸실 매치가 0건이어도(공동주택 멸실이 진짜 없는 지역) 유효한
    "스캔 완료·0건" 값이므로 scanned_demol에 추가한다.
  - rep이 전혀 커버 안 됨(멤버 전원이 universe 밖): 이 벌크 파일이 그
    지역을 커버하지 않는다는 뜻 — 원인 조사가 필요하므로 scanned_demol에
    추가하지 않고 WARNING으로만 남긴다(무음 처리 금지).
  - 부천(41190, `hub_common.OLD_GU_MAP`발 unresolved_legacy): 준공/준공예정
    수집기가 이미 `[SKIP legacy]`로 완전히 건너뛰는 그룹이다 — 동일 정책을
    유지해 이 스크립트도 부천 그룹은 처리하지 않는다(집계도, scanned_demol
    등록도 안 함). 벌크 파일엔 41190 원자코드로 실제 철거 행이 있지만,
    unresolved_legacy 그룹이라 hub_derive가 그 zone을 애초에 미완결로
    취급하므로 무해하나, 기존 [SKIP legacy] 정책과 명시적으로 일치시킨다.

사용:
  python tools/import_demol_bulk.py                # 실제 병합 + 저장
  python tools/import_demol_bulk.py --dry-run       # 집계·요약만(저장 안 함)
  python tools/import_demol_bulk.py --bulk-path P   # 파일 경로 override(테스트용)
"""
import io
import os
import sys
import argparse
import collections

# cp949 콘솔에서도 한글/기호 출력이 죽지 않도록(다른 verify_*/hub 스크립트와 동일 처리).
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_common as H
import fetch_hub_permits as F

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DEFAULT_BULK_PATH = os.path.join(
    DATA, '국토교통부_건축인허가_철거멸실관리대장+(2026년+06월)', 'mart_kcy_07.txt')

# 컬럼 인덱스(실측 확인)
COL_SIGUNGU = 3
COL_BJDONG = 4
COL_DEMOL_STRT = 13
COL_DEMOL_END = 14
COL_DEMOL_EXTNG = 15
COL_MAIN_PURPS = 19
COL_HHLD = 22
MIN_COLS = 23   # index 22까지 참조하므로 최소 23개 컬럼 필요


# ---------------------------------------------------------------------------
# 1. 벌크 파일 스트리밍 파싱(순수, 파일 I/O만)
# ---------------------------------------------------------------------------

def parse_bulk_stream(path):
    """벌크 파일을 한 줄씩 순회(전체를 메모리에 올리지 않음).

    반환: (agg, seen_codes, stats)
      agg: {원자 sigunguCd: {'YYYYQn': 세대합}} — _aggregate_demol과 동일한
           필터·분기화 규칙 적용, 아직 rep로 접지 않은 원자 코드 단위.
      seen_codes: 파일에 등장한 전체 시군구코드 집합(필터 무관, 커버리지
           판정용 — "이 지역이 벌크 파일에 존재하는가"는 공동주택 필터와
           무관하게 판단해야 한다).
      stats: {'total_rows', 'malformed_rows', 'apt_positive_rows',
              'apt_positive_no_quarter_rows'}
    """
    agg = collections.defaultdict(lambda: collections.defaultdict(int))
    seen_codes = set()
    total_rows = 0
    malformed_rows = 0
    apt_positive_rows = 0
    apt_positive_no_quarter_rows = 0

    with io.open(path, encoding='utf-8') as f:
        for line in f:
            total_rows += 1
            line = line.rstrip('\n').rstrip('\r')
            if not line:
                continue
            parts = line.split('|')
            if len(parts) < MIN_COLS:
                malformed_rows += 1
                continue
            sgg = parts[COL_SIGUNGU].strip()
            if sgg:
                seen_codes.add(sgg)
            if parts[COL_MAIN_PURPS].strip() != '공동주택':
                continue
            try:
                hh = int(float(parts[COL_HHLD] or 0))
            except (TypeError, ValueError):
                continue
            if hh <= 0:
                continue
            apt_positive_rows += 1
            day = parts[COL_DEMOL_END] or parts[COL_DEMOL_EXTNG] or parts[COL_DEMOL_STRT]
            q = H.to_quarter(day)
            if not q:
                apt_positive_no_quarter_rows += 1
                continue
            if sgg:
                agg[sgg][q] += hh

    stats = {
        'total_rows': total_rows,
        'malformed_rows': malformed_rows,
        'apt_positive_rows': apt_positive_rows,
        'apt_positive_no_quarter_rows': apt_positive_no_quarter_rows,
    }
    return {k: dict(v) for k, v in agg.items()}, seen_codes, stats


# ---------------------------------------------------------------------------
# 2. rep 매핑(fetch_hub_permits.build_targets 재사용) + 병합(순수)
# ---------------------------------------------------------------------------

def build_rep_maps():
    """fetch_hub_permits.build_targets()를 그대로 호출해 148개 논리 그룹을
    얻고, 원자 sigunguCd -> rep 코드 역맵과 legacy-불능(부천) rep 집합을
    파생한다. 그룹핑 규칙을 재구현하지 않고 원본 함수를 재사용한다."""
    groups, unresolved_names = F.build_targets()
    raw_to_rep = {}
    excluded_reps = set()
    for rep, g in groups.items():
        if g['legacy'] and not g['legacy']['enumerable']:
            excluded_reps.add(rep)
        for m in g['members']:
            raw_to_rep[m] = rep
    return groups, raw_to_rep, excluded_reps


def merge_into_hub_permits(hp, agg, seen_codes, groups, raw_to_rep, excluded_reps):
    """agg(원자코드 단위)를 rep 단위로 접어 hp['sgg'][rep]['demol_q']에
    OVERWRITE하고 hp['meta']['scanned_demol']을 갱신한다(hp를 제자리에서
    변경). 순수 함수화(네트워크·파일 I/O 없음)로 테스트 가능하게 분리.

    반환: (newly_scanned, warnings, zero_marked, total_seats)
      newly_scanned: 이번 실행으로 새로 scanned_demol에 추가된 rep 목록
      warnings: 파일 커버리지가 전혀 없어 scanned_demol에 못 넣은 (rep, name) 목록
      zero_marked: 커버는 됐지만 실제 철거멸실 매치가 0건이라 demol_q={}로
                   기록된 rep 목록(정상 — "0도 값"이라는 정책의 확인용)
      total_seats: 이번에 기록된 demol_q 전체 세대 합(모든 rep, 모든 분기)
    """
    # 원자코드 -> rep 단위 재집계 (target 밖 코드는 raw_to_rep에 없어 자동 제외)
    rep_agg = collections.defaultdict(lambda: collections.defaultdict(int))
    for raw_cd, qmap in agg.items():
        rep = raw_to_rep.get(raw_cd)
        if rep is None or rep in excluded_reps:
            continue
        for q, n in qmap.items():
            rep_agg[rep][q] += n

    scanned_demol = set(hp.setdefault('meta', {}).get('scanned_demol', []))
    newly_scanned = []
    warnings = []
    zero_marked = []
    total_seats = 0

    for rep, g in groups.items():
        if rep in excluded_reps:
            continue
        member_codes = set(g['members'])
        covered = bool(member_codes & seen_codes)
        if not covered:
            warnings.append((rep, g['name']))
            continue
        demol_q = dict(rep_agg.get(rep, {}))
        entry = hp.setdefault('sgg', {}).setdefault(rep, {})
        entry['name'] = g['name']
        entry['demol_q'] = demol_q   # OVERWRITE(정책은 모듈 docstring 참고)
        if rep not in scanned_demol:
            newly_scanned.append(rep)
        scanned_demol.add(rep)
        if not demol_q:
            zero_marked.append(rep)
        total_seats += sum(demol_q.values())

    hp['meta']['scanned_demol'] = sorted(scanned_demol)
    return newly_scanned, warnings, zero_marked, total_seats


# ---------------------------------------------------------------------------
# 3. CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='철거멸실관리대장 전국 벌크 파일 1회성 임포트')
    ap.add_argument('--bulk-path', default=DEFAULT_BULK_PATH, help='벌크 파일 경로(기본: 실제 배포 경로)')
    ap.add_argument('--dry-run', action='store_true', help='집계·요약만 출력, hub_permits.json 저장 안 함')
    args = ap.parse_args()

    if not os.path.exists(args.bulk_path):
        print('ERROR: 벌크 파일을 찾을 수 없음:', args.bulk_path)
        sys.exit(2)

    print('벌크 파일 파싱 시작:', args.bulk_path)
    agg, seen_codes, stats = parse_bulk_stream(args.bulk_path)
    print('파싱 완료: 총 %d행(malformed %d), 공동주택·세대>0 %d행(분기 미상 %d행 미반영), 시군구코드 universe %d개'
          % (stats['total_rows'], stats['malformed_rows'], stats['apt_positive_rows'],
             stats['apt_positive_no_quarter_rows'], len(seen_codes)))

    groups, raw_to_rep, excluded_reps = build_rep_maps()
    print('대상(target) 그룹: %d개, legacy 제외 그룹: %d개(%s)'
          % (len(groups), len(excluded_reps), sorted(excluded_reps)))

    hp = F.load_existing()
    prior_scanned_demol = len(hp.get('meta', {}).get('scanned_demol', []))
    newly_scanned, warnings, zero_marked, total_seats = merge_into_hub_permits(
        hp, agg, seen_codes, groups, raw_to_rep, excluded_reps)

    print('---')
    print('신규 scanned_demol 편입: %d개 그룹 (기존 %d개 -> 총 %d개)'
          % (len(newly_scanned), prior_scanned_demol, len(hp['meta']['scanned_demol'])))
    print('그중 실제 철거멸실 0건(유효한 0값)으로 기록된 그룹: %d개' % len(zero_marked))
    print('이번에 기록된 demol_q 전체 세대 합계: %d' % total_seats)
    if warnings:
        print('WARNING: 벌크 파일 커버리지 없는 target 그룹 %d개(원인 조사 필요, scanned_demol 미등록):'
              % len(warnings))
        for rep, name in warnings:
            print('  - %s(%s)' % (rep, name))
    else:
        print('WARNING 없음: 모든 target 그룹(부천 제외)이 벌크 파일에서 커버됨')

    if args.dry_run:
        print('--dry-run: hub_permits.json 저장 생략')
        return

    F.save(hp)
    print('저장 완료:', F.OUT_PATH)


if __name__ == '__main__':
    main()

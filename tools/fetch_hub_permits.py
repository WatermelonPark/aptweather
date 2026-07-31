# -*- coding: utf-8 -*-
"""건축HUB(HsPmsHubService) 주택인허가 시군구 실측 페이싱 수집기.

`data.go.kr`의 건축인허가 기본개요 조회(`getHpBasisOulnInfo`)를 시군구·법정동
단위로 순차 호출해, 생활권(LIVEZONE) 참조 대상 시군구의 단지별 최신단계를
분기별 준공(done_q)·준공예정(sched_q) 세대수로 1회 분류·집계한다(착공/인허가는
점수에 직접 안 씀). 첫 실행은 전국 대상이라 ~13시간급이므로
반드시 `--full`(명시)로만 전량 실행하고, 이후에는 `productive_bjdong` 캐시로
좁힌 증분(기본 모드)만 돈다.

대상 시군구 도출 규칙 (Task 4 확정):
  target = { LIVEZONE의 각 원소를 전개('*'→해당 시도 전체 시군구, 이름→그 시군구) }
            ∪ { 경기도 전체 시/군(경기는 LIVEZONE에 없고 gg_zone으로 동적 생활권) }
  구가 있는 시(성남·창원·청주·수원 등)는 `code_bdong.json` 상 "{시명} {구명}"
  형태로 쪼개져 있어, 시군구코드 하위 구 코드별로 개별 호출한 뒤 시명 기준으로
  접어(fold) 하나의 출력 항목으로 합산한다.

옛 구코드(부천 등, `hub_common.OLD_GU_MAP`)는 `code_bdong.json`에 법정동이
전혀 남아있지 않으면(Task 1 실측 확인) 브루트포스하지 않고 `unresolved_legacy`로
기록만 하고 건너뛴다.

사용:
  python tools/fetch_hub_permits.py --list-targets          # 대상만 도출(호출 없음)
  python tools/fetch_hub_permits.py --full --only 41370,41190,41130   # 표본 실호출
  python tools/fetch_hub_permits.py --full                  # 전국 첫 전량(약 13시간, 로컬에서 돌리지 말 것)
  python tools/fetch_hub_permits.py                         # 증분(productive_bjdong만)

  python tools/fetch_hub_permits.py --demol --full --only 26110,41370  # 멸실 표본 실호출
  python tools/fetch_hub_permits.py --demol --full           # 멸실 전량(준공과 별도 meta['scanned_demol'])

멸실(--demol, 순공급=준공−멸실 보정용): ArchPmsHubService/getApDemolExtngMgmRgstInfo
(철거멸실관리대장)를 같은 대상 시군구/법정동에 대해 순회해 sgg[key]['demol_q']를
채운다. 준공(HsPmsHubService)과는 완전히 다른 서비스/필드명(mainPurpsCdNm·hhldCnt·
demolEndDay 등)이라 별도 집계 경로(_aggregate_demol)를 쓰고, resume 추적도
meta['scanned_demol']/productive_bjdong_demol로 준공(meta['scanned'])과 독립시켜
--demol 실행이 이미 ~90% 끝난 준공 시딩을 절대 재스캔·오염시키지 않는다.

RESUMABLE --full (Fix pass): GitHub 호스티드 러너는 6시간/잡 하드 캡이 있어
전국 첫 전량(~11~14시간)이 한 번의 워크플로 실행으로 안 끝난다. `--full`은
meta['scanned']에 이미 깨끗하게 스캔 완료된 그룹은 건너뛰므로, 워크플로가
중간에 킬되어도 --full을 그대로 재트리거하면 남은 그룹부터 이어서 돈다
(사람이 ~2~3회 재트리거하면 전량 완료). 처음부터 진짜 다시 돌리려면(연 1회
재구축 등) `--reseed`를 함께 준다.
"""
import io, os, sys, re, json, time, math, subprocess, datetime, argparse, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hub_common as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
BDONG_PATH = os.path.join(DATA, 'code_bdong.json')
OUT_PATH = os.path.join(DATA, 'hub_permits.json')

KEY = os.environ.get('DATA_GO_KR_KEY', '')
EP = 'https://apis.data.go.kr/1613000/HsPmsHubService/getHpBasisOulnInfo'
# 멸실(철거멸실관리대장) — 준공과 다른 서비스/엔드포인트지만 파라미터 형태
# (serviceKey·sigunguCd·bjdongCd·numOfRows·pageNo)와 페이싱·재시도·에러분류는
# 동일해 같은 fetch_page/fetch_bjdong_all_pages를 endpoint 인자만 바꿔 재사용한다.
EP_DEMOL = 'https://apis.data.go.kr/1613000/ArchPmsHubService/getApDemolExtngMgmRgstInfo'
PACE = 2.5          # 초당 페이싱(호출 사이 최소 대기)
NUM_ROWS = 1000
MAX_RETRY = 4


# ---------------------------------------------------------------------------
# 1. bjdong 자산 로딩 · 대상 시군구/법정동 도출 (순수, 네트워크 없음)
# ---------------------------------------------------------------------------

def _isnan(x):
    return isinstance(x, float) and math.isnan(x)


def load_bdong_rows(path=BDONG_PATH):
    """code_bdong.json(컬럼-딕셔너리 형태)을 활성(말소일자 없음) 행 리스트로 변환."""
    d = json.load(io.open(path, encoding='utf-8'))
    n = len(d['시도명'])
    rows = []
    for i in range(n):
        k = str(i)
        if not _isnan(d['말소일자'][k]):
            continue
        rows.append({
            'sido': d['시도명'][k], 'sgg_cd': d['시군구코드'][k], 'sgg_nm': d['시군구명'][k],
            'bjd_cd': str(d['법정동코드'][k]), 'eup': d['읍면동명'][k],
        })
    return rows


def build_target_index(rows, lz_sido_full):
    """활성 행 → (시도-short별 시군구코드 집합, 이름→시군구코드 집합,
    시군구코드→법정동5자리 집합, 시군구코드→시군구명, 시군구코드→시도-short)."""
    sido_codes = collections.defaultdict(set)
    name_codes = collections.defaultdict(set)
    sgg_name_by_code = {}
    sido_by_code = {}
    bjdong_by_sgg = collections.defaultdict(set)
    for r in rows:
        nm = r['sgg_nm']
        short = lz_sido_full.get(r['sido'])
        if not isinstance(nm, str) or not nm:
            # 시군구명이 없는 두 경우: (1) 시도 합계행(시군구코드가 '...000'로 끝남,
            # 예: 서울 11000) — 제외. (2) 세종특별자치시처럼 시군구 계층이 아예
            # 없어 시군구코드 자체가 시 전체를 뜻하는 행(예: 세종 36110, 시군구명은
            # 언제나 결측) — 시도 short명을 시군구명으로 대신 채워 포함시킨다.
            if str(r['sgg_cd']).endswith('000') or not short:
                continue
            nm = short
        if short:
            sido_codes[short].add(r['sgg_cd'])
            sido_by_code[r['sgg_cd']] = short
        sgg_name_by_code[r['sgg_cd']] = nm
        name_codes[nm].add(r['sgg_cd'])
        name_codes[nm.split(' ')[0]].add(r['sgg_cd'])   # "창원시 마산합포구" -> "창원시"도 매칭
        eup = r['eup']
        if isinstance(eup, str) and eup:
            bjdong_by_sgg[r['sgg_cd']].add(r['bjd_cd'][5:])
    return sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg


def expand_livezone(livezone, sido_codes, name_codes, sgg_name_by_code, unresolved_names):
    """LIVEZONE 전개(‘*’→시도 전체, 이름→그 시군구) + 경기 전체 시/군. sgg_cd->name."""
    targets = {}
    for zone, members in livezone.items():
        for sido, sgg in members:
            if sgg == '*':
                codes = sido_codes.get(sido, set())
                if not codes:
                    unresolved_names.append((zone, sido, sgg))
                for c in codes:
                    targets[c] = sgg_name_by_code.get(c, c)
            else:
                codes = name_codes.get(sgg)
                if not codes:
                    unresolved_names.append((zone, sido, sgg))
                    continue
                for c in codes:
                    targets[c] = sgg_name_by_code.get(c, c)
    for c in sido_codes.get('경기', set()):
        targets.setdefault(c, sgg_name_by_code.get(c, c))
    return targets


def fold_groups(targets, sido_by_code, bjdong_by_sgg, old_gu_map):
    """target sgg_cd(구 단위 분할 포함) -> 논리 시군구 그룹으로 접기.

    그룹 키 = 대표 코드. 구가 있는 시(성남·창원·청주 등)는 "{시명}"만 있는
    본체 행(법정동 0개인 상위 코드)이 항상 그 시의 하위 구 코드보다 수치가
    작다(실측 확인: 41130 성남시 < 41131/41133/41135 각 구) — 정렬 후 첫 코드를
    대표 키로 쓴다. 구 분할이 없는 시군구는 코드가 하나뿐이라 그 자신이 대표.
    옛 구코드(old_gu_map)를 가진 그룹은 code_bdong.json에 법정동이 하나도
    없으면(Task 1 실측) enumerable=False로 표시해 fetch 단계에서 건너뛴다.
    """
    by_key = collections.defaultdict(list)   # (sido, base명) -> [sgg_cd...]
    for c, nm in targets.items():
        base = nm.split(' ')[0]
        by_key[(sido_by_code.get(c), base)].append(c)

    out = {}
    for (sido, base), codes in by_key.items():
        codes_sorted = sorted(codes)
        rep = codes_sorted[0]                # 대표(그룹) 키
        member_bjdong = {c: sorted(bjdong_by_sgg.get(c, ())) for c in codes_sorted}
        legacy = None
        if rep in old_gu_map:
            legacy_codes = old_gu_map[rep]
            # 옛 구코드(41192/94/96 등) 자신은 code_bdong.json에 법정동 행이
            # 전혀 없다(2016 구 폐지로 통째 삭제) — 그래서 예전엔 이 조건이
            # 항상 False였다. 실측(2026-07-27)으로 뒤집혔다: 대표(rep, 여기선
            # 통합 부천시 41190) 자신의 법정동 목록을 "옛 구코드로" 조회하면
            # 실데이터가 나온다. 그래서 enumerable은 옛 구코드가 아니라 대표
            # 자신의 법정동 보유 여부로 판정한다(항상 참에 가까움 — 대표는
            # targets에 있던 코드라 법정동이 있을 수밖에 없다).
            enumerable = bool(member_bjdong.get(rep))
            legacy = {'legacy_codes': legacy_codes, 'enumerable': enumerable}
        out[rep] = {
            'name': base, 'sido': sido, 'members': codes_sorted,
            'bjdong': member_bjdong, 'legacy': legacy,
        }
    return out


def apply_gangwon_fix(groups, code_fix=None):
    """강원 원주/춘천/강릉권 rep 코드를 스테일 42xxx -> 실사용 51xxx로 옮긴다
    (hub_common.GANGWON_CODE_FIX, 배경은 그 상수 주석 참고).

    fold_groups는 code_bdong.json 실측 그대로 42xxx를 대표(rep) 코드로 뽑아내는데,
    이 코드는 라이브 API에서 죽은 코드다. bjdong(법정동) 목록은 신/구 코드가
    동일하므로(실측 확인) 그대로 재사용하고, rep 키·members·bjdong dict의 키만
    51xxx로 다시 쓴다 — RENAME이지 단순 추가가 아니다(42xxx 키를 남겨두면 나중에
    두 코드가 서로 다른 그룹으로 따로 잡혀 있던 값이 뒤섞일 수 있다)."""
    code_fix = code_fix or H.GANGWON_CODE_FIX
    out = dict(groups)
    for old, new in code_fix.items():
        if old not in out:
            continue
        g = out.pop(old)
        # 구 분할 도시(전주=본체+완산구+덕진구)는 rep뿐 아니라 멤버 코드도 전부
        # 스테일이다. 예전엔 `m == old`로 rep만 갈아끼워 45111/45113이 그대로 남았고,
        # 그 구들이 라이브 API에서 0건이라 전주 준공이 통째로 비었다(2026-07-31 실측).
        # 그래서 rep만이 아니라 members/bjdong의 모든 코드에 매핑을 적용한다.
        new_members = [code_fix.get(m, m) for m in g['members']]
        new_bjdong = {code_fix.get(k, k): v for k, v in g['bjdong'].items()}
        out[new] = dict(g, members=new_members, bjdong=new_bjdong)
    return out


def apply_legacy_gu_fix(groups):
    """옛 구코드(OLD_GU_MAP)를 가진 그룹의 조회를 legacy 코드로 팬아웃한다.

    실측(2026-07-27, 부천 24개 법정동 x 옛 원미/소사/오정구 72콤보 프로브):
    부천시(41190) 자신으로 조회하면 0건이지만, 부천시 "자신의" 법정동 코드를
    옛 3구(41192/41194/41196) 각각으로 조회하면 실데이터가 나온다 — 예:
    bjdong=10100(부천시 기준)을 41192/41194/41196에 각각 물으면 68/208/85건
    (셋 다 겹치지 않는 서로 다른 값). 2016 구 폐지 통합 이전 옛 3구가 각자
    독립된 법정동 번호체계를 썼던 흔적으로 보인다 — 같은 숫자 코드가 옛구마다
    다른 실제 동을 가리킨다. 그래서 하나의 법정동 코드를 옛구 전부에 물어야
    누락이 없다(24개 동 중 9개만 실제로 히트, 15개는 셋 다 0건 — 무해한
    빈호출, 기존 무데이터 처리로 안전하게 스킵됨).

    group['bjdong']를 {대표코드: [법정동...]}에서 {옛구코드: 대표의 법정동
    목록} × N개 옛구로 재구성한다 — fetch_group/fetch_group_demol은 이미
    (sigunguCd, bjdong) 쌍을 순회하므로 이 재구성만으로 팬아웃이 자동
    적용된다(fetch 로직 자체는 무변경). 대표 키(hub_permits.json의 sgg
    엔트리 키) 자체는 그대로 41190 — GANGWON_CODE_FIX(대표 자체를 rekey)와
    달리 이건 대표 아래 "무엇을 조회하느냐"만 바꾸는 팬아웃이다.
    """
    out = dict(groups)
    for rep, g in groups.items():
        legacy = g.get('legacy')
        if not legacy or not legacy.get('enumerable'):
            continue
        rep_bjdong = g['bjdong'].get(rep)
        if not rep_bjdong:
            continue
        new_bjdong = {lc: rep_bjdong for lc in legacy['legacy_codes']}
        out[rep] = dict(g, bjdong=new_bjdong)
    return out


def build_targets():
    """전체 대상 도출 파이프라인. 반환: (groups, unresolved_names).

    apply_legacy_gu_fix는 여기서 전역 적용하지 않는다 — 두 API(준공
    HsPmsHubService·멸실 ArchPmsHubService)가 옛 구코드 요구가 다르다는 게
    실측으로 확인됐다(부천, 2026-07-27): 준공은 대표코드(41190) 자체가
    빈응답이라 옛구코드(41192/94/96) 팬아웃이 필요하지만, 멸실은 대표코드
    자체로 실데이터가 나온다(41190/10100→521건 등, 벌크파일과도 정합: 부천
    멸실 46,580세대가 전부 41190 키로 잡혀 있음). 그래서 팬아웃은 준공 전용
    fetch_group()이 필요할 때만 그때그때 적용하고, group['bjdong']의
    "정본"(멸실 fetch_group_demol·hub_derive 등 다른 소비자가 보는 형태)은
    항상 대표코드 기준 그대로 둔다."""
    from update_adv_data import LIVEZONE, LZ_SIDO_FULL
    rows = load_bdong_rows()
    sido_codes, name_codes, sgg_name_by_code, sido_by_code, bjdong_by_sgg = \
        build_target_index(rows, LZ_SIDO_FULL)
    unresolved_names = []
    targets = expand_livezone(LIVEZONE, sido_codes, name_codes, sgg_name_by_code, unresolved_names)
    groups = fold_groups(targets, sido_by_code, bjdong_by_sgg, H.OLD_GU_MAP)
    groups = apply_gangwon_fix(groups)
    return groups, unresolved_names


# ---------------------------------------------------------------------------
# 2. HTTP 호출·XML 파싱 (curl subprocess, 페이싱·재시도)
# ---------------------------------------------------------------------------

def classify_response(body):
    """'empty'(재시도 대상) | 'no_data_json'(파라미터 누락형, 정상 무재시도) |
    'no_data_xml'(진짜 0건, 정상 무재시도) | 'error'(인증/쿼터 등 오류, 재시도+로그
    대상) | 'data'.

    함정(Finding 1): data.go.kr의 인증/쿼터 오류 응답(SERVICE KEY IS NOT
    REGISTERED ERROR, LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR 등)도
    <item> 태그가 없는 XML로 온다 — 즉 겉모습이 진짜 "0건" 응답과 똑같다.
    구분 없이 전부 no_data_xml로 취급하면, 여러 시간 걸리는 --full 실행
    도중에 발생한 rate-limit 차단이나 키 오류가 "그 법정동은 인허가 0건"으로
    조용히 기록되어 데이터가 유실된다. 그래서 <item> 없는 XML은 반드시
    resultCode/오류봉투를 먼저 확인한다: resultCode가 정상(00)일 때만 진짜
    0건(no_data_xml)이고, 그 외(다른 resultCode, <cmmMsgHeader>/
    returnReasonCode/returnAuthMsg 오류 봉투, resultCode 자체가 없는 예상 밖
    포맷)는 전부 'error'로 분류해 재시도·로그 경로를 타게 한다.
    """
    b = (body or '').strip()
    if len(b) == 0:
        return 'empty'
    if b.startswith('{'):
        return 'no_data_json'
    if '<item>' not in b:
        if ('<cmmMsgHeader>' in b or 'returnReasonCode' in b or 'returnAuthMsg' in b):
            return 'error'
        m = re.search(r'<resultCode>\s*([^<]*)\s*</resultCode>', b)
        if m and m.group(1).strip() == '00':
            return 'no_data_xml'
        return 'error'
    return 'data'


def _extract_error_info(body):
    """오류 XML에서 코드/메시지 추출(로그 출력용). 봉투 형식이 두 가지라 순서대로 탐색."""
    b = body or ''
    code = re.search(r'<returnReasonCode>\s*([^<]*)\s*</returnReasonCode>', b) \
        or re.search(r'<resultCode>\s*([^<]*)\s*</resultCode>', b)
    msg = re.search(r'<returnAuthMsg>\s*([^<]*)\s*</returnAuthMsg>', b) \
        or re.search(r'<resultMsg>\s*([^<]*)\s*</resultMsg>', b)
    return (code.group(1).strip() if code else '?',
            msg.group(1).strip() if msg else b[:120].strip())


def _curl_get(sigungu, bjdong, page, endpoint=EP):
    cmd = ['curl', '-sS', '-G', endpoint,
           '--data-urlencode', 'serviceKey=%s' % KEY,
           '--data-urlencode', 'sigunguCd=%s' % sigungu,
           '--data-urlencode', 'bjdongCd=%s' % bjdong,
           '--data-urlencode', 'numOfRows=%d' % NUM_ROWS,
           '--data-urlencode', 'pageNo=%d' % page]
    try:
        # Windows에서 text=True 기본 인코딩은 로케일(cp949)이라, curl이 뱉는
        # UTF-8 한글(bldNm/platPlc 등)을 디코딩하다 UnicodeDecodeError로 죽는다.
        # 반드시 encoding='utf-8'을 명시해야 한다(2026-07-23 실측 확인).
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=30)
        return r.stdout or ''
    except subprocess.TimeoutExpired:
        return ''


def fetch_page(sigungu, bjdong, page, endpoint=EP):
    """재시도 포함 1페이지 호출. 반환 (body, cls).

    'error'(Finding 1: 인증/쿼터 오류 등 <item> 없는 오류 XML)는 'empty'와
    동일하게 재시도 대상으로 취급한다 — 그러지 않으면 rate-limit/키 오류가
    진짜 0건과 구별 없이 그대로 통과해버린다. 매 시도마다 WARN을 찍어
    무인 클라우드 실행 로그에서 바로 보이게 하고, 재시도를 다 써도 풀리지
    않으면 ERROR로 명확히 남긴다(어느 시군구/법정동이 실패했는지 추적 가능).

    endpoint 인자(기본 EP=준공)로 멸실(EP_DEMOL) 등 다른 서비스도 동일
    페이싱/재시도/에러분류 경로를 재사용한다 — --demol을 안 주면 항상 EP라
    준공 경로는 byte-identical.
    """
    body, cls = '', 'empty'
    for attempt in range(MAX_RETRY):
        body = _curl_get(sigungu, bjdong, page, endpoint=endpoint)
        cls = classify_response(body)
        if cls == 'error':
            code, msg = _extract_error_info(body)
            print('WARN %s/%s p%d 시도%d/%d: API 오류 응답(code=%s msg=%s) — 재시도'
                  % (sigungu, bjdong, page, attempt + 1, MAX_RETRY, code, msg))
        time.sleep(PACE)
        if cls not in ('empty', 'error'):
            return body, cls
        time.sleep(PACE * (attempt + 1))   # 추가 backoff
    if cls == 'error':
        code, msg = _extract_error_info(body)
        print('ERROR %s/%s p%d: 재시도(%d회) 소진 — API 오류 지속(code=%s msg=%s), 0건으로 기록하지 않음'
              % (sigungu, bjdong, page, MAX_RETRY, code, msg))
    return body, cls


def parse_items(xml):
    items = []
    for blk in re.findall(r'<item>(.*?)</item>', xml, re.S):
        d = {t: v for t, v in re.findall(r'<(\w+)>([^<]*)</\1>', blk)}
        items.append(d)
    return items


def parse_total_count(xml):
    m = re.search(r'<totalCount>(\d+)</totalCount>', xml)
    return int(m.group(1)) if m else None


def fetch_bjdong_all_pages(sigungu, bjdong, log=None, endpoint=EP):
    """법정동 하나의 전 페이지를 모아 (아이템 리스트, had_error) 반환.

    Fix pass 2: had_error=True는 이 법정동의 마지막 페이지 호출이 재시도
    (MAX_RETRY)를 다 쓰고도 'error'로 남았다는 뜻 — 즉 fetch_page가 이미
    ERROR를 찍은 "수집 실패"다(Finding 1과 동일 신호를 여기서 상위로
    전달). 이 플래그가 하나라도 True인 그룹은 fetch_group이
    had_unresolved_error로 묶어 올려 run()이 그룹 전체 결과를 신뢰하지
    않게 한다 — 그러지 않으면 지속 장애 중 일부만 실패한 그룹도 나머지
    법정동의 빈약한 부분합으로 done_q/sched_q가 조용히 확정돼버린다.
    """
    items = []
    page = 1
    had_error = False
    total_count = None
    while True:
        body, cls = fetch_page(sigungu, bjdong, page, endpoint=endpoint)
        if cls == 'data':
            page_items = parse_items(body)
            items.extend(page_items)
            if total_count is None:
                total_count = parse_total_count(body)
            # ⚠️ 실측(2026-07-27): 서버가 요청한 numOfRows(=NUM_ROWS=1000)를
            # 무시하고 페이지당 자체 상한(관측값 100)만 돌려준다 — 응답의
            # <numOfRows> 에코도 100이다. 예전엔 "이번 페이지 건수 <
            # 요청한 NUM_ROWS"를 "마지막 페이지"로 오판해, totalCount가
            # 100을 넘는 법정동은 뒤 페이지를 통째로 놓쳤다(강남 삼성동
            # totalCount=1072인데 100건만 수집되는 등 — 준공·멸실 둘 다
            # 영향, 이 실측으로 프로젝트 전체 재시딩 필요 확정). 그래서
            # "요청값 대비 이번 페이지 크기"가 아니라 "누적 items가
            # totalCount에 도달했는가"로 종료를 판단한다 — 서버의 페이지당
            # 실제 상한이 얼마든(100이든 다른 값이든) 안전하다.
            if total_count is not None and len(items) >= total_count:
                break
            if not page_items:   # 안전판: totalCount 파싱 실패 등으로 무한루프 방지
                break
            page += 1
            continue
        if cls == 'no_data_json' and log is not None:
            log.append('WARN %s/%s p%d: 파라미터 누락형 무자료 응답(호출 확인 필요)'
                        % (sigungu, bjdong, page))
        if cls == 'error':
            had_error = True
        # no_data_xml(진짜 0건) / no_data_json / 재시도 소진(empty, error) 모두
        # 더 페이지 없음으로 종료. 'error'가 재시도 끝까지 안 풀린 경우 이미
        # fetch_page가 ERROR 라인을 찍었으므로 이 법정동은 0건이 아니라
        # "수집 실패"로 로그에 남고, items에는 아무것도 추가되지 않는다
        # (진짜 0건과 겉보기 결과는 같아도 로그로는 구분된다 — Finding 1).
        break
    return items, had_error


# ---------------------------------------------------------------------------
# 3. 그룹 단위 수집·집계
# ---------------------------------------------------------------------------

UNITS_CAP = 40   # 시군구당 단지 리스트 상한(세대 큰 순) — 원시 전량 보존 방지
# 2단계 캡: 여기서 시군구당 40개(수집기 슈퍼셋)로 자르고, tools/update_adv_data.py
# _zone_units()의 UCAP=20이 생활권(존)당 다시 상위 20개(표시 서브셋)로 자른다.
# 시군구 1곳이 생활권 1곳에 대응하는 게 보통이라 40>20 여유를 의도적으로 둔 것 —
# 두 상수가 "안 맞는다"고 하나로 통일하지 말 것.


def _aggregate(items):
    """apt_records(공동주택·세대>0·PK dedupe) → 단지 최신단계 1회 분류.
    준공(useInsptDay) 있으면 done_q, 없고 준공예정(useInsptSchedDay) 있으면 sched_q,
    둘 다 없으면 미정(어디에도 안 감). 착공/인허가는 점수에 직접 안 쓴다.

    Task 7: done_q/sched_q 분류와 함께 단지 단위 raw 목록도 축적한다
    (`units`: [bldNm, 세대, 'YYYY-MM', 'done'|'sched']) — 존 상세페이지의
    "앞으로 들어올 물량"/"최근 들어온 물량" 리스트 렌더용. 원시 전량이 아니라
    세대 큰 순 상위 UNITS_CAP개로 잘라 hub_permits.json 비대화를 막는다."""
    done_q = collections.defaultdict(int)
    sched_q = collections.defaultdict(int)
    units = []
    for r in H.apt_records(items):
        try:
            n = int(float(r.get('totHhldCnt') or 0))
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        name = r.get('bldNm') or ''
        dq = H.to_quarter(r.get('useInsptDay'))
        if dq:
            done_q[dq] += n
            units.append([name, n, H.to_yearmonth(r.get('useInsptDay')), 'done'])
            continue
        sq = H.to_quarter(r.get('useInsptSchedDay'))
        if sq:
            sched_q[sq] += n
            units.append([name, n, H.to_yearmonth(r.get('useInsptSchedDay')), 'sched'])
        # 둘 다 없으면 미정 — 미반영
    # ⚠️ 캡을 stage별로 따로 건다(2026-08-01). 예전엔 done+sched를 섞어 세대 큰 순
    # 상위 40개만 남겼는데, 큰 시군구는 옛 준공 대단지가 40칸을 다 차지해 '앞으로
    # 들어올 단지' 목록이 비다시피 했다(춘천권 차트 5분기 중 목록엔 2곳만).
    # done/sched 각각 UNITS_CAP개면 존 페이지 두 섹션이 모두 채워진다.
    units.sort(key=lambda u: -u[1])
    kept = ([u for u in units if u[3] == 'done'][:UNITS_CAP]
            + [u for u in units if u[3] == 'sched'][:UNITS_CAP])
    return dict(done_q), dict(sched_q), kept


def _aggregate_demol(items):
    """demol_records(공동주택·세대>0·mgmPmsrgstPk dedupe) -> 분기별 멸실 세대수.

    순공급 = 준공 − 멸실 보정(기준표 근거)을 위해 "시장에서 실제로 빠진 시점"을
    기준으로 분기화한다: demolEndDay(철거완료일)을 최우선으로 쓰고, 없으면
    demolExtngDay(멸실일), 그마저 없으면 demolStrtDay(철거시작일) 순으로
    fallback한다. 준공의 useInsptDay/useInsptSchedDay와 필드명이 완전히
    달라(mainPurpsCdNm/hhldCnt/철거일 3종) _aggregate()와 별개 경로로 둔다."""
    demol_q = collections.defaultdict(int)
    for r in H.demol_records(items):
        try:
            n = int(float(r.get('hhldCnt') or 0))
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        day = r.get('demolEndDay') or r.get('demolExtngDay') or r.get('demolStrtDay')
        q = H.to_quarter(day)
        if q:
            demol_q[q] += n
        # 철거일 3종 모두 없으면 미정 — 미반영(준공의 "둘 다 없으면 미반영"과 동일 정책)
    return dict(demol_q)


def fetch_group(group, only_bjdong=None):
    """그룹(시/구 분할 포함) 호출해 done_q/sched_q/units 집계 + productive bjdong 목록.

    only_bjdong이 주어지면(증분 모드) 그 집합(10자리 전체 법정동코드)에 속하는
    법정동만 재조회한다. None이면(--full) 그룹 소속 전체 법정동을 조회한다.

    반환에 had_unresolved_error(bool)를 추가(Fix pass 2): 그룹 소속 법정동
    중 하나라도 재시도 소진 후에도 'error'로 남았으면 True. 지속 장애(인증/
    쿼터/레이트리밋) 중에는 이미 처리한 법정동의 실제 카운트와 아직 못 푼
    법정동의 공백이 뒤섞인 done_q/sched_q가 나오므로, 이 신호를 호출자
    (run())에게 넘겨 "이번 회차 결과를 그룹 값으로 확정하면 안 된다"고
    판단하게 한다.

    반환 튜플 순서: (done_q, sched_q, units, productive, had_unresolved_error).

    준공(HsPmsHubService) 전용 옛구코드 팬아웃: legacy 그룹(부천 등)은 대표
    코드 자체로 조회하면 빈응답이라(실측), 여기서만 그때그때
    apply_legacy_gu_fix를 적용해 옛구코드들로 팬아웃한다. group 자체(다른
    호출자가 보는 원본)는 건드리지 않는다 — fetch_group_demol은 이 팬아웃이
    필요 없다(멸실 API는 대표코드 자체로 응답, 실측 확인).
    """
    bjdong_map = group['bjdong']
    if group.get('legacy') and group['legacy'].get('enumerable'):
        rep_key = next(iter(group['bjdong']), None)   # legacy 그룹은 현재 항상 단일 멤버(부천)
        if rep_key is not None:
            bjdong_map = apply_legacy_gu_fix({rep_key: group})[rep_key]['bjdong']
    all_items = []
    productive = []
    had_unresolved_error = False
    for member_cd, bjdongs in bjdong_map.items():
        for bjdong in bjdongs:
            full = member_cd + bjdong   # 10자리 전체 법정동코드
            if only_bjdong is not None and full not in only_bjdong:
                continue
            items, had_error = fetch_bjdong_all_pages(member_cd, bjdong)
            if had_error:
                had_unresolved_error = True
            if H.apt_records(items):
                productive.append(full)
            all_items.extend(items)
    done_q, sched_q, units = _aggregate(all_items)
    return done_q, sched_q, units, productive, had_unresolved_error


def fetch_group_demol(group, only_bjdong=None):
    """fetch_group의 멸실 버전 — 같은 그룹/법정동 순회·페이싱·에러분류
    기계를 EP_DEMOL과 _aggregate_demol로 재사용한다. 준공용 fetch_group은
    건드리지 않고 별도 함수로 둬 준공 경로가 byte-identical하게 남는다.

    반환 튜플 순서: (demol_q, productive, had_unresolved_error). 준공과
    달리 sched_q/units 개념이 없어(철거는 '예정'을 점수화 대상으로 안 씀)
    3-튜플로 단순화했다.

    ⚠️ 전북 예외(H.DEMOL_CODE_REVERSE, 상세는 그 상수 주석): 멸실 API는 전북을
    아직 구 코드(45xxx)로만 응답한다. build_targets가 준공 기준으로 신 코드
    (52xxx)를 물려주므로, 여기서만 조회 코드를 구 코드로 되돌린다. 저장 키
    (productive의 full 코드)는 그룹 기준(신 코드) 그대로 유지해 준공 쪽
    productive_bjdong과 체계가 어긋나지 않게 한다.
    """
    all_items = []
    productive = []
    had_unresolved_error = False
    for member_cd, bjdongs in group['bjdong'].items():
        query_cd = H.DEMOL_CODE_REVERSE.get(member_cd, member_cd)
        for bjdong in bjdongs:
            full = member_cd + bjdong
            if only_bjdong is not None and full not in only_bjdong:
                continue
            items, had_error = fetch_bjdong_all_pages(query_cd, bjdong, endpoint=EP_DEMOL)
            if had_error:
                had_unresolved_error = True
            if H.demol_records(items):
                productive.append(full)
            all_items.extend(items)
    demol_q = _aggregate_demol(all_items)
    return demol_q, productive, had_unresolved_error


def should_refresh_group(key, group_bjdong, cached_productive, mode_full):
    """기본(증분) 모드에서 이 그룹을 갱신해도 되는지 판정(순수, 네트워크 없음).

    Finding 2: 기본 모드는 그룹 소속 법정동 중 cached_productive에 있는 것만
    fetch_group(only_bjdong=cached_productive)로 재조회한다. 그런데 자기
    소속 법정동이 cached_productive에 하나도 없는 그룹(=아직 한 번도 --full/
    --only로 스캔된 적 없는 그룹)은 fetch_group이 호출을 아예 하지 않고 빈
    dict({}, {})를 돌려주는데, 이걸 그대로 out['sgg'][key]에 쓰면 "스캔했더니
    0건"과 "아직 스캔 안 함"이 구별 불가능한 거짓 0으로 기록된다. 148개 그룹 중
    소수만 seed된 상태에서 인자 없이(기본모드) 실행하면 나머지 대부분이 이렇게
    오염된다 — 이 함수는 그런 그룹을 걸러 out['sgg'][key]를 건드리지 않게 한다.
    --full/--only는 실제로 전량(또는 지정 그룹 전량)을 스캔하므로 항상 True.
    """
    if mode_full:
        return True
    group_bjdong_flat = {member_cd + b for member_cd, bs in group_bjdong.items() for b in bs}
    return bool(group_bjdong_flat & cached_productive)


# ---------------------------------------------------------------------------
# 4. 출력 I/O(체크포인트 저장) · CLI
# ---------------------------------------------------------------------------

def load_existing():
    if os.path.exists(OUT_PATH):
        d = json.load(io.open(OUT_PATH, encoding='utf-8'))
        # 하위호환(Fix pass 2): 이 필드 이전에 저장된 hub_permits.json에는
        # meta['scanned']가 아예 없다 — 없으면 빈 목록으로 취급해 로드가
        # 죽지 않게 한다(누락 = 아직 아무것도 '깨끗하게 스캔됨'으로 기록 안 됨).
        d.setdefault('meta', {}).setdefault('scanned', [])
        # 멸실(demol) 추가 시점 이전 파일에는 아래 키가 없다 — 준공 스캔
        # 진행상황(scanned/productive_bjdong)과 완전히 독립된 별도 자원이라
        # 없으면 빈 목록으로 채워 로드가 죽지 않게 하고, 준공 쪽 값은 절대
        # 건드리지 않는다.
        d['meta'].setdefault('scanned_demol', [])
        d.setdefault('productive_bjdong_demol', [])
        return d
    return {'meta': {'fetched': '', 'mode': '', 'unresolved_legacy': [], 'scanned': [], 'scanned_demol': []},
            'sgg': {}, 'productive_bjdong': [], 'productive_bjdong_demol': []}


def save(out):
    io.open(OUT_PATH, 'w', encoding='utf-8').write(
        json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))


def run(mode_full, only_codes, list_targets_only, reseed=False):
    groups, unresolved_names = build_targets()

    if list_targets_only:
        total_bjdong = sum(len(bs) for g in groups.values() for bs in g['bjdong'].values())
        gg_groups = [k for k, g in groups.items() if g['sido'] == '경기']
        multi_gu = {k: g for k, g in groups.items() if len(g['members']) > 1}
        legacy = {k: g for k, g in groups.items() if g['legacy']}
        print('논리 시군구(그룹) 수:', len(groups))
        print('원자 시군구코드 수(구 분할 포함):', sum(len(g['members']) for g in groups.values()))
        print('총 법정동 수:', total_bjdong)
        print('경기 시/군 그룹 수:', len(gg_groups))
        print('구 분할(다자녀) 그룹 수:', len(multi_gu), '예:',
              [(k, v['name'], v['members']) for k, v in list(multi_gu.items())[:3]])
        print('옛구코드 그룹:', {k: v['legacy'] for k, v in legacy.items()})
        if unresolved_names:
            print('LIVEZONE 미해결 항목:', unresolved_names)
        else:
            print('LIVEZONE 미해결 항목: 없음')
        return

    if not KEY:
        print('ERROR: DATA_GO_KR_KEY 환경변수가 비었다. 실호출 불가.')
        sys.exit(2)

    out = load_existing()
    cached_productive = set(out.get('productive_bjdong', []))
    unresolved_legacy = set(out['meta'].get('unresolved_legacy', []))
    # Fix pass 2: '깨끗하게(무재시도-오류 없이) 스캔 완료'된 그룹 키 집합.
    # should_refresh_group과 별개로, 스킵 로그가 "아직 스캔 안 함"과 "스캔은
    # 했는데 진짜 0건"을 구분하는 데 쓴다(Minor).
    scanned = set(out['meta'].get('scanned', []))

    target_keys = list(groups.keys())
    if only_codes:
        wanted = set(only_codes)
        missing = wanted - set(target_keys)
        if missing:
            print('WARN: --only 코드가 대상 집합에 없음:', missing)
        target_keys = [k for k in target_keys if k in wanted]

    if not mode_full and not cached_productive:
        print('WARN: productive_bjdong 캐시가 비어 있다. --full로 최초 1회 전량 수집이 필요하다.')

    t0 = time.time()
    n_done = 0
    for key in target_keys:
        group = groups[key]
        n_done += 1
        if group['legacy'] and not group['legacy']['enumerable']:
            print('[SKIP legacy] %s(%s): code_bdong.json에 법정동 없음 — unresolved_legacy 기록' % (key, group['name']))
            unresolved_legacy.add(key)
        elif mode_full and not reseed and key in scanned:
            # Fix pass(resumability): GitHub 호스티드 러너는 6시간 하드 캡이라
            # --full 전량(약 11~14시간)이 한 번의 워크플로 실행으로 안 끝난다.
            # 재트리거된 --full 실행이 처음부터 다시 도는 걸 막기 위해, 이미
            # 깨끗하게 스캔 완료된(meta['scanned']) 그룹은 건너뛰고 남은
            # 그룹만 이어서 스캔한다 — 그래야 여러 회 재트리거로 전량이
            # 언젠가 끝난다. 중간에 죽어 scanned에 못 들어간 그룹은 이
            # 분기를 안 타므로 다음 실행에서 자동으로 다시 스캔된다(허용:
            # 그룹 하나 재스캔은 무해). --reseed는 이 스킵을 무시하고 진짜
            # 처음부터 전량을 다시 돈다(연 1회 등 의도적 재구축용).
            print('[RESUME skip] %s(%s) 이미 스캔 완료' % (key, group['name']))
        elif not should_refresh_group(key, group['bjdong'], cached_productive, mode_full):
            # Finding 2: 기본(증분) 모드에서 아직 한 번도 스캔된 적 없는 그룹은
            # 건드리지 않는다. 그냥 fetch_group을 불러버리면 only_bjdong으로
            # 넘긴 cached_productive와 이 그룹 소속 법정동이 하나도 안 겹쳐
            # 호출 없이 빈 dict가 나오고, 그걸 out['sgg'][key]에 쓰면 "스캔해서
            # 0건"과 "아직 미수집"이 구별 안 되는 거짓 0이 찍힌다.
            # Fix pass 2(Minor): 다만 두 경우(never-scanned / scanned-genuinely-
            # zero) 모두 cached_productive와 겹치지 않아 이 분기로 온다 —
            # meta['scanned']로 실제 어느 쪽인지 갈라 로그만 정확히 남긴다
            # (동작 자체는 두 경우 다 skip으로 동일, 오해를 부르는 로그만 고침).
            if key in scanned:
                print('[SKIP scanned-zero] %s(%s): 이전에 깨끗하게 스캔 완료 — 생산적 법정동 없음(증분 재조회 대상 아님)'
                      % (key, group['name']))
            else:
                print('[SKIP not-yet-scanned] %s(%s): productive_bjdong 캐시에 자기 법정동 없음 — --full/--only로 먼저 수집 필요'
                      % (key, group['name']))
        else:
            elapsed = time.time() - t0
            print('[%d/%d] %s(%s) %d개 법정동 수집 시작 (경과 %ds)'
                  % (n_done, len(target_keys), key, group['name'],
                     sum(len(b) for b in group['bjdong'].values()), int(elapsed)))
            done_q, sched_q, units, productive, had_unresolved_error = fetch_group(
                group, only_bjdong=None if mode_full else cached_productive)
            if had_unresolved_error:
                # Important: 지속 장애(인증/쿼터/레이트리밋 등) 중에 그룹의
                # 일부 법정동만 실패해도, 그 부분합으로 out['sgg'][key]를
                # 덮어쓰면 이전에 실측된 진짜 카운트가 빈약한 값으로 조용히
                # clobber된다(콘솔 ERROR 로그 외엔 흔적이 없음). 기존 값이
                # 있으면 그대로 두고, 없으면 빈 placeholder도 쓰지 않는다.
                # productive_bjdong/scanned도 갱신하지 않아 다음 실행이 이
                # 그룹을 온전히 다시 시도하게 둔다.
                print('[SKIP error] %s(%s): 재시도 소진된 오류 있음 — 기존 값 보존, 다음 실행에서 재시도'
                      % (key, group['name']))
            else:
                new_entry = {'name': group['name'], 'done_q': done_q, 'sched_q': sched_q, 'units': units}
                # 멸실(--demol)이 먼저 이 시군구에 demol_q를 써놨을 수 있다 —
                # 준공 재스캔이 dict를 통째로 새로 만들며 그 값을 조용히
                # 지우면 두 수집기가 서로의 결과를 clobber한다. demol_q가
                # 있으면 그대로 이어붙인다(준공 쪽 출력 필드/값 자체는 이전과
                # byte-identical, demol_q가 없던 기존 상태에선 동작 변화 없음).
                prior_demol_q = out['sgg'].get(key, {}).get('demol_q')
                if prior_demol_q is not None:
                    new_entry['demol_q'] = prior_demol_q
                out['sgg'][key] = new_entry
                cached_productive.update(productive)
                scanned.add(key)   # 깨끗하게 스캔 완료 — never-scanned/scanned-zero 구분용 기록
                # apply_legacy_gu_fix로 enumerable=True가 된 legacy 그룹(부천 등)이
                # 실제로 스캔에 성공하면, 예전 실행이 남긴 unresolved_legacy 잔존
                # 마킹을 지운다 — 안 지우면 hub_derive가 이 시군구를 계속 존
                # 멤버에서 제외해(그 필터가 unresolved_legacy 기준) 실데이터를
                # 모아놓고도 영영 방출 안 되는 상태가 된다.
                unresolved_legacy.discard(key)
        out['productive_bjdong'] = sorted(cached_productive)
        out['meta']['unresolved_legacy'] = sorted(unresolved_legacy)
        out['meta']['scanned'] = sorted(scanned)
        out['meta']['fetched'] = str(datetime.date.today())
        out['meta']['mode'] = 'full' if mode_full else 'incr'
        save(out)   # 체크포인트: 그룹 하나 끝날 때마다 저장(스킵 포함)

    print('완료: %d개 그룹, 총 %ds' % (n_done, int(time.time() - t0)))


def run_demol(mode_full, only_codes, reseed=False):
    """멸실(--demol) 수집 실행. run()과 그룹 순회·resume·pacing 뼈대는 동일하되:

    - meta['scanned']/productive_bjdong(준공)은 절대 건드리지 않는다. 대신
      완전히 독립된 meta['scanned_demol']/productive_bjdong_demol을 쓴다 —
      준공 시딩이 ~90% 끝난 상태라 재스캔/오염되면 안 되기 때문(Task 지시).
    - out['sgg'][key]에 demol_q만 추가/갱신한다(name은 유지, done_q/sched_q/
      units는 절대 안 건드림 — 그 그룹이 아직 준공 스캔 전이면 name만 있는
      부분 항목이 생기고, 이후 준공이 스캔되면 위 new_entry의 prior_demol_q
      보존 로직이 합쳐준다).
    - 대상 시군구/법정동 도출(build_targets)은 준공과 완전히 동일한 규칙을
      그대로 재사용한다(Task 지시: "대상 집합은 준공과 동일").
    """
    groups, unresolved_names = build_targets()

    if not KEY:
        print('ERROR: DATA_GO_KR_KEY 환경변수가 비었다. 실호출 불가.')
        sys.exit(2)

    out = load_existing()
    cached_productive_demol = set(out.get('productive_bjdong_demol', []))
    scanned_demol = set(out['meta'].get('scanned_demol', []))

    target_keys = list(groups.keys())
    if only_codes:
        wanted = set(only_codes)
        missing = wanted - set(target_keys)
        if missing:
            print('WARN: --only 코드가 대상 집합에 없음:', missing)
        target_keys = [k for k in target_keys if k in wanted]

    if not mode_full and not cached_productive_demol:
        print('WARN: productive_bjdong_demol 캐시가 비어 있다. --full로 최초 1회 전량 수집이 필요하다.')

    t0 = time.time()
    n_done = 0
    for key in target_keys:
        group = groups[key]
        n_done += 1
        if group['legacy'] and not group['legacy']['enumerable']:
            print('[SKIP legacy][demol] %s(%s): code_bdong.json에 법정동 없음 — unresolved_legacy는 준공 쪽에서 관리'
                  % (key, group['name']))
        elif mode_full and not reseed and key in scanned_demol:
            print('[RESUME skip][demol] %s(%s) 이미 스캔 완료' % (key, group['name']))
        elif not should_refresh_group(key, group['bjdong'], cached_productive_demol, mode_full):
            if key in scanned_demol:
                print('[SKIP scanned-zero][demol] %s(%s): 이전에 깨끗하게 스캔 완료 — 생산적 법정동 없음'
                      % (key, group['name']))
            else:
                print('[SKIP not-yet-scanned][demol] %s(%s): productive_bjdong_demol 캐시에 자기 법정동 없음 — --full/--only로 먼저 수집 필요'
                      % (key, group['name']))
        else:
            elapsed = time.time() - t0
            print('[%d/%d][demol] %s(%s) %d개 법정동 수집 시작 (경과 %ds)'
                  % (n_done, len(target_keys), key, group['name'],
                     sum(len(b) for b in group['bjdong'].values()), int(elapsed)))
            demol_q, productive, had_unresolved_error = fetch_group_demol(
                group, only_bjdong=None if mode_full else cached_productive_demol)
            if had_unresolved_error:
                # 준공 쪽과 동일한 clobber 방지 정책: 지속 장애로 부분합만
                # 나온 회차는 기존 demol_q를 덮어쓰지 않는다.
                print('[SKIP error][demol] %s(%s): 재시도 소진된 오류 있음 — 기존 값 보존, 다음 실행에서 재시도'
                      % (key, group['name']))
            else:
                # 준공(done_q/sched_q/units)이 있으면 그대로 보존하고 demol_q만
                # 추가/갱신한다. 아직 준공 스캔 전인 그룹은 name만 있는 부분
                # 항목이 생긴다 — 준공이 나중에 스캔되면 run()의 prior_demol_q
                # 보존 로직이 합쳐 완전한 항목이 된다.
                sgg_entry = out['sgg'].setdefault(key, {})
                sgg_entry['name'] = group['name']
                sgg_entry['demol_q'] = demol_q
                cached_productive_demol.update(productive)
                scanned_demol.add(key)
        out['productive_bjdong_demol'] = sorted(cached_productive_demol)
        out['meta']['scanned_demol'] = sorted(scanned_demol)
        out['meta']['fetched_demol'] = str(datetime.date.today())
        save(out)   # 체크포인트: 그룹 하나 끝날 때마다 저장(스킵 포함)

    print('완료(멸실): %d개 그룹, 총 %ds' % (n_done, int(time.time() - t0)))


def main():
    ap = argparse.ArgumentParser(description='건축HUB 시군구 인허가/착공 페이싱 수집기')
    ap.add_argument('--list-targets', action='store_true', help='대상 시군구/법정동만 도출해 개수 출력(호출 없음)')
    ap.add_argument('--full', action='store_true',
                     help='전량 수집(첫 실행 필수). 이미 meta["scanned"]에 있는 그룹은 건너뛰고 '
                          '이어서 스캔한다(RESUMABLE) — GitHub 러너 6시간 캡을 넘는 첫 시딩을 '
                          '여러 번 재트리거해 이어서 완료하기 위함. 처음부터 다시 돌리려면 --reseed.')
    ap.add_argument('--reseed', action='store_true',
                     help='--full과 함께: meta["scanned"] 무시하고 전량을 처음부터 다시 스캔(의도적 재구축용, 예: 연 1회)')
    ap.add_argument('--only', default='', help='콤마구분 그룹 코드로 제한(표본 검증용, 예: 41370,41190,41130)')
    ap.add_argument('--demol', action='store_true',
                     help='멸실(철거) 수집 모드 — ArchPmsHubService 철거멸실관리대장 엔드포인트. '
                          'meta["scanned_demol"]/productive_bjdong_demol로 준공(meta["scanned"])과 '
                          '완전히 독립적으로 추적하므로 준공 시딩 진행상황을 건드리지 않는다.')
    args = ap.parse_args()
    only_codes = [c.strip() for c in args.only.split(',') if c.strip()] if args.only else None
    if args.demol and not args.list_targets:
        run_demol(args.full, only_codes, reseed=args.reseed)
    else:
        run(args.full, only_codes, args.list_targets, reseed=args.reseed)


if __name__ == '__main__':
    main()

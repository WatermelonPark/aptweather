"""건축HUB 수집·집계 공용 순수 헬퍼 (네트워크 없음)."""
import re

# Task 1에서 실측 확정한 값으로 채운다.
OLD_GU_MAP = {
    '41190': ['41192', '41194', '41196'],  # 부천(2016 구 폐지)
}

# 강원(2023 강원도->강원특별자치도 개편, sigunguCd 42xxx->51xxx) 대응.
# code_bdong.json(3rd-party 법정동코드 미러)에는 원주권/춘천권/강릉권의 신 코드
# (51110/51130/51150) 행이 아예 없고, 구 코드(42110/42130/42150)가 말소일자
# 없이(=활성인 것처럼) 남아있다(실측 확인) — build_targets()가 이 스테일 코드로
# 대상을 도출해 라이브 API에 넣으면 빈/오결과가 나온다.
# 실측으로 확정한 사실: bjdong(법정동) 5자리 접미사는 구/신 코드가 완전히 동일하다
# (예: sigunguCd=51110&bjdongCd=11200 -> resultCode=00, totalCount=64 실호출 확인,
# 11200은 code_bdong.json의 42110 그룹 bjdong 목록에 이미 있음). 그래서 sigunguCd
# 접두만 이 표로 고쳐 쓰면 되고, bjdong 목록은 그대로 재사용할 수 있다(신규 소스
# 불필요) — 부천 OLD_GU_MAP(레거시->다중 구코드 전개)과는 방향이 정반대(구->신
# 단일 코드 치환)다.
# 강릉권은 LIVEZONE상 강릉시 외에 동해시(42170)·속초시(42210)도 멤버인데, fold_groups는
# LIVEZONE 존이 아니라 (시도,시명) 단위로 그룹을 접기 때문에 이 둘은 강릉시와 별개
# 그룹(각자가 자기 rep)이라 원래 3코드 표에 없었다 — 그래서 42150만 고쳐진 뒤에도
# 동해/속초는 계속 스테일 상태였다. 42110/42130/42150과 동일 패턴(sigunguCd=51170/
# 51210 실호출 -> resultCode=00, item 존재; 42170/42210은 resultCode=00·item 0개)을
# 실측 확인(2026-07-25)하여 추가.
# 전북특별자치도(2024-01-18 출범)도 같은 패턴이 2026-07-31 실측으로 확인됐다:
# code_bdong.json은 구 코드(45xxx)만 활성으로 갖고 있는데 라이브 API는 신 코드
# (52xxx)로만 응답한다 — 군산 45130/10100 -> totalCount 0 vs 52130/10100 -> 3건,
# 익산 45140 4개동 0건 vs 52140 7건, 전주 덕진구 45113/10100 0건 vs 52113 3건.
# 이 때문에 전북 4개 그룹(전주·군산·익산·완주)이 전량 재시딩(148/148 "완료")에도
# 준공 0세대로 남아 군산익산권이 fallback으로 방출됐다(전주권은 sched만 잡혀
# inventory였으나 done이 0이라 역시 오염). 전주는 구 분할 도시라 본체+완산구+
# 덕진구 3코드를 모두 옮겨야 한다.
# ⚠️ 이름은 GANGWON_CODE_FIX지만 실제로는 "시도 개편 스테일 코드" 일반 표다
# (강원 5 + 전북 6). 다른 시도가 또 개편되면 여기에 추가한다.
GANGWON_CODE_FIX = {
    # 강원특별자치도(2023-06-11 출범) 42xxx -> 51xxx
    '42110': '51110', '42130': '51130', '42150': '51150',
    '42170': '51170', '42210': '51210',
    # 전북특별자치도(2024-01-18 출범) 45xxx -> 52xxx
    '45110': '52110', '45111': '52111', '45113': '52113',   # 전주시(본체·완산구·덕진구)
    '45130': '52130', '45140': '52140', '45710': '52710',   # 군산시·익산시·완주군
}

# ⚠️ 두 API가 시도 개편을 서로 다른 속도로 반영한다(2026-07-31 실측).
#   준공(HsPmsHubService): 강원·전북 모두 신 코드로만 응답 -> GANGWON_CODE_FIX 그대로 적용.
#   멸실(ArchPmsHubService): 강원은 신 코드(원주 51130 3개동 68건 vs 42130 0건)인데
#     **전북만 아직 구 코드**다(군산 45130 3개동 15건 vs 52130 0건, 익산 45140 5개동
#     83건 vs 52140 0건). 즉 전북은 준공=52xxx / 멸실=45xxx로 갈린다.
# 그래서 멸실 조회 때만 전북 신->구로 되돌리는 역매핑을 둔다. 강원은 여기 넣지 않는다
# (넣으면 멀쩡히 나오던 강원 멸실이 죽는다). 나중에 멸실 API가 전북을 신 코드로
# 옮기면 이 표를 비우면 된다 — 그때까진 이게 없으면 전북 4곳 멸실이 통째로 0이 된다.
DEMOL_CODE_REVERSE = {
    '52110': '45110', '52111': '45111', '52113': '45113',
    '52130': '45130', '52140': '45140', '52710': '45710',
}

def to_quarter(day):
    if not day:
        return None
    s = re.sub(r'\D', '', str(day))
    if len(s) < 6:
        return None
    y, m = int(s[:4]), int(s[4:6])
    if not (1900 < y < 2100 and 1 <= m <= 12):
        return None
    return '%dQ%d' % (y, (m - 1) // 3 + 1)

def to_yearmonth(day):
    """'YYYYMMDD'류 원자료 날짜 -> 'YYYY-MM' 또는 None(결측/형식오류)."""
    if not day:
        return None
    s = re.sub(r'\D', '', str(day))
    if len(s) < 6:
        return None
    y, m = int(s[:4]), int(s[4:6])
    if not (1900 < y < 2100 and 1 <= m <= 12):
        return None
    return '%04d-%02d' % (y, m)

def dedupe(items, key='mgmHsrgstPk'):
    seen = {}
    for it in items:
        k = it.get(key)
        if k is None:
            continue
        seen[k] = it
    return list(seen.values())

# 이중등재 접기(2026-08-03 감사)에서 무시할 필드.
#   mgmHsrgstPk — 관리대장 키. **'단지' 키가 아니다.** 같은 사업이 서로 다른 PK로
#     두 번 적재된 사례가 전국적으로 확인됐다(아래 참고).
#   rnum — 응답 안의 행번호(페이지네이션 부산물). 데이터가 아니다.
DUP_IGNORE_FIELDS = ('mgmHsrgstPk', 'rnum')

def collapse_dup_registrations(items, ignore=DUP_IGNORE_FIELDS):
    """PK·행번호를 뺀 모든 필드가 같은 레코드를 하나로 접는다.

    근거(2026-08-03 원시 대조, 4개 시군구 28개 중복그룹): 같은 사업이 지번·
    세대수·연면적·인허가일·준공(예정)일·레코드생성일까지 **전 필드가 동일한 채**
    PK만 다르게 두 번 등재돼 있다 — HUB 적재/이관이 만든 시스템성 중복이다.
    관측된 세 변형 전부 이 규칙 하나로 접힌다:
      · PK 인접 연번        1000...220546 / 1000...220547 (제물포역 3,497세대)
      · 신·구 PK 체계 혼재  1000...099016 / 1044100006146 (달서 본리동 589세대)
      · 접수기관 접두 상이  1044100004684 / 1049100009042 (대구 학정역 1,098세대)
    미래 준공예정 중복 174건 중 173건이 정확히 ×2인 것도 이 패턴과 정합한다.

    ⚠️ 일부러 좁게 잡았다. 같은 사업이 **호별·동별 대장으로 쪼개져** 각 대장에
    단지 총세대수가 복제된 유형(신림현대 1,634세대 × 56개 호별 대장, block/lot에
    동·호수가 들어 있음)은 block·lot·apprvDay가 서로 달라 여기서 접히지 않는다 —
    그건 지번 단위 사업 계상으로 따로 풀 문제다(감사 ③단계).

    ⚠️ 멸실(demol_records)에는 적용하지 않는다. 같은 패턴이 있는지 아직 실측하지
    않았고, 현재 멸실 값의 대부분은 API가 아니라 벌크파일 백필분이라 여기서
    바꾸면 검증 안 된 변경이 순부족에 흘러든다.
    """
    seen = {}
    for it in items:
        sig = tuple(sorted(
            (k, v.strip() if isinstance(v, str) else v)
            for k, v in it.items() if k not in ignore))
        seen.setdefault(sig, it)
    return list(seen.values())

def collapse_units_by_project(units):
    """units([이름, 세대, 'YYYY-MM', stage, 지번]) -> **사업 단위** 1건씩.

    같은 사업이 호별·동별·부속동 대장으로 쪼개진 채 각 대장에 단지 총세대수가
    복제돼 있다(2026-08-03 감사). 대장을 그대로 합산하면 단지 하나가 수십 번
    계상된다 — 외부 실측으로 확정한 사례:
      · 봉화산 e편한세상(원주 단계동) 실제 690세대 -> 105개 대장 = 72,450세대
        (원주시 전체 재고의 51%)
      · 신림현대(관악 신림동) 실제 1,634세대·14개 동 -> 53개 대장 = 약 86,600세대
        (대장마다 block=동번호·lot=호수가 다른 호별 등기)
      · 원주 명륜동 847-4의 '경비실' 대장이 세대수 280을 그대로 달고 있음
    [[collapse_dup_registrations]](PK만 다른 완전 복제)로는 이들이 안 접힌다 —
    block/lot/인허가일이 서로 달라 '실질 필드가 다른' 별개 레코드로 보이기 때문이다.

    키는 (지번, 세대수)다. 세대수를 키에 넣는 게 핵심 안전장치다: 한 지번에
    동별 대장이 **서로 다른 세대수**로 올라와 있으면(진짜 동별 분할) 각각
    살아남아 정상적으로 합산되고, **같은 세대수**가 반복될 때만 접힌다 —
    그건 단지 총세대수가 복제된 신호다.

    남길 1건을 고르는 규칙:
      · done이 하나라도 있으면 done을 남긴다(수집기의 '단지 최신단계 1회 분류'를
        사업 단위로 올린 것 — 이미 준공된 단지를 미래공급으로도 세면 이중계상).
      · 연월은 최빈값, 동률이면 이른 쪽. 리모델링·대수선으로 뒤늦게 붙은 소수
        대장이 원래 준공 시점을 밀어내지 않게 한다.
      · 이름은 최빈 비어있지 않은 값(표기 흔들림 흡수, 화면 표시용).

    ⚠️ 지번이 빈 항목은 접지 않고 그대로 둔다 — 판단 근거가 없는데 접으면
    서로 다른 사업을 뭉갤 수 있다(지번은 2026-08-03부터 수집한다).
    """
    out = []
    groups = {}
    for u in units:
        plat = (u[4] if len(u) > 4 else '') or ''
        if not plat.strip():
            out.append(u)          # 판단 불가 — 원본 유지
            continue
        groups.setdefault((plat.strip(), u[1]), []).append(u)
    for (plat, n), us in groups.items():
        stage = 'done' if any(x[3] == 'done' for x in us) else us[0][3]
        same = [x for x in us if x[3] == stage]
        yms = [x[2] for x in same if x[2]]
        ym = sorted(set(yms), key=lambda y: (-yms.count(y), y))[0] if yms else None
        names = [x[0] for x in same if (x[0] or '').strip()]
        name = max(set(names), key=lambda v: (names.count(v), -len(v))) if names else (same[0][0] or '')
        out.append([name, n, ym, stage, plat])
    return out


def apt_records(items, collapse=True):
    """공동주택·세대>0 → PK dedupe → 이중등재 접기.

    collapse=False는 접기 전후 건수를 비교해 로그를 남기는 호출자
    (fetch_group)를 위한 것이다. 집계 경로는 항상 기본값(True)을 쓴다.
    """
    def ok(it):
        if (it.get('purpsCdNm') or '').strip() != '공동주택':
            return False
        try:
            return int(float(it.get('totHhldCnt') or 0)) > 0
        except (TypeError, ValueError):
            return False
    out = dedupe([it for it in items if ok(it)])
    return collapse_dup_registrations(out) if collapse else out

def demol_records(items):
    """철거멸실관리대장(ArchPmsHubService/getApDemolExtngMgmRgstInfo) 원시
    item -> 공동주택·세대>0·PK dedupe. 준공(apt_records)과 필드명이 다르다
    (purpsCdNm/totHhldCnt/mgmHsrgstPk 대신 mainPurpsCdNm/hhldCnt/mgmPmsrgstPk)."""
    def ok(it):
        if (it.get('mainPurpsCdNm') or '').strip() != '공동주택':
            return False
        try:
            return int(float(it.get('hhldCnt') or 0)) > 0
        except (TypeError, ValueError):
            return False
    return dedupe([it for it in items if ok(it)], key='mgmPmsrgstPk')

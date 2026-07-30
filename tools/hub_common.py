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

def apt_records(items):
    def ok(it):
        if (it.get('purpsCdNm') or '').strip() != '공동주택':
            return False
        try:
            return int(float(it.get('totHhldCnt') or 0)) > 0
        except (TypeError, ValueError):
            return False
    return dedupe([it for it in items if ok(it)])

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

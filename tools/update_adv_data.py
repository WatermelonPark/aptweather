# -*- coding: utf-8 -*-
"""심화통계 데이터 자동 갱신 (KOSIS OpenAPI).

data.js 안의 /*ADV_DATA_START*/ ... /*ADV_DATA_END*/ 블록을 최신 데이터로 교체한다.
(2026-07-19 분리: 데이터는 index.html이 아니라 data.js에 있다.)
실운영 갱신은 로컬 작업 스케줄러(tools/run_weekly_update.bat, 매주 금 09:30)가 담당한다.
GitHub Actions(.github/workflows/update-stats.yml)는 KOSIS의 해외 IP 차단 때문에
갱신이 실패해 클라우드는 IP 프리플라이트로 우회한다(update-cloud.yml).

사용:
  KOSIS_API_KEY=... python tools/update_adv_data.py --update      # 실제 갱신
  KOSIS_API_KEY=... python tools/update_adv_data.py --discover 주택규모별   # 표 ID 탐색
  python tools/update_adv_data.py --dry-run                        # 키 없이 재작성 로직만 검증

데이터셋 구성 (docs/advanced_stats_catalog.md 참조):
  permits  — 국토교통부 「주택건설실적통계」 주택규모별 인허가실적(월별 누계):
             6월·12월 누계에서 (계 − 40㎡이하)로 '40제외' 반기값 산출
  occupancy — 입주물량은 공공 API가 없어 자동 갱신 대상에서 제외(수동 시딩 유지)
  monthly  — 월간 매매·전세·월세 동향(R-ONE 단일 소스): 시장동향 월간 지도·그래프에
             쓰이는 라이브 데이터로 매 실행 갱신한다(fetch_monthly, adv['monthly']).
"""
import io, os, re, sys, json, time
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data.js')
TOOLS_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')   # tools/data (hub_permits.json, code_bdong.json)
API = 'https://kosis.kr/openapi/Param/statisticsParameterData.do'
LIST_API = 'https://kosis.kr/openapi/statisticsList.do'
KEY = os.environ.get('KOSIS_API_KEY', '')
ECOS_KEY = os.environ.get('ECOS_API_KEY', '')   # 한국은행 ECOS (CD금리용, 없으면 금리만 건너뜀)
DATAGO_KEY = os.environ.get('DATA_GO_KR_KEY', '')   # 공공데이터포털 (입주예정물량용, 없으면 입주물량만 건너뜀)
RONE_KEY = os.environ.get('RONE_API_KEY', '')       # 부동산원 R-ONE (주간 속보용 — KOSIS보다 4~7일 빠름)
# R-ONE 주간 아파트 가격지수 (발표 당일 반영). 지수 → 전주비 변동률 계산.
RONE_API = 'https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do'
# 공공데이터 특일정보 — 법정공휴일. 발표일 휴일 보정에 쓴다(프론트 _bizDay).
HOLIDAY_API = 'https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo'
RONE_TBL = {'maega': 'T244183132827305', 'jeonse': 'T247713133046872'}
# 월간 아파트 매매/전세 가격지수 (R-ONE, KOSIS보다 한 달 빠름). 시작 2003.
# 월세는 '월세통합가격지수'(순수월세+준월세+준전세 통합)를 쓴다. 순수 월세가격지수
# (A_2024_00055)는 보증금이 적은 계약만 담아 시장 전체를 대표하지 못한다.
# 2026-07-25 실측: 매매표와 CLS_ID 234개·최신월이 완전히 같아 기존 매핑을 그대로 재사용한다.
RONE_MONTHLY_TBL = {'maega': 'A_2024_00045', 'jeonse': 'A_2024_00050', 'wolse': 'A_2024_00054'}
# 한국부동산원 주택공급정보 입주예정물량정보 (data.go.kr/data/15111714) — 반기 갱신, 30세대 이상 단지별
OCC_API = 'https://api.odcloud.kr/api/15111714/v1/uddi:0b257760-ac19-4841-adb4-b38b4d153397'
# 청약홈 APT 분양정보 — 입주예정월이 2031년까지 있어 odcloud(2027-12까지)보다 멀리 본다.
# 다만 분양 공고 기준이라 후분양·임대·조합 물량이 빠져 같은 구간에서는 odcloud보다 적다
# (2026-01~2027-12 실측: odcloud 414,906세대 vs 청약홈 278,125세대).
# 그래서 odcloud를 대체하지 않고 '그 시야 밖'만 채운다.
CHUNG_API = 'https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail'

# ---- KOSIS 표 설정 ------------------------------------------------------
# tblId는 `--discover <검색어>` 로 확인 후 채운다.
# DT_MLTM_1948(주택유형별 인허가실적 월별누계)은 2024 강의 화면 URL에서 직접 확인됨.
CONF = {
    'permits_size': {          # 주택규모별 인허가실적(월별 누계) — 40제외 산출용
        'orgId': '116',
        'tblId': 'DT_MLTM_1952',   # 2026-07 API 실측 확인 (C1=규모, C2/C3=권역, C4=시도)
    },
    # 주간·월간 시세는 R-ONE 단일 소스(RONE_TBL/RONE_MONTHLY_TBL). KOSIS 표 설정은
    # 2026-07-28 폴백 제거와 함께 삭제 — 여기 남은 건 보관 깊이뿐이다.
    'weekly': {
        'sgg_hist': 156,       # 서울 구·시군구 시계열 유지 주수. 표는 최근 12개만 쓰지만
                               # 그래프에서 구 단위 3년을 보려면 쌓아둬야 한다.
                               # 이 분량은 data-sgg.json으로 분리돼 구를 고를 때만 전송된다.
        'weeks_hist': 156,     # 시도 시계열 유지 주수 (그래프 과거 탐색용)
    },
    'monthly': {
        'sgg_hist': 120,       # 시군구 시계열 유지 개월수(그래프 '전체'용, 지연 로드 파일로 분리)
        'months_hist': 120,    # 시도 시계열 유지 개월수
    },
}

WEEKLY_REGIONS = ['전국','수도권','지방','서울','경기','인천','부산','대구','광주','대전','세종','울산',
                  '강원','충북','충남','전북','전남','경북','경남','제주']

# ---- 버블밴드 (전월세전환율 × 전세가율 밴드 vs 주담대금리) -------------------
# 전세가율은 STATS(DT_30404_N0006_R1)에 이미 있어 페이지에서 병합. 여기선 전환율+금리만.
BUBBLE_REGIONS = ['전국','수도권','서울','경기','인천','부산','대구','광주','대전','울산',
                  '세종','강원','충북','충남','전북','전남','경북','경남','제주']
BUBBLE_SHORT = {'서울특별시':'서울','부산광역시':'부산','대구광역시':'대구','인천광역시':'인천',
                '광주광역시':'광주','대전광역시':'대전','울산광역시':'울산','세종특별자치시':'세종',
                '경기도':'경기','강원도':'강원','강원특별자치도':'강원','충청북도':'충북','충청남도':'충남',
                '전라북도':'전북','전북특별자치도':'전북','전라남도':'전남','경상북도':'경북',
                '경상남도':'경남','제주도':'제주','제주특별자치도':'제주'}

# ---- 기본통계(STATS) 월간 자동 갱신 --------------------------------------
# data.js의 /*STATS_DATA_START*/const STATS={...};/*STATS_DATA_END*/ 블록을
# 증분 갱신한다(최근 N개월만 조회해 기존 시계열 끝에 병합 — 소급 정정 반영).
# 연간 통계(보급률·아파트건설·멸실·노후)와 금리(ECOS 필요)는 대상 아님.
BASIC_CONF = {
    '매매지수': {'org': '408', 'tbl': 'DT_KAB_11672_S1',   'mode': 'flat',  'itm': '지수', 'objn': 1, 'dec': 2},
    '전세지수': {'org': '408', 'tbl': 'DT_KAB_11672_S23',  'mode': 'flat',  'itm': '지수', 'objn': 1, 'dec': 2},
    '전세가율': {'org': '408', 'tbl': 'DT_30404_N0006_R1', 'mode': 'typed', 'type': '아파트', 'objn': 2, 'dec': 1},
    '인허가':   {'org': '116', 'tbl': 'DT_MLTM_1948',      'mode': 'mltm',  'type': '아파트', 'objn': 4, 'dec': 0},
    '착공':     {'org': '116', 'tbl': 'DT_MLTM_5387',      'mode': 'mltm',  'type': '아파트', 'objn': 4, 'dec': 0},
    '준공':     {'org': '116', 'tbl': 'DT_MLTM_5373',      'mode': 'mltm',  'type': '아파트', 'objn': 4, 'dec': 0},
}
BASIC_REGMAP = {'지방소계': '지방', '총계': '전국', '수도권소계': '수도권'}   # KOSIS 지역명 → STATS 지역명
BASIC_MONTHS = 8                      # 최근 8개월 조회(잠정치 소급 정정 커버)
# ⚠️ '1년 전 대비'를 그리는 계열은 **12개월 전 값도 다시 받아야 한다**. 8개월만
# 훑으면 KOSIS가 그보다 옛 달을 소급 정정해도 영영 반영되지 않아, 기준점만 옛 값인
# 채로 증감을 계산한다 — 전세가율 서울 2025.09가 저장 54.3 vs 원천 53.0으로
# 1.3%p 어긋난 채 /jeonse-ratio/의 '1년 전 대비'에 쓰였다(2026-08-07 감사).
BASIC_MONTHS_DEEP = {'전세가율': 15}   # 계열별 조회 깊이 override
# ⚠️ 지역을 **이름으로만** 키잉하면 시도와 시군구가 같은 이름일 때 뒤 행이 앞을 덮는다.
# DT_30404_N0006_R1(아파트)에 '제주'가 둘(C2=c8 제주도 · c801 제주시), '광주'가 둘
# (C2=b3 광주광역시 · a80404 경기 광주시) 있고, 응답 순서가 c8→c801이라 제주는
# **제주시 값**이 저장돼 있었다(2026-08-07 감사, 65.9 vs 65.2). 지역코드가 짧을수록
# 상위 행정단위라는 KOSIS 규칙을 써서 같은 이름이면 짧은 코드를 채택한다.

# ---- 분양·미분양 (기본통계 공급 파이프라인 보강) --------------------------
# 기본통계 공급 구간이 인허가→착공→준공이라, 실제 단계(인허가→착공→분양→준공)의
# 중간이 비어 있었다. 분양·미분양을 나란히 넣어 그 고리를 잇는다.
# ⚠️ 미분양은 '결과값'이라 아공맵 순위 산식(원인값=인허가)에는 넣지 않는다.
#    분양물량을 함께 넣는 이유: 분양이 없으면 미분양도 자동으로 줄어든다.
#    분모 없이 미분양만 보면 그 감소를 '수요 회복'으로 오독한다.
# 준공후 미분양은 월간·시도별 공개 소스가 없어(KOSIS DT_MLTM_2086은 전국·연간) 제외.
SUPPLY_CONF = {
    '분양':   {'tbl': 'T244633134461863', 'unit': '세대 (월별)',
               'source': '한국부동산원 R-ONE 신규 분양세대수'},
    '미분양': {'tbl': 'T237973129847263', 'unit': '호 (월별)',
               'source': '한국부동산원 R-ONE 미분양주택현황'},
}
SUPPLY_MONTHS = 8          # 최근 8개월(소급 정정 커버) — BASIC_MONTHS와 같은 기조
SUPPLY_SIDO = [r for r in WEEKLY_REGIONS if r not in ('전국', '수도권', '지방')]


def _supply_region(full):
    """R-ONE CLS_FULLNM → STATS 지역명. 두 표의 계층이 서로 다르다.
       분양표:  '전국' · '수도권' · '수도권>서울' · '기타지방>강원'
       미분양표: '강원>계' (시도 소계가 '계')
       '기타지방'·'5대광역시 및 세종특별자치시' 같은 중간 집계행은 STATS에
       대응 지역이 없어 버린다(전국/수도권/지방은 아래 _supply_rollup이 만든다)."""
    parts = [p.strip() for p in (full or '').split('>') if p.strip()]
    if not parts:
        return None
    last = parts[-1]
    if last == '계':
        return parts[0] if len(parts) > 1 else None
    if last in ('전국', '수도권'):
        return last
    if len(parts) == 1:
        return None
    return last


def _supply_rollup(fetched, regions):
    """미분양표는 시도만 주므로 전국/수도권/지방 합계를 직접 만든다.
       분양표처럼 원천이 이미 주는 경우엔 덮어쓰지 않는다."""
    for vals in fetched.values():
        sido = {k: v for k, v in vals.items() if k in SUPPLY_SIDO}
        if len(sido) < len(SUPPLY_SIDO) - 2:     # 결측이 많으면 합계를 만들지 않는다
            continue
        if '전국' in regions and '전국' not in vals:
            vals['전국'] = sum(sido.values())
        cap = [vals.get(x) for x in ('서울', '경기', '인천')]
        if '수도권' in regions and '수도권' not in vals and all(c is not None for c in cap):
            vals['수도권'] = sum(cap)
        if ('지방' in regions and '지방' not in vals
                and '전국' in vals and '수도권' in vals):
            vals['지방'] = vals['전국'] - vals['수도권']


def _fetch_supply_one(cfg, regions, months=None):
    """R-ONE 월간표에서 최근 months개월치 {(y,m):{region:val}}.
       months=0이면 전량(최초 시딩용 — 미분양은 2000-12부터 26년치가 있다)."""
    months = SUPPLY_MONTHS if months is None else months
    # 미분양은 시군구까지 담겨 월당 ~246행, 분양은 ~21행. 넉넉히 받아 뒤에서 자른다.
    need = 10 ** 9 if months == 0 else max((months + 2) * 260, 3000)
    rows = _rone_recent_rows(cfg['tbl'], need, cycle='MM')
    out = {}
    for r in rows:
        t = (r.get('WRTTIME_IDTFR_ID') or '').strip()
        if len(t) != 6 or not t.isdigit():
            continue
        reg = _supply_region(r.get('CLS_FULLNM'))
        if reg not in regions:
            continue
        try:
            v = float(r['DTA_VAL'])
        except (TypeError, ValueError, KeyError):
            continue
        out.setdefault((int(t[:4]), int(t[4:6])), {})[reg] = v
    keys = sorted(out)
    return {k: out[k] for k in (keys if months == 0 else keys[-months:])}


def update_supply(stats, months=None):
    changed = []
    base = list(((stats.get('준공') or {}).get('series') or {}).keys()) or list(WEEKLY_REGIONS)
    for name, cfg in SUPPLY_CONF.items():
        try:
            # 시딩(months=0)은 계열을 새로 만든다. 증분 8개월이 이미 들어간 계열에
            # 과거 전량을 merge하면 merge_basic이 뒤에 append만 하므로
            # dates가 '2025.11 ~ 2025.10'처럼 뒤섞인다(정렬하지 않는 함수다).
            if months == 0:
                stats.pop(name, None)
            if name not in stats:
                stats[name] = {'dates': [], 'unit': cfg['unit'],
                               'series': {r: [] for r in base}, 'source': cfg['source']}
            D = stats[name]
            regions = set(D['series'])
            fetched = _fetch_supply_one(cfg, regions, months)
            if not fetched:
                print('supply %s: 빈 응답 — 건너뜀' % name)
                continue
            _supply_rollup(fetched, regions)
            n = merge_basic(D, fetched)
            if n:
                changed.append('%s(%d)' % (name, n))
            time.sleep(0.2)
        except Exception as e:
            print('supply %s skip: %s' % (name, e))
    return changed


# ---- 연간 계열 자동 갱신 --------------------------------------------------
# 연 1회 발표라 수동 시딩으로 두었더니 아무도 새 연도를 가져오지 않아 뒤처졌다
# (2026-07-30 감사에서 노후주택30년이 2025 미반영으로 발견). 배치에 편입한다.
# 표는 각 계열의 기존 값과 대조해 특정했다(전국 2024: 보급률 102.9·멸실 85,069·
# 아파트건설 333,452·노후 2,517,244가 아래 표에서 그대로 재현됨).
#   only: 그 컬럼이 해당 값인 행만 사용. region: 지역축이 없는 표의 고정 지역명.
#   shortmap: 원천이 '서울특별시' 같은 전체명이라 BUBBLE_SHORT로 축약해 맞춘다.
ANNUAL_CONF = {
    '보급률':      {'org': '116', 'tbl': 'DT_MLTM_2100', 'objn': 1, 'dec': 1,
                    'itm': '보급률(다가구 구분거처 반영)'},
    '주택멸실':    {'org': '116', 'tbl': 'DT_MLTM_5416', 'objn': 1, 'dec': 0,
                    'itm': '계'},
    # 같은 표에서 유형만 '아파트'로 좁힌 계열. 러닝재고(준공−멸실−적정)가 쓰는 건
    # 이쪽이다 — '계'는 단독이 절반 가까이(2024 전국 85,069호 중 39,169호)라
    # 아파트 재고에서 빼면 과대 차감된다. 2010~ 시도별 연간으로 모형 앵커(2010Q1)와
    # 시작점이 같다. 건축HUB 철거멸실관리대장은 2020년에서 끊겨 있어(전 기간 누적
    # 189,939세대 < KOSIS 2024 한 해 85,069호) 이걸 단일 소스로 쓴다.
    '아파트멸실':  {'org': '116', 'tbl': 'DT_MLTM_5416', 'objn': 1, 'dec': 0,
                    'itm': '아파트'},
    '아파트건설':  {'org': '116', 'tbl': 'DT_MLTM_692', 'objn': 2, 'dec': 0,
                    'itm': '계', 'only': {'C1_NM': '총합계', 'C2_NM': '계'},
                    'region': '전국'},
    '노후주택30년': {'org': '101', 'tbl': 'DT_1JU1521', 'objn': 2, 'dec': 0,
                    'itm': '아파트', 'only': {'C2_NM': '30년 이상'},
                    'shortmap': True},
}
ANNUAL_YEARS = 3                      # 최근 3개년 조회(소급 정정 흡수)

# 시세(주간·월간)는 3년 히스토리를 매번 전량 재조회하면 R-ONE 페이징이 수십 회라
# 배치가 느리다(클라우드 40분의 83%). 과거 주/월은 소급수정 외엔 안 바뀌고 저장돼
# 있으며 main()의 병합이 저장분을 보존하므로, 실제 fetch는 최근 구간만 받는다.
# 서울 구별 상세(12주/12월)와 병합 겹침을 덮을 여유를 둔다 — 이 값을 넘겨 미조회된
# 과거가 필요하면 저장분이 이미 그 깊이를 갖고 있어 그래프는 온전하다.
RECENT_WEEKS = 20     # 주간 fetch 깊이 (서울 12주 + 여유). 3년(156주)은 병합이 보존.
RECENT_MONTHS = 14    # 월간 fetch 깊이 (서울 12월 + 여유). 10년(120월)은 병합이 보존.

REG15 = ['수도권','부산','대구','광주','대전','울산','세종','강원','충북','충남','전북','전남','경북','경남','제주']
# 아파트 인허가(fetch_permits)용 — 수도권 뒤에 하위 서울/경기/인천을 개별로. KOSIS
# DT_MLTM_1948이 셋을 개별 + 수도권 소계로 모두 주므로(합=수도권) 필터만 열면 된다.
# REG15는 규모별표(_region_of)가 계속 쓰므로 건드리지 않는다.
# 형제 탭(입주물량)에는 전국·지방이 있는데 인허가에만 없어 지역 선택이 어긋났다
# (2026-08-08 감사). 원천 DT_MLTM_1948에 '전국'·'지방소계'가 실재함을 실호출로 확인.
PERMIT_REGIONS = (['전국', '수도권', '지방', '서울', '경기', '인천']
                  + [r for r in REG15 if r != '수도권'])


def http_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:   # 순단(타임아웃 등)은 잠시 쉬고 재시도
            last = e
            time.sleep(3 * (i + 1))
    raise last


def kosis(params):
    q = dict(method='getList', apiKey=KEY, format='json', jsonVD='Y', **params)
    url = API + '?' + urllib.parse.urlencode(q)
    data = http_json(url)
    if isinstance(data, dict) and data.get('err'):
        raise RuntimeError('KOSIS err %s: %s' % (data.get('err'), data.get('errMsg')))
    return data


def discover(keyword):
    """통계표 이름으로 tblId 탐색 (국토부 116, 부동산원 408 하위 전체 훑기)"""
    assert KEY, 'KOSIS_API_KEY 필요'
    hits = []
    for vw in ['MT_ZTITLE']:
        stack = ['']
        seen = set()
        while stack:
            parent = stack.pop()
            q = dict(method='getList', apiKey=KEY, format='json', jsonVD='Y', vwCd=vw)
            if parent: q['parentListId'] = parent
            url = LIST_API + '?' + urllib.parse.urlencode(q)
            try:
                items = http_json(url)
            except Exception:
                continue
            if not isinstance(items, list): continue
            for it in items:
                lid = it.get('LIST_ID'); nm = it.get('LIST_NM') or it.get('TBL_NM') or ''
                tbl = it.get('TBL_ID')
                if tbl and keyword in nm:
                    hits.append((it.get('ORG_ID'), tbl, nm))
                    print('HIT', it.get('ORG_ID'), tbl, nm)
                if lid and lid not in seen and ('주택' in nm or '부동산' in nm or not parent):
                    seen.add(lid); stack.append(lid)
            time.sleep(0.15)
    return hits


# ---- permits: 규모별 월별누계 → 40제외 반기 -----------------------------
# DT_MLTM_1952 구조: C1=규모(계/40㎡이하/...), C2=권역별1, C3=권역별2, C4=시도
# '수도권' 값 = C3=수도권 & C4=소계, 나머지 14개 시도 = C4 이름 그대로.
def _region_of(row):
    c3 = (row.get('C3_NM') or '').strip()
    c4 = (row.get('C4_NM') or '').strip()
    if c3 == '수도권' and c4 == '소계':
        return '수도권'
    return c4 if c4 in REG15 else None


def _fetch_period(cfg, prd_de):
    try:
        data = _fetch_period_raw(cfg, prd_de)
    except RuntimeError as e:
        if 'err 30' in str(e):  # 해당 시점 데이터 없음
            return {}
        raise
    out = {}
    for row in data:
        region = _region_of(row)
        if not region: continue
        size_nm = (row.get('C1_NM') or '').strip()
        try: v = int(float(row['DT']))
        except (TypeError, ValueError, KeyError): continue
        g = out.setdefault(region, {})
        if size_nm == '계': g['total'] = v
        elif size_nm == '40㎡이하': g['small'] = v
    ex = {}
    for region, g in out.items():
        if 'total' in g:
            ex[region] = g['total'] - g.get('small', 0)
    return ex


def _fetch_period_raw(cfg, prd_de):
    return kosis({
        'orgId': cfg['orgId'], 'tblId': cfg['tblId'],
        'objL1': 'ALL', 'objL2': 'ALL', 'objL3': 'ALL', 'objL4': 'ALL',
        'itmId': 'ALL', 'prdSe': 'M',
        'startPrdDe': prd_de, 'endPrdDe': prd_de,
    })


def _fetch_apt_permits(prd_de):
    """아파트 인허가 누계(유형별 표 DT_MLTM_1948) → {지역: 호}.
    C1_NM=지역, C2_NM=주택유형. 규모별 표(1952)는 주택 전체라 아파트만 못 뽑아 이 표를 쓴다."""
    try:
        data = kosis({'orgId': '116', 'tblId': 'DT_MLTM_1948',
                      'objL1': 'ALL', 'objL2': 'ALL', 'objL3': 'ALL', 'objL4': 'ALL',
                      'itmId': 'ALL', 'prdSe': 'M', 'startPrdDe': prd_de, 'endPrdDe': prd_de})
    except RuntimeError as e:
        if 'err 30' in str(e):   # 해당 시점 데이터 없음
            return {}
        raise
    out = {}
    for row in data:
        if (row.get('C2_NM') or '').strip() != '아파트': continue
        if (row.get('C4_NM') or '').strip() != '아파트': continue
        reg = (row.get('C1_NM') or '').strip()
        reg = BASIC_REGMAP.get(reg, reg)      # 지방소계 → 지방, 총계 → 전국
        if reg not in PERMIT_REGIONS: continue
        try: out[reg] = int(float(row['DT']))
        except (TypeError, ValueError, KeyError): continue
    return out


def fetch_permits():
    import datetime
    now = datetime.date.today()
    rows_out = []
    for y in range(2007, now.year + 1):
        h1 = _fetch_apt_permits('%d06' % y)
        time.sleep(0.15)
        v1 = [h1.get(r) for r in PERMIT_REGIONS]
        if any(v is not None for v in v1):
            rows_out.append({'p': '%dH1' % y, 'v': v1})
        cum = _fetch_apt_permits('%d12' % y)
        time.sleep(0.15)
        vc = [cum.get(r) for r in PERMIT_REGIONS]
        if any(v is not None for v in vc):
            v2 = [None if (a is None or b is None) else a - b for a, b in zip(vc, v1)]
            rows_out.append({'p': '%dH2' % y, 'v': v2})
    return rows_out


# ---- weekly: 주간 아파트 매매·전세 변동률 --------------------------------
# KOSIS 지역 분류코드: 서울 25개 구 = ^a70\d{5}$ (주간 C1, 월간 C2 공통).
# 이름만으로는 '중'·'강서' 등이 타 도시 구와 겹쳐 코드로 식별한다.
# KOSIS SGG 코드 → R-ONE 주간표(T244183132827305) CLS_ID. 월간(A_2024_00045)과
# CLS_ID 체계가 달라 별도. gen_map_wk.py로 재생성. (KOSIS 폴백은 2026-07-28 제거)
SGG_RONE_CLS_WK = {"a901": 50261, "a902": 50262, "a908": 50264, "a909": 50263, "a0": 50001, "a7": 50008, "a7010101": 50043, "a7010102": 50044, "a7010103": 50045, "a7010201": 50047, "a7010202": 50048, "a7010203": 50049, "a7010204": 50050, "a7010205": 50051, "a7010206": 50052, "a7010207": 50053, "a7010208": 50054, "a7010301": 50056, "a7010302": 50057, "a7010303": 50058, "a7020101": 50060, "a7020102": 50061, "a7020103": 50062, "a7020104": 50063, "a7020105": 50064, "a7020106": 50065, "a7020107": 50066, "a7020201": 50067, "a7020202": 50068, "a7020203": 50069, "a7020204": 50070, "a8": 50016, "a80101": 50071, "a80104": 50075, "a80105": 50076, "a80201": 50081, "a80303": 50103, "a80304": 50097, "a80306": 50102, "a80307": 50098, "a80401": 50107, "a80402": 50106, "a80403": 50108, "a80404": 50109, "a80501": 50111, "a80502": 50112, "a80601": 50118, "a80603": 50253, "a80701": 50123, "a80702": 50121, "a80703": 50122, "a80704": 50120, "a9": 50124, "a903": 50254, "a904": 50127, "a905": 50128, "a906": 50129, "a907": 50130, "b1": 50025, "b10101": 50132, "b10102": 50133, "b10103": 50134, "b10104": 50135, "b10105": 50137, "b10106": 50136, "b10107": 50138, "b10108": 50139, "b10201": 50142, "b10202": 50143, "b10203": 50141, "b10204": 50144, "b10301": 50146, "b10302": 50148, "b10303": 50149, "b10304": 50147, "b2": 50150, "b201": 50151, "b202": 50152, "b203": 50153, "b204": 50154, "b205": 50155, "b206": 50156, "b207": 50157, "b208": 50158, "b3": 50159, "b301": 50160, "b302": 50161, "b303": 50162, "b304": 50163, "b305": 50164, "b4": 50165, "b401": 50166, "b402": 50167, "b403": 50168, "b404": 50169, "b405": 50170, "b5": 50171, "b501": 50172, "b502": 50173, "b503": 50174, "b504": 50175, "b505": 50176, "b6": 50033, "c1": 50177, "c101": 50178, "c102": 50179, "c103": 50180, "c104": 50181, "c105": 50182, "c106": 50183, "c107": 50184, "c2": 50185, "c201": 50186, "c20101": 50187, "c20102": 50188, "c20103": 50189, "c20104": 50190, "c203": 50191, "c204": 50192, "c206": 50193, "c3": 50194, "c301": 50195, "c302": 50196, "c303": 50197, "c304": 50198, "c305": 50199, "c306": 50200, "c307": 50201, "c308": 50202, "c309": 50203, "c311": 50205, "c312": 50206, "c313": 50204, "c4": 50207, "c401": 50208, "c402": 50209, "c403": 50210, "c404": 50211, "c405": 50212, "c406": 50213, "c407": 50214, "c408": 50215, "c5": 50216, "c501": 50217, "c502": 50218, "c503": 50219, "c504": 50220, "c505": 50221, "c506": 50222, "c6": 50223, "c601": 50227, "c602": 50230, "c603": 50224, "c60301": 50225, "c60302": 50226, "c604": 50228, "c605": 50229, "c606": 50231, "c607": 50232, "c608": 50233, "c609": 50234, "c610": 50235, "c611": 50236, "c7": 50237, "c701": 50238, "c70101": 50239, "c70102": 50240, "c70103": 50241, "c70104": 50242, "c702": 50243, "c703": 50255, "c704": 50244, "c705": 50245, "c706": 50246, "c707": 50247, "c708": 50248, "c709": 50249, "c8": 50250, "c801": 50251, "c802": 50252, "a802031": 50084, "a802032": 50085, "a802033": 50086, "a802034": 50087, "a801031": 50078, "a801032": 50079, "a801033": 50080, "a802021": 50089, "a802022": 50090, "a802023": 50091, "a801021": 50073, "a801022": 50074, "a806021": 50115, "a806022": 50116, "a806023": 50117, "a803011": 50094, "a803012": 50095, "a803013": 50096, "a803021": 50100, "a803022": 50101, "a803051": 50259, "a803052": 50256, "a803053": 50258, "a803054": 50257, "a80203": 50083, "a80103": 50077, "a80202": 50088, "a80102": 50072, "a80602": 50114, "a80301": 50093, "a80302": 50099, "a80305": 50104}

SEOUL_GU_RE = re.compile(r'^a70\d{5}$')

# 전국 상세 지도(ENJ식 시군구 타일)용 지역코드 — index.html NATION_TILE과 동일 집합
SGG_CODES = ["a0", "a7", "a7010101", "a7010102", "a7010103", "a7010201", "a7010202", "a7010203", "a7010204", "a7010205", "a7010206", "a7010207", "a7010208", "a7010301", "a7010302", "a7010303", "a7020101", "a7020102", "a7020103", "a7020104", "a7020105", "a7020106", "a7020107", "a7020201", "a7020202", "a7020203", "a7020204", "a8", "a80101", "a80102", "a801021", "a801022", "a80103", "a801031", "a801032", "a801033", "a80104", "a80105", "a80201", "a80202", "a802021", "a802022", "a802023", "a80203", "a802031", "a802032", "a802033", "a802034", "a80301", "a803011", "a803012", "a803013", "a80302", "a803021", "a803022", "a80303", "a80304", "a80305", "a803051", "a803052", "a803053", "a803054", "a80306", "a80307", "a80401", "a80402", "a80403", "a80404", "a80501", "a80502", "a80601", "a80602", "a806021", "a806022", "a806023", "a80603", "a80701", "a80702", "a80703", "a80704", "a9", "a901", "a902", "a903", "a904", "a905", "a906", "a907", "a908", "a909", "b1", "b10101", "b10102", "b10103", "b10104", "b10105", "b10106", "b10107", "b10108", "b10201", "b10202", "b10203", "b10204", "b10301", "b10302", "b10303", "b10304", "b2", "b201", "b202", "b203", "b204", "b205", "b206", "b207", "b208", "b3", "b301", "b302", "b303", "b304", "b305", "b4", "b401", "b402", "b403", "b404", "b405", "b5", "b501", "b502", "b503", "b504", "b505", "b6", "c1", "c101", "c102", "c103", "c104", "c105", "c106", "c107", "c2", "c201", "c20101", "c20102", "c20103", "c20104", "c203", "c204", "c206", "c3", "c301", "c302", "c303", "c304", "c305", "c306", "c307", "c308", "c309", "c311", "c312", "c313", "c4", "c401", "c402", "c403", "c404", "c405", "c406", "c407", "c408", "c5", "c501", "c502", "c503", "c504", "c505", "c506", "c6", "c601", "c602", "c603", "c60301", "c60302", "c604", "c605", "c606", "c607", "c608", "c609", "c610", "c611", "c7", "c701", "c70101", "c70102", "c70103", "c70104", "c702", "c703", "c704", "c705", "c706", "c707", "c708", "c709", "c8", "c801", "c802"]
SGG_SET = set(SGG_CODES)

# KOSIS SGG 코드 → R-ONE CLS_ID (월간 시군구를 R-ONE로 받기 위한 매핑, 208개).
# 부동산원 통계표 재구조화·행정구역 개편 시 갱신 필요.
#
# 재생성:  python tools/gen_sgg_rone_map.py            # 현재 값과 대조만
#          python tools/gen_sgg_rone_map.py --write    # tools/data/sgg_rone_cls.json 저장
# 저장소 안의 자료(SGG_CODES + index.html SGG_QNAME)와 R-ONE 최신월 응답만으로
# 208개 전부 재현된다(2026-08-01 확인: 일치 208 · 불일치 0). 스크립트가 못 붙인
# 코드는 이유와 함께 출력하므로, 그 목록만 보고 수작업 여부를 판단하면 된다
# (현재 미해결 4건은 인천 신설구 — R-ONE에 아직 없어 이 표에도 없는 게 정상).
SGG_RONE_CLS = {"a0": 500001, "a7": 500008, "a7010101": 530011, "a7010102": 530012, "a7010103": 530013, "a7010201": 530015, "a7010202": 530016, "a7010203": 530017, "a7010204": 530018, "a7010205": 530019, "a7010206": 530020, "a7010207": 530021, "a7010208": 530022, "a7010301": 530024, "a7010302": 530025, "a7010303": 530026, "a7020101": 530029, "a7020102": 530030, "a7020103": 530031, "a7020104": 530032, "a7020105": 530033, "a7020106": 530034, "a7020107": 530035, "a7020201": 530037, "a7020202": 530038, "a7020203": 530039, "a7020204": 530040, "a8": 500009, "a80101": 520018, "a80104": 520021, "a80105": 520022, "a80201": 520024, "a80303": 520030, "a80304": 520031, "a80306": 520033, "a80307": 520034, "a80401": 520036, "a80402": 520037, "a80403": 520038, "a80404": 520039, "a80501": 520041, "a80502": 520042, "a80601": 520044, "a80603": 520046, "a80701": 520048, "a80702": 520049, "a80703": 520050, "a80704": 520051, "a9": 500010, "a903": 510022, "a904": 510023, "a905": 510024, "a906": 510025, "a907": 510026, "b1": 500011, "b10101": 520063, "b10102": 520064, "b10103": 520065, "b10104": 520066, "b10105": 520067, "b10106": 520068, "b10107": 520069, "b10108": 520070, "b10201": 520072, "b10202": 520073, "b10203": 520074, "b10204": 520075, "b10301": 520077, "b10302": 520078, "b10303": 520079, "b10304": 520080, "b2": 500012, "b201": 510033, "b202": 510034, "b203": 510035, "b204": 510036, "b205": 510037, "b206": 510038, "b207": 510039, "b208": 510040, "b3": 500013, "b301": 510042, "b302": 510043, "b303": 510044, "b304": 510045, "b305": 510046, "b4": 500014, "b401": 510048, "b402": 510049, "b403": 510050, "b404": 510051, "b405": 510052, "b5": 500015, "b501": 510054, "b502": 510055, "b503": 510056, "b504": 510057, "b505": 510058, "b6": 500016, "c1": 500017, "c101": 510061, "c102": 510062, "c103": 510063, "c104": 510064, "c105": 510065, "c106": 510066, "c107": 510067, "c2": 500018, "c201": 510069, "c20101": 520119, "c20102": 520120, "c20103": 520121, "c20104": 520122, "c203": 510070, "c204": 510071, "c206": 510072, "c3": 500019, "c301": 510074, "c302": 520128, "c303": 520129, "c304": 510075, "c305": 510076, "c306": 510077, "c307": 510078, "c308": 510079, "c309": 510080, "c311": 510081, "c312": 510082, "c313": 510083, "c4": 500020, "c401": 510085, "c402": 520141, "c403": 520142, "c404": 510086, "c405": 510087, "c406": 510088, "c407": 510089, "c408": 510090, "c5": 500021, "c501": 510092, "c502": 510093, "c503": 510094, "c504": 510095, "c505": 510096, "c506": 510097, "c6": 500022, "c601": 510100, "c602": 510103, "c603": 510099, "c60301": 520157, "c60302": 520158, "c604": 510101, "c605": 510102, "c606": 510104, "c607": 510105, "c608": 510106, "c609": 510107, "c610": 510108, "c611": 510109, "c7": 500023, "c701": 510111, "c70101": 520171, "c70102": 520172, "c70103": 520173, "c70104": 520174, "c702": 520175, "c703": 510112, "c704": 510113, "c705": 510114, "c706": 510115, "c707": 510116, "c708": 510117, "c709": 510118, "c8": 500024, "c801": 510120, "c802": 510121, "a802031": 530060, "a802032": 530061, "a802033": 530062, "a802034": 530063, "a801031": 530048, "a801032": 530049, "a801033": 530050, "a802021": 530056, "a802022": 530057, "a802023": 530058, "a801021": 530045, "a801022": 530046, "a806021": 530085, "a806022": 530086, "a806023": 530087, "a803011": 530088, "a803012": 530089, "a803013": 530090, "a803021": 530067, "a803022": 530068, "a803051": 530094, "a803052": 530091, "a803053": 530093, "a803054": 530092, "a80203": 520026, "a80103": 520020, "a80202": 520025, "a80102": 520019, "a80602": 520045, "a80301": 520028, "a80302": 520029, "a80305": 520032}

def _gu_name(nm):
    return nm + '구'   # 강남→강남구, 중→중구

# ---- R-ONE 주간 속보 (시도 18 + 서울 25구 + 시군구) ------------------------
# 주간·월간 시세는 부동산원 R-ONE 단일 소스다(KOSIS는 같은 데이터가 4~7일 늦음).
def _rone_recent_rows(tbl, need_rows, cycle='WK'):
    base = {'KEY': RONE_KEY, 'Type': 'json', 'pSize': 1000, 'STATBL_ID': tbl, 'DTACYCLE_CD': cycle}
    d = http_json(RONE_API + '?' + urllib.parse.urlencode(dict(base, pIndex=1, pSize=1)))
    k = list(d.keys())[0]
    total = d[k][0]['head'][0]['list_total_count']
    rows = []
    p = (total + 999) // 1000
    while p >= 1 and len(rows) < need_rows:
        d = http_json(RONE_API + '?' + urllib.parse.urlencode(dict(base, pIndex=p)))
        k = list(d.keys())[0]
        rows = d[k][1]['row'] + rows
        p -= 1
        time.sleep(0.15)
    return rows


def fetch_weekly_rone(weeks=None):
    weeks = weeks or RECENT_WEEKS   # 최근 구간만 — 3년 히스토리는 main() 병합이 보존
    need = (weeks + 2) * 240        # 주당 ~236행
    need = max(need, 12000)   # 시군구(236지역)는 최신주 전량이 여러 페이지에 흩어져 있어 넉넉히
    by, by_cls = {}, {}   # by=이름키(시도/서울구), by_cls=CLS_ID키(시군구 지도용)
    for key, tbl in RONE_TBL.items():
        m, mc = {}, {}
        for r in _rone_recent_rows(tbl, need):
            full = (r.get('CLS_FULLNM') or '').strip()
            cid = r.get('CLS_ID')
            t = (r.get('WRTTIME_DESC') or '').strip()
            try: v = float(r['DTA_VAL'])
            except (TypeError, ValueError, KeyError): continue
            if len(t) == 10:
                m.setdefault(t, {})[full] = v
                if cid is not None: mc.setdefault(t, {})[cid] = v
        by[key] = m; by_cls[key] = mc
        time.sleep(0.2)
    dates = sorted(set(by['maega']) & set(by['jeonse']))[-(weeks + 1):]
    if len(dates) < 2:
        raise RuntimeError('R-ONE 주간 데이터 부족')

    def sido(week, name):   # 시도·수도권 (광주/전남은 상위그룹 밑에 있음)
        full = {'광주': '전남광주>광주', '전남': '전남광주>전남', '지방': '지방권'}.get(name, name)
        return week.get(full)

    def seoul_gu(week):
        out = {}
        for full, v in week.items():
            if full.startswith('서울>') and full.endswith('구'):
                out[full.rsplit('>', 1)[-1]] = v
        return out

    def chg(a, b):
        return None if (a in (None, 0) or b is None) else round((b / a - 1) * 100, 4)

    rows, se_rows = [], []
    gus = sorted(seoul_gu(by['maega'][dates[-1]]))
    for prev, cur in zip(dates, dates[1:]):
        rows.append({'p': cur,
                     'ma': [chg(sido(by['maega'][prev], r), sido(by['maega'][cur], r)) for r in WEEKLY_REGIONS],
                     'je': [chg(sido(by['jeonse'][prev], r), sido(by['jeonse'][cur], r)) for r in WEEKLY_REGIONS]})
        ma_p, ma_c = seoul_gu(by['maega'][prev]), seoul_gu(by['maega'][cur])
        je_p, je_c = seoul_gu(by['jeonse'][prev]), seoul_gu(by['jeonse'][cur])
        se_rows.append({'p': cur,
                        'ma': [chg(ma_p.get(g), ma_c.get(g)) for g in gus],
                        'je': [chg(je_p.get(g), je_c.get(g)) for g in gus]})
    # 시군구 지도(전국 187) — R-ONE 주간표에서 직접 산출(KOSIS 수일 지연 회피).
    # 미매핑 코드는 값이 None으로 남는다(지도에서 '·' 표기).
    sg_rows = []
    for prev, cur in zip(dates, dates[1:]):
        mp, mc2 = by_cls['maega'].get(prev, {}), by_cls['maega'].get(cur, {})
        jp, jc2 = by_cls['jeonse'].get(prev, {}), by_cls['jeonse'].get(cur, {})
        sg_rows.append({'p': cur,
            'ma': [chg(mp.get(SGG_RONE_CLS_WK.get(c)), mc2.get(SGG_RONE_CLS_WK.get(c))) for c in SGG_CODES],
            'je': [chg(jp.get(SGG_RONE_CLS_WK.get(c)), jc2.get(SGG_RONE_CLS_WK.get(c))) for c in SGG_CODES]})
    return {'regions': WEEKLY_REGIONS, 'rows': rows,
            'seoul': {'regions': gus, 'rows': se_rows[-CONF['weekly']['sgg_hist']:]},
            'sgg': {'codes': SGG_CODES, 'rows': sg_rows[-CONF['weekly']['sgg_hist']:]},
            'note': '주간 아파트 매매·전세가격지수 변동률(%) · 발표 당일 반영'}



def _keep_wolse(new_rows, cur_rows):
    """새 rows에 wo(월세)가 없는데 기존에 있으면 살려 준다. KOSIS 폴백 시절
    월세 12개월이 통째로 지워진 실사고(2026-07)의 재발 방지 — 폴백은 제거했지만
    부분 응답 등 어떤 경로로든 wo 없는 rows가 오면 같은 사고가 나므로 유지한다."""
    if not (new_rows and cur_rows):
        return
    old = {r['p']: r.get('wo') for r in cur_rows if isinstance(r.get('wo'), list)}
    for r in new_rows:
        if not isinstance(r.get('wo'), list) and r['p'] in old:
            r['wo'] = old[r['p']]


def _merge_hist(new, cur, keep):
    """시군구·서울구 시계열도 시도처럼 과거를 살린다.
    매 실행은 최근 구간만 받아오므로, 이게 없으면 통째 교체돼 히스토리가 12개에서
    영영 늘지 않는다(구 단위 그래프가 '최근 12개'에 갇히던 원인)."""
    if not (new and new.get('rows')):
        return cur if (cur and cur.get('rows')) else new
    if not (cur and cur.get('rows')):
        return new
    first = new['rows'][0]['p']
    older = [r for r in cur['rows'] if r['p'] < first]
    if older:
        new = dict(new)
        new['rows'] = (older + new['rows'])[-keep:]
    return new


def fetch_weekly():
    """주간 시세는 R-ONE 단일 소스(2026-07-28 KOSIS 폴백 제거).
    KOSIS 주간표는 같은 부동산원 데이터를 4~7일 늦게 실을 뿐이라, R-ONE이 실패한
    회차에 폴백이 반환돼도 main()의 역행 가드가 걸러내 '갱신 없음'과 결과가 같았다.
    반면 월세처럼 R-ONE에만 있는 계열을 폴백이 지우는 사고가 실제로 났다(2026-07,
    월세 12개월 결손). 실패는 예외로 올려 main()이 해당 소스만 건너뛰게 한다."""
    assert RONE_KEY, 'RONE_API_KEY 필요'
    return fetch_weekly_rone()


# ---- occupancy: 준공실적(과거) + 입주예정물량(미래) ------------------------
def _q_of(p): return (int(p[:4]), int(p[5]))          # '2026Q3' → (2026,3)
def _qlabel(y, q): return '%dQ%d' % (y, q)


# ── odcloud 입주예정 경로는 2026-08-07에 걷어냈다 ──────────────────────────
# 통계 탭 '입주물량'과 /moveins/가 이 소스를 쓰는 바람에 같은 서울 2027Q2를 홈은
# 2,107, 통계 탭은 1,073으로 보여줬고(2배), 기준선도 적정물량·적정밴드·ref 셋이
# 공존해 제주가 동시에 '매우 부족'이자 '밴드 상단 초과'였다. 지금은 sido_zones.
# supply_rows()가 홈 표와 **같은 소스**(준공+착공 3년 시프트)로 만든다.
# 삭제한 것: occ_rows / fetch_moveins / fetch_completions / _complete_quarters /
# update_occupancy, 그리고 --rebuild-occupancy CLI.

def fetch_holidays():
    """올해+내년 법정공휴일 ['YYYY-MM-DD']. 연말 경계까지 다음 발표일을 계산하려면
    두 해가 필요하다. DATAGO 키가 없거나 실패하면 None(프론트가 하드코딩 폴백)."""
    import datetime
    if not DATAGO_KEY:
        return None
    yr = datetime.date.today().year
    out = []
    for y in (yr, yr + 1):
        try:
            url = HOLIDAY_API + '?' + urllib.parse.urlencode(
                {'serviceKey': DATAGO_KEY, 'solYear': y, 'numOfRows': 50, '_type': 'json'})
            d = http_json(url)
            items = (d.get('response', {}).get('body', {}) or {}).get('items') or {}
            it = items.get('item', []) if items else []
            if isinstance(it, dict):
                it = [it]
            for x in it:
                v = str(x.get('locdate', ''))
                if len(v) == 8 and v.isdigit():
                    out.append('%s-%s-%s' % (v[:4], v[4:6], v[6:8]))
        except Exception as e:
            print('holidays %d skip: %s' % (y, e))
    return sorted(set(out)) or None


# ---- monthly: 월간 아파트 매매·전세·월세 지수 → 전월비 변동률 (R-ONE) ------
def fetch_monthly_rone(months=None):
    """월간 시도·서울구·시군구 변동률을 R-ONE에서 직접 산출한다."""
    months = months or RECENT_MONTHS  # 최근 구간만 — 10년 히스토리는 main() 병합이 보존
    need = (months + 2) * 260        # 월당 계층 지역 ~234
    by, by_cls = {}, {}   # by=이름키(시도/서울구), by_cls=CLS_ID키(시군구 지도용)
    for key, tbl in RONE_MONTHLY_TBL.items():
        m, mc = {}, {}
        for r in _rone_recent_rows(tbl, need, cycle='MM'):
            full = (r.get('CLS_FULLNM') or '').strip()
            cid = r.get('CLS_ID')
            tid = (r.get('WRTTIME_IDTFR_ID') or '').strip()   # '202606'
            try: v = float(r['DTA_VAL'])
            except (TypeError, ValueError, KeyError): continue
            if len(tid) == 6 and tid.isdigit():
                d = tid[:4] + '-' + tid[4:6]
                m.setdefault(d, {})[full] = v
                if cid is not None: mc.setdefault(d, {})[cid] = v
        by[key] = m; by_cls[key] = mc
        time.sleep(0.2)
    # 월세는 나중에 붙은 계열이라 결측/지연 가능 — 교집합에 넣지 않고 없는 달은 None으로 둔다
    dates = sorted(set(by['maega']) & set(by['jeonse']))[-(months + 1):]
    if len(dates) < 2:
        raise RuntimeError('R-ONE 월간 데이터 부족')

    def sido(mon, name):
        """시도 이름 → 그 달의 값. **계층 개편을 자동으로 따라간다.**

        ⚠️ R-ONE은 시도를 상위 묶음 밑으로 옮기곤 한다. 2025-05부터 광주·전남이
        '광주'·'전남'에서 '전남광주>광주'·'전남광주>전남'으로 바뀌었는데, 이 함수가
        평평한 이름만 찾아서 두 지역이 **15개월째 전 항목 결측**이었다(2026-08-07 감사).
        이 프로젝트는 같은 함정에 강원·전북으로 두 번 당했다 — 이름이 안 맞으면
        '>이름'으로 끝나는 키 중 가장 얕은 것을 쓴다(시군구가 아니라 시도를 집는다).
        """
        key = {'지방': '지방권'}.get(name, name)
        if key in mon:
            return mon[key]
        tail = '>' + key
        cand = [k for k in mon if k.endswith(tail)]
        if not cand:
            return None
        return mon[min(cand, key=lambda k: k.count('>'))]

    def seoul_gu(mon):
        out = {}
        for full, v in mon.items():
            if full.startswith('서울>') and full.endswith('구'):
                out[full.rsplit('>', 1)[-1]] = v
        return out

    def chg(a, b):
        return None if (a in (None, 0) or b is None) else round((b / a - 1) * 100, 4)

    wo = by.get('wolse', {})
    rows, se_rows = [], []
    gus = sorted(seoul_gu(by['maega'][dates[-1]]))
    for prev, cur in zip(dates, dates[1:]):
        wo_p, wo_c = wo.get(prev, {}), wo.get(cur, {})
        rows.append({'p': cur,
                     'ma': [chg(sido(by['maega'][prev], r), sido(by['maega'][cur], r)) for r in WEEKLY_REGIONS],
                     'je': [chg(sido(by['jeonse'][prev], r), sido(by['jeonse'][cur], r)) for r in WEEKLY_REGIONS],
                     'wo': [chg(sido(wo_p, r), sido(wo_c, r)) for r in WEEKLY_REGIONS]})
        ma_p, ma_c = seoul_gu(by['maega'][prev]), seoul_gu(by['maega'][cur])
        je_p, je_c = seoul_gu(by['jeonse'][prev]), seoul_gu(by['jeonse'][cur])
        wg_p, wg_c = seoul_gu(wo_p), seoul_gu(wo_c)
        se_rows.append({'p': cur,
                        'ma': [chg(ma_p.get(g), ma_c.get(g)) for g in gus],
                        'je': [chg(je_p.get(g), je_c.get(g)) for g in gus],
                        'wo': [chg(wg_p.get(g), wg_c.get(g)) for g in gus]})
    # 시군구 지도(전국 187) — KOSIS(수일 지연) 대신 R-ONE에서 직접 산출해 최신월로.
    sg_rows = []
    for prev, cur in zip(dates, dates[1:]):
        mp, mc2 = by_cls['maega'].get(prev, {}), by_cls['maega'].get(cur, {})
        jp, jc2 = by_cls['jeonse'].get(prev, {}), by_cls['jeonse'].get(cur, {})
        wp, wc2 = by_cls.get('wolse', {}).get(prev, {}), by_cls.get('wolse', {}).get(cur, {})
        sg_rows.append({'p': cur,
            'ma': [chg(mp.get(SGG_RONE_CLS.get(c)), mc2.get(SGG_RONE_CLS.get(c))) for c in SGG_CODES],
            'je': [chg(jp.get(SGG_RONE_CLS.get(c)), jc2.get(SGG_RONE_CLS.get(c))) for c in SGG_CODES],
            'wo': [chg(wp.get(SGG_RONE_CLS.get(c)), wc2.get(SGG_RONE_CLS.get(c))) for c in SGG_CODES]})
    return {'regions': WEEKLY_REGIONS, 'rows': rows,
            'seoul': {'regions': gus, 'rows': se_rows[-CONF['monthly']['sgg_hist']:]},
            'sgg': {'codes': SGG_CODES, 'rows': sg_rows[-CONF['monthly']['sgg_hist']:]},
            'note': '월간 아파트 매매·전세·월세가격지수 변동률(%) · 매월 발표 (지수 전월비 환산)'}


def fetch_monthly():
    """월간 시세도 R-ONE 단일 소스(fetch_weekly와 같은 이유로 폴백 제거)."""
    assert RONE_KEY, 'RONE_API_KEY 필요'
    return fetch_monthly_rone()


# ---- 기본통계 fetch & merge ----------------------------------------------
def _fetch_basic_one(name, months=None, upto=None):
    """upto=(y,m)이 주어지면 그 달을 끝으로 months개월을 받는다(이력 교정용).
       기본은 오늘 기준 최근 창(BASIC_MONTHS / BASIC_MONTHS_DEEP)."""
    import datetime
    cfg = BASIC_CONF[name]
    base = {'orgId': cfg['org'], 'tblId': cfg['tbl'], 'itmId': 'ALL', 'prdSe': 'M'}
    for k in range(1, cfg['objn'] + 1):
        base['objL%d' % k] = 'ALL'
    n = months or BASIC_MONTHS_DEEP.get(name, BASIC_MONTHS)
    if cfg['mode'] == 'mltm':
        # objL 4단 × 다월 요청은 40,000셀 초과(err31) → 월별 개별 호출
        data = []
        today = datetime.date.today()
        y, m = upto or (today.year, today.month)
        for _ in range(n):
            prd = '%d%02d' % (y, m)
            try:
                data += kosis(dict(base, startPrdDe=prd, endPrdDe=prd))
            except RuntimeError as e:
                if 'err 30' not in str(e): raise
            time.sleep(0.15)
            m -= 1
            if m == 0: y, m = y - 1, 12
    elif upto:
        y, m = upto
        sy, sm = y, m - n + 1
        while sm <= 0: sy, sm = sy - 1, sm + 12
        data = kosis(dict(base, startPrdDe='%d%02d' % (sy, sm), endPrdDe='%d%02d' % (y, m)))
    else:
        data = kosis(dict(base, newEstPrdCnt=str(n)))
    out = {}    # 확정치 {(y,m): {region: value}}
    rates = {}  # 잠정 증감률(%) — 실거래지수의 최신월은 지수 대신 이것만 발표됨
    regcol = 'C2' if cfg['mode'] == 'typed' else 'C1'   # 지역축이 실린 컬럼
    won = {}    # {(ym, region): 채택한 지역코드} — 같은 이름이면 짧은 코드가 이긴다
    for row in data:
        itm = (row.get('ITM_NM') or '').strip()
        if cfg['mode'] == 'flat':
            if itm not in (cfg['itm'], '잠정 증감률'): continue
            reg = (row.get('C1_NM') or '').strip()
        elif cfg['mode'] == 'typed':   # C1=유형, C2=지역
            if (row.get('C1_NM') or '').strip() != cfg['type']: continue
            reg = (row.get('C2_NM') or '').strip()
        else:                          # mltm: C1=지역, C2=유형
            if (row.get('C2_NM') or '').strip() != cfg['type']: continue
            reg = (row.get('C1_NM') or '').strip()
        reg = BASIC_REGMAP.get(reg, reg)
        try: v = float(row['DT'])
        except (TypeError, ValueError, KeyError): continue
        prd = row['PRD_DE']
        ym = (int(prd[:4]), int(prd[4:6]))
        if cfg['mode'] == 'flat' and itm == '잠정 증감률':
            rates.setdefault(ym, {})[reg] = v
        else:
            code = str(row.get(regcol) or '')
            prev = won.get((ym, reg))
            if prev is not None and len(prev) <= len(code):
                continue            # 이미 더 상위(짧은) 코드를 잡았다 — 시군구 행은 버린다
            won[(ym, reg)] = code
            v = round(v, cfg['dec']) if cfg['dec'] else int(round(v))
            out.setdefault(ym, {})[reg] = v
    return out, rates


def _label_ym(label):
    m = re.match(r'^(\d{4})[.\/]\s*(\d{1,2})', str(label).strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def merge_basic(D, fetched):
    """fetched {(y,m):{region:val}} 를 D(dates/series)에 병합. 변경 셀 수 반환."""
    key2idx = {}
    for i, d in enumerate(D['dates']):
        ym = _label_ym(d)
        if ym: key2idx[ym] = i
    changed = 0
    for ym in sorted(fetched):
        vals = {r: v for r, v in fetched[ym].items() if r in D['series']}
        if not vals: continue
        if ym in key2idx:
            i = key2idx[ym]
            plain = '%d.%02d' % ym
            if _label_ym(D['dates'][i]) == ym and D['dates'][i] != plain and 'p' in str(D['dates'][i]):
                D['dates'][i] = plain   # 잠정(p) 꼬리표 제거
        else:
            D['dates'].append('%d.%02d' % ym)
            for s_ in D['series'].values(): s_.append(None)
            i = len(D['dates']) - 1
            key2idx[ym] = i
        for r, v in vals.items():
            if D['series'][r][i] != v:
                D['series'][r][i] = v
                changed += 1
    return changed


def merge_prov(D, rates, dec):
    """잠정 증감률 → 전월 지수 × (1+r/100)로 잠정 지수 계산해 'YYYY.MM p)' 행에 반영.
    해당 월에 확정 지수가 이미 있으면 건드리지 않는다."""
    changed = 0
    for ym in sorted(rates):
        key2idx = {}
        for i, d in enumerate(D['dates']):
            k = _label_ym(d)
            if k: key2idx[k] = i
        prev = ym[0] - 1 if ym[1] == 1 else ym[0]
        prev_ym = (prev, 12 if ym[1] == 1 else ym[1] - 1)
        if prev_ym not in key2idx: continue
        pi = key2idx[prev_ym]
        if ym in key2idx:
            i = key2idx[ym]
            if 'p' not in str(D['dates'][i]):   # 확정 라벨이면 잠정으로 덮지 않음
                if any(D['series'][r][i] is not None for r in D['series']): continue
                D['dates'][i] = '%d.%02d p)' % ym
        else:
            D['dates'].append('%d.%02d p)' % ym)
            for s_ in D['series'].values(): s_.append(None)
            i = len(D['dates']) - 1
        for r, rate in rates[ym].items():
            base = D['series'].get(r, [None])[pi] if r in D['series'] else None
            if base is None: continue
            v = round(base * (1 + rate / 100), dec)
            if D['series'][r][i] != v:
                D['series'][r][i] = v
                changed += 1
    return changed


def fetch_bubble():
    """버블밴드: 전월세전환율(아파트·시도, KOSIS DT_30404_N0010) + 주담대 신규취급 가중평균금리
    (ECOS 121Y006/BECBLA0302). {'prd','loan':{'v','p'},'regions','conv':{지역:%}} 반환."""
    assert KEY and ECOS_KEY, 'KOSIS_API_KEY, ECOS_API_KEY 필요'
    rows = kosis(dict(orgId='408', tblId='DT_30404_N0010', itmId='ALL',
                      objL1='ALL', objL2='ALL', prdSe='M', newEstPrdCnt='3'))
    by_prd = {}
    # ⚠️ 지역을 이름으로만 키잉하면 시도와 시군구가 같은 이름일 때 뒤 행이 앞을 덮는다.
    # 이 표에도 '광주'가 둘(a11 광주광역시 · a1525 경기 광주시), '제주'가 둘(a23 · a2301
    # 제주시) 있고 응답 순서가 a11→a1525라 **광주가 경기 광주시 값**이었다
    # (2026-08-08 감사, 5.71 vs 5.57). _fetch_basic_one과 같은 규칙 — 짧은 코드가 이긴다.
    won = {}
    for r in rows:
        if (r.get('C1_NM') or '').strip() != '아파트':
            continue
        rg = (r.get('C2_NM') or '').strip()
        rg = BUBBLE_SHORT.get(rg, rg)
        if rg not in BUBBLE_REGIONS:
            continue
        try:
            v = round(float(r['DT']), 2)
        except (TypeError, ValueError, KeyError):
            continue
        prd = r.get('PRD_DE', '')
        code = str(r.get('C2') or '')
        prev = won.get((prd, rg))
        if prev is not None and len(prev) <= len(code):
            continue
        won[(prd, rg)] = code
        by_prd.setdefault(prd, {})[rg] = v
    full = [p for p in sorted(by_prd) if len(by_prd[p]) >= 10]   # 값이 충분히 채워진 최신 월
    assert full, '전월세전환율 응답 없음'
    prd, conv = full[-1], by_prd[full[-1]]
    import datetime
    today = datetime.date.today()
    sy, sm = (today.year, today.month - 5) if today.month > 5 else (today.year - 1, today.month + 7)
    url = ('https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/10/121Y006/M/%d%02d/%d%02d/BECBLA0302'
           % (ECOS_KEY, sy, sm, today.year, today.month))
    lr = [r for r in ((http_json(url).get('StatisticSearch') or {}).get('row') or []) if r.get('DATA_VALUE')]
    assert lr, '주담대 금리 응답 없음'
    loan = {'v': round(float(lr[-1]['DATA_VALUE']), 2),
            'p': lr[-1]['TIME'][:4] + '.' + lr[-1]['TIME'][4:6]}
    return {'prd': prd[:4] + '.' + prd[4:6], 'loan': loan,
            'regions': [r for r in BUBBLE_REGIONS if r in conv], 'conv': conv}


# ---- data.js 재작성 ----------------------------------------------------
START, END = '/*ADV_DATA_START*/', '/*ADV_DATA_END*/'
BSTART, BEND = '/*STATS_DATA_START*/', '/*STATS_DATA_END*/'

def read_current_stats():
    c = io.open(DATA, encoding='utf-8').read()
    i, j = c.find(BSTART), c.find(BEND)
    assert i >= 0 and j > i, 'STATS 마커를 찾을 수 없음'
    blob = c[i + len(BSTART):j]
    m = re.match(r'const STATS=(.*);$', blob, re.S)
    return json.loads(m.group(1))


def write_stats(stats):
    c = io.open(DATA, encoding='utf-8').read()
    i, j = c.find(BSTART), c.find(BEND)
    blob = 'const STATS=' + json.dumps(stats, ensure_ascii=False, separators=(',', ':')) + ';'
    io.open(DATA, 'w', encoding='utf-8').write(c[:i + len(BSTART)] + blob + c[j:])


def update_rate(stats):
    """CD(91일) 월평균 — 한국은행 ECOS 721Y001/2010000. 최근 13개월 병합."""
    if not ECOS_KEY:
        print('rate skip: ECOS_API_KEY 없음')
        return []
    import datetime
    today = datetime.date.today()
    start = '%d%02d' % (today.year - 1, today.month)
    end = '%d%02d' % (today.year, today.month)
    url = ('https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/50/721Y001/M/%s/%s/2010000'
           % (ECOS_KEY, start, end))
    data = http_json(url)
    rows = (data.get('StatisticSearch') or {}).get('row') or []
    fetched = {}
    for r in rows:
        t = r.get('TIME') or ''
        try: v = round(float(r['DATA_VALUE']), 2)
        except (TypeError, ValueError, KeyError): continue
        if len(t) == 6:
            fetched[(int(t[:4]), int(t[4:6]))] = {'CD(91일)': v}
    n = merge_basic(stats['금리'], fetched)
    return ['금리(%d)' % n] if n else []


def _fetch_annual_one(name, years=None):
    """{연도(str): {지역: 값}} 반환. 다년 요청이 40,000셀을 넘으면 연 단위로 쪼갠다
       (노후주택30년은 지역×유형이 넓어 3년치가 한계다)."""
    import datetime
    cfg = ANNUAL_CONF[name]
    n = years or ANNUAL_YEARS
    p = {'orgId': cfg['org'], 'tblId': cfg['tbl'], 'itmId': 'ALL', 'prdSe': 'Y',
         'newEstPrdCnt': str(n)}
    for i in range(1, cfg['objn'] + 1):
        p['objL%d' % i] = 'ALL'
    try:
        data = kosis(p)
    except RuntimeError as e:
        if 'err 31' not in str(e):
            raise
        data = []
        y0 = datetime.date.today().year
        for y in range(y0, y0 - n, -1):
            q = dict(p); q.pop('newEstPrdCnt')
            q['startPrdDe'] = q['endPrdDe'] = str(y)
            try:
                data += kosis(q)
            except RuntimeError as e2:
                if 'err 30' not in str(e2):
                    raise
            time.sleep(0.15)
    out = {}
    for row in data:
        if (row.get('ITM_NM') or '').strip() != cfg['itm']:
            continue
        if any((row.get(k) or '').strip() != v for k, v in (cfg.get('only') or {}).items()):
            continue
        reg = cfg.get('region') or (row.get('C1_NM') or '').strip()
        if cfg.get('shortmap'):
            reg = BUBBLE_SHORT.get(reg, reg)
        reg = BASIC_REGMAP.get(reg, reg)
        y = (row.get('PRD_DE') or '').strip()
        try:
            v = float(row['DT'])
        except (TypeError, ValueError, KeyError):
            continue
        if len(y) == 4 and y.isdigit():
            out.setdefault(y, {})[reg] = v
    return out


def merge_annual(D, fetched, dec):
    """연도 문자열('2025') 축의 병합. 새 연도는 뒤에 붙이고, 기존 연도는 값만 고친다."""
    changed = 0
    for y in sorted(fetched):
        vals = {r: v for r, v in fetched[y].items() if r in D['series']}
        if not vals:
            continue
        if y in D['dates']:
            i = D['dates'].index(y)
        else:
            D['dates'].append(y)
            for s_ in D['series'].values():
                s_.append(None)
            i = len(D['dates']) - 1
        for r, v in vals.items():
            nv = round(v, dec) if dec else round(v)
            if D['series'][r][i] != nv:
                D['series'][r][i] = nv
                changed += 1
    return changed


def update_annual(stats):
    changed = []
    for name in ANNUAL_CONF:
        if name not in stats:
            print('annual %s skip: STATS에 없음' % name)
            continue
        try:
            fetched = _fetch_annual_one(name)
            time.sleep(0.2)
            n = merge_annual(stats[name], fetched, ANNUAL_CONF[name]['dec'])
            if n:
                changed.append('%s(%d)' % (name, n))
        except Exception as e:
            print('annual %s skip: %s' % (name, e))
    return changed


def update_basic():
    stats = read_current_stats()
    changed = []
    try:
        changed += update_rate(stats)
    except Exception as e:
        print('rate skip:', e)
    for name in BASIC_CONF:
        try:
            fetched, rates = _fetch_basic_one(name)
            time.sleep(0.2)
            n = merge_basic(stats[name], fetched)
            n += merge_prov(stats[name], rates, BASIC_CONF[name]['dec'])
            if n:
                changed.append('%s(%d)' % (name, n))
        except Exception as e:
            print('basic %s skip: %s' % (name, e))
    try:
        changed += update_size(stats)
    except Exception as e:
        print('size skip:', e)
    try:
        changed += update_supply(stats)
    except Exception as e:
        print('supply skip:', e)
    try:
        changed += update_annual(stats)
    except Exception as e:
        print('annual skip:', e)
    if changed:
        write_stats(stats)
    return changed


# ---- 규모별 동향 (기본통계 '규모별' 피벗) ---------------------------------
# 시장 관행: 가격지수는 총계·유형별이 아니라 규모별로
# 본다 — 총계는 초소형(오피스텔성)이 섞여 왜곡되기 때문. 월간 4표를 아파트만
# 걸러 시도급 20지역 × 규모 6구간으로 담는다. 지수 3종은 전월비 %를 사전 계산,
# 전월세전환율은 수준(%) 그대로(단위가 달라 UI가 지표 블록으로 격리 표기).
# 매 실행 전량 재조회(62개월×4호출, 표당 ~15k셀<40k)라 증분 병합이 필요 없다.
SIZE_TBLS = [('매매', 'DT_30404_B014', True), ('전세', 'DT_30404_B015', True),
             ('월세', 'DT_30404_B005', True), ('전환율', 'DT_30404_N0009', False)]
SIZE_LABELS = ['40㎡↓', '40~60㎡', '60~85㎡', '85~102㎡', '102~135㎡', '135㎡↑']
SIZE_MONTHS = 62


def update_size(stats):
    metrics, dates = {}, set()
    for name, tbl, is_idx in SIZE_TBLS:
        rows = kosis({'orgId': '408', 'tblId': tbl, 'objL1': '01', 'objL2': 'ALL',
                      'objL3': 'ALL', 'itmId': 'ALL', 'prdSe': 'M',
                      'newEstPrdCnt': str(SIZE_MONTHS)})
        time.sleep(0.2)
        by = {}
        for r in rows:
            reg = (r.get('C2_NM') or '').strip()
            if reg not in WEEKLY_REGIONS:
                continue
            try:
                si = int(r.get('C3') or 0) - 1
                v = float(r['DT'])
            except (TypeError, ValueError, KeyError):
                continue
            p = r.get('PRD_DE') or ''
            if not (0 <= si < 6) or len(p) != 6:
                continue
            by.setdefault(reg, {}).setdefault(p, [None] * 6)[si] = v
        out = {}
        for reg, mp in by.items():
            ps = sorted(mp)
            ser = {}
            for i, p in enumerate(ps):
                if is_idx:
                    if i == 0:
                        continue
                    prev = mp[ps[i - 1]]
                    ser[p] = [round((mp[p][k] / prev[k] - 1) * 100, 2)
                              if (mp[p][k] is not None and prev[k]) else None
                              for k in range(6)]
                else:
                    ser[p] = [round(mp[p][k], 2) if mp[p][k] is not None else None
                              for k in range(6)]
            out[reg] = ser
            dates.update(ser)
        metrics[name] = out
    # 공통 시간축: 지수 변동률이 시작되는 달부터 (전환율의 2011~ 과거는 싣지 않음)
    base = min(min(s) for s in metrics['매매'].values())
    ds = sorted(d for d in dates if d >= base)
    series = {}
    for name, _, _ in SIZE_TBLS:
        series[name] = {reg: [metrics[name].get(reg, {}).get(d) for d in ds]
                        for reg in WEEKLY_REGIONS if reg in metrics[name]}
    # ⚠️ 전면 대체가 아니라 **병합**이다. 예전엔 이 자리에서 통째로 갈아 끼워,
    # KOSIS가 한 번만 부분 응답을 주면 20지역×60개월이 1지역×5개월로 조용히
    # 쪼그라들었다(2026-08-07 감사). 기존 계열보다 얕거나 좁으면 채택하지 않는다.
    _prev = stats.get('규모별') or {}
    _pd, _pr = _prev.get('dates') or [], _prev.get('regions') or []
    _nd = ['%s.%s' % (d[:4], d[4:6]) for d in ds]
    _nr = [r for r in WEEKLY_REGIONS if r in series['매매']]
    if _pd and (len(_nd) < len(_pd) * 0.8 or len(_nr) < len(_pr) * 0.8):
        print('규모별 GUARD: %d개월×%d지역 -> %d개월×%d지역으로 급감해 채택하지 않음 '
              '(KOSIS 부분 응답 의심)' % (len(_pd), len(_pr), len(_nd), len(_nr)))
        return []
    stats['규모별'] = {
        'dates': _nd,
        'sizes': SIZE_LABELS,
        # 아파트 전월세전환율(N0009)은 자체 3구간(값은 배열 0~2번 슬롯에만) —
        # 가격표 6구간과 경계가 달라 UI가 이 라벨로 매핑해 표기한다.
        # ⚠️ 실측(R-ONE A_2024_00159 · KOSIS DT_30404_N0009, 2026-08-07):
        # 전환율 구간은 '60㎡이하 / 60㎡초과 85㎡이하 / 85㎡초과'다.
        # 옛 라벨 ['40㎡↓','40~60㎡','60㎡↑']은 셋 다 틀렸고, UI 매핑도 그 전제라
        # 6개 규모 버튼 중 2개가 다른 평형대 값을 읽었다.
        'conv_sizes': ['60㎡↓', '60~85㎡', '85㎡↑'],
        'metrics': [n for n, _, _ in SIZE_TBLS],
        'regions': _nr,
        'unit': '전월 대비 % (전환율은 %)',
        'source': '한국부동산원 전국주택가격동향조사(월간) · 아파트',
        'note': '지수 3종은 전월 대비 변동률, 전월세전환율은 수준(%)',
        'series': series}
    return ['규모별(%d)' % len(ds)]


def read_current_adv():
    c = io.open(DATA, encoding='utf-8').read()
    i, j = c.find(START), c.find(END)
    assert i >= 0 and j > i, 'ADV 마커를 찾을 수 없음'
    blob = c[i + len(START):j]
    m = re.match(r'const ADV=(.*);$', blob, re.S)
    return c, i, j, json.loads(m.group(1))


def write_adv(adv):
    c, i, j, _ = read_current_adv()
    blob = 'const ADV=' + json.dumps(adv, ensure_ascii=False, separators=(',', ':')) + ';'
    c2 = c[:i + len(START)] + blob + c[j:]
    io.open(DATA, 'w', encoding='utf-8').write(c2)


# ── 생활권(31곳)·건축HUB 파생 코드는 2026-08-06에 통째로 걷어냈다 ──────────
# 지역이 국토부 통계와 같은 시도 단위가 되면서 안분 잣대(LIVEZONE/LZ_*)도,
# 단지별 수집(fetch_hub_permits → hub_derive)도 필요 없어졌다. 미래 공급을
# 인허가 기반 준공예정으로 세던 게 1.29~1.68배 과대였던 게 직접적인 이유다.
# 지금은 tools/sido_zones.py가 STATS의 준공·착공만으로 점수를 낸다.
# 근거: docs/superpowers/specs/2026-08-06-sido-supply-table-design.md

def main():
    # 기본값을 --update로. --dry-run 핸들러는 사라졌는데 기본 인자만 남아
    # 인자 없이 실행하면 AssertionError로 죽었다(2026-08-07 감사).
    arg = sys.argv[1] if len(sys.argv) > 1 else '--update'
    if arg == '--discover':
        discover(sys.argv[2])
        return
    _, _, _, adv = read_current_adv()
    if arg == '--seed-bubble':   # 버블밴드 최초 시딩 (KOSIS+ECOS 필요)
        adv['bubble'] = fetch_bubble()
        write_adv(adv)
        print('bubble seeded: prd %s, loan %s, %d regions' % (
            adv['bubble']['prd'], adv['bubble']['loan'], len(adv['bubble']['regions'])))
        return
    if arg == '--seed-supply':   # 분양·미분양 장기 시계열 최초 시딩(1회성, R-ONE 전량)
        st = read_current_stats()
        ch = update_supply(st, months=0)
        if ch:
            write_stats(st)
        print('supply seeded:', ', '.join(ch) or '변경 없음')
        for k in SUPPLY_CONF:
            D = st.get(k) or {}
            if D.get('dates'):
                print('  %s: %s ~ %s (%d개월)' % (k, D['dates'][0], D['dates'][-1], len(D['dates'])))
        return
    if arg == '--heal-price':
        # 주간·월간 시세도 **최근 구간만** 다시 받는다(RECENT_WEEKS 20 / RECENT_MONTHS 14).
        # 그 밖의 과거는 저장분을 그대로 보존하므로, 옛 회차가 잘못 담은 값이 영영 남는다 —
        # 주간 제주가 2026-03-02 이전 88주 동안 제주도가 아니라 **제주시** 계열이었다
        # (2026-08-08 감사, 최근 22주는 정상이라 평소 배치로는 안 드러난다).
        # usage: --heal-price [주] [월]
        weeks = int(sys.argv[2]) if len(sys.argv) > 2 else 160
        months = int(sys.argv[3]) if len(sys.argv) > 3 else 130
        assert RONE_KEY, 'RONE_API_KEY 필요'
        fixed = 0
        for kind, fn, depth in (('weekly', fetch_weekly_rone, weeks),
                                ('monthly', fetch_monthly_rone, months)):
            cur = adv.get(kind) or {}
            new = fn(depth)
            got = {r['p']: r for r in new.get('rows') or []}
            n = 0
            for r in cur.get('rows') or []:
                g = got.get(r['p'])
                if not g:
                    continue
                for f in ('ma', 'je', 'wo'):
                    if isinstance(g.get(f), list) and r.get(f) != g[f]:
                        r[f] = g[f]; n += 1
            print('  %s: %d주/월 조회, %d개 계열행 교정 (%s ~ %s)'
                  % (kind, len(got), n, min(got or ['-']), max(got or ['-'])))
            fixed += n
        if fixed:
            write_adv(adv)
        print('heal-price: %d개 행 교정' % fixed)
        return
    if arg == '--heal-annual':
        # 연간 계열도 ANNUAL_YEARS(3년)만 덮어쓰므로, 그보다 옛 구간은 최초 시딩 때의
        # 판본이 그대로 굳는다. 주택보급률이 2014년까지 **구지표**, 2015년부터 신지표라
        # 2015년에 1.9%p짜리 없던 급락이 그려졌다(2026-08-08 감사). 전량 재조회한다.
        # ⚠️ 새 지표가 없는 옛 연도는 값을 지운다 — 정의가 다른 값을 한 선으로 잇는 것보다
        #    선이 늦게 시작하는 게 정직하다.
        # usage: --heal-annual <계열> [연수]
        name = sys.argv[2]
        years = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        assert name in ANNUAL_CONF, '계열: %s' % ', '.join(ANNUAL_CONF)
        assert KEY, 'KOSIS_API_KEY 환경변수 필요'
        st = read_current_stats()
        fetched = _fetch_annual_one(name, years)
        D = st[name]
        n = merge_annual(D, fetched, ANNUAL_CONF[name]['dec'])
        # ⚠️ 조회 범위 **안**에서만 지운다. 밖(더 옛 연도)은 '새 지표에 없다'가 아니라
        # '이번에 안 물어봤다'이다 — 이걸 구분하지 않아 아파트건설의 1970~1994년
        # 25셀을 한 번 날렸다(2026-08-08, 백업에서 복원).
        lo, hi = (min(fetched), max(fetched)) if fetched else ('9999', '0000')
        wiped = 0
        for i, y in enumerate(D['dates']):
            if y in fetched or not (lo <= y <= hi):
                continue
            for r in D['series']:
                if D['series'][r][i] is not None:
                    D['series'][r][i] = None
                    wiped += 1
        if n or wiped:
            write_stats(st)
        print('heal %s: %d개 연도 조회(%s~%s), %d셀 교정, %d셀 삭제(새 지표 없음)'
              % (name, len(fetched), min(fetched or ['-']), max(fetched or ['-']), n, wiped))
        return
    if arg == '--heal-basic':
        # 갱신창(BASIC_MONTHS / _DEEP) 밖 이력을 원천과 다시 맞춘다. 창 안만 훑는
        # 평소 배치로는 옛 달의 오류가 스스로 낫지 않는다 — 전세가율이 2025.03↔04
        # 경계로 두 판본이 이어 붙어 전북에 +8.9%p 인공 절벽이 있었다(2026-08-07 감사).
        # usage: --heal-basic <계열> [개월수]
        import datetime
        name = sys.argv[2]
        months = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        assert name in BASIC_CONF, '계열: %s' % ', '.join(BASIC_CONF)
        assert KEY, 'KOSIS_API_KEY 환경변수 필요'
        st = read_current_stats()
        today = datetime.date.today()
        y, m = today.year, today.month
        got, fixed, chunk = 0, 0, 12   # 12개월씩 — 지역×유형 전량이라 한 번에 받으면 40,000셀 초과
        while got < months:
            k = min(chunk, months - got)
            fetched, rates = _fetch_basic_one(name, months=k, upto=(y, m))
            fixed += merge_basic(st[name], fetched)
            fixed += merge_prov(st[name], rates, BASIC_CONF[name]['dec'])
            print('  ~%d.%02d %d개월: %d셀 누적 교정' % (y, m, k, fixed))
            got += k
            m -= k
            while m <= 0: y, m = y - 1, m + 12
            time.sleep(0.2)
        if fixed:
            write_stats(st)
        print('heal %s: %d개월 조회, %d셀 교정' % (name, months, fixed))
        return
    if arg == '--seed-sido':
        # 시도 20곳 공급 지표 재계산. STATS만 읽으므로 API 키가 필요 없다 —
        # 산식이나 적정물량 상수를 고친 뒤 데이터를 즉시 맞출 때 쓴다.
        import sido_zones
        st = read_current_stats()
        adv['sido'] = sido_zones.calc(st)
        adv.pop('livezone', None)   # 생활권 31곳 체제 잔재 (2026-08-06 폐기)
        # ⚠️ occupancy(통계 탭 입주물량·/moveins/)도 같은 함수에서 나온다. 여기서 같이
        # 갱신하지 않으면 산식을 고친 뒤 홈만 새 값, 통계 탭은 옛 값이 된다 —
        # supply_rows의 반올림을 고쳤는데 --update를 돌리기 전까지 안 따라왔다
        # (2026-08-08). --seed-sido는 STATS만 읽으므로 API 키가 필요 없다.
        sup = sido_zones.supply_rows(st)
        if sup:
            occ = dict(adv.get('occupancy') or {})
            occ.update(sup)
            for dead in ('band', 'band_note', 'ref_note'):
                occ.pop(dead, None)
            adv['occupancy'] = occ
        write_adv(adv)
        print('sido seeded: %d곳, 실적~%s, 착공~%s, 미래 %d분기 (occupancy %s)'
              % (len(adv['sido']['zones']), adv['sido']['L'], adv['sido']['S'],
                 adv['sido']['H'], '갱신' if sup else '건너뜀'))
        return
    assert arg == '--update', 'usage: --update | --seed-bubble | --seed-sido | --seed-supply | --heal-basic <계열> [개월] | --heal-annual <계열> [연수] | --discover <kw>'
    assert KEY, 'KOSIS_API_KEY 환경변수 필요'
    changed = []
    failed = []     # 어떤 지표 fetch가 죽었는지 집계 — 전량 실패를 '변경 없음'과 구분한다

    def differs(a, b):
        return json.dumps(a, sort_keys=True, ensure_ascii=False) != json.dumps(b, sort_keys=True, ensure_ascii=False)

    try:
        weekly = fetch_weekly()
        cur = adv.get('weekly') or {}
        cur_last = cur['rows'][-1]['p'] if cur.get('rows') else ''
        # 역행 방지 + 병합: R-ONE 부분 응답 등으로 새 데이터가 기존 최신 주보다 뒤처지면
        # 최신 주와 서울/시군구 상세는 기존 것을 유지하고 과거 시계열만 확장한다
        if weekly['rows'] and weekly['rows'][-1]['p'] < cur_last:
            new_last = weekly['rows'][-1]['p']
            weekly['rows'] += [r for r in cur['rows'] if r['p'] > new_last]
            if cur.get('seoul'): weekly['seoul'] = cur['seoul']
            if cur.get('sgg'): weekly['sgg'] = cur['sgg']
        # 깊이 역행 방지: 이번에 짧게 받아졌더라도 이미 갖고 있던 과거는 살린다.
        # 이게 없으면 통째 교체라 화면의 '3년' 탭이 주 단위로 나타났다 사라진다.
        if weekly['rows'] and cur.get('rows'):
            first = weekly['rows'][0]['p']
            older = [r for r in cur['rows'] if r['p'] < first]
            if older:
                weekly['rows'] = (older + weekly['rows'])[-CONF['weekly'].get('weeks_hist', len(weekly['rows'])):]
        kw = CONF['weekly']['sgg_hist']
        weekly['sgg'] = _merge_hist(weekly.get('sgg'), cur.get('sgg'), kw)
        weekly['seoul'] = _merge_hist(weekly.get('seoul'), cur.get('seoul'), kw)
        if weekly['rows'] and differs(weekly, cur):
            adv['weekly'] = weekly
            # '바이트가 달라짐'과 '새 주차가 나옴'은 다르다. 부동산원이 과거 주차를
            # 소급 수정하기만 해도 differs()는 참이 되므로, 실제로 기간이 전진했을 때만
            # 'weekly(~주차)' 토큰을, 아니면 '주간소급수정' 토큰을 커밋 메시지에 남긴다.
            # (2026-07-24 발송 채널 제거 전엔 이 구분이 뉴스레터 중복발송 방지에도 쓰였다.)
            new_last = weekly['rows'][-1]['p']
            changed.append(('weekly(~%s)' % new_last) if new_last > cur_last
                           else ('주간소급수정(~%s)' % new_last))
    except Exception as e:
        failed.append('weekly'); print('weekly skip:', e)
    try:
        monthly = fetch_monthly()
        mo_cur = adv.get('monthly') or {}
        mo_last = mo_cur['rows'][-1]['p'] if mo_cur.get('rows') else ''
        # 역행 방지(weekly와 동일 가드). 부분 응답으로 옛 월만 받아졌더라도
        # 이미 갖고 있던 더 최신 월을 덮어쓰지 않는다(과거 실사고 재발 방지).
        if monthly['rows'] and mo_last and monthly['rows'][-1]['p'] < mo_last:
            new_last = monthly['rows'][-1]['p']
            monthly['rows'] += [r for r in mo_cur['rows'] if r['p'] > new_last]
            if mo_cur.get('seoul'): monthly['seoul'] = mo_cur['seoul']
            if mo_cur.get('sgg'): monthly['sgg'] = mo_cur['sgg']
        # 주간과 같은 이유 — 월간도 깊이가 줄지 않게 과거를 살려 병합한다.
        if monthly['rows'] and mo_cur.get('rows'):
            m_first = monthly['rows'][0]['p']
            m_older = [r for r in mo_cur['rows'] if r['p'] < m_first]
            if m_older:
                monthly['rows'] = (m_older + monthly['rows'])[-CONF['monthly'].get('months_hist', len(monthly['rows'])):]
        _keep_wolse(monthly.get('rows'), mo_cur.get('rows'))
        for _p in ('sgg', 'seoul'):
            if monthly.get(_p) and mo_cur.get(_p):
                _keep_wolse(monthly[_p].get('rows'), mo_cur[_p].get('rows'))
        km = CONF['monthly']['sgg_hist']
        monthly['sgg'] = _merge_hist(monthly.get('sgg'), mo_cur.get('sgg'), km)
        monthly['seoul'] = _merge_hist(monthly.get('seoul'), mo_cur.get('seoul'), km)
        if monthly['rows'] and differs(monthly, adv.get('monthly')):
            adv['monthly'] = monthly
            # weekly와 같은 이유 — 소급 수정은 커밋만 하고 발송은 하지 않는다.
            mo_new = monthly['rows'][-1]['p']
            changed.append(('monthly(~%s)' % mo_new) if mo_new > mo_last
                           else ('월간소급수정(~%s)' % mo_new))
    except Exception as e:
        failed.append('monthly'); print('monthly skip:', e)
    try:
        rows = fetch_permits()
        if rows and len(rows) >= len(adv['permits']['rows']) and differs(rows, adv['permits']['rows']):
            adv['permits']['rows'] = rows
            changed.append('permits(%d)' % len(rows))
    except Exception as e:
        failed.append('permits'); print('permits skip:', e)
    try:
        h = fetch_holidays()
        if h and h != adv.get('holidays'):
            # changed에 넣지 않으면 main()의 `if changed: write_adv(adv)`가 그 회차에
            # 호출되지 않을 때 새 공휴일 목록이 메모리에서 그대로 버려진다
            # (2026-08-04 감사). 값이 실제로 달라졌을 때만 신호를 올린다.
            adv['holidays'] = h
            changed.append('holidays')
    except Exception as e:
        failed.append('holidays'); print('holidays skip:', e)
    try:
        if ECOS_KEY:
            bub = fetch_bubble()
            if differs(bub, adv.get('bubble')):
                adv['bubble'] = bub
                changed.append('bubble(%s)' % bub['prd'])
        else:
            print('bubble skip: ECOS_API_KEY 없음')
    except Exception as e:
        failed.append('bubble'); print('bubble skip:', e)
    if changed:
        write_adv(adv)
    changed += update_basic()   # 기본통계(STATS) 증분 갱신
    # ── 시도 공급 지표 ───────────────────────────────────────────────────────
    # STATS의 준공·착공·아파트멸실에서 파생하므로 **update_basic 뒤**에 와야 한다.
    # 앞에 두면 이번 회차에 갱신된 통계가 아니라 지난 회차 값으로 점수가 나온다.
    try:
        import sido_zones
        sd = sido_zones.calc(read_current_stats())
        n_new = len(sd['zones'])
        n_old = len((adv.get('sido') or {}).get('zones') or [])
        # 가드: 지역이 빠지면 채택하지 않는다. make_sido_pages가 매 실행마다 /zone/을
        # 통째로 지우고 이 목록으로만 재생성하므로, 통계 부분 응답을 그대로 받으면
        # 색인된 URL이 무더기로 404가 된다(옛 livezone 가드와 같은 이유).
        # ⚠️ 이전 값과의 비교만으로는 부족하다 — 첫 시딩(n_old==0)에는 검사가 통째로
        # 건너뛰어져 17곳짜리 결과가 그대로 실린다(2026-08-07 리뷰). 기대 개수는
        # sido_zones.ORDER가 알고 있으므로 절대 기준으로도 본다.
        want = len(sido_zones.ORDER)
        gone = sorted(sd.get('missing') or [])
        if n_new < want or (n_old and n_new < n_old):
            if not gone and n_old:
                gone = sorted({z['z'] for z in adv['sido']['zones']} - {z['z'] for z in sd['zones']})
            print('sido GUARD: 지역이 %d곳뿐이라 채택하지 않음(%d곳이어야 함, 직전 %d곳). 빠진 곳: %s '
                  '(통계 부분 응답 의심. zone 페이지·sitemap 보존)'
                  % (n_new, want, n_old, ', '.join(gone) or '?'))
            failed.append('sido-shrink')
        elif differs(sd, adv.get('sido')):
            adv['sido'] = sd
            changed.append('sido(%d곳, 실적~%s, 미래 %d분기)' % (n_new, sd['L'], sd['H']))
            write_adv(adv)
        # ⚠️ 가드에 걸린 회차는 occupancy도 쓰지 않는다. 점수(ADV.sido)만 지키고
        # 여기서 쓰면 홈 표와 통계 탭이 다시 갈리고, write_adv가 성공해 '변경 있음'이
        # 되면서 전량실패 회로차단기(len(failed)>=5 and not changed)까지 풀린다
        # (2026-08-07 감사).
        if 'sido-shrink' in failed:
            raise RuntimeError('sido 가드에 걸려 occupancy도 갱신하지 않는다')
        # 통계 탭 '입주물량'과 /moveins/도 **같은 소스**를 쓴다. 2026-08-07까지
        # 여기는 odcloud 입주예정이라 같은 서울 2027Q2를 홈은 2,107, 통계 탭은
        # 1,073으로 보여줬고 기준선도 셋(적정물량·밴드·ref)이 공존했다.
        sup = sido_zones.supply_rows(read_current_stats())
        if sup and differs(sup, {k: (adv.get('occupancy') or {}).get(k) for k in sup}):
            occ = dict(adv.get('occupancy') or {})
            occ.update(sup)
            for dead in ('band', 'band_note', 'ref_note'):
                occ.pop(dead, None)      # 충돌하던 두 번째·세 번째 기준선
            adv['occupancy'] = occ
            changed.append('occupancy(공급표와 통일)')
            write_adv(adv)
    except Exception as e:
        failed.append('sido'); print('sido skip:', e)
    # 후속 단계(뉴스레터 발송 등)에 변경 내역 전달 — 커밋 대상 아님
    io.open(os.path.join(ROOT, '.stats_changed'), 'w', encoding='utf-8').write(','.join(changed))
    # 클라우드 冗長 러너 게이트용: 이 실행에서 fetch가 하나라도 실패했는지 남긴다.
    # 나쁜 IP를 뽑은 러너는 여기에 실패 목록이 차므로, 워크플로가 그 러너의
    # 산출물을 커밋 후보에서 제외한다(오염 데이터 커밋 방지). 성공 러너는 빈 파일.
    io.open(os.path.join(ROOT, '.fetch_failed'), 'w', encoding='utf-8').write(','.join(failed))
    if failed:
        print('WARN: fetch 실패 %d개 -> %s' % (len(failed), ', '.join(failed)))
    if changed:
        print('updated:', ', '.join(changed))
    else:
        print('no changes')
    # 전량 실패는 '변경 없음'과 겉모습이 같다. 예전에는 이 둘이 구분되지 않아
    # 데이터 소스가 멎어도 배치가 매일 'OK'를 보고했다(watchdog 13일 임계까지 무증상).
    # 주요 지표가 하나도 안 살아 돌아왔으면 배치를 중단시킨다(배치 rc=12).
    if len(failed) >= 5 and not changed:
        print('ERROR: 주요 지표 fetch가 모두 실패했다 — 데이터 소스 장애로 판단해 중단한다')
        sys.exit(3)


if __name__ == '__main__':
    main()

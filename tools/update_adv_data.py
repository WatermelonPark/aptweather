# -*- coding: utf-8 -*-
"""심화통계 데이터 자동 갱신 (KOSIS OpenAPI).

data.js 안의 /*ADV_DATA_START*/ ... /*ADV_DATA_END*/ 블록을 최신 데이터로 교체한다.
(2026-07-19 분리: 데이터는 index.html이 아니라 data.js에 있다.)
실운영 갱신은 로컬 작업 스케줄러(tools/run_weekly_update.bat, 매주 금 09:30)가 담당한다.
GitHub Actions(.github/workflows/update-stats.yml)는 KOSIS의 해외 IP 차단 때문에
갱신이 실패하며, 차단 해제 시를 대비한 폴백으로만 유지된다.

사용:
  KOSIS_API_KEY=... python tools/update_adv_data.py --update      # 실제 갱신
  KOSIS_API_KEY=... python tools/update_adv_data.py --discover 주택규모별   # 표 ID 탐색
  python tools/update_adv_data.py --dry-run                        # 키 없이 재작성 로직만 검증

데이터셋 구성 (docs/advanced_stats_catalog.md 참조):
  permits  — 국토교통부 「주택건설실적통계」 주택규모별 인허가실적(월별 누계):
             6월·12월 누계에서 (계 − 40㎡이하)로 '40제외' 반기값 산출
  occupancy — 입주물량은 공공 API가 없어 자동 갱신 대상에서 제외(수동 시딩 유지)
  monthly  — 월간 매매·전세 동향(KOSIS DT_30404_B012/B013): 시황 탭 월간 지도·그래프에
             쓰이는 라이브 데이터로 매 실행 갱신한다(fetch_monthly, adv['monthly']).
"""
import io, os, re, sys, json, time
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data.js')
API = 'https://kosis.kr/openapi/Param/statisticsParameterData.do'
LIST_API = 'https://kosis.kr/openapi/statisticsList.do'
KEY = os.environ.get('KOSIS_API_KEY', '')
ECOS_KEY = os.environ.get('ECOS_API_KEY', '')   # 한국은행 ECOS (CD금리용, 없으면 금리만 건너뜀)
DATAGO_KEY = os.environ.get('DATA_GO_KR_KEY', '')   # 공공데이터포털 (입주예정물량용, 없으면 입주물량만 건너뜀)
RONE_KEY = os.environ.get('RONE_API_KEY', '')       # 부동산원 R-ONE (주간 속보용 — KOSIS보다 4~7일 빠름)
# R-ONE 주간 아파트 가격지수 (발표 당일 반영). 지수 → 전주비 변동률 계산.
RONE_API = 'https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do'
RONE_TBL = {'maega': 'T244183132827305', 'jeonse': 'T247713133046872'}
# 한국부동산원 주택공급정보 입주예정물량정보 (data.go.kr/data/15111714) — 반기 갱신, 30세대 이상 단지별
OCC_API = 'https://api.odcloud.kr/api/15111714/v1/uddi:0b257760-ac19-4841-adb4-b38b4d153397'

# ---- KOSIS 표 설정 ------------------------------------------------------
# tblId는 `--discover <검색어>` 로 확인 후 채운다.
# DT_MLTM_1948(주택유형별 인허가실적 월별누계)은 2024 강의 화면 URL에서 직접 확인됨.
CONF = {
    'permits_size': {          # 주택규모별 인허가실적(월별 누계) — 40제외 산출용
        'orgId': '116',
        'tblId': 'DT_MLTM_1952',   # 2026-07 API 실측 확인 (C1=규모, C2/C3=권역, C4=시도)
    },
    'weekly': {                # 주간 아파트 가격지수 변동률 (부동산원, 매주 발표)
        'maega':  {'orgId': '408', 'tblId': 'DT_304004_WEEK_001_B'},
        'jeonse': {'orgId': '408', 'tblId': 'DT_304004_WEEK_003_B'},
        'weeks': 12,           # 서울 구·시군구 상세 유지 주수
        'weeks_hist': 104,     # 시도 시계열 유지 주수 (그래프 과거 탐색용)
    },
    'monthly': {               # 월간 아파트 가격지수 (부동산원 월간동향) — 전월비 변동률 계산
        'maega':  {'orgId': '408', 'tblId': 'DT_30404_B012'},   # 유형별 매매가격지수 (C1=유형, C2=지역)
        'jeonse': {'orgId': '408', 'tblId': 'DT_30404_B013'},   # 유형별 전세가격지수
        'months': 12,          # 서울 구·시군구 상세 유지 개월수
        'months_hist': 60,     # 시도 시계열 유지 개월수 (그래프 과거 탐색용)
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

REG15 = ['수도권','부산','대구','광주','대전','울산','세종','강원','충북','충남','전북','전남','경북','경남','제주']


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
        if reg not in REG15: continue
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
        v1 = [h1.get(r) for r in REG15]
        if any(v is not None for v in v1):
            rows_out.append({'p': '%dH1' % y, 'v': v1})
        cum = _fetch_apt_permits('%d12' % y)
        time.sleep(0.15)
        vc = [cum.get(r) for r in REG15]
        if any(v is not None for v in vc):
            v2 = [None if (a is None or b is None) else a - b for a, b in zip(vc, v1)]
            rows_out.append({'p': '%dH2' % y, 'v': v2})
    return rows_out


# ---- weekly: 주간 아파트 매매·전세 변동률 --------------------------------
# KOSIS 지역 분류코드: 서울 25개 구 = ^a70\d{5}$ (주간 C1, 월간 C2 공통).
# 이름만으로는 '중'·'강서' 등이 타 도시 구와 겹쳐 코드로 식별한다.
SEOUL_GU_RE = re.compile(r'^a70\d{5}$')

# 전국 상세 지도(ENJ식 시군구 타일)용 지역코드 — index.html NATION_TILE과 동일 집합
SGG_CODES = ["a0", "a7", "a7010101", "a7010102", "a7010103", "a7010201", "a7010202", "a7010203", "a7010204", "a7010205", "a7010206", "a7010207", "a7010208", "a7010301", "a7010302", "a7010303", "a7020101", "a7020102", "a7020103", "a7020104", "a7020105", "a7020106", "a7020107", "a7020201", "a7020202", "a7020203", "a7020204", "a8", "a80101", "a80102", "a80103", "a80104", "a80105", "a80201", "a80202", "a80203", "a80301", "a80302", "a80303", "a80304", "a80305", "a80306", "a80307", "a80401", "a80402", "a80403", "a80404", "a80501", "a80502", "a80601", "a80602", "a80603", "a80701", "a80702", "a80703", "a80704", "a9", "a901", "a902", "a903", "a904", "a905", "a906", "a907", "a908", "b1", "b10101", "b10102", "b10103", "b10104", "b10105", "b10106", "b10107", "b10108", "b10201", "b10202", "b10203", "b10204", "b10301", "b10302", "b10303", "b10304", "b2", "b201", "b202", "b203", "b204", "b205", "b206", "b207", "b208", "b3", "b301", "b302", "b303", "b304", "b305", "b4", "b401", "b402", "b403", "b404", "b405", "b5", "b501", "b502", "b503", "b504", "b505", "b6", "c1", "c101", "c102", "c103", "c104", "c105", "c106", "c107", "c2", "c201", "c20101", "c20102", "c20103", "c20104", "c203", "c204", "c206", "c3", "c301", "c302", "c303", "c304", "c305", "c306", "c307", "c308", "c309", "c311", "c312", "c313", "c4", "c401", "c402", "c403", "c404", "c405", "c406", "c407", "c408", "c5", "c501", "c502", "c503", "c504", "c505", "c506", "c6", "c601", "c602", "c603", "c60301", "c60302", "c604", "c605", "c606", "c607", "c608", "c609", "c610", "c611", "c7", "c701", "c70101", "c70102", "c70103", "c70104", "c702", "c703", "c704", "c705", "c706", "c707", "c708", "c709", "c8", "c801", "c802"]
SGG_SET = set(SGG_CODES)

def _gu_name(nm):
    return nm + '구'   # 강남→강남구, 중→중구

def _fetch_weekly_one(cfg, weeks):
    data = kosis({
        'orgId': cfg['orgId'], 'tblId': cfg['tblId'],
        'objL1': 'ALL', 'itmId': 'ALL', 'prdSe': 'F',
        'newEstPrdCnt': str(weeks),
    })
    by, seoul, sgg = {}, {}, {}
    for row in data:
        code = (row.get('C1') or '').strip()
        reg = (row.get('C1_NM') or '').strip()
        try: v = float(row['DT'])
        except (TypeError, ValueError, KeyError): continue
        if SEOUL_GU_RE.match(code):
            seoul.setdefault(row['PRD_DE'], {})[_gu_name(reg)] = v
        if code in SGG_SET:
            sgg.setdefault(row['PRD_DE'], {})[code] = v
        if reg in WEEKLY_REGIONS:
            by.setdefault(row['PRD_DE'], {})[reg] = v
    return by, seoul, sgg


def _gu_regions(*maps):
    gus = set()
    for m in maps:
        for d in m.values(): gus.update(d)
    return sorted(gus)


# ---- R-ONE 주간 속보 (시도 18 + 서울 25구) --------------------------------
# KOSIS는 발표 후 4~7일 지연되므로, 주간은 부동산원 R-ONE에서 직접 받는다.
# 시군구 상세(sgg)는 지역코드 재매핑 부담이 커서 KOSIS 유지(수일 뒤 자동 보충).
def _rone_recent_rows(tbl, need_rows):
    base = {'KEY': RONE_KEY, 'Type': 'json', 'pSize': 1000, 'STATBL_ID': tbl, 'DTACYCLE_CD': 'WK'}
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


def fetch_weekly_rone():
    weeks = CONF['weekly'].get('weeks_hist', CONF['weekly']['weeks'])
    need = (weeks + 2) * 240        # 주당 ~236행
    by = {}   # {'maega'|'jeonse': {date: {FULLNM: idx}}}
    for key, tbl in RONE_TBL.items():
        m = {}
        for r in _rone_recent_rows(tbl, need):
            full = (r.get('CLS_FULLNM') or '').strip()
            t = (r.get('WRTTIME_DESC') or '').strip()
            try: v = float(r['DTA_VAL'])
            except (TypeError, ValueError, KeyError): continue
            if len(t) == 10:
                m.setdefault(t, {})[full] = v
        by[key] = m
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
    return {'regions': WEEKLY_REGIONS, 'rows': rows,
            'seoul': {'regions': gus, 'rows': se_rows[-CONF['weekly']['weeks']:]},
            'note': '주간 아파트 매매·전세가격지수 변동률(%) · 발표 당일 반영'}


def fetch_weekly():
    kosis = _fetch_weekly_kosis()
    if not RONE_KEY:
        return kosis
    try:
        rone = fetch_weekly_rone()
        k_last = kosis['rows'][-1]['p'] if kosis.get('rows') else ''
        if rone['rows'] and rone['rows'][-1]['p'] >= k_last:
            rone['sgg'] = kosis.get('sgg')      # 시군구 상세는 KOSIS(자체 주차 라벨 유지)
            return rone
    except Exception as e:
        print('rone weekly skip:', e)
    return kosis


def _fetch_weekly_kosis():
    w = CONF['weekly']
    hist = w.get('weeks_hist', w['weeks'])   # 105주 x ~240행 = 25k셀 < KOSIS 40k 제한
    ma, ma_se, ma_sg = _fetch_weekly_one(w['maega'], hist)
    time.sleep(0.2)
    je, je_se, je_sg = _fetch_weekly_one(w['jeonse'], hist)
    # 매매·전세가 모두 발표된 주만 반영 (한쪽만 먼저 올라온 반쪽 주차로 인한 이중 알림 방지)
    dates = sorted(set(ma) & set(je))[-hist:]
    rows = []
    for d in dates:
        rows.append({
            'p': '%s-%s-%s' % (d[:4], d[4:6], d[6:8]),
            'ma': [ma.get(d, {}).get(r) for r in WEEKLY_REGIONS],
            'je': [je.get(d, {}).get(r) for r in WEEKLY_REGIONS],
        })
    gus = _gu_regions(ma_se, je_se)
    d12 = dates[-w['weeks']:]   # 서울 구·시군구 상세는 최근 주만 (index.html 비대화 방지)
    se_rows = [{'p': '%s-%s-%s' % (d[:4], d[4:6], d[6:8]),
                'ma': [ma_se.get(d, {}).get(r) for r in gus],
                'je': [je_se.get(d, {}).get(r) for r in gus]} for d in d12]
    sg_rows = [{'p': '%s-%s-%s' % (d[:4], d[4:6], d[6:8]),
                'ma': [ma_sg.get(d, {}).get(c) for c in SGG_CODES],
                'je': [je_sg.get(d, {}).get(c) for c in SGG_CODES]} for d in d12]
    return {'regions': WEEKLY_REGIONS, 'rows': rows,
            'seoul': {'regions': gus, 'rows': se_rows},
            'sgg': {'codes': SGG_CODES, 'rows': sg_rows},
            'note': '주간 아파트 매매·전세가격지수 변동률(%) · 매주 발표'}


# ---- occupancy: 준공실적(과거) + 입주예정물량(미래) ------------------------
# 과거·완료 분기 = 국토부 준공실적(DT_MLTM_5373, 아파트) 3개월 합산.
# 미래 분기 = 부동산원 입주예정물량(단지별)을 분기×지역 합산. 서울/경기/인천 → 수도권.
def _q_of(p): return (int(p[:4]), int(p[5]))          # '2026Q3' → (2026,3)
def _qlabel(y, q): return '%dQ%d' % (y, q)


def fetch_moveins(regions):
    url = OCC_API + '?' + urllib.parse.urlencode({'page': 1, 'perPage': 1000, 'serviceKey': DATAGO_KEY})
    d = http_json(url)
    agg = {}
    for r in d.get('data', []):
        ym = str(r.get('입주예정월') or '')
        if len(ym) < 7 or not ym[5:7].isdigit() or not 1 <= int(ym[5:7]) <= 12:
            continue   # 입주월 미정 단지는 제외
        reg = (r.get('지역') or '').strip()
        if reg in ('서울', '경기', '인천'): reg = '수도권'
        if reg not in regions: continue
        try: n = int(r.get('세대수') or 0)
        except (TypeError, ValueError): continue
        key = (int(ym[:4]), (int(ym[5:7]) - 1) // 3 + 1)
        agg.setdefault(key, {x: 0 for x in regions})
        agg[key][reg] += n
    return agg


def fetch_completions(start, end, regions):
    """(y,m) 범위의 준공실적 → {(y,m): {지역: 호수}} (아파트 기준, 월별 개별 호출)"""
    out = {}
    y, m = start
    while (y, m) <= end:
        prd = '%d%02d' % (y, m)
        try:
            data = kosis({'orgId': '116', 'tblId': 'DT_MLTM_5373',
                          'objL1': 'ALL', 'objL2': 'ALL', 'objL3': 'ALL', 'objL4': 'ALL',
                          'itmId': 'ALL', 'prdSe': 'M', 'startPrdDe': prd, 'endPrdDe': prd})
        except RuntimeError as e:
            if 'err 30' in str(e): data = []
            else: raise
        by = {}
        for row in data:
            if (row.get('C2_NM') or '').strip() != '아파트': continue
            reg = (row.get('C1_NM') or '').strip()
            if reg == '수도권소계': reg = '수도권'
            if reg not in regions: continue
            try: by[reg] = int(float(row['DT']))
            except (TypeError, ValueError, KeyError): continue
        if by: out[(y, m)] = by
        time.sleep(0.12)
        m += 1
        if m == 13: y, m = y + 1, 1
    return out


def _complete_quarters(comp, regions):
    """월별 준공 → 3개월이 모두 있는 분기만 합산 {(y,q): {지역: 호수}}"""
    grp = {}
    for (y, m), by in comp.items():
        grp.setdefault((y, (m - 1) // 3 + 1), []).append(by)
    return {k: {r: sum(b.get(r, 0) for b in v) for r in regions}
            for k, v in grp.items() if len(v) == 3}


def update_occupancy(adv, full=False):
    if not DATAGO_KEY:
        print('occupancy skip: DATA_GO_KR_KEY 없음')
        return []
    import datetime
    O = adv['occupancy']
    regs = O['regions']
    today = datetime.date.today()
    if full:
        start = (2017, 1)
    else:                       # 최근 3개 분기 재계산 분량만 조회
        y, m = today.year, today.month
        for _ in range(10):
            m -= 1
            if m == 0: y, m = y - 1, 12
        start = (y, m)
    comp = fetch_completions(start, (today.year, today.month), regs)
    cq = _complete_quarters(comp, regs)
    mv = fetch_moveins(regs)
    rows_map = {} if full else {_q_of(r['p']): r['v'] for r in O['rows']}
    est = set() if full else {_q_of(r['p']) for r in O['rows'] if r.get('e')}
    for k, by in cq.items():
        rows_map[k] = [by.get(r) for r in regs]
        est.discard(k)                          # 실적 확정 → 예정 딱지 제거
    last_cq = max(cq) if cq else None
    for k, by in mv.items():
        if last_cq and k <= last_cq: continue   # 준공 실적이 있으면 실적 우선
        rows_map[k] = [by.get(r, 0) for r in regs]
        est.add(k)                              # 입주예정 기반 = 미확정 표시
    if full and mv:
        # 준공 이후~입주예정 커버리지 안의 빈 분기는 '예정 없음(0)'으로 채움
        y, q = last_cq if last_cq else min(mv)
        while (y, q) < max(mv):
            q += 1
            if q == 5: y, q = y + 1, 1
            if (y, q) not in rows_map:
                rows_map[(y, q)] = [0] * len(regs)
                est.add((y, q))
    keys = sorted(rows_map)
    O['rows'] = [dict({'p': _qlabel(*k), 'v': rows_map[k]}, **({'e': 1} if k in est else {}))
                 for k in keys]
    O['note'] = '분기별 아파트 준공 실적 + 입주예정 물량 · 미래 분기 포함'
    return ['occupancy(%d)' % len(keys)]


# ---- monthly: 월간 아파트 매매·전세 지수 → 전월비 변동률 ------------------
def _fetch_monthly_one(cfg, months):
    # KOSIS 40,000셀 제한 회피: 12개월 단위 기간 분할 조회 후 병합
    import datetime as _dt
    def _shift(y, m, n):
        m += n
        while m > 12: y += 1; m -= 12
        while m < 1: y -= 1; m += 12
        return y, m
    _t = _dt.date.today()
    cy, cm = _shift(_t.year, _t.month, -months)
    data = []
    while (cy, cm) <= (_t.year, _t.month):
        ey, em = _shift(cy, cm, 11)
        if (ey, em) > (_t.year, _t.month): ey, em = _t.year, _t.month
        try:
            data += kosis({
                'orgId': cfg['orgId'], 'tblId': cfg['tblId'],
                'objL1': 'ALL', 'objL2': 'ALL', 'itmId': 'ALL', 'prdSe': 'M',
                'startPrdDe': '%04d%02d' % (cy, cm), 'endPrdDe': '%04d%02d' % (ey, em),
            })
        except RuntimeError as e:
            if 'err 30' not in str(e): raise   # 미발표 구간(데이터 없음)만 허용
        cy, cm = _shift(ey, em, 1)
        time.sleep(0.25)
    by, seoul, sgg = {}, {}, {}
    for row in data:
        if (row.get('C1_NM') or '').strip() != '아파트': continue
        code = (row.get('C2') or '').strip()
        reg = (row.get('C2_NM') or '').strip()
        try: v = float(row['DT'])
        except (TypeError, ValueError, KeyError): continue
        if SEOUL_GU_RE.match(code):
            seoul.setdefault(row['PRD_DE'], {})[_gu_name(reg)] = v
        if code in SGG_SET:
            sgg.setdefault(row['PRD_DE'], {})[code] = v
        if reg in WEEKLY_REGIONS:
            by.setdefault(row['PRD_DE'], {})[reg] = v
    return by, seoul, sgg


def _idx_to_chg(ma, je, regions):
    dates = sorted(set(ma) & set(je))
    rows = []
    for prev, cur in zip(dates, dates[1:]):
        def chg(by):
            out = []
            for r in regions:
                a, b = by.get(prev, {}).get(r), by.get(cur, {}).get(r)
                out.append(None if (a in (None, 0) or b is None) else round((b / a - 1) * 100, 2))
            return out
        rows.append({'p': '%s-%s' % (cur[:4], cur[4:6]), 'ma': chg(ma), 'je': chg(je)})
    return rows


def fetch_monthly():
    m = CONF['monthly']
    ma, ma_se, ma_sg = _fetch_monthly_one(m['maega'], m.get('months_hist', m['months']))
    time.sleep(0.2)
    je, je_se, je_sg = _fetch_monthly_one(m['jeonse'], m.get('months_hist', m['months']))
    rows = _idx_to_chg(ma, je, WEEKLY_REGIONS)[-m.get('months_hist', m['months']):]
    gus = _gu_regions(ma_se, je_se)
    se_rows = _idx_to_chg(ma_se, je_se, gus)[-m['months']:]
    sg_rows = _idx_to_chg(ma_sg, je_sg, SGG_CODES)[-m['months']:]
    return {'regions': WEEKLY_REGIONS, 'rows': rows,
            'seoul': {'regions': gus, 'rows': se_rows},
            'sgg': {'codes': SGG_CODES, 'rows': sg_rows},
            'note': '월간 아파트 매매·전세가격지수 변동률(%) · 매월 발표 (지수 전월비 환산)'}


# ---- 기본통계 fetch & merge ----------------------------------------------
def _fetch_basic_one(name):
    import datetime
    cfg = BASIC_CONF[name]
    base = {'orgId': cfg['org'], 'tblId': cfg['tbl'], 'itmId': 'ALL', 'prdSe': 'M'}
    for k in range(1, cfg['objn'] + 1):
        base['objL%d' % k] = 'ALL'
    if cfg['mode'] == 'mltm':
        # objL 4단 × 다월 요청은 40,000셀 초과(err31) → 월별 개별 호출
        data = []
        today = datetime.date.today()
        y, m = today.year, today.month
        for _ in range(BASIC_MONTHS):
            prd = '%d%02d' % (y, m)
            try:
                data += kosis(dict(base, startPrdDe=prd, endPrdDe=prd))
            except RuntimeError as e:
                if 'err 30' not in str(e): raise
            time.sleep(0.15)
            m -= 1
            if m == 0: y, m = y - 1, 12
    else:
        data = kosis(dict(base, newEstPrdCnt=str(BASIC_MONTHS)))
    out = {}    # 확정치 {(y,m): {region: value}}
    rates = {}  # 잠정 증감률(%) — 실거래지수의 최신월은 지수 대신 이것만 발표됨
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
        by_prd.setdefault(r.get('PRD_DE', ''), {})[rg] = v
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
    if changed:
        write_stats(stats)
    return changed

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


# ---- 생활권 입주예정 (odcloud 단지별 → 생활권 집계, 인구 대비 강도) ----
LZ_SIDO_FULL = {'서울특별시':'서울','부산광역시':'부산','대구광역시':'대구','인천광역시':'인천','광주광역시':'광주',
    '대전광역시':'대전','울산광역시':'울산','세종특별자치시':'세종','경기도':'경기','강원특별자치도':'강원','강원도':'강원',
    '충청북도':'충북','충청남도':'충남','전북특별자치도':'전북','전라북도':'전북','전라남도':'전남',
    '경상북도':'경북','경상남도':'경남','제주특별자치도':'제주','제주도':'제주'}
LZ_GWANG = {'서울','부산','대구','인천','광주','대전','울산','세종'}
LIVEZONE = {
 '부산권':[('부산','*'),('경남','양산시')], '김해권':[('경남','김해시')], '창원권':[('경남','창원시')],
 '울산권':[('울산','*')], '진주권':[('경남','진주시')], '대구권':[('대구','*'),('경북','경산시'),('경북','칠곡군')],
 '포항권':[('경북','포항시'),('경북','경주시')], '구미권':[('경북','구미시'),('경북','김천시')],
 '안동권':[('경북','안동시'),('경북','예천군')], '대전세종권':[('대전','*'),('세종','*'),('충남','계룡시')],
 '청주권':[('충북','청주시')], '천안아산권':[('충남','천안시'),('충남','아산시')], '서산당진권':[('충남','서산시'),('충남','당진시')],
 '광주권':[('광주','*'),('전남','나주시'),('전남','담양군'),('전남','화순군'),('전남','장성군')],
 '전주권':[('전북','전주시'),('전북','완주군')], '군산익산권':[('전북','군산시'),('전북','익산시')],
 '여순광권':[('전남','여수시'),('전남','순천시'),('전남','광양시')], '목포권':[('전남','목포시'),('전남','무안군'),('전남','영암군')],
 '원주권':[('강원','원주시')], '춘천권':[('강원','춘천시')], '강릉권':[('강원','강릉시'),('강원','동해시'),('강원','속초시')],
 '제주권':[('제주','*')], '서울권':[('서울','*')], '인천권':[('인천','*')],
}
LZ_GU2SI = {'서원구':'청주시','상당구':'청주시','흥덕구':'청주시','청원구':'청주시','동남구':'천안시','서북구':'천안시',
 '완산구':'전주시','덕진구':'전주시','의창구':'창원시','성산구':'창원시','마산합포구':'창원시','마산회원구':'창원시','진해구':'창원시'}
LZ_PSIDO = {'서울권':'수도권','인천권':'수도권','부산권':'부산','김해권':'경남','창원권':'경남','진주권':'경남',
 '울산권':'울산','대구권':'대구','포항권':'경북','구미권':'경북','안동권':'경북','대전세종권':'대전',
 '청주권':'충북','천안아산권':'충남','서산당진권':'충남','광주권':'광주','전주권':'전북','군산익산권':'전북',
 '여순광권':'전남','목포권':'전남','원주권':'강원','춘천권':'강원','강릉권':'강원','제주권':'제주'}
LZ_REGION = {'서울권':'수도권','인천권':'수도권','원주권':'강원','춘천권':'강원','강릉권':'강원',
 '대전세종권':'충청','청주권':'충청','천안아산권':'충청','서산당진권':'충청',
 '광주권':'전라','전주권':'전라','군산익산권':'전라','여순광권':'전라','목포권':'전라',
 '부산권':'경상','김해권':'경상','창원권':'경상','울산권':'경상','진주권':'경상','대구권':'경상',
 '포항권':'경상','구미권':'경상','안동권':'경상','제주권':'제주'}

def _lz_pop():
    url = API + '?' + urllib.parse.urlencode(dict(method='getList', apiKey=KEY, format='json', jsonVD='Y',
        orgId='101', tblId='DT_1B040A3', objL1='ALL', itmId='T20', prdSe='M', newEstPrdCnt='1'))
    sido, sgg, cur = {}, {}, None
    for r in http_json(url):
        nm = (r.get('C1_NM') or '').strip()
        try: pop = int(r.get('DT') or 0)
        except (TypeError, ValueError): continue
        if nm in LZ_SIDO_FULL:
            cur = LZ_SIDO_FULL[nm]; sido[cur] = pop; continue
        if nm == '전국' or cur is None or cur in LZ_GWANG or nm.endswith('구'): continue
        sgg[(cur, nm)] = pop
    return sido, sgg

def fetch_livezone():
    import collections, datetime
    assert KEY and DATAGO_KEY, 'KOSIS_API_KEY, DATA_GO_KR_KEY 필요'
    sido_pop, sgg_pop = _lz_pop()
    m2z = {m: z for z, mm in LIVEZONE.items() for m in mm}
    def zone_of(sd, sg):
        if (sd, '*') in m2z: return m2z[(sd, '*')]
        sg = LZ_GU2SI.get(sg, sg)
        if (sd, sg) in m2z: return m2z[(sd, sg)]
        if sd == '경기': return sg.replace('시', '').replace('군', '') + '권'
        return None
    def zone_pop(z):
        if z in LIVEZONE:
            return sum(sido_pop.get(m[0], 0) if m[1] == '*' else sgg_pop.get(m, 0) for m in LIVEZONE[z])
        nm = z[:-1]
        return sum(sgg_pop.get(('경기', nm + s), 0) for s in ('시', '군'))
    supply = collections.defaultdict(int)
    detail = collections.defaultdict(lambda: collections.defaultdict(int))
    qset = collections.defaultdict(set)
    byq = collections.defaultdict(lambda: collections.defaultdict(int))
    for pg in range(1, 9):
        d = http_json(OCC_API + '?' + urllib.parse.urlencode({'page': pg, 'perPage': 1000, 'serviceKey': DATAGO_KEY}))
        data = d.get('data', [])
        if not data: break
        for r in data:
            sd = (r.get('지역') or '').strip(); ym = str(r.get('입주예정월') or '')
            if len(ym) < 7 or not ym[5:7].isdigit(): continue
            a = (r.get('주소') or '').split(); sg = a[1] if len(a) > 1 else ''
            if sd == '세종': sg = '세종'
            z = zone_of(sd, sg)
            if not z: continue
            try: n = int(r.get('세대수') or 0)
            except (TypeError, ValueError): n = 0
            q = (int(ym[:4]), (int(ym[5:7]) - 1) // 3 + 1)
            supply[z] += n; detail[z][LZ_GU2SI.get(sg, sg)] += n
            qset[z].add(q); byq[z]['%dQ%d' % q] += n
    def mk(z, region):
        pop = zone_pop(z); s = supply.get(z, 0); qs = sorted(qset.get(z, []))
        span = ((qs[-1][0] - qs[0][0]) * 4 + (qs[-1][1] - qs[0][1]) + 1) if qs else 0
        det = sorted(detail[z].items(), key=lambda x: -x[1])
        return {'z': z, 'region': region, 'psido': LZ_PSIDO.get(z, '수도권'), 'pop': pop, 'supply': s,
                'inten': round(s / (pop / 10000), 1) if pop else 0, 'span': span,
                'q0': ('%dQ%d' % qs[0] if qs else ''), 'q1': ('%dQ%d' % qs[-1] if qs else ''),
                'sgg': [[k, v] for k, v in det],
                'byq': dict(byq.get(z, {}))}
    zones = []
    for z in LIVEZONE:
        if zone_pop(z) >= 300000: zones.append(mk(z, LZ_REGION.get(z, '기타')))
    for z in supply:
        if z not in LIVEZONE and zone_pop(z) >= 300000: zones.append(mk(z, '수도권'))
    zones.sort(key=lambda x: -x['inten'])
    td = datetime.date.today()
    spop = dict(sido_pop)
    spop['수도권'] = sido_pop.get('서울', 0) + sido_pop.get('인천', 0) + sido_pop.get('경기', 0)
    return {'prd': '%d.%02d' % (td.year, td.month), 'unit': '만명당 예정세대(향후 전량)',
            'sidopop': spop, 'zones': zones}


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else '--dry-run'
    if arg == '--discover':
        discover(sys.argv[2])
        return
    _, _, _, adv = read_current_adv()
    if arg == '--rebuild-occupancy':   # 입주물량 시계열 전체 재구축 (준공 2017~ 전량 조회, 1회성)
        assert KEY and DATAGO_KEY, 'KOSIS_API_KEY, DATA_GO_KR_KEY 필요'
        ch = update_occupancy(adv, full=True)
        write_adv(adv)
        print('rebuilt:', ', '.join(ch))
        return
    if arg == '--dry-run':
        write_adv(adv)  # 동일 데이터 재기록 = 마커·직렬화 왕복 검증
        print('dry-run ok: permits %d rows, occupancy %d rows' % (
            len(adv['permits']['rows']), len(adv['occupancy']['rows'])))
        return
    if arg == '--seed-bubble':   # 버블밴드 최초 시딩 (KOSIS+ECOS 필요)
        adv['bubble'] = fetch_bubble()
        write_adv(adv)
        print('bubble seeded: prd %s, loan %s, %d regions' % (
            adv['bubble']['prd'], adv['bubble']['loan'], len(adv['bubble']['regions'])))
        return
    if arg == '--seed-livezone':   # 생활권 입주예정 최초 시딩 (KOSIS+DATAGO 필요)
        adv['livezone'] = fetch_livezone()
        write_adv(adv)
        print('livezone seeded: %d zones, prd %s' % (len(adv['livezone']['zones']), adv['livezone']['prd']))
        return
    assert arg == '--update', 'usage: --update | --seed-bubble | --seed-livezone | --dry-run | --discover <kw>'
    assert KEY, 'KOSIS_API_KEY 환경변수 필요'
    changed = []

    def differs(a, b):
        return json.dumps(a, sort_keys=True, ensure_ascii=False) != json.dumps(b, sort_keys=True, ensure_ascii=False)

    try:
        weekly = fetch_weekly()
        cur = adv.get('weekly') or {}
        cur_last = cur['rows'][-1]['p'] if cur.get('rows') else ''
        # 역행 방지 + 병합: 새 데이터(KOSIS 폴백)가 기존 최신 주(R-ONE 속보)보다 뒤처지면
        # 최신 주와 서울/시군구 상세는 기존 것을 유지하고 과거 시계열만 확장한다
        if weekly['rows'] and weekly['rows'][-1]['p'] < cur_last:
            new_last = weekly['rows'][-1]['p']
            weekly['rows'] += [r for r in cur['rows'] if r['p'] > new_last]
            if cur.get('seoul'): weekly['seoul'] = cur['seoul']
            if cur.get('sgg'): weekly['sgg'] = cur['sgg']
        if weekly['rows'] and differs(weekly, cur):
            adv['weekly'] = weekly
            changed.append('weekly(~%s)' % weekly['rows'][-1]['p'])
    except Exception as e:
        print('weekly skip:', e)
    try:
        monthly = fetch_monthly()
        if monthly['rows'] and differs(monthly, adv.get('monthly')):
            adv['monthly'] = monthly
            changed.append('monthly(~%s)' % monthly['rows'][-1]['p'])
    except Exception as e:
        print('monthly skip:', e)
    try:
        rows = fetch_permits()
        if rows and len(rows) >= len(adv['permits']['rows']) and differs(rows, adv['permits']['rows']):
            adv['permits']['rows'] = rows
            changed.append('permits(%d)' % len(rows))
    except Exception as e:
        print('permits skip:', e)
    try:
        before = json.dumps(adv['occupancy']['rows'], sort_keys=True)
        occ_ch = update_occupancy(adv)
        if occ_ch and json.dumps(adv['occupancy']['rows'], sort_keys=True) != before:
            changed += occ_ch
    except Exception as e:
        print('occupancy skip:', e)
    try:
        if ECOS_KEY:
            bub = fetch_bubble()
            if differs(bub, adv.get('bubble')):
                adv['bubble'] = bub
                changed.append('bubble(%s)' % bub['prd'])
        else:
            print('bubble skip: ECOS_API_KEY 없음')
    except Exception as e:
        print('bubble skip:', e)
    try:
        if DATAGO_KEY:
            lz = fetch_livezone()
            if lz['zones'] and differs(lz, adv.get('livezone')):
                adv['livezone'] = lz
                changed.append('livezone(%d)' % len(lz['zones']))
        else:
            print('livezone skip: DATA_GO_KR_KEY 없음')
    except Exception as e:
        print('livezone skip:', e)
    if changed:
        write_adv(adv)
    changed += update_basic()   # 기본통계(STATS) 증분 갱신
    # 후속 단계(뉴스레터 발송 등)에 변경 내역 전달 — 커밋 대상 아님
    io.open(os.path.join(ROOT, '.stats_changed'), 'w', encoding='utf-8').write(','.join(changed))
    if changed:
        print('updated:', ', '.join(changed))
    else:
        print('no changes')


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""심화통계 데이터 자동 갱신 (KOSIS OpenAPI).

index.html 안의 /*ADV_DATA_START*/ ... /*ADV_DATA_END*/ 블록을 최신 데이터로 교체한다.
GitHub Actions(.github/workflows/update-stats.yml)가 매달 실행한다.

사용:
  KOSIS_API_KEY=... python tools/update_adv_data.py --update      # 실제 갱신
  KOSIS_API_KEY=... python tools/update_adv_data.py --discover 주택규모별   # 표 ID 탐색
  python tools/update_adv_data.py --dry-run                        # 키 없이 재작성 로직만 검증

데이터셋 구성 (docs/advanced_stats_catalog.md 참조):
  permits  — 국토교통부 「주택건설실적통계」 주택규모별 인허가실적(월별 누계):
             6월·12월 누계에서 (계 − 40㎡이하)로 '40제외' 반기값 산출
  occupancy — 입주물량은 공공 API가 없어 자동 갱신 대상에서 제외(수동 시딩 유지)
  (월간 가격동향 섹션은 UI에서 제외되어 갱신 대상 아님 — 2026-07-11)
"""
import io, os, re, sys, json, time
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'index.html')
API = 'https://kosis.kr/openapi/Param/statisticsParameterData.do'
LIST_API = 'https://kosis.kr/openapi/statisticsList.do'
KEY = os.environ.get('KOSIS_API_KEY', '')
ECOS_KEY = os.environ.get('ECOS_API_KEY', '')   # 한국은행 ECOS (CD금리용, 없으면 금리만 건너뜀)

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
        'weeks': 12,           # 최근 12주 유지
    },
    'monthly': {               # 월간 아파트 가격지수 (부동산원 월간동향) — 전월비 변동률 계산
        'maega':  {'orgId': '408', 'tblId': 'DT_30404_B012'},   # 유형별 매매가격지수 (C1=유형, C2=지역)
        'jeonse': {'orgId': '408', 'tblId': 'DT_30404_B013'},   # 유형별 전세가격지수
        'months': 12,          # 최근 12개월 변동률 유지 (지수는 13개월 조회)
    },
}

WEEKLY_REGIONS = ['수도권','서울','경기','인천','부산','대구','광주','대전','세종','울산',
                  '강원','충북','충남','전북','전남','경북','경남','제주']

# ---- 기본통계(STATS) 월간 자동 갱신 --------------------------------------
# index.html의 /*STATS_DATA_START*/const STATS={...};/*STATS_DATA_END*/ 블록을
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


def http_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'aptweather-stats-bot'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


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


def fetch_permits():
    import datetime
    cfg = CONF['permits_size']
    now = datetime.date.today()
    rows_out = []
    for y in range(2007, now.year + 1):
        h1 = _fetch_period(cfg, '%d06' % y)
        time.sleep(0.15)
        v1 = [h1.get(r) for r in REG15]
        if any(v is not None for v in v1):
            rows_out.append({'p': '%dH1' % y, 'v': v1})
        cum = _fetch_period(cfg, '%d12' % y)
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


def fetch_weekly():
    w = CONF['weekly']
    ma, ma_se, ma_sg = _fetch_weekly_one(w['maega'], w['weeks'])
    time.sleep(0.2)
    je, je_se, je_sg = _fetch_weekly_one(w['jeonse'], w['weeks'])
    dates = sorted(set(ma) | set(je))[-w['weeks']:]
    rows = []
    for d in dates:
        rows.append({
            'p': '%s-%s-%s' % (d[:4], d[4:6], d[6:8]),
            'ma': [ma.get(d, {}).get(r) for r in WEEKLY_REGIONS],
            'je': [je.get(d, {}).get(r) for r in WEEKLY_REGIONS],
        })
    gus = _gu_regions(ma_se, je_se)
    se_rows = [{'p': '%s-%s-%s' % (d[:4], d[4:6], d[6:8]),
                'ma': [ma_se.get(d, {}).get(r) for r in gus],
                'je': [je_se.get(d, {}).get(r) for r in gus]} for d in dates]
    sg_rows = [{'p': '%s-%s-%s' % (d[:4], d[4:6], d[6:8]),
                'ma': [ma_sg.get(d, {}).get(c) for c in SGG_CODES],
                'je': [je_sg.get(d, {}).get(c) for c in SGG_CODES]} for d in dates]
    return {'regions': WEEKLY_REGIONS, 'rows': rows,
            'seoul': {'regions': gus, 'rows': se_rows},
            'sgg': {'codes': SGG_CODES, 'rows': sg_rows},
            'note': '주간 아파트 매매·전세가격지수 변동률(%) · 매주 발표'}


# ---- monthly: 월간 아파트 매매·전세 지수 → 전월비 변동률 ------------------
def _fetch_monthly_one(cfg, months):
    data = kosis({
        'orgId': cfg['orgId'], 'tblId': cfg['tblId'],
        'objL1': 'ALL', 'objL2': 'ALL', 'itmId': 'ALL', 'prdSe': 'M',
        'newEstPrdCnt': str(months + 1),
    })
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
    ma, ma_se, ma_sg = _fetch_monthly_one(m['maega'], m['months'])
    time.sleep(0.2)
    je, je_se, je_sg = _fetch_monthly_one(m['jeonse'], m['months'])
    rows = _idx_to_chg(ma, je, WEEKLY_REGIONS)[-m['months']:]
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


# ---- index.html 재작성 ----------------------------------------------------
START, END = '/*ADV_DATA_START*/', '/*ADV_DATA_END*/'
BSTART, BEND = '/*STATS_DATA_START*/', '/*STATS_DATA_END*/'

def read_current_stats():
    c = io.open(INDEX, encoding='utf-8').read()
    i, j = c.find(BSTART), c.find(BEND)
    assert i >= 0 and j > i, 'STATS 마커를 찾을 수 없음'
    blob = c[i + len(BSTART):j]
    m = re.match(r'const STATS=(.*);$', blob, re.S)
    return json.loads(m.group(1))


def write_stats(stats):
    c = io.open(INDEX, encoding='utf-8').read()
    i, j = c.find(BSTART), c.find(BEND)
    blob = 'const STATS=' + json.dumps(stats, ensure_ascii=False, separators=(',', ':')) + ';'
    io.open(INDEX, 'w', encoding='utf-8').write(c[:i + len(BSTART)] + blob + c[j:])


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
    c = io.open(INDEX, encoding='utf-8').read()
    i, j = c.find(START), c.find(END)
    assert i >= 0 and j > i, 'ADV 마커를 찾을 수 없음'
    blob = c[i + len(START):j]
    m = re.match(r'const ADV=(.*);$', blob, re.S)
    return c, i, j, json.loads(m.group(1))


def write_adv(adv):
    c, i, j, _ = read_current_adv()
    blob = 'const ADV=' + json.dumps(adv, ensure_ascii=False, separators=(',', ':')) + ';'
    c2 = c[:i + len(START)] + blob + c[j:]
    io.open(INDEX, 'w', encoding='utf-8').write(c2)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else '--dry-run'
    if arg == '--discover':
        discover(sys.argv[2])
        return
    _, _, _, adv = read_current_adv()
    if arg == '--dry-run':
        write_adv(adv)  # 동일 데이터 재기록 = 마커·직렬화 왕복 검증
        print('dry-run ok: permits %d rows, occupancy %d rows' % (
            len(adv['permits']['rows']), len(adv['occupancy']['rows'])))
        return
    assert arg == '--update', 'usage: --update | --dry-run | --discover <kw>'
    assert KEY, 'KOSIS_API_KEY 환경변수 필요'
    changed = []
    try:
        weekly = fetch_weekly()
        if weekly['rows']:
            adv['weekly'] = weekly
            changed.append('weekly(~%s)' % weekly['rows'][-1]['p'])
    except Exception as e:
        print('weekly skip:', e)
    try:
        monthly = fetch_monthly()
        if monthly['rows']:
            adv['monthly'] = monthly
            changed.append('monthly(~%s)' % monthly['rows'][-1]['p'])
    except Exception as e:
        print('monthly skip:', e)
    try:
        rows = fetch_permits()
        if rows and len(rows) >= len(adv['permits']['rows']):
            adv['permits']['rows'] = rows
            changed.append('permits(%d)' % len(rows))
    except Exception as e:
        print('permits skip:', e)
    if changed:
        write_adv(adv)
    changed += update_basic()   # 기본통계(STATS) 증분 갱신
    if changed:
        print('updated:', ', '.join(changed))
    else:
        print('no changes')


if __name__ == '__main__':
    main()

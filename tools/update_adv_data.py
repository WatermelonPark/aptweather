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
}

WEEKLY_REGIONS = ['수도권','서울','경기','인천','부산','대구','광주','대전','세종','울산',
                  '강원','충북','충남','전북','전남','경북','경남','제주']

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
def _fetch_weekly_one(cfg, weeks):
    data = kosis({
        'orgId': cfg['orgId'], 'tblId': cfg['tblId'],
        'objL1': 'ALL', 'itmId': 'ALL', 'prdSe': 'F',
        'newEstPrdCnt': str(weeks),
    })
    by = {}
    for row in data:
        reg = (row.get('C1_NM') or '').strip()
        if reg not in WEEKLY_REGIONS: continue
        try: v = float(row['DT'])
        except (TypeError, ValueError, KeyError): continue
        by.setdefault(row['PRD_DE'], {})[reg] = v
    return by


def fetch_weekly():
    w = CONF['weekly']
    ma = _fetch_weekly_one(w['maega'], w['weeks'])
    time.sleep(0.2)
    je = _fetch_weekly_one(w['jeonse'], w['weeks'])
    dates = sorted(set(ma) | set(je))[-w['weeks']:]
    rows = []
    for d in dates:
        rows.append({
            'p': '%s-%s-%s' % (d[:4], d[4:6], d[6:8]),
            'ma': [ma.get(d, {}).get(r) for r in WEEKLY_REGIONS],
            'je': [je.get(d, {}).get(r) for r in WEEKLY_REGIONS],
        })
    return {'regions': WEEKLY_REGIONS, 'rows': rows,
            'note': '주간 아파트 매매·전세가격지수 변동률(%) · 매주 발표'}


# ---- index.html 재작성 ----------------------------------------------------
START, END = '/*ADV_DATA_START*/', '/*ADV_DATA_END*/'

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
        rows = fetch_permits()
        if rows and len(rows) >= len(adv['permits']['rows']):
            adv['permits']['rows'] = rows
            changed.append('permits(%d)' % len(rows))
    except Exception as e:
        print('permits skip:', e)
    if changed:
        write_adv(adv)
        print('updated:', ', '.join(changed))
    else:
        print('no changes')


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""data.js에서 홈 화면이 실제로 쓰는 조각만 뽑아 data-core.js를 만든다.

배경: data.js 397KB를 모든 방문자가 매번 내려받는데, 홈이 실제로 쓰는 건
그중 일부다. 통계 탭을 열지 않는 방문자에게 주간 155주·기본통계 11계열을
보낼 이유가 없다.

전략은 '쪼개서 나눠 보내기'가 아니라 '핵심만 먼저 보내기'다.
  - data-core.js : 홈이 쓰는 것만. index.html이 즉시 로드.
  - data.js      : 그대로 둔다. 통계 탭을 열 때 fetch로 받아 core에 병합.
data.js를 손대지 않으므로 생활권 41장과 /cycle/은 아무 영향이 없다.

실행: python tools/split_data.py   (update_adv_data.py --update 뒤에)
"""
import io, json, os, re, sys

# 배치는 chcp 65001을 하지만 다른 경로로 불릴 수도 있다. 콘솔 인코딩 때문에
# 산출물을 다 만들고도 print에서 죽으면 배치가 exit 20으로 실패한다.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data.js')
OUT = os.path.join(ROOT, 'data-core.js')
REST = os.path.join(ROOT, 'data-rest.json')
TREND = os.path.join(ROOT, 'data-trend.json')
SGG = os.path.join(ROOT, 'data-sgg.json')
SIZE = os.path.join(ROOT, 'data-size.json')

# '규모별 동향'은 지표4×규모6 피벗이라 STATS 14계열 중 혼자 186KB(rest의 39%)다.
# 기본통계 세그먼트에서 그걸 실제로 누른 사람만 필요하므로 별도 지연 파일로 뺀다
# (2026-08-01: rest 408KB → 250KB). index.html ensureSizeStats()가 받아 채운다.
LAZY_STATS = ['규모별']
# 파일 → 그 파일이 싣는 계열. 감시(check_freshness)가 이걸로 조회 목록을 만든다 —
# 지연 파일이 늘면 여기만 늘리면 감시가 자동으로 따라온다(파일명 하드코딩 금지).
LAZY_FILES = {os.path.basename(SIZE): list(LAZY_STATS)}

# 시군구·서울구 전체 시계열은 '구를 실제로 고른 사람'만 필요하다. trend에 통째로
# 실으면 통계 탭을 여는 모든 방문자가 4배 큰 파일을 받는다(실측 91→418KB gzip).
# 그래서 최근 TREND_SGG_KEEP개만 trend에 남기고 전체는 data-sgg.json으로 뺀다.
TREND_SGG_KEEP = 12
NL = chr(10)

# 홈이 쓰는 STATS 계열.
# 준공·착공은 2026-08-06부터 core에 싣는다 — 공급·가격 통합표가 이 둘을 직접 그리고,
# 그게 홈의 주 컨텐츠다(합쳐 65KB). 대신 같은 날 permits의 HUB 파생분(done/sched/demol,
# 83KB)이 통째로 빠져 core는 오히려 가벼워졌다.
# ⚠️ 주택멸실·아파트멸실은 2026-08-07에 뺐다. 이중구현 미러가 사라지면서
# 브라우저 소비자가 0이 됐는데(index.html의 STATS['주택멸실']·['아파트멸실'] 참조
# 각 0건), 옛 주석이 '러닝재고가 직접 읽는다'고 적혀 있어 아무도 못 지웠다.
# 멸실은 이제 빌드 시점에 sido_zones가 data.js에서 읽어 점수에 녹인다.
# 기본통계 화면은 data-rest.json 사본을 쓰므로 손실 없다(동일 바이트 확인).
CORE_STATS = ['전세가율', '준공', '착공']

# 홈이 통째로 쓰는 ADV 키
CORE_ADV = ['sido', 'occupancy', 'permits', 'bubble', 'holidays']

# ⚠️ 거부목록이 아니라 **허용목록**이다. 예전엔 뺄 키를 나열했더니 새로 생긴 키가
# 아무도 안 막아준 채 홈 페이로드로 새어 나갔다 — permits.city(150KB)로 data-core가
# 131KB -> 311KB가 됐고(2026-08-05), 생활권 시대 잔재 meas·fwd_far는 그 뒤로도
# 계속 실려 나갔다(2026-08-07 감사). 홈이 실제로 읽는 건 ref 하나(index.html의
# `ADV.permits.ref[region]`)이고 나머지는 표기용이다. 여기 없는 키는 자동으로 빠진다.
KEEP_PERMITS = ('regions', 'ref', 'rows', 'note')

# 홈 통합표가 그리는 구간·지역. 적정물량 기준표와 같은 시작점(2017)이다.
TABLE_FROM = '2017.01'
TABLE_STATS = ('준공', '착공')
try:
    import sido_zones as _SZ
    TABLE_REGIONS = set(_SZ.ORDER)
except Exception:                     # 산식 모듈이 없어도 스플릿은 돌아야 한다
    TABLE_REGIONS = {'전국', '수도권', '지방', '서울', '경기', '인천', '부산', '대구', '광주',
                     '대전', '세종', '울산', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주'}


def _r2(a):
    """변동률 소수 2자리 — 원자료는 자리수가 들쭉날쭉해 그대로 실으면 30% 커진다."""
    return None if a is None else [None if v is None else round(v, 2) for v in a]


def main():
    src = io.open(SRC, encoding='utf-8').read()
    adv = json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S).group(1))
    stats = json.loads(re.search(r'const STATS\s*=\s*(\{.*?\});?\s*(?:/\*|const |$)', src, re.S).group(1))

    core_adv = {k: adv[k] for k in CORE_ADV if k in adv}

    def strip_units(a):
        """빌드 전용 키 제거. 단지 목록·시군 시계열은 지역 정적 페이지
        (make_zone_pages가 data.js를 직접 읽어 렌더) 전용이라 브라우저 페이로드가
        실어 나를 이유가 없다. 홈은 ADV.sido의 점수와 STATS 준공·착공만 쓴다."""
        a = dict(a)
        p = a.get('permits')
        if p:
            p = dict(p)
            p = {k: v for k, v in p.items() if k in KEEP_PERMITS}
            a['permits'] = p
        return a

    core_adv = strip_units(core_adv)

    # 히어로 배경 지도는 마지막 한 주만 쓴다(renderHeroMap: rows[rows.length-1]).
    # 전체 sgg는 59.7KB인데 그중 필요한 건 4.8KB뿐이다.
    w = adv.get('weekly') or {}
    sgg = w.get('sgg') or {}
    if sgg.get('rows'):
        # rows(시도 20곳 최신 1주)도 함께 싣는다 — 홈 주간 배너가 카드 격자를
        # 직접 그리는 입력이다(2026-08-17). 예전엔 그 자리에 1200×630 PNG를
        # 넣었는데 고정 비율이라 화면 폭이 좁으면 글자가 뭉갰다. 20개 지역 ×
        # 값 2개뿐이라 페이로드는 1KB 미만이고, 지연 로드로 미루면 첫 화면에
        # 빈 칸이 보였다가 채워진다.
        core_adv['weekly'] = {'regions': w.get('regions', []),
                              'rows': (w.get('rows') or [])[-1:],
                              'sgg': {'codes': sgg.get('codes', []), 'rows': sgg['rows'][-1:]}}

    # 홈 통합표가 쓰는 가격 변동률 — 매매·전세·월세만, 시도 20곳만.
    # 전체 monthly는 753.9KB(대부분 seoul 76.8 + sgg 617.1)라 통째로는 못 싣는다.
    # 통계 탭이 열리면 loadFullData가 전체로 덮어쓴다(상위 키 통째 교체라 안전).
    mo = adv.get('monthly') or {}
    if mo.get('rows'):
        core_adv['monthly'] = {
            'regions': mo.get('regions', []),
            'rows': [{'p': r['p'],
                      'ma': _r2(r.get('ma')), 'je': _r2(r.get('je')), 'wo': _r2(r.get('wo'))}
                     # ⚠️ monthly는 '2017-01', STATS는 '2017.01'로 구분자가 다르다.
                     # 그대로 비교하면 '-'(0x2D) < '.'(0x2E)라 2017년이 통째로 잘린다.
                     for r in mo['rows'] if r['p'].replace('-', '.') >= TABLE_FROM],
            'note': mo.get('note', ''),
        }

    core_stats = {k: stats[k] for k in CORE_STATS if k in stats}
    missing = [k for k in CORE_STATS if k not in stats]
    assert not missing, '홈이 쓰는 STATS 계열이 없다: %s' % missing
    # 준공·착공은 표가 그리는 구간(TABLE_FROM~)만, 표에 나오는 지역만 싣는다.
    # 전 구간 22개 지역이면 65KB인데 이렇게 자르면 절반 아래다. 점수(ADV.sido)는
    # 이미 계산돼 있으므로 홈이 옛 구간을 다시 읽을 일이 없다.
    for k in TABLE_STATS:
        s = core_stats.get(k)
        if not s:
            continue
        keep = [i for i, d in enumerate(s['dates']) if d >= TABLE_FROM]
        core_stats[k] = {
            'unit': s.get('unit'), 'source': s.get('source'),
            'dates': [s['dates'][i] for i in keep],
            'series': {r: [v[i] for i in keep] for r, v in s['series'].items() if r in TABLE_REGIONS},
        }

    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(',', ':'))
    body = (
        '/* 자동 생성 — tools/split_data.py. 직접 고치지 말 것.\n'
        '   홈 화면이 쓰는 조각만 담는다. 통계 탭을 열면 loadFullData()가\n'
        '   data-rest.json을 받아 이 전역에 Object.assign으로 채운다. */\n'
        'const ADV=%s;\n'
        'const STATS=%s;\n'
        'window.__DATA_CORE__=true;\n' % (dump(core_adv), dump(core_stats)))
    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(body)

    # 나머지는 JSON으로 따로 낸다. 런타임에 data.js를 정규식으로 파싱하는 방식은
    # 선언 형태가 조금만 바뀌어도 조용히 깨지므로 쓰지 않는다.
    # 통계 탭에서 먼저 보이는 건 그래프(주간·월간)다. 기본통계 11계열(rest)도
    # 탭 진입 시 이어서 받지만, 그래프가 rest 크기를 기다리지 않도록 둘로 쪼갠다.
    trend_adv = strip_units(adv)
    sgg_full = {}
    for k in ('weekly', 'monthly'):
        w = trend_adv.get(k)
        if not w:
            continue
        w = dict(w)
        keep = {}
        for part in ('sgg', 'seoul'):
            sec = w.get(part)
            if sec and sec.get('rows') and len(sec['rows']) > TREND_SGG_KEEP:
                keep[part] = sec                      # 전체는 지연 로드 파일로
                w[part] = dict(sec, rows=sec['rows'][-TREND_SGG_KEEP:])
        if keep:
            sgg_full[k] = keep
        trend_adv[k] = w
    io.open(TREND, 'w', encoding='utf-8', newline=NL).write(
        dump({'ADV': trend_adv}))
    io.open(SGG, 'w', encoding='utf-8', newline=NL).write(dump({'ADV': sgg_full}))
    # rest에 ADV를 또 담으면 trend와 중복돼 총 전송량이 오히려 는다(399→629KB).
    # rest는 기본통계 계열만 담는다 — ADV는 trend가 이미 실어 보냈다.
    lazy_stats = {k: stats[k] for k in LAZY_STATS if k in stats}
    rest_stats = {k: v for k, v in stats.items() if k not in lazy_stats}
    io.open(REST, 'w', encoding='utf-8', newline='\n').write(dump({'STATS': rest_stats}))
    io.open(SIZE, 'w', encoding='utf-8', newline=NL).write(dump({'STATS': lazy_stats}))

    full = len(src)
    rest = os.path.getsize(REST)
    print('data.js        %7.1f KB  (그대로 유지 — 다른 소비자 보호)' % (full / 1024))
    print('data-core.js   %7.1f KB  (홈 즉시 로드, %.0f%% 절감)'
          % (len(body) / 1024, 100 * (1 - len(body) / full)))
    print('data-trend.json%7.1f KB  (그래프 — 통계 탭 진입 시)' % (os.path.getsize(TREND) / 1024))
    print('data-rest.json %7.1f KB  (기본통계 — 세그먼트 누를 때)' % (rest / 1024))
    print('data-sgg.json  %7.1f KB  (시군구 시계열 — 구를 고를 때만)' % (os.path.getsize(SGG) / 1024))
    print('  core ADV   :', ', '.join(core_adv))
    print('  core STATS :', ', '.join(core_stats))


if __name__ == '__main__':
    main()

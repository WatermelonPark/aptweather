# -*- coding: utf-8 -*-
"""SGG_RONE_CLS(KOSIS SGG 코드 → R-ONE CLS_ID) 재생성·검증.

update_adv_data.SGG_RONE_CLS는 월간 시군구 시세를 R-ONE에서 받기 위한 매핑인데,
예전 주석이 존재하지 않는 `tools/scratchpad gen_map2.py`를 가리켜 부동산원이 표를
재구조화하면 재생성 방법이 없었다(2026-08-01 병렬 세션 인수인계 ①). 이 스크립트가
그 절차다 — 저장소 안의 자료만으로 전부 복원된다.

재료
  · KOSIS 코드 목록      : update_adv_data.SGG_CODES (index.html NATION_TILE과 동일 집합)
  · KOSIS 코드 → 지역명  : index.html SGG_QNAME (예: 'a80703' → '양주')
  · R-ONE CLS_ID → 지역명: R-ONE 월간 매매지수표(A_2024_00045) 최신월 행의
                           CLS_ID / CLS_NM / CLS_FULLNM

매칭 규칙
  R-ONE CLS_NM은 '양주시'처럼 접미사가 붙고 SGG_QNAME은 '양주'라 접미사(시/군/구)를
  떼고 맞춘다. 이름이 겹치는 구(중구·동구 등)는 CLS_FULLNM의 시도 접두로 가른다 —
  KOSIS 코드의 시도 접두(a7=서울, a8=경기, b1=부산 …)를 SIDO_PREFIX로 대조한다.

사용
  python tools/gen_sgg_rone_map.py            # 현재 매핑과 대조만(변경 없음)
  python tools/gen_sgg_rone_map.py --write    # tools/data/sgg_rone_cls.json으로 저장
"""
import io, json, os, re, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update_adv_data as U

API = 'https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do'
TBL = 'A_2024_00045'          # (월) 매매가격지수_아파트 — 시도·권역·시군구가 다 있다
OUT = os.path.join(HERE, 'data', 'sgg_rone_cls.json')

# KOSIS SGG 코드의 시도 접두 → R-ONE CLS_FULLNM의 시도 토큰
SIDO_PREFIX = {
    'a7': '서울', 'a8': '경기', 'a9': '인천', 'b1': '부산', 'b2': '대구',
    'b3': '광주', 'b4': '대전', 'b5': '울산', 'b6': '세종',
    'c1': '강원', 'c2': '충북', 'c3': '충남', 'c4': '전북', 'c5': '전남',
    'c6': '경북', 'c7': '경남', 'c8': '제주',
}
SUFFIX = re.compile(r'(특별자치시|특별자치도|광역시|특별시|시|군|구)$')


def _key():
    k = os.environ.get('RONE_API_KEY', '')
    if k:
        return k
    p = os.path.expanduser('~/.aptweather_keys.bat')
    if os.path.exists(p):
        for ln in io.open(p, encoding='utf-8', errors='ignore'):
            m = re.search(r'RONE_API_KEY=(\S+)', ln)
            if m:
                return m.group(1).strip()
    raise SystemExit('RONE_API_KEY 필요 (환경변수 또는 ~/.aptweather_keys.bat)')


def qname_map():
    """index.html SGG_QNAME — KOSIS 코드 → 표시용 지역명(접미사 없는 형태)."""
    h = io.open(os.path.join(HERE, os.pardir, 'index.html'), encoding='utf-8').read()
    m = re.search(r'SGG_QNAME\s*=\s*(\{.*?\})\s*;', h, re.S)
    if not m:
        raise SystemExit('index.html에서 SGG_QNAME을 찾지 못했다 — 구조가 바뀌었는지 확인할 것')
    return json.loads(m.group(1).replace("'", '"'))


def rone_regions(key):
    """R-ONE 최신월 행 → [(CLS_ID, 시도토큰, 이름토큰들)]."""
    base = {'KEY': key, 'Type': 'json', 'STATBL_ID': TBL, 'DTACYCLE_CD': 'MM'}
    d = _get(API + '?' + urllib.parse.urlencode(dict(base, pIndex=1, pSize=1)))
    k = list(d.keys())[0]
    total = d[k][0]['head'][0]['list_total_count']
    last = (total + 999) // 1000
    d = _get(API + '?' + urllib.parse.urlencode(dict(base, pIndex=last, pSize=1000)))
    rows = d[list(d.keys())[0]][1].get('row') or []
    mx = max(r['WRTTIME_IDTFR_ID'] for r in rows)
    out = []
    for r in rows:
        if r['WRTTIME_IDTFR_ID'] != mx:
            continue
        full = (r.get('CLS_FULLNM') or '').strip()
        parts = [p.strip() for p in full.split('>') if p.strip()]
        nm = (r.get('CLS_NM') or (parts[-1] if parts else '')).strip()
        out.append((int(r['CLS_ID']), parts[0] if parts else '', parts, nm))
    return out


def _get(url, tries=3):
    import time
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def strip_sfx(s):
    return SUFFIX.sub('', s) or s


def build():
    key = _key()
    qn = qname_map()
    regions = rone_regions(key)
    # (시도토큰, 이름토큰) -> CLS_ID. 같은 이름이 여러 depth에 있으면 더 깊은 쪽(구)을 우선.
    idx = {}
    for cid, sido, parts, nm in regions:
        k = (sido, strip_sfx(nm))
        if k not in idx or len(parts) > idx[k][1]:
            idx[k] = (cid, len(parts))
    # 전국·시도 레벨: SGG_QNAME(타일 표시용)엔 없고 R-ONE 최상위 depth에 있다.
    # ⚠️ 시도명엔 strip_sfx를 쓰지 않는다 — '대구'가 '대'로 잘린다(접미사 정규식이
    # 끝의 '구'를 시군구 접미사로 본다). R-ONE 최상위 이름은 이미 정규형이다.
    top = {}
    for cid, sido, parts, nm in regions:
        if len(parts) == 1:
            top[parts[0]] = cid
    # 분구 도시 본체(a80102 안양 등): SGG_QNAME엔 '안양 동안구'처럼 구 단위만 있어
    # 시 레벨 이름이 없다. 같은 접두를 공유하는 하위 코드들의 시 이름에서 되찾는다
    # (예: a801021 '안양 만안구' → 시 이름 '안양').
    # 부모 코드 자릿수가 지역마다 달라(경기 a801021→a80102, 충북 c20101→c201)
    # 고정 슬라이스는 못 쓴다. SGG_CODES에 실재하는 모든 접두를 후보로 등록한다.
    codeset = set(U.SGG_CODES)
    city_of = {}
    for c, n in qn.items():
        if ' ' not in n:
            continue
        city = strip_sfx(n.split(' ')[0])
        for L in range(len(c) - 1, 1, -1):
            pre = c[:L]
            if pre in codeset:
                city_of.setdefault(pre, city)
                break

    out, miss = {}, []
    for code in U.SGG_CODES:
        sido = SIDO_PREFIX.get(code[:2])
        # ① 전국
        if code == 'a0':
            if '전국' in top:
                out[code] = top['전국']
            else:
                miss.append((code, '전국', 'R-ONE 최상위에 전국 없음'))
            continue
        # ② 시도 자체(a7, b1 …)
        if sido and code == code[:2]:
            if sido in top:
                out[code] = top[sido]
            else:
                miss.append((code, sido, 'R-ONE 시도 레벨 없음'))
            continue
        nm = qn.get(code) or city_of.get(code)
        if not sido or not nm:
            miss.append((code, nm or '(이름없음)', '접두/이름 없음'))
            continue
        # SGG_QNAME이 '고양 덕양구'처럼 시+구 형태면 마지막 토큰이 R-ONE 이름
        leaf = strip_sfx(nm.split(' ')[-1])
        hit = idx.get((sido, leaf))
        if hit:
            out[code] = hit[0]
        else:
            # 현재 매핑에도 없으면 R-ONE 미수록(신설 행정구역 등) — 결함이 아니다.
            why = ('R-ONE 미수록(신설·개편 등)' if code not in U.SGG_RONE_CLS
                   else '%s에서 %s 못 찾음' % (sido, leaf))
            miss.append((code, nm, why))

    # 폴백 — 천안(c301)·전주(c401)는 구 코드가 자식이 아니라 '형제'라(c302/c303이
    # c301의 하위가 아님) 접두 규칙으로 시 이름을 못 얻는다. 경기·충북은 자식 구조라
    # 위에서 해결된다. KOSIS 코드 체계가 시도별로 다른 탓이므로, 남은 코드와 남은
    # R-ONE 시 레벨 항목이 그 시도에서 **정확히 1:1일 때만** 짝짓는다(모호하면 포기).
    used = set(out.values())
    unnamed = [(c, SIDO_PREFIX.get(c[:2])) for c, n, why in miss if why == '접두/이름 없음']
    # qn에 '<시> <구>' 형태로 등장하는 분구 도시 이름(시도별)
    split_cities = {}
    for c, n in qn.items():
        if ' ' in n:
            split_cities.setdefault(SIDO_PREFIX.get(c[:2]), set()).add(strip_sfx(n.split(' ')[0]))
    for sido in {sd for _, sd in unnamed if sd}:
        codes = [c for c, sd in unnamed if sd == sido]
        cands = [(cid, nm) for (sd, nm), (cid, _d) in
                 ((k, v) for k, v in idx.items() if k[0] == sido)
                 if cid not in used and nm in (split_cities.get(sido) or set())]
        if len(codes) == 1 and len(cands) == 1:
            out[codes[0]] = cands[0][0]
            miss = [m for m in miss if m[0] != codes[0]]
    return out, miss


def main():
    built, miss = build()
    cur = U.SGG_RONE_CLS
    same = sum(1 for k, v in built.items() if cur.get(k) == v)
    diff = {k: (cur.get(k), v) for k, v in built.items() if k in cur and cur[k] != v}
    only_cur = sorted(set(cur) - set(built))
    only_new = sorted(set(built) - set(cur))
    print('재생성 %d개 · 현재 %d개' % (len(built), len(cur)))
    print('  일치 %d · 불일치 %d · 현재에만 %d · 신규 %d'
          % (same, len(diff), len(only_cur), len(only_new)))
    if diff:
        print('  불일치(코드: 현재→재생성):')
        for k, (a, b) in sorted(diff.items())[:20]:
            print('    %-10s %s -> %s' % (k, a, b))
    if only_cur:
        print('  현재에만 있음(재생성이 못 찾음):', ', '.join(only_cur[:20]))
    if miss:
        print('  매칭 실패 %d건:' % len(miss))
        for c, n, why in miss[:15]:
            print('    %-10s %-12s %s' % (c, n, why))
    if '--write' in sys.argv:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump(built, io.open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        print('saved', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())

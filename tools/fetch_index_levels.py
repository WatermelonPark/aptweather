# -*- coding: utf-8 -*-
"""R-ONE 월간 아파트 매매지수(A_2024_00045) '레벨' 전체 이력 수집 -> 캐시.

기존 update_adv_data.fetch_monthly_rone()은 같은 표를 받아 전월비 변동률로
바꿔 버려서 지수 절대값(레벨)이 남지 않는다. 생활권별 저점(가격 사이클 바닥)을
찾으려면 레벨이 필요해서 별도로 전량(2003-11~)을 받아 캐시한다.
"""
import io, json, os, re, sys, time, urllib.parse, urllib.request

API = 'https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do'
TBL = {'maega': 'A_2024_00045', 'jeonse': 'A_2024_00050'}
OUT = os.path.join(os.path.dirname(__file__), 'cache', 'index_levels.json')


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
    raise SystemExit('RONE_API_KEY 필요')


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def fetch_levels(tbl, key):
    base = {'KEY': key, 'Type': 'json', 'STATBL_ID': tbl, 'DTACYCLE_CD': 'MM'}
    d = _get(API + '?' + urllib.parse.urlencode(dict(base, pIndex=1, pSize=1)))
    k = list(d.keys())[0]
    total = d[k][0]['head'][0]['list_total_count']
    pages = (total + 999) // 1000
    # region -> {'YYYY-MM': level}
    out, names = {}, {}
    seen = 0
    for p in range(1, pages + 1):
        d = _get(API + '?' + urllib.parse.urlencode(dict(base, pIndex=p, pSize=1000)))
        rows = d[list(d.keys())[0]][1].get('row') or []
        for r in rows:
            cid = str(r.get('CLS_ID') or '')
            tid = (r.get('WRTTIME_IDTFR_ID') or '').strip()
            if not cid or len(tid) != 6 or not tid.isdigit():
                continue
            try:
                v = float(r['DTA_VAL'])
            except (TypeError, ValueError, KeyError):
                continue
            out.setdefault(cid, {})[tid[:4] + '-' + tid[4:6]] = v
            names[cid] = (r.get('CLS_FULLNM') or r.get('CLS_NM') or '').strip()
        seen += len(rows)
        sys.stderr.write('\r  %s page %d/%d rows=%d' % (tbl, p, pages, seen))
        sys.stderr.flush()
        time.sleep(0.15)
    sys.stderr.write('\n')
    return {'total': total, 'names': names, 'levels': out}


def main():
    key = _key()
    res = {}
    for name, tbl in TBL.items():
        print('fetch %s (%s)' % (name, tbl))
        res[name] = fetch_levels(tbl, key)
        print('  regions=%d' % len(res[name]['levels']))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False)
    print('saved %s (%.1f MB)' % (OUT, os.path.getsize(OUT) / 1e6))


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""안분 기준 비교 — 인구(현행) vs 주민등록 세대수.

적정물량(수요)만 시도값을 존으로 안분한다(공급 3종은 HUB 시군구 실측이라 안분 없음).
현행 잣대는 인구(KOSIS DT_1B040A3/T20). 아파트 수요는 사람 수보다 '가구 수'에 가깝고
1인가구 증가를 반영하지 못하므로, 세대수(DT_1B040B3/T1)로 바꿔볼 가치가 있다.

⚠️ 잣대는 반드시 **공급과 독립**이어야 한다. 2026-07-31에 'HUB 누적준공(재고) 비중으로
안분'을 시험했다가 예측력이 0.142 -> 0.084로 무너졌다 — 많이 지은 존에 수요도 크게
배정돼 존 간 과잉/부족 차이(=신호 그 자체)가 지워지는 내생성 때문이다. 세대수는 인구와
마찬가지로 공급과 독립이라 이 함정이 없다.

실행: python tools/zone_share_basis.py
"""
import io, os, re, sys, json, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update_adv_data as U

API = 'https://kosis.kr/openapi/Param/statisticsParameterData.do'
HH_TBL, HH_ITM = 'DT_1B040B3', 'T1'      # 행정구역(시군구)별 주민등록세대수
POP_TBL, POP_ITM = 'DT_1B040A3', 'T20'   # 행정구역(시군구)별 총인구수 (현행)


def _key():
    k = os.environ.get('KOSIS_API_KEY', '')
    if k:
        return k
    p = os.path.expanduser('~/.aptweather_keys.bat')
    for ln in io.open(p, encoding='utf-8', errors='ignore'):
        m = re.search(r'KOSIS_API_KEY=(\S+)', ln)
        if m:
            return m.group(1).strip()
    raise SystemExit('KOSIS_API_KEY 필요')


def fetch_region(tbl, itm, key):
    """update_adv_data._lz_pop()과 동일한 파싱 규칙 — (sido, sgg) 두 딕셔너리.
    광역시 소속 구는 시도 단위로 처리하므로 sgg에 넣지 않는다."""
    url = API + '?' + urllib.parse.urlencode(dict(
        method='getList', apiKey=key, format='json', jsonVD='Y',
        orgId='101', tblId=tbl, objL1='ALL', itmId=itm, prdSe='M', newEstPrdCnt='1'))
    with urllib.request.urlopen(url, timeout=90) as r:
        rows = json.loads(r.read().decode('utf-8'))
    sido, sgg, cur = {}, {}, None
    for r in rows:
        nm = (r.get('C1_NM') or '').strip()
        try:
            v = int(r.get('DT') or 0)
        except (TypeError, ValueError):
            continue
        if nm in U.LZ_SIDO_FULL:
            cur = U.LZ_SIDO_FULL[nm]
            sido[cur] = v
            continue
        if nm == '전국' or cur is None or cur in U.LZ_GWANG or nm.endswith('구'):
            continue
        sgg[(cur, nm)] = v
    return sido, sgg


def zone_value(z, sido, sgg):
    """fetch_livezone.zone_pop()과 동일 규칙으로 존 단위 합산."""
    if z in U.LIVEZONE:
        return sum(sido.get(m[0], 0) if m[1] == '*' else sgg.get(m, 0) for m in U.LIVEZONE[z])
    nm = z[:-1]
    if nm.startswith('경기'):
        nm = nm[2:]
    return sum(sgg.get(('경기', nm + s), 0) for s in ('시', '군'))


def zone_table(zones, key):
    """존 -> {'pop':…, 'hh':…} + 시도 총계. 존이 속한 시도(psido)는 호출측이 준다."""
    p_sido, p_sgg = fetch_region(POP_TBL, POP_ITM, key)
    h_sido, h_sgg = fetch_region(HH_TBL, HH_ITM, key)
    # '수도권'은 KOSIS에 없는 합성 시도 — 서울+인천+경기로 만든다(sidopop과 동일 취급)
    for d in (p_sido, h_sido):
        d['수도권'] = d.get('서울', 0) + d.get('인천', 0) + d.get('경기', 0)
    out = {}
    for z in zones:
        out[z] = {'pop': zone_value(z, p_sido, p_sgg), 'hh': zone_value(z, h_sido, h_sgg)}
    return out, p_sido, h_sido


def main():
    key = _key()
    src = io.open(os.path.join(HERE, os.pardir, 'data.js'), encoding='utf-8').read()
    adv = json.loads(re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});\s*/\*ADV_DATA_END\*/',
                               src, re.S).group(1))
    zones = [z['z'] for z in adv['livezone']['zones']]
    cur_pop = {z['z']: z['pop'] for z in adv['livezone']['zones']}
    tbl, p_sido, h_sido = zone_table(zones, key)
    bad = [z for z in zones if not tbl[z]['hh'] or not tbl[z]['pop']]
    print('존 %d개 · 세대수 결측 %d개 %s' % (len(zones), len(bad), bad or ''))
    print('%-10s %12s %12s %10s %8s' % ('생활권', '인구(현행)', '인구(재산출)', '세대수', '세대당인구'))
    for z in zones[:6]:
        t = tbl[z]
        print('%-10s %12s %12s %10s %8.2f' % (
            z, format(cur_pop[z], ','), format(t['pop'], ','), format(t['hh'], ','),
            t['pop'] / t['hh'] if t['hh'] else 0))
    mism = [z for z in zones if abs(tbl[z]['pop'] - cur_pop[z]) > max(2000, cur_pop[z] * 0.02)]
    print('\n인구 재산출이 data.js와 어긋난 존: %d개 %s' % (len(mism), mism[:6]))
    json.dump({'zones': tbl, 'sido_pop': p_sido, 'sido_hh': h_sido},
              io.open(os.path.join(HERE, 'cache', 'zone_share_basis.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    print('saved tools/cache/zone_share_basis.json')


if __name__ == '__main__':
    main()

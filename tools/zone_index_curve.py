# -*- coding: utf-8 -*-
"""생활권별 아파트 매매지수 곡선 + 저점(사이클 바닥) 산출.

배경: 지금 적정물량(수요)은 기준표이 시도 단위로만 주기 때문에 생활권으로 안분해
쓰고 있다(공급은 HUB 시군구 실측이라 안분 없음). 기준표 모형은 "재고 소진 후
~1년 뒤 가격 상승"이므로, 생활권별 가격 저점을 알면 거꾸로 그 시점의 적정물량을
역산할 수 있다 -> 안분 제거. 이 스크립트는 그 1단계(곡선·저점 산출)다.

입력: tools/cache/index_levels.json (fetch_index_levels.py)
      tools/data/hub_permits.json  (가중치: 시군구 누적 준공 세대 = 아파트 재고 proxy)
출력: tools/cache/zone_index.json
"""
import io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update_adv_data as U   # LIVEZONE / _load_bdong_map / _hub_zone_map

CACHE = os.path.join(HERE, 'cache', 'index_levels.json')
HUB = os.path.join(HERE, 'data', 'hub_permits.json')
OUT_JSON = os.path.join(HERE, 'cache', 'zone_index.json')

WIN = 12             # 저점 판정 창(+-개월)
MIN_DRAWDOWN = 3.0   # 직전 고점 대비 최소 하락률(%) — 잔물결을 저점으로 세지 않기 위함


def build_name_index():
    """(시도약칭, 시군구풀네임) -> (생활권, 시군구코드). _hub_zone_map과 같은 규칙."""
    bdong = U._load_bdong_map()
    z_of = U._hub_zone_map(bdong)
    idx = {}
    for cd, (sido_full, nm) in bdong.items():
        z = z_of.get(cd)
        sd = U.LZ_SIDO_FULL.get(sido_full)
        if not z or not sd:
            continue
        idx.setdefault((sd, nm), (z, cd))          # '성남시 분당구'
        idx.setdefault((sd, nm.split(' ')[0]), (z, cd))   # '성남시'
    return idx


def hub_weight():
    """시군구코드 -> 누적 준공 세대(아파트 재고 proxy)."""
    hp = json.load(io.open(HUB, encoding='utf-8'))
    return {cd: sum((v.get('done_q') or {}).values()) for cd, v in hp['sgg'].items()}


def published_zones():
    """data.js에 실제로 실린 생활권만(인구 20만 미만은 애초에 존이 아니다)."""
    t = io.open(os.path.join(HERE, os.pardir, 'data.js'), encoding='utf-8').read()
    adv = json.loads(re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});\s*/\*ADV_DATA_END\*/',
                               t, re.S).group(1))
    return set(z['z'] for z in adv['livezone']['zones'])


def resolve(full, idx):
    """R-ONE CLS_FULLNM -> (zone, cd, base시군구명, depth) 또는 None.

    R-ONE 계층은 시도별로 깊이가 다르다:
      '서울>종로구'                      (2)
      '충남>천안시>동남구'               (3)
      '경기>경부1권>과천시'              (3, 중간에 권역)
      '경기>경부1권>성남시>분당구'       (4, 권역 + 분구)
      '부산>중부산권>중구'               (3, 권역)
    그래서 parts[1]을 시군구로 가정하면 경기가 통째로 날아간다. 대신 뒤에서부터
    '부모 자식'(='성남시 분당구') -> '자식' 순으로 bdong 이름에 맞춰본다.
    """
    parts = [p.strip() for p in (full or '').split('>') if p.strip()]
    if len(parts) < 2:
        return None                                  # 전국/시도 단독
    sd = parts[0]
    cands = []
    if len(parts) >= 3:
        cands.append(parts[-2] + ' ' + parts[-1])    # '성남시 분당구', '천안시 동남구'
    cands.append(parts[-1])                          # '과천시', '중구'
    for c in cands:
        hit = idx.get((sd, c))
        if hit:
            z, cd = hit
            return z, cd, c.split(' ')[0], len(parts)
    return None


def find_troughs(months, vals, win=WIN, min_dd=MIN_DRAWDOWN):
    """중심 +-win개월에서 최소인 점 중, 직전 고점 대비 min_dd% 이상 빠진 것만 저점으로.

    끝에서 win개월 안쪽은 '앞으로 더 내려갈지'를 알 수 없으므로 저점으로 확정하지
    않고 unconf=True로 표시만 한다(확정 저점과 섞으면 역산 기준이 오염된다).
    """
    n = len(vals)
    out = []
    for i in range(n):
        lo, hi = max(0, i - win), min(n, i + win + 1)
        if any(vals[j] < vals[i] for j in range(lo, hi)):
            continue
        peak = max(vals[:i + 1])
        dd = (peak - vals[i]) / peak * 100 if peak else 0
        if dd < min_dd:
            continue
        rec = {'m': months[i], 'v': round(vals[i], 2), 'dd': round(dd, 1),
               'unconf': i >= n - win}
        if out and months.index(out[-1]['m']) > i - win:   # 인접 중복 제거
            if vals[i] < out[-1]['v']:
                out[-1] = rec
            continue
        out.append(rec)
    return out


def analyse(blk, idx, wmap, keep):
    levels, names = blk['levels'], blk['names']
    by_base, unmatched = {}, []
    for cid, full in names.items():
        r = resolve(full, idx)
        if not r:
            unmatched.append(full)
            continue
        z, cd, base, depth = r
        if z not in keep:
            unmatched.append(full)
            continue
        # 같은 시군구가 부모('경기>고양시')와 자식('...>고양시>덕양구')으로 둘 다
        # 실리는 경우가 있어, base 단위로 모아 가장 깊은 층만 남긴다(중복 가중 방지).
        by_base.setdefault((z, base), []).append((depth, cid, full, cd))

    zone_members = {}
    for (z, base), lst in by_base.items():
        deepest = max(d for d, _, _, _ in lst)
        kids = [(cid, full, cd) for d, cid, full, cd in lst if d == deepest]
        # 분구 도시는 HUB가 시 단위(44130 천안시)로만 수집돼 구 코드(44131) 가중치가
        # 0이다. 그대로 두면 '무가중=1'이 돼서 같은 존의 단일시(아산시 85,201)에
        # 완전히 눌린다 — 부모 시 물량을 형제 구 수로 나눠 승계한다.
        parent_cd = None
        for _, _, _, cd in lst:
            if wmap.get(cd):
                parent_cd = cd
                break
        pw = 0
        if not any(wmap.get(cd) for _, _, cd in kids):
            for d, cid, full, cd in lst:
                pw = max(pw, wmap.get(cd, 0))
            if not pw:
                # base 이름 자체(=시)의 코드로 한 번 더
                hit = idx.get((full.split('>')[0], base)) if lst else None
                if hit:
                    pw = wmap.get(hit[1], 0)
        for cid, full, cd in kids:
            w = wmap.get(cd, 0) or (pw / len(kids) if pw else 0)
            zone_members.setdefault(z, []).append((cid, full, cd, w))

    zones = {}
    for z, mem in sorted(zone_members.items()):
        allm = sorted(set(m for cid, _, _, _ in mem for m in levels[cid]))
        months, vals = [], []
        for m in allm:
            num = den = 0.0
            for cid, full, cd, w in mem:
                v = levels[cid].get(m)
                if v is None:
                    continue
                w = float(w) or 1.0
                num += v * w
                den += w
            if den:
                months.append(m)
                vals.append(num / den)
        zones[z] = {
            'months': months,
            'vals': [round(v, 3) for v in vals],
            'members': [{'nm': f, 'cd': cd, 'w': int(w), 'n': len(levels[cid])}
                        for cid, f, cd, w in sorted(mem, key=lambda x: -x[3])],
            'troughs': find_troughs(months, vals),
        }
    return {'zones': zones, 'unmatched': sorted(set(unmatched))}


def main():
    src = json.load(io.open(CACHE, encoding='utf-8'))
    idx = build_name_index()
    wmap = hub_weight()
    keep = published_zones()
    report = {k: analyse(src[k], idx, wmap, keep) for k in ('maega', 'jeonse') if k in src}
    json.dump(report, io.open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False)
    got = set(report['maega']['zones'])
    print('zones matched: %d / %d' % (len(got), len(keep)))
    if keep - got:
        print('  MISSING:', sorted(keep - got))
    print('saved', OUT_JSON)
    return report


if __name__ == '__main__':
    main()

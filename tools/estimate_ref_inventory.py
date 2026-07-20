# -*- coding: utf-8 -*-
"""적정물량 최종 산출 — 재고 모형 · 시도 + 생활권 · 사이트 척도 환산.

모형(신쌤 강의 원문):
  "하락장은 누적 공급량을 소진시키는 장, 상승장은 쌓아가는 장"
  "입주 물량이 끊어져도 바로 안 뛴다. 누적된 게 어느 정도 소진돼야 상승이 발생"
  "누적된 게 소진되는 기간을 잡아줘야 돼. 보통 1년을 잡는다"

  재고 I(t) = max(0, I(t-1) + 공급 - 적정)
  재고가 0으로 소진된 뒤 **1년(4분기)** 지나면 상승 전환 → 이 시점이 실제 저점과
  가장 잘 맞는 적정물량 X를 찾는다. 지연은 강의 근거로 4분기 고정한다.
"""
import io, os, json, re, statistics, collections

SC = r'C:\Users\shpar\AppData\Local\Temp\claude\C--Users-shpar-OneDrive----Claude\6daa8fa3-db54-41a3-bab0-72d67ac03f73\scratchpad'
ROOT = r'C:\Users\shpar\OneDrive\문서\Claude\aptweather'
LAG = 4          # 강의: 소진 후 약 1년
TOL = 3          # 예측-실제 허용 오차(분기)

EXCL = set(json.load(io.open(os.path.join(SC, 'rate_shock.json'), encoding='utf-8'))['excl_quarters'])
kapt = json.load(io.open(os.path.join(SC, 'kapt.json'), encoding='utf-8'))
cache = json.load(io.open(os.path.join(SC, 'trade_raw.json'), encoding='utf-8'))
lawd = json.load(io.open(os.path.join(SC, 'lawd.json'), encoding='utf-8'))
import sys
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import update_adv_data as U

SD = {'서울특별시': '수도권', '인천광역시': '수도권', '경기도': '수도권',
      '부산광역시': '부산', '대구광역시': '대구', '광주광역시': '광주',
      '대전광역시': '대전', '울산광역시': '울산', '세종특별자치시': '세종',
      '강원특별자치도': '강원', '충청북도': '충북', '충청남도': '충남',
      '전북특별자치도': '전북', '경상북도': '경북', '경상남도': '경남',
      '제주특별자치도': '제주'}
GGU = {'동구', '서구', '남구', '북구', '광산구'}
SPLIT = ['고양', '부천', '성남', '수원', '안산', '안양', '용인', '화성',
         '천안', '청주', '전주', '포항', '창원']
GG_ALL = {'동구', '서구', '남구', '북구', '광산구', '중구', '유성구', '대덕구', '수성구',
          '달서구', '달성군', '해운대구', '사하구', '금정구', '연제구', '수영구', '사상구',
          '기장군', '부산진구', '동래구', '영도구', '강서구', '남동구', '부평구', '계양구',
          '미추홀구', '연수구', '옹진군', '울주군'}
m2z = {m: z for z, mm in U.LIVEZONE.items() for m in mm}


def sido_of(a, b):
    return ('광주' if b in GGU else '전남') if '통합' in a else SD.get(a)


def zone_of(a, b):
    if a in ('서울특별시', '인천광역시', '경기도'):
        return '수도권'
    sd = ('광주' if b in GG_ALL else '전남') if '통합' in a else U.LZ_SIDO_FULL.get(a, a)
    sg = b
    for c in SPLIT:
        if b.startswith(c) and b.endswith('구'):
            sg = c + '시'
            break
    if (sd, '*') in m2z:
        return m2z[(sd, '*')]
    if (sd, sg) in m2z:
        return m2z[(sd, sg)]
    return None


def build(keyfn, min_tr):
    sup = collections.defaultdict(lambda: collections.defaultdict(int))
    for d in kapt:
        k = keyfn(d['sd'], d['sg'])
        if k:
            sup[k]['%sQ%d' % (d['ym'][:4], (int(d['ym'][4:6]) - 1) // 3 + 1)] += d['n']
    cd2k = {}
    for kk, cd in lawd.items():
        a, b = kk.split('|')
        k = keyfn(a, b)
        if k:
            cd2k[cd] = k
    pool = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, vals in cache.items():
        if not vals:
            continue
        cd, ym = key.split('_')
        k = cd2k.get(cd)
        if k:
            pool[k]['%sQ%d' % (ym[:4], (int(ym[4:6]) - 1) // 3 + 1)] += vals
    price = {k: {q: statistics.median(v) for q, v in qm.items() if len(v) >= min_tr}
             for k, qm in pool.items()}
    return sup, price


qn = lambda q: int(q[:4]) * 4 + int(q[5]) - 1


def med3(v, w=3):
    return [statistics.median(v[max(0, i - w // 2):min(len(v), i + w // 2 + 1)])
            for i in range(len(v))]


def troughs(price, k):
    pm = price.get(k, {})
    qs = sorted(pm, key=qn)
    if len(qs) < 24:
        return None, None
    vals = [pm[q] for q in qs]
    sm, W = med3(vals), 3
    raw = [i for i in range(W, len(vals) - W)
           if sm[i] == min(sm[i - W:i + W + 1])
           and (sm[i] < sm[i - W] * 0.95 or sm[i] < sm[i + W] * 0.95)
           and qs[i] not in EXCL]
    ids = []
    for i in raw:
        if ids and i - ids[-1] < 6:
            if sm[i] < sm[ids[-1]]:
                ids[-1] = i
        else:
            ids.append(i)
    return qs, ids


def depletion(sup, k, qs, X):
    d = sup.get(k, {})
    inv, out, pos = 0.0, [], False
    for i, q in enumerate(qs):
        inv = max(0.0, inv + (d.get(q, 0) - X))
        if pos and inv <= 0 and i + LAG < len(qs):
            out.append(i + LAG)
        pos = inv > 0
    thin = []
    for i in out:
        if thin and i - thin[-1] < 6:
            continue
        thin.append(i)
    return thin


def f1(act, pred):
    if not act or not pred:
        return 0.0
    hit = sum(1 for a in act if any(abs(a - p) <= TOL for p in pred))
    pr, rc = hit / len(pred), hit / len(act)
    return 2 * pr * rc / (pr + rc) if (pr + rc) else 0.0


def fit(sup, price, k):
    qs, act = troughs(price, k)
    if not act:
        return None
    base = statistics.mean(sup[k].get(q, 0) for q in qs)
    if base <= 0:
        return None
    best = None
    for mult in [x / 50 for x in range(20, 111)]:      # 0.40~2.20
        X = base * mult
        s = f1(act, depletion(sup, k, qs, X))
        if best is None or s > best[0]:
            best = (s, X)
    return {'f1': round(best[0], 2), 'ref': round(best[1]), 'n_act': len(act)}


src = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
adv = json.loads(re.search(r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/',
                           src, re.S).group(1))
REF = adv['occupancy']['ref']
sc = json.load(io.open(os.path.join(SC, 'scale.json'), encoding='utf-8'))
SITE_H, KAPT_H = sc['site_over_hog'], sc['kapt_over_hog']

# ── ① 시도 ───────────────────────────────────────────────────────
sup_s, price_s = build(sido_of, 20)
ORDER = ['수도권', '부산', '대구', '경남', '경북', '광주', '전남', '대전',
         '충남', '충북', '전북', '강원', '울산', '세종']
print('=== ① 시도 · 지연 1년 고정 ===')
print('%-6s %4s %6s %10s %11s %10s %7s' % (
    '시도', '저점', '적합도', '산출(K척도)', '산출(사이트척도)', '현행 ref', '권장/현행'))
print('-' * 72)
sido = {}
for s in ORDER:
    r = fit(sup_s, price_s, s)
    if not r:
        continue
    kh, sh_ = KAPT_H.get(s), SITE_H.get(s)
    site_val = r['ref'] / kh * sh_ if (kh and sh_) else None   # K척도→호갱→사이트척도
    cur = REF.get(s)
    sido[s] = dict(r, site=round(site_val) if site_val else None, cur=cur)
    print('%-6s %4d %6.2f %10s %11s %10s %7s' % (
        s, r['n_act'], r['f1'], format(r['ref'], ','),
        format(int(site_val), ',') if site_val else '-',
        format(cur, ',') if cur else '-',
        ('%.2f' % (site_val / cur)) if (site_val and cur) else '-'))
print('-' * 72)
fs = [v['f1'] for v in sido.values()]
print('적합도 중앙 %.2f · 0.5 이상 %d/%d' % (statistics.median(fs), sum(1 for x in fs if x >= .5), len(fs)))

# ── ② 생활권 ─────────────────────────────────────────────────────
sup_z, price_z = build(zone_of, 10)
print()
print('=== ② 생활권 · 지연 1년 고정 ===')
print('%-11s %4s %6s %10s %s' % ('생활권', '저점', '적합도', '산출(K척도)', '판정'))
print('-' * 52)
zone = {}
for z in sorted(price_z, key=lambda x: -(9e9 if x == '수도권' else len(price_z[x]))):
    r = fit(sup_z, price_z, z)
    if not r:
        continue
    zone[z] = r
    print('%-11s %4d %6.2f %10s %s' % (
        z, r['n_act'], r['f1'], format(r['ref'], ','),
        '채택' if r['f1'] >= 0.5 else '표본·적합 부족'))
print('-' * 52)
fz = [v['f1'] for v in zone.values()]
print('생활권 %d곳 · 적합도 중앙 %.2f · 0.5 이상 %d곳'
      % (len(zone), statistics.median(fz), sum(1 for x in fz if x >= .5)))

# ── ③ 확정값 ─────────────────────────────────────────────────────
print()
print('=== ③ 확정 권장값 (사이트 척도, 시도) ===')
print('%-6s %10s %10s %8s  %s' % ('시도', '현행', '권장', '변화', '근거'))
print('-' * 60)
final = {}
for s in ORDER:
    v = sido.get(s)
    if not v or not v.get('site') or not v.get('cur'):
        continue
    if v['f1'] >= 0.5:
        rec, why = round(v['site'] / 100) * 100, '적합도 %.2f — 산출값 채택' % v['f1']
    else:
        rec, why = v['cur'], '적합도 %.2f — 현행 유지' % v['f1']
    final[s] = rec
    print('%-6s %10s %10s %+7.0f%%  %s' % (
        s, format(v['cur'], ','), format(rec, ','),
        (rec / v['cur'] - 1) * 100, why))
print('-' * 60)
io.open(os.path.join(SC, 'ref_final.json'), 'w', encoding='utf-8').write(
    json.dumps({'sido': sido, 'zone': zone, 'final': final}, ensure_ascii=False, indent=1))
print('저장: ref_final.json')

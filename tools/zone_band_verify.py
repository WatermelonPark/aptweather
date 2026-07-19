# -*- coding: utf-8 -*-
"""생활권 단위 '하락→상승 반전 밴드' 산출·검증 (2026-07-20).

신쌤 논리를 준용하되 두 가지가 다르다:
  ① 시도가 아니라 **생활권 단위 실측**
  ② 절대값 하나가 아니라 **밴드[하단, 중앙, 상단]**

⚠️ 범위: **하락→상승 반전만**. 상승→하락 반전은 별도 검증 단계라 다루지 않는다.

── 데이터 조합 (여기까지 오는 데 여러 번 막혔던 부분) ──────────────
  공급  K-apt 단지 기본정보(공공데이터포털 파일) — 단지별 **사용승인일 + 세대수 + 시군구**
        21,641단지 · 1968~2026 · 결측 0 · 총 1,233만 세대.
        KOSIS 준공실적은 시도가 최대 해상도라 생활권 단위가 불가능했고,
        청약홈은 2020년 이후만 있어 사이클을 못 덮는다. 이 파일이 유일한 해법이었다.
  가격  국토부 아파트 매매 실거래가 API — 시군구 × 분기(중간달 표본), 2006~2026.
        전용면적당 단가(만원/㎡)의 **중앙값**을 쓴다. 거래 총액 평균은
        그 분기에 어떤 평형이 팔렸느냐에 휘둘려 국면 판단을 망친다.
  기준  ADV.occupancy.ref = 신쌤이 준 시도별 적정물량(생활권엔 인구비중 배분)

── 방법에서 실패했다가 고친 것 ────────────────────────────────────
  · 전환 '분기 한 점'의 물량을 읽으면 안 된다. 그 분기는 골짜기 바닥이라
    대표성이 없다(경북 전환분기 1,084 vs 하락기 평균 5,123). 전후 2분기를 함께 본다.
  · 분기 원값은 단지 하나(2,000세대)에 휘둘린다. **4분기 이동평균**으로 잡는다.
    이걸 적용하자 규모-상대폭 상관이 -0.26 -> -0.53으로 선명해졌다.
  · 결측 분기를 0으로 세는 건 맞다. K-apt는 준공 단지만 담으므로 '없음 = 공급 0'이다.

사용:
  python tools/zone_band_verify.py <kapt.xlsx> <trade_raw.json> <lawd.json>
  (원자료는 저장소 밖에 둔다 — 이 저장소는 그대로 웹사이트라 커밋하면 공개된다)
"""
import io, os, sys, json, re, math, statistics, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import update_adv_data as U

WIN = 2      # 반전 전후 포함 분기
AMP = 0.05   # 극값 최소 진폭
GAP = 6      # 반전점 최소 이격(분기)
MIN_Q = 24   # 이 미만 시계열은 제외
MA = 4       # 이동평균 창

SPLIT_CITY = ['고양', '부천', '성남', '수원', '안산', '안양', '용인', '화성',
              '천안', '청주', '전주', '포항', '창원']
GWANG_GU = {'동구', '서구', '남구', '북구', '광산구', '중구', '유성구', '대덕구',
            '수성구', '달서구', '달성군', '해운대구', '사하구', '금정구', '연제구',
            '수영구', '사상구', '기장군', '부산진구', '동래구', '영도구', '강서구',
            '남동구', '부평구', '계양구', '미추홀구', '연수구', '옹진군', '울주군'}


def zone_of(sd_full, sg_raw):
    """K-apt·실거래 주소 → 생활권.

    K-apt는 시와 구를 붙여 쓴다('고양덕양구','창원마산합포구').
    2026년 광주+전남 행정통합이 반영돼 시도명이 '전남광주통합특별시'다.
    """
    m2z = {m: z for z, mm in U.LIVEZONE.items() for m in mm}
    if '통합' in sd_full:
        sd = '광주' if sg_raw in GWANG_GU else '전남'
    else:
        sd = U.LZ_SIDO_FULL.get(sd_full, sd_full)
    sg = sg_raw
    for c in SPLIT_CITY:
        if sg_raw.startswith(c) and sg_raw.endswith('구'):
            sg = c + '시'
            break
    if (sd, '*') in m2z:
        return m2z[(sd, '*')]
    if (sd, sg) in m2z:
        return m2z[(sd, sg)]
    return re.sub(r'(시|군)$', '', sg) + '권' if sd == '경기' else None


def qn(q):
    return int(q[:4]) * 4 + int(q[5]) - 1


def ql(n):
    return '%dQ%d' % (n // 4, n % 4 + 1)


def _med3(v, w=3):
    return [statistics.median(v[max(0, i - w // 2):min(len(v), i + w // 2 + 1)])
            for i in range(len(v))]


def troughs(vals):
    """하락→상승 반전(저점)만. 고점은 이번 범위 밖이라 찾지 않는다."""
    s, W = _med3(vals), 3
    raw = [i for i in range(W, len(vals) - W)
           if s[i] == min(s[i - W:i + W + 1])
           and (s[i] < s[i - W] * (1 - AMP) or s[i] < s[i + W] * (1 - AMP))]
    out = []
    for i in raw:
        if out and i - out[-1] < GAP:
            if s[i] < s[out[-1]]:
                out[-1] = i
        else:
            out.append(i)
    return out


def build_bands(price, supply):
    """price {생활권:{분기:{'p':단가}}} · supply {생활권:{분기:세대}} → 밴드"""
    def masup(z, q):
        d = supply.get(z, {})
        n = qn(q)
        return sum(d.get(ql(n - k), 0) for k in range(MA)) / MA

    bands, turns = {}, {}
    for z, pm in price.items():
        pq = sorted(pm, key=qn)
        if len(pq) < MIN_Q:
            continue
        idxs = troughs([pm[q]['p'] for q in pq])
        if not idxs:
            continue
        pool, pts = [], []
        for i in idxs:
            w = [pq[j] for j in range(max(0, i - WIN), min(len(pq), i + WIN + 1))]
            v = [masup(z, x) for x in w]
            pool += v
            pts.append((pq[i], round(statistics.median(v))))
        if len(pool) < 8:
            continue
        q1, q2, q3 = statistics.quantiles(pool, n=4)
        bands[z] = {'lo': round(q1), 'mid': round(q2), 'hi': round(q3),
                    'n_turn': len(idxs), 'n_obs': len(pool)}
        turns[z] = pts
    return bands, turns


def corr(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    n = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    d = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** .5
    return n / d if d else 0


if __name__ == '__main__':
    print(__doc__)
    print('이 파일은 산출 로직을 저장소에 남겨두기 위한 것이다.')
    print('원자료(엑셀·실거래 캐시)는 저장소 밖에 있으므로 경로를 인자로 준다.')

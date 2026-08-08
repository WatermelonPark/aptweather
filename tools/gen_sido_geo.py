# -*- coding: utf-8 -*-
"""시도 17곳 실경계 SVG 자산 생성 — 홈 지도 모드용.

원본: southkorea-maps (github.com/southkorea/southkorea-maps)
      kostat/2013/json/skorea_provinces_geo_simple.json
      KOSTAT(통계청) 센서스용 행정구역경계 2013 — 라이선스 "Free to share or remix".
      ⚠️ 같은 저장소의 GADM 파일은 비상업·재배포 금지라 쓰지 않는다.
      2013년 경계지만 시도 단위는 이후 변동이 없다(세종 2012 출범 반영됨).

원본 3,681점 → Douglas-Peucker 단순화 + 잔섬 정리 + 0.5px 양자화로
sido-geo.js 하나(목표 ~12KB)를 굽는다. 화면은 이 파일만 읽는다.

투영은 등장방형 + cos(중심위도) 보정 — 시도 식별이 목적이라 이걸로 충분하고,
라이브러리 의존이 없다.

사용: python tools/gen_sido_geo.py
입력: tools/data/sido_geo_raw.json   출력: /sido-geo.js
"""
import io
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, 'data', 'sido_geo_raw.json')
OUT = os.path.join(ROOT, 'sido-geo.js')

W = 420.0            # viewBox 폭 (높이는 지리 비율에서 유도)
TOL = 0.018          # 단순화 허용 오차(도 단위, ≈2km) — 시도 식별 가능선에서 최소 점수
MIN_RING_DEG2 = 3e-3 # 이보다 작은 링(섬)은 버린다. 제주 본섬 0.18, 거제 0.033,
                     # 강화 0.025, 진도 0.021, 남해 0.015, 안면도 0.009 등은 남고
                     # 다도해 잔섬 수백 개가 떨어진다.
LON_MAX = 130.5      # 울릉도(130.79~) 제외 — 빈 바다가 폭의 11%를 먹어 본토가
                     # 그만큼 작아진다. 이 원본에는 독도가 아예 없어서, 울릉도만
                     # 그리면 독도 누락으로 읽힌다 — 안 그리는 쪽이 낫다.
                     # 울릉도·독도 인셋(별도 박스)은 필요해지면 그때 넣는다.

# 데이터(REF_Q)·존 디렉터리와 같은 표기로
SHORT = {
    '서울특별시': '서울', '부산광역시': '부산', '대구광역시': '대구',
    '인천광역시': '인천', '광주광역시': '광주', '대전광역시': '대전',
    '울산광역시': '울산', '세종특별자치시': '세종', '경기도': '경기',
    '강원도': '강원', '충청북도': '충북', '충청남도': '충남',
    '전라북도': '전북', '전라남도': '전남', '경상북도': '경북',
    '경상남도': '경남', '제주특별자치도': '제주',
}


def ring_area(r):
    """slon/lat 평면에서의 부호 있는 면적(도²) — 크기 필터용."""
    a = 0.0
    for i in range(len(r) - 1):
        a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
    return abs(a) / 2


def dp_ring(r, tol):
    """닫힌 링용 DP. ⚠️ 링은 첫 점==끝 점이라 그대로 DP에 넣으면 기준 현이
    '같은 점 두 개'가 되고, 그 현까지의 거리가 전부 0으로 계산돼 링 전체가
    버려진다(제주가 2점으로 붕괴 — 실측). 첫 점에서 가장 먼 점으로 갈라
    두 호를 따로 단순화한 뒤 잇는다."""
    body = r[:-1]
    if len(body) < 4:
        return r
    x0, y0 = body[0]
    far = max(range(1, len(body)),
              key=lambda i: (body[i][0] - x0) ** 2 + (body[i][1] - y0) ** 2)
    a = dp(body[:far + 1], tol)
    b = dp(body[far:] + [body[0]], tol)
    return a + b[1:]


def dp(pts, tol):
    """Douglas-Peucker. 재귀 대신 스택 — 전남 해안선은 깊다."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i0, i1 = stack.pop()
        x0, y0 = pts[i0]
        x1, y1 = pts[i1]
        dx, dy = x1 - x0, y1 - y0
        norm = math.hypot(dx, dy) or 1e-12
        dmax, imax = -1.0, -1
        for i in range(i0 + 1, i1):
            d = abs(dy * (pts[i][0] - x0) - dx * (pts[i][1] - y0)) / norm
            if d > dmax:
                dmax, imax = d, i
        if dmax > tol:
            keep[imax] = True
            stack.append((i0, imax))
            stack.append((imax, i1))
    return [p for p, k in zip(pts, keep) if k]


def centroid(r):
    """다각형 무게중심 — 라벨 기준점."""
    a = cx = cy = 0.0
    for i in range(len(r) - 1):
        w = r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
        a += w
        cx += (r[i][0] + r[i + 1][0]) * w
        cy += (r[i][1] + r[i + 1][1]) * w
    if abs(a) < 1e-12:
        return r[0]
    return (cx / (3 * a), cy / (3 * a))


# 라벨 수동 보정(투영 px). 경기는 링이 서울·인천을 감싸 무게중심이 서울 라벨
# 위에 떨어진다(실측 겹침) — 도형이 실제로 넓은 동남쪽으로 민다.
# ⚠️ 보정량은 최종 투영 좌표 기준이다 — 울릉도 컷으로 전체 척도가 한 번
# 바뀌었을 때 옛 좌표 기준 보정이 그대로 서울 옆에 떨어졌다(실측).
NUDGE = {'경기': (34, 30)}   # -> (250.9, 141.1) 이천·광주 어간, 도형 안


def main():
    d = json.load(io.open(SRC, encoding='utf-8'))

    # 경위도 범위 → 투영 파라미터
    lons, lats = [], []
    for f in d['features']:
        g = f['geometry']
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in polys:
            for pt in poly[0]:
                if pt[0] > LON_MAX:
                    break                      # 울릉도 링 통째로 제외
                lons.append(pt[0]); lats.append(pt[1])
    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)
    k = math.cos(math.radians((lat0 + lat1) / 2))   # 위도 보정
    scale = W / ((lon1 - lon0) * k)
    H = (lat1 - lat0) * scale

    def prj(pt):
        return ((pt[0] - lon0) * k * scale, (lat1 - pt[1]) * scale)

    areas = []
    tot_in = tot_out = 0
    for f in d['features']:
        name = SHORT[f['properties']['name']]
        g = f['geometry']
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        rings, best = [], None
        for poly in polys:
            r = poly[0]                       # 구멍은 시도 단위에 없다 — 외곽 링만
            tot_in += len(r)
            if ring_area(r) < MIN_RING_DEG2 or max(p[0] for p in r) > LON_MAX:
                continue
            s = dp_ring(r, TOL)
            if len(s) < 4:
                continue
            tot_out += len(s)
            rings.append(s)
            if best is None or ring_area(r) > ring_area(best):
                best = r
        assert rings, name
        # path d — 0.5px 양자화(소수 1자리, x2 정수 아님: %.1f로 충분)
        ds = []
        for r in rings:
            pts = [prj(p) for p in r]
            ds.append('M' + 'L'.join('%.1f %.1f' % (x, y) for x, y in pts[:-1]) + 'Z')
        cx, cy = prj(centroid(best))
        dx, dy = NUDGE.get(name, (0, 0))
        areas.append({'n': name, 'd': ''.join(ds),
                      'x': round(cx + dx, 1), 'y': round(cy + dy, 1)})

    js = ('// 생성: tools/gen_sido_geo.py — 손으로 고치지 말 것\n'
          '// 원본: southkorea-maps kostat 2013 (KOSTAT, Free to share or remix)\n'
          'const SIDO_GEO=' + json.dumps(
              {'w': round(W), 'h': round(H), 'p': areas},
              ensure_ascii=False, separators=(',', ':')) + ';\n')
    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(js)
    print('점 %d -> %d, %s: %.1fKB (viewBox %dx%d)'
          % (tot_in, tot_out, os.path.basename(OUT), len(js.encode('utf-8')) / 1024, W, H))


if __name__ == '__main__':
    main()

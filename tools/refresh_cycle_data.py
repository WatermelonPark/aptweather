# -*- coding: utf-8 -*-
"""/cycle/ 리포트의 '현재 시세' 배열을 data.js에서 다시 만든다.

리포트는 서술형 문서라 대부분 고정 분석값이지만, **지수·전세가율처럼 계속 갱신되는
계열을 하드코딩해 둔 부분**이 있었다. 그게 세 번 연속 감사에 걸렸다:
  - 2026-08-08 jratio_level이 /jeonse-ratio/와 값·순위가 달랐다(서울 55.4 vs 52.3).
  - 같은 날 zones·rate_overlay의 지수 레벨이 --heal-basic 교정분(6,041셀)을 안 따라와
    수도권 2026Q1이 154.7 vs 통계 탭 157.8로 3.1포인트 어긋났다.
손으로 고치면 다음 갱신에 또 어긋나므로 생성기로 옮긴다.

⚠️ 지역 구성이 바뀌었다. 옛 배열은 생활권 4곳(수도권·부산권·대경권·대전권)인데
2026-08-06 재편으로 생활권이 폐기돼 부산권·대경권·대전권은 **재현할 수 없다**
(어느 시군을 묶었는지 정의가 사라졌다). 지금 데이터로 정직하게 표현할 수 있는
단위인 수도권·부산·대구·대전으로 바꾼다 — 리포트의 논지("수도권만 매매가 전세를
크게 따돌린다")는 그대로 성립한다.

사용: python tools/refresh_cycle_data.py
"""
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data.js')
PAGE = os.path.join(ROOT, 'cycle', 'index.html')

# 차트에 세울 지역. 옛 생활권 4곳을 대신한다(위 주석 참조).
ZONE_REGIONS = ['수도권', '부산', '대구', '대전']
SIDO17 = ['서울', '경기', '인천', '부산', '대구', '광주', '대전', '울산', '세종',
          '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
SUDO = {'서울', '경기', '인천'}
ZONES_FROM = 2006          # 옛 배열과 같은 시작점
OVERLAY_FROM = 2015        # 금리 오버레이 구간


def load_stats():
    c = io.open(DATA, encoding='utf-8').read()
    i = c.find('const STATS=')
    j = c.find('/*STATS_DATA_END*/')
    return json.loads(c[i + len('const STATS='):j].rstrip().rstrip(';'))


def ym(label):
    """'2026.06' / '2026.06 p)' → (2026, 6). 연간 라벨이면 None."""
    m = re.match(r'^(\d{4})\.(\d{1,2})', str(label).strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def quarterly(D, region, y_from):
    """{연.분기(2026.25 형식): 그 분기 평균}. 값이 하나도 없는 분기는 넣지 않는다."""
    ser = (D.get('series') or {}).get(region)
    if not ser:
        return {}
    acc = {}
    for k, lab in enumerate(D['dates']):
        p = ym(lab)
        if not p or p[0] < y_from:
            continue
        v = ser[k]
        if v is None:
            continue
        t = p[0] + (p[1] - 1) // 3 * 0.25
        acc.setdefault(t, []).append(v)
    return {t: round(sum(a) / len(a), 1) for t, a in acc.items()}


def build_zones(S):
    ma, je = S['매매지수'], S['전세지수']
    out = {}
    for rg in ZONE_REGIONS:
        qm = quarterly(ma, rg, ZONES_FROM)
        qj = quarterly(je, rg, ZONES_FROM)
        ts = sorted(qm)
        if not ts:
            print('  ⚠️ %s: 매매지수 없음 — 건너뜀' % rg)
            continue
        # 전세지수는 2014년부터라 그 이전은 null(옛 배열과 같은 모양)
        out[rg] = {'t': ts,
                   'maemae': [qm[t] for t in ts],
                   'jeonse': [qj.get(t) for t in ts]}
    return out


def build_overlay(S):
    ma = quarterly(S['매매지수'], '수도권', OVERLAY_FROM)
    je = quarterly(S['전세지수'], '수도권', OVERLAY_FROM)
    jr = quarterly(S['전세가율'], '수도권', OVERLAY_FROM)
    rt = quarterly(S['금리'], 'CD(91일)', OVERLAY_FROM)
    ts = sorted(t for t in ma if t in rt)
    return {'t': ts,
            'maemae': [ma[t] for t in ts],
            'jeonse': [je.get(t) for t in ts],
            'rate': [round(rt[t], 2) for t in ts],
            'jratio': [jr.get(t) for t in ts]}


def build_jratio(S):
    """전세가율 최신월 기준 시도 스펙트럼 + 수도권·지방 평균."""
    D = S['전세가율']
    k = len(D['dates']) - 1
    rows = [(r, D['series'][r][k]) for r in SIDO17
            if D['series'].get(r) and D['series'][r][k] is not None]
    rows.sort(key=lambda x: x[1])
    lvl = [{'region': r, 'val': round(v, 1), 'sudo': r in SUDO,
            'type': '투자성' if v < 60 else ('중간' if v < 73 else '실거주성')}
           for r, v in rows]
    sudo = [v for r, v in rows if r in SUDO]
    jib = [v for r, v in rows if r not in SUDO]
    return lvl, round(sum(sudo) / len(sudo), 1), round(sum(jib) / len(jib), 1), D['dates'][k]


def splice(page, key, value):
    """const D={...} 안의 "key": <값> 하나를 통째로 갈아 끼운다."""
    i = page.find('"%s": ' % key)
    assert i >= 0, '%s 키를 못 찾음' % key
    start = i + len('"%s": ' % key)
    dec = json.JSONDecoder()
    _, end = dec.raw_decode(page[start:])
    return page[:start] + json.dumps(value, ensure_ascii=False) + page[start + end:]


def main():
    S = load_stats()
    page = io.open(PAGE, encoding='utf-8').read()

    zones = build_zones(S)
    overlay = build_overlay(S)
    lvl, sudo_mean, jib_mean, prd = build_jratio(S)

    page = splice(page, 'zones', zones)
    page = splice(page, 'rate_overlay', overlay)
    page = splice(page, 'jratio_level', lvl)
    page = splice(page, 'sudo_mean', sudo_mean)
    page = splice(page, 'jibang_mean', jib_mean)

    io.open(PAGE, 'w', encoding='utf-8', newline='').write(page)
    z0 = zones[ZONE_REGIONS[0]]
    print('cycle 갱신 (전세가율 기준 %s)' % prd)
    print('  zones      : %s · %d분기 (%.2f ~ %.2f)'
          % (' / '.join(zones), len(z0['t']), z0['t'][0], z0['t'][-1]))
    print('             수도권 매매 끝 %s · 전세 끝 %s' % (z0['maemae'][-1], z0['jeonse'][-1]))
    print('  rate_overlay: %d분기, 매매 끝 %s · 금리 끝 %s'
          % (len(overlay['t']), overlay['maemae'][-1], overlay['rate'][-1]))
    print('  jratio_level: %d개 시도, 수도권 평균 %s · 지방 평균 %s'
          % (len(lvl), sudo_mean, jib_mean))


if __name__ == '__main__':
    main()

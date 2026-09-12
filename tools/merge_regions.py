# -*- coding: utf-8 -*-
"""광주·전남 → '전남광주' 과거 시계열 병합 (2026-09-10, 1회성).

왜: 국토부가 인허가·착공·준공을 2026.07분부터 '전남광주' 하나로만 발표하기
시작했다. 시군구 계층이 없어 되살릴 수 없으므로 판정 단위를 합쳤다. 새 데이터는
원천이 통합값을 주지만 **과거는 우리가 만들어야** 지역 페이지의 분기별 표가
빈칸이 되지 않는다.

병합 규칙은 계열의 성질이 정한다.
  - 물량(호·세대): 단순 합. 광주 100 + 전남 200 = 300이 곧 정답이다.
  - 지수·비율(%): 합칠 수 없다. 가중평균해야 한다.

가중치 근거: R-ONE이 2026.06부터 통합 지수를 함께 발표하는데, 거기서 광주 몫을
역산하면 **9주 연속 0.5988~0.5991**로 사실상 상수다(주간 매매). 월간 1개 시점은
0.5756. 세대수 비율(0.474)보다 이쪽을 쓰는 이유는 단순하다 — 원천이 발표한
통합 지수를 거의 그대로 재현한다(잔차 0.004 지수포인트). 우리가 지어낸 값이
아니라 원천의 집계 방식을 따라간 값이다.

⚠️ 되돌릴 수 없는 작업이므로 실행 전 원본을 백업하고, 실행 후 합계 정합
(16시도합=전국)이 성립하는지 확인할 것.
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data.js')

W_GJ = 0.599          # 광주 몫. R-ONE 통합 지수에서 역산(위 주석).
SRC, DST = ('광주', '전남'), '전남광주'

# 지수·비율 계열은 가중평균, 나머지는 합. 계열이 늘면 여기에 적어야 한다 —
# 빠뜨리면 지수를 더해 두 배가 된 값이 조용히 화면에 나간다.
WEIGHTED = {'매매지수', '전세지수', '전세가율', '보급률'}


def merge_series(name, series):
    """series {지역: [값...]}에서 광주·전남을 합쳐 전남광주로 만든다."""
    a, b = series.get(SRC[0]), series.get(SRC[1])
    if a is None and b is None:
        return 0
    n = max(len(a or []), len(b or []))
    out = []
    for i in range(n):
        x = a[i] if a and i < len(a) else None
        y = b[i] if b and i < len(b) else None
        if x is None and y is None:
            out.append(None)
        elif name in WEIGHTED:
            # 한쪽만 있으면 그 값을 쓴다(0으로 세면 지수가 반토막 난다).
            if x is None:
                out.append(y)
            elif y is None:
                out.append(x)
            else:
                out.append(round(W_GJ * x + (1 - W_GJ) * y, 2))
        else:
            out.append((x or 0) + (y or 0))
    series[DST] = out
    series.pop(SRC[0], None)
    series.pop(SRC[1], None)
    return n


def merge_rows(rows, regions, keys):
    """ADV의 rows(지역이 배열 인덱스)에서 두 지역을 합친다. 변동률이라 가중평균."""
    if SRC[0] not in regions or SRC[1] not in regions:
        return regions, 0
    ig, ij = regions.index(SRC[0]), regions.index(SRC[1])
    n = 0
    for r in rows:
        for k in keys:
            v = r.get(k)
            if not isinstance(v, list):
                continue
            x = v[ig] if ig < len(v) else None
            y = v[ij] if ij < len(v) else None
            if x is None and y is None:
                m = None
            elif x is None:
                m = y
            elif y is None:
                m = x
            else:
                m = round(W_GJ * x + (1 - W_GJ) * y, 4)
            for idx in sorted((ig, ij), reverse=True):
                if idx < len(v):
                    v.pop(idx)
            v.append(m)
            n += 1
    regs = [x for x in regions if x not in SRC] + [DST]
    return regs, n


def main():
    src = io.open(DATA, encoding='utf-8').read()
    m = re.search(r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S)
    adv = json.loads(m.group(1))
    m2 = re.search(r'const STATS\s*=\s*(\{.*?\});?\s*(?:/\*|const |$)', src, re.S)
    stats = json.loads(m2.group(1))

    print('[STATS]')
    for name, D in sorted(stats.items()):
        ser = D.get('series') or {}
        if SRC[0] not in ser and SRC[1] not in ser:
            continue
        n = merge_series(name, ser)
        print('  %-10s %-6s %d기간' % (name, '가중평균' if name in WEIGHTED else '합', n))

    print('[ADV]')
    for key, valkeys in (('weekly', ('ma', 'je', 'wo')), ('monthly', ('ma', 'je', 'wo'))):
        blk = adv.get(key)
        if not blk or 'regions' not in blk:
            continue
        regs, n = merge_rows(blk.get('rows') or [], blk['regions'], valkeys)
        blk['regions'] = regs
        print('  %-8s 지역 %d개 · 셀 %d개 가중평균' % (key, len(regs), n))

    out = src[:m2.start(1)] + json.dumps(stats, ensure_ascii=False, separators=(',', ':')) + src[m2.end(1):]
    m3 = re.search(r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', out, re.S)
    out = out[:m3.start(1)] + json.dumps(adv, ensure_ascii=False, separators=(',', ':')) + out[m3.end(1):]
    io.open(DATA, 'w', encoding='utf-8', newline='\n').write(out)
    print('data.js 갱신')
    return 0


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""신쌤 호갱노노 입주물량 표(PDF) 파싱 — 분기별 물량 + 국면 라벨.

이 표가 특별한 이유: **신쌤이 상승기/하락기를 색으로 직접 표시해두었다.**
빨강 = 그 지역 그 분기가 상승기, 파랑 = 하락기.
즉 우리 지표를 채점할 수 있는 '정답지'다. 매매지수에서 전환점을 추정할 필요가 없다.

산출물(JSON):
  {"order": ["2017.04", ...], "data": {"2017.04": {"수도권": [29644, 13136338], ...}},
   "ref_rows": [{"y": 585, "values": {"수도권": 55000, ...}}, ...]}

⚠️ 표 구조에서 주의할 점 (2026-06-05 판 실측):
  - 문서는 연속된 하나의 분기표인데 3개 블록으로 나뉘어 있고, 블록마다 헤더와
    적정물량 행이 반복된다. **적정물량 행이 3개이고 값이 서로 다르다** —
    맨 아래(y가 가장 큰) 것이 최신이다. 위쪽 것을 읽으면 구버전을 집는다.
  - 문서 제목의 '20231114 기준'은 갱신되지 않은 잔재다. 파일명 날짜를 믿을 것.
  - 헤더에 '전 국' 열이 있으나 데이터 행은 비어 있다. 첫 숫자는 수도권이다.
  - 셀에 단지명이 섞여 들어온다('김해12,363', '배방4,296') — 숫자만 추출한다.

사용:
  python tools/parse_shinssam_table.py <pdf경로> [출력.json]
  (PyMuPDF 필요: python -m pip install pymupdf)
"""
import sys, os, io, json, re

RED, BLUE = 0xc75252, 0x0000fe          # 상승기 / 하락기
# 분기 라벨. 앞뒤에 표시 기호가 붙는 경우가 있어(예: '-21.10-12', '22.04-06 금리인상')
# 앞의 부호와 뒤의 주석을 허용한다. 이걸 놓치면 그 분기가 통째로 누락되고,
# 숫자만 남은 그 행이 '적정물량 행'으로 오인된다(2026-06-05 판에서 실제로 발생).
QRE = re.compile(r'^[-+~]?\s*(\d{2})\.(\d{2})-(\d{2})\b')
COL_TOL = 40                             # 열 중심에서 이 이상 벗어나면 소속 없음


def rows_of(page):
    """y좌표로 묶은 행 목록 → [(y, [(x중심, 색, 텍스트), ...]), ...]"""
    spans = []
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            for s in l.get('spans', []):
                t = s['text'].strip()
                if t:
                    spans.append((round(s['bbox'][1]), (s['bbox'][0] + s['bbox'][2]) / 2,
                                  s['color'], t))
    out = []
    for y, xc, c, t in sorted(spans):
        if out and abs(out[-1][0] - y) <= 4:
            out[-1][1].append((xc, c, t))
        else:
            out.append([y, [(xc, c, t)]])
    for _, cells in out:
        cells.sort()
    return out


def parse(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    rows = rows_of(doc[0])

    # 지역 열 좌표 — 첫 헤더 행(수도권이 있는 가장 위 행)에서 잡는다
    hdr = next(cells for _, cells in rows if any(t.replace(' ', '') == '수도권' for _, _, t in cells))
    regions = [(xc, t.replace(' ', '')) for xc, _, t in hdr]

    def col_of(xc):
        best, bd = None, 1e9
        for rx, rn in regions:
            if abs(xc - rx) < bd:
                best, bd = rn, abs(xc - rx)
        return best if bd <= COL_TOL else None

    def nums(cells):
        out = {}
        for xc, c, t in cells:
            if QRE.match(t):
                continue
            v = re.sub(r'[^\d]', '', t)          # 단지명·부호·물음표 제거
            if not v:
                continue
            reg = col_of(xc)
            if reg and reg != '전국':
                out[reg] = (int(v), c)
        return out

    data, order, ref_rows = {}, [], []
    for y, cells in rows:
        lab = next((m for m in (QRE.match(t) for _, _, t in cells) if m), None)
        if lab:
            key = '20%s.%s' % (lab.group(1), lab.group(2))
            order.append(key)
            data[key] = nums(cells)
            continue
        # 적정물량 행 후보: 분기 라벨이 없고 숫자만 여럿, 헤더 바로 아래
        vals = nums(cells)
        txt = ' '.join(t for _, _, t in cells)
        looks_quarterly = re.search(r'\d{2}\.\d{2}-\d{2}', txt)
        if len(vals) >= 8 and not looks_quarterly and not any(
                '권' in t or '도' in t or '시' in t for _, _, t in cells):
            ref_rows.append({'y': y, 'values': {k: v[0] for k, v in vals.items()}})

    return {'order': order, 'data': data, 'ref_rows': ref_rows}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    pdf = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(pdf)[0] + '.json'
    r = parse(pdf)
    io.open(out, 'w', encoding='utf-8').write(json.dumps(r, ensure_ascii=False))

    tot = sum(len(v) for v in r['data'].values())
    red = sum(1 for v in r['data'].values() for x in v.values() if x[1] == RED)
    blue = sum(1 for v in r['data'].values() for x in v.values() if x[1] == BLUE)
    print('분기 %d개 (%s ~ %s)' % (len(r['order']), r['order'][0], r['order'][-1]))
    print('셀 %d개 — 상승(빨강) %d · 하락(파랑) %d · 무라벨 %d' % (tot, red, blue, tot - red - blue))
    print('적정물량 행 %d개 발견 — **맨 아래(y 최대)가 최신**:' % len(r['ref_rows']))
    for rr in r['ref_rows']:
        tag = '  <- 최신' if rr is r['ref_rows'][-1] else ''
        print('  y=%-5d %s%s' % (rr['y'], json.dumps(rr['values'], ensure_ascii=False)[:110], tag))
    print('저장:', out)


if __name__ == '__main__':
    main()

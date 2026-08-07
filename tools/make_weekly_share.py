# -*- coding: utf-8 -*-
"""주간 시장상황 공유용 PNG 생성 — 블로그·카페·인스타 배포용.

data.js의 ADV.weekly 최신 주차를 읽어 17개 시도 타일 지도를 그린다.
출력: share/weekly-map.png (매주 덮어씀 — /weekly/ og:image로도 사용)

사용: python tools/make_weekly_share.py
"""
import io, os, re, json, sys, datetime
from PIL import Image, ImageDraw, PngImagePlugin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from make_beginner_cards import noto  # noqa: E402

def _pubdate(basis):
    """조사기준일(월요일 'YYYY-MM-DD') -> 부동산원 공표일(그 주 목요일).

    주간 아파트가격동향은 월요일 조사·목요일 공표라 +3일이면 맞는다. 공휴일이
    끼면 하루씩 밀리는 주가 있는데, 그건 원천 공표 일정이라 우리가 알 수 없다 —
    통상 일정으로 적고, 어긋나도 하루 차이라 신선도 판별에는 지장이 없다.
    """
    y, m, d = (int(x) for x in basis.split('-'))
    return (datetime.date(y, m, d) + datetime.timedelta(days=3)).isoformat()


INK = (22, 32, 58)
PAPER = (246, 244, 238)
MUTED = (111, 106, 92)
LINE = (218, 213, 201)
UP = (224, 86, 74)
DN = (58, 123, 213)

TILE = [('전국', 0, 0), ('수도권', 1, 0), ('지방', 2, 0), ('제주', 3, 0),
        ('인천', 0, 1), ('서울', 1, 1), ('경기', 2, 1), ('강원', 3, 1),
        ('충남', 0, 2), ('세종', 1, 2), ('충북', 2, 2), ('경북', 3, 2),
        ('전북', 0, 3), ('대전', 1, 3), ('대구', 2, 3), ('울산', 3, 3),
        ('전남', 0, 4), ('광주', 1, 4), ('경남', 2, 4), ('부산', 3, 4)]


def load_weekly():
    c = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    i, j = c.find('/*ADV_DATA_START*/'), c.find('/*ADV_DATA_END*/')
    adv = json.loads(re.match(r'const ADV=(.*);$', c[i + 18:j], re.S).group(1))
    return adv['weekly']


def cell_bg(v, ref=0.4):
    if v is None or v == 0:
        return (239, 234, 221)
    a = min(abs(v) / ref, 1.0)
    base = UP if v > 0 else DN
    # PAPER 위에 알파 합성한 값을 직접 계산
    al = 0.14 + 0.72 * a
    return tuple(round(b * al + p * (1 - al)) for b, p in zip(base, PAPER))


def fmt(v):
    if v is None: return '·'
    return ('%+.2f' % v) if v != 0 else '0.00'


def main():
    W = load_weekly()
    regs, row = W['regions'], W['rows'][-1]
    val = {r: row['ma'][i] for i, r in enumerate(regs)}
    je = {r: row['je'][i] for i, r in enumerate(regs)}

    IW, IH = 900, 1130
    img = Image.new('RGB', (IW, IH), PAPER)
    d = ImageDraw.Draw(img)

    # 헤더
    d.text((IW // 2, 66), '이번 주 아파트 시세 지도', font=noto(46), fill=INK, anchor='mm')
    # 조사기준일(월)이 아니라 **발표일(목)**을 적는다(2026-08-06 사용자).
    # 둘 다 사실이지만 발표일 하나로 충분하다 — 사람들이 '몇 월 며칠 발표된
    # 주간시세'로 인식하고, 카드가 멈추면 이 날짜가 안 움직여 신선도까지 드러난다
    # (실제로 2026-07-18 카드가 3주간 '이번 주'로 나갔다).
    # ⚠️ 오늘 날짜를 쓰지 않는다. 배치가 하루 늦게 돌면 발표일이 아닌 날을 발표일로
    # 적게 된다. 데이터의 조사기준일에서 유도해야 언제 구워도 같은 값이 나온다.
    d.text((IW // 2, 122), '%s 발표 · 매매가격 전주 대비 변동률(%%)' % _pubdate(row['p']),
           font=noto(24), fill=MUTED, anchor='mm')
    # 범례
    d.rounded_rectangle((IW // 2 - 190, 150, IW // 2 - 168, 172), 5, fill=UP)
    d.text((IW // 2 - 158, 161), '상승', font=noto(21), fill=INK, anchor='lm')
    d.rounded_rectangle((IW // 2 + 20, 150, IW // 2 + 42, 172), 5, fill=DN)
    d.text((IW // 2 + 52, 161), '하락', font=noto(21), fill=INK, anchor='lm')

    # 타일 지도 (4열)
    TW, TH, G = 196, 128, 14
    ox = (IW - 4 * TW - 3 * G) // 2
    oy = 205
    for name, x, y in TILE:
        px, py = ox + x * (TW + G), oy + y * (TH + G)
        v = val.get(name)
        d.rounded_rectangle((px, py, px + TW, py + TH), 16, fill=cell_bg(v), outline=LINE, width=2)
        d.text((px + TW // 2, py + 34), name, font=noto(30), fill=INK, anchor='mm')
        tc = (143, 35, 24) if (v or 0) > 0 else ((18, 60, 92) if (v or 0) < 0 else MUTED)
        d.text((px + TW // 2, py + 74), fmt(v), font=noto(31), fill=tc, anchor='mm')
        jv = je.get(name)
        d.text((px + TW // 2, py + 105), '전세 %s' % fmt(jv), font=noto(18),
               fill=(143, 35, 24) if (jv or 0) > 0 else ((18, 60, 92) if (jv or 0) < 0 else MUTED), anchor='mm')

    # 요약 한 줄 (상승·하락 상위)
    ranked = sorted((r for r in regs if val.get(r) is not None and r != '수도권'), key=lambda r: val[r], reverse=True)
    up3 = [r for r in ranked if val[r] > 0][:3]
    dn3 = [r for r in reversed(ranked) if val[r] < 0][:3]
    sy = oy + 5 * TH + 4 * G + 34
    if up3:
        d.text((IW // 2, sy), '상승: ' + ' · '.join('%s %s' % (r, fmt(val[r])) for r in up3),
               font=noto(24), fill=(143, 35, 24), anchor='mm')
    if dn3:
        d.text((IW // 2, sy + 36), '하락: ' + ' · '.join('%s %s' % (r, fmt(val[r])) for r in dn3),
               font=noto(24), fill=(18, 60, 92), anchor='mm')

    # 푸터
    d.line((60, IH - 92, IW - 60, IH - 92), fill=LINE, width=2)
    d.text((IW // 2, IH - 62), 'agongmap.co.kr — 서울 구별·전국 시군구 상세 지도', font=noto(26), fill=INK, anchor='mm')
    d.text((IW // 2, IH - 30), '자료: KOSIS 한국부동산원 전국주택가격동향조사 · 매주 목요일 자동 갱신', font=noto(18), fill=MUTED, anchor='mm')

    out = os.path.join(ROOT, 'share', 'weekly-map.png')
    # 조사기준일을 PNG 메타(tEXt)에 심는다 — 감시가 라이브 카드의 신선도를 읽을
    # 유일한 방법이다. 그림에서 날짜를 OCR할 수는 없고, 파일 해시로는 '배포가
    # 됐나'만 알지 '언제 주차인가'를 모른다. 2026-07-18 카드가 3주간 라이브에
    # 걸려 있었는데 아무 신호가 없던 이유가 이것이다(2026-08-06).
    meta = PngImagePlugin.PngInfo()
    meta.add_text('agongmap-basis', row['p'])
    img.save(out, 'PNG', pnginfo=meta)
    print('wrote share/weekly-map.png (%s)' % row['p'])


if __name__ == '__main__':
    main()

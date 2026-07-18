# -*- coding: utf-8 -*-
"""투자자 테스트 점수별 공유 카드 11장 (800x800).

문구는 index.html QUIZSETS.investor와 톤을 맞춘다. 둘 중 하나를 고치면 같이 볼 것.
이모지는 폰트(OS)에 의존하지 않도록 art_raw/emoji/ 에 PNG로 번들해 합성한다.

사용:  python tools/make_investor_cards.py
"""
import os, sys
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_beginner_cards import noto  # noqa: E402  (번들 폰트 로더 공유)

W = H = 800
BG = (255, 255, 255)
INK = (22, 32, 58)
MUTED = (139, 133, 118)
SLASH = (200, 195, 183)
METER_ON = (31, 138, 112)
METER_OFF = (228, 224, 214)
BRAND = (192, 57, 43)          # 상단 바 · 헤더 알약

# 점수별 숫자 색 (0~10) — beginner/calc 카드와 같은 팔레트
SCORE_COLORS = [
    (178, 59, 46), (178, 59, 46), (192, 57, 43), (192, 57, 43), (207, 91, 42),
    (217, 154, 0), (217, 154, 0), (61, 154, 99), (31, 138, 112), (184, 134, 47),
    (184, 134, 47),
]

# 티어별 (도장 문구, 도장 색, 문구 2줄, 이모지 파일)
TIERS = [
    (range(0, 3),  '거꾸로 독법', (197, 73, 60),   ['호재를 악재로', '읽고 계시네요'],       'compass'),
    (range(3, 5),  '재도전 요망', (197, 73, 60),   ['부동산 뉴스,', '헤드라인만 보셨죠?'],   'sweat'),
    (range(5, 7),  '반쯤 고수',   (220, 162, 20),  ['감은 있어요.', '계약은 아직 이르지만'], 'moon'),
    (range(7, 9),  '고수 인정',   (49, 146, 122),  ['머릿속엔 이미', '다주택자시네요'],      'cool'),
    (range(9, 11), '업자 의심',   (197, 73, 60),   ['이걸 다 맞히네...', '혹시 업자세요?'],   'trophy'),
]

ART = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'art_raw', 'emoji')


def tier_of(score):
    for rng, stamp, col, lines, emo in TIERS:
        if score in rng:
            return stamp, col, lines, emo
    raise ValueError(score)


def fit_h(text, target_h, weight='Bold', lo=8, hi=520):
    """글자 높이가 target_h가 되는 폰트 크기를 이분 탐색."""
    best = noto(lo, weight)
    while lo <= hi:
        mid = (lo + hi) // 2
        f = noto(mid, weight)
        b = f.getbbox(text)
        h = b[3] - b[1]
        if h <= target_h:
            best = f
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def draw_centered(d, cx, cy, text, font, fill):
    b = d.textbbox((0, 0), text, font=font)
    d.text((cx - (b[2] - b[0]) / 2 - b[0], cy - (b[3] - b[1]) / 2 - b[1]), text, font=font, fill=fill)


def stamp_img(text, color):
    """살짝 기울어진 테두리 도장."""
    f = fit_h(text, 43, 'Bold')
    tmp = Image.new('RGBA', (10, 10)); td = ImageDraw.Draw(tmp)
    b = td.textbbox((0, 0), text, font=f)
    tw, th = b[2] - b[0], b[3] - b[1]
    padx, pady = 37, 26
    bw, bh = tw + padx * 2, th + pady * 2
    im = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([2, 2, bw - 3, bh - 3], radius=16, outline=color + (255,), width=5)
    d.text((padx - b[0], pady - b[1]), text, font=f, fill=color + (255,))
    return im.rotate(7, expand=True, resample=Image.BICUBIC)


def make_card(score, out):
    stamp, scol, lines, emo = tier_of(score)
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)

    # 상단 바
    d.rectangle([0, 0, W, 14], fill=BRAND)

    # 헤더: 독수리 + 알약
    eagle = os.path.join(ART, 'eagle.png')
    if os.path.exists(eagle):
        e = Image.open(eagle).convert('RGBA')
        im.paste(e, (49, 51), e)
    d.rounded_rectangle([114, 46, 347, 100], radius=27, fill=BRAND)
    draw_centered(d, (114 + 347) // 2, (46 + 100) // 2, '투자자 테스트', fit_h('투자자 테스트', 26, 'Bold'), (255, 255, 255))

    # 도장 (우상단)
    st = stamp_img(stamp, scol)
    im.paste(st, (int(608 - st.width / 2), int(104 - st.height / 2)), st)

    # 숫자 + /10  (아래 정렬, 그룹 중심 x≈265)
    num = str(score)
    fnum = fit_h(num, 256, 'Bold')
    fsl = fit_h('/10', 73, 'Bold')
    bn = d.textbbox((0, 0), num, font=fnum)
    bs = d.textbbox((0, 0), '/10', font=fsl)
    nw, sw = bn[2] - bn[0], bs[2] - bs[0]
    gap = 32
    gx = 265 - (nw + gap + sw) / 2            # 그룹 왼쪽
    d.text((gx - bn[0], 479 - bn[3]), num, font=fnum, fill=SCORE_COLORS[score])
    d.text((gx + nw + gap - bs[0], 448 - bs[3]), '/10', font=fsl, fill=SLASH)

    # 이모지 (숫자 오른쪽)
    p = os.path.join(ART, '%s.png' % emo)
    if os.path.exists(p):
        e = Image.open(p).convert('RGBA')
        ex = int(gx + nw + gap + sw + 70)
        im.paste(e, (ex, int(310 - e.height / 2)), e)

    # 점 미터 (10개)
    r, sp = 11, 40
    x0 = 400 - (9 * sp) / 2
    for i in range(10):
        cx = x0 + i * sp
        d.ellipse([cx - r, 525 - r, cx + r, 525 + r], fill=METER_ON if i < score else METER_OFF)

    # 문구 2줄
    f1 = fit_h(lines[0], 54, 'Bold')
    if d.textbbox((0, 0), lines[0], font=f1)[2] > 700:
        f1 = fit_h(lines[0], 44, 'Bold')
    draw_centered(d, 400, 609, lines[0], f1, INK)
    f2 = fit_h(lines[1], 54, 'Bold')
    if d.textbbox((0, 0), lines[1], font=f2)[2] > 700:
        f2 = fit_h(lines[1], 44, 'Bold')
    draw_centered(d, 400, 680, lines[1], f2, INK)

    # 푸터
    full = '10문항 2지선다 · 3분 · agongmap.co.kr'
    ffoot = fit_h(full, 25, 'Medium')
    left, right = '10문항 2지선다 · 3분 · ', 'agongmap.co.kr'
    fb = noto(ffoot.size, 'Bold')
    lw = d.textbbox((0, 0), left, font=ffoot)[2] - d.textbbox((0, 0), left, font=ffoot)[0]
    rw = d.textbbox((0, 0), right, font=fb)[2] - d.textbbox((0, 0), right, font=fb)[0]
    sx = 400 - (lw + rw) / 2
    bl = d.textbbox((0, 0), left, font=ffoot)
    d.text((sx - bl[0], 748 - (bl[3] - bl[1]) / 2 - bl[1]), left, font=ffoot, fill=MUTED)
    br = d.textbbox((0, 0), right, font=fb)
    d.text((sx + lw - br[0], 748 - (br[3] - br[1]) / 2 - br[1]), right, font=fb, fill=MUTED)

    im.save(out, 'PNG')
    return True


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    share = os.path.join(root, 'share')
    os.makedirs(share, exist_ok=True)
    for s in range(11):
        make_card(s, os.path.join(share, 'investor-%d.png' % s))
    print('11 cards written -> %s' % share)

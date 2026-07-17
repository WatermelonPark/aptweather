# -*- coding: utf-8 -*-
"""재건축 계산 테스트 점수별 공유 카드 11장 (800x800) — 숫자 히어로(v3) 스타일.

문구는 index.html QUIZSETS.calc.grade와 톤을 맞춘다. 둘 중 하나를 고치면 같이 볼 것.

사용:  python tools/make_calc_cards.py
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W = H = 800
PAPER = (246, 244, 238)
CARD = (255, 255, 255)
LINE = (228, 224, 214)
INK = (22, 32, 58)
MUTED = (139, 133, 118)
GRAY = (203, 198, 187)
METER_OFF = (233, 230, 221)

# 0~4 붉은 계열(위험) / 5~8 주황→청록 / 9~10 남색·금
RAMP = [
    (178, 59, 46), (178, 59, 46), (192, 57, 43), (207, 91, 42), (217, 130, 0),
    (217, 163, 0), (106, 168, 79), (61, 154, 99), (31, 138, 112), (26, 82, 118),
    (184, 134, 47),
]

NOTO = 'C:/Windows/Fonts/NotoSansKR-VF.ttf'

# (LV배지, 이름, 도발 문구 2줄) — QUIZSETS.calc.grade 구간과 대응
LEVELS = [
    ('LV1', '묻지마 매수 직전', ['공식부터', '다시 볼까요?']),
    ('LV1', '묻지마 매수 직전', ['용적률이', '어디에 곱해지더라?']),
    ('LV1', '묻지마 매수 직전', ['분담금 고지서', '조심하세요']),
    ('LV2', '분담금 주의보', ['뼈대는 잡혔고', '연습만 남았어요']),
    ('LV2', '분담금 주의보', ['절반까지', '거의 왔어요']),
    ('LV3', '공식 암기 완료', ['공식은 압니다', '손이 느릴 뿐']),
    ('LV3', '공식 암기 완료', ['눈대중 견적', '슬슬 됩니다']),
    ('LV4', '눈대중 견적사', ['예비 조합원', '자격 충분']),
    ('LV4', '눈대중 견적사', ['사업성이', '보이기 시작했죠?']),
    ('LV5', '사업성 스캐너', ['조합 총회에서', '마이크 잡으세요']),
    ('LV5', '재건축 계산 선수', ['이제 임장 가서', '대지지분 물어보세요']),
]


def noto(size, weight='Bold'):
    f = ImageFont.truetype(NOTO, size)
    f.set_variation_by_name(weight)
    return f


def fit_font(text, target, weight='Bold', axis='h', lo=10, hi=460):
    pr = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        bb = pr.textbbox((0, 0), text, font=noto(mid, weight))
        v = (bb[3] - bb[1]) if axis == 'h' else (bb[2] - bb[0])
        if v <= target:
            best = mid; lo = mid + 1
        else:
            hi = mid - 1
    return noto(best, weight)


def make_card(score, out_path):
    lv, name, taunt2 = LEVELS[score]
    accent = RAMP[score]

    img = Image.new('RGBA', (W, H), PAPER)
    M, R = 26, 38
    sh = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([M, M + 6, W - M, H - M + 6], R, fill=(22, 32, 58, 34))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(11)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([M, M, W - M, H - M], R, fill=CARD, outline=LINE, width=2)

    # 헤더: 이름 + 레벨 배지
    d.text((60, 86), '재건축 계산 테스트', font=noto(27), fill=INK, anchor='lm')
    bf, sf = noto(30), noto(19, 'Medium')
    bw = d.textbbox((0, 0), lv, font=bf)[2] + d.textbbox((0, 0), '/ 10', font=sf)[2] + 20
    bx1 = W - M - 34
    d.rounded_rectangle([bx1 - bw - 28, 66, bx1, 108], 21, fill=accent)
    d.text((bx1 - bw - 14, 88), lv, font=bf, fill=CARD, anchor='lm')
    d.text((bx1 - 14, 89), '/ 10', font=sf, fill=CARD, anchor='rm')

    # 히어로: 큰 점수 숫자
    st = str(score)
    sfnt = fit_font(st, 200)
    sb = d.textbbox((0, 0), st, font=sfnt)
    of = fit_font('/10', 108, axis='w')
    ob = d.textbbox((0, 0), '/10', font=of)
    sw_, ow = sb[2] - sb[0], ob[2] - ob[0]
    gx = (W - (sw_ + 22 + ow)) / 2
    base = 400
    d.text((gx - sb[0], base - sb[3]), st, font=sfnt, fill=accent)
    d.text((gx + sw_ + 22 - ob[0], base - 6 - ob[3]), '/10', font=of, fill=GRAY)

    # 레벨 미터 10칸
    lvl = max(1, score)
    gap, bh = 9, 12
    x0 = M + 46
    bw2 = ((W - 2 * x0) - gap * 9) / 10
    meter_y = 470
    for i in range(10):
        x = x0 + i * (bw2 + gap)
        d.rounded_rectangle([x, meter_y, x + bw2, meter_y + bh], 6, fill=accent if i < lvl else METER_OFF)

    name_y = meter_y + 46
    d.text((W // 2, name_y), name, font=noto(44), fill=accent, anchor='mm')

    taunt_y0 = name_y + 86
    line_gap = 74
    tf = noto(60)
    for i, line in enumerate(taunt2):
        y = taunt_y0 + i * line_gap
        bb = d.textbbox((W // 2, y), line, font=tf, anchor='mm')
        if not (bb[0] >= M + 24 and bb[2] <= W - M - 24):
            tf2 = fit_font(line, W - 2 * (M + 24), axis='w')
            d.text((W // 2, y), line, font=tf2, fill=INK, anchor='mm')
        else:
            d.text((W // 2, y), line, font=tf, fill=INK, anchor='mm')

    footer_line_y = min(taunt_y0 + (len(taunt2) - 1) * line_gap + 52, 732)
    d.line([320, footer_line_y, 480, footer_line_y], fill=LINE, width=2)
    d.text((W // 2, footer_line_y + 26), 'agongmap.co.kr', font=noto(25), fill=INK, anchor='mm')

    img.convert('RGB').save(out_path, 'PNG', optimize=True)


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    share = os.path.join(root, 'share')
    os.makedirs(share, exist_ok=True)
    for s in range(11):
        make_card(s, os.path.join(share, 'calc-%d.png' % s))
    print('11 cards written -> %s' % share)

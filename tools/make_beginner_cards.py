# -*- coding: utf-8 -*-
"""부린이 테스트 점수별 공유 카드 (800x800) — 10단계 레벨"""
import io, os, sys
from PIL import Image, ImageDraw, ImageFont

W = H = 800
WHITE = (255, 255, 255)
BAR = (26, 107, 84)          # 부린이 = 짙은 초록
PILL = (26, 107, 84)
INK = (22, 32, 58)
GRAY = (200, 195, 183)       # /10
FOOT = (139, 133, 118)
DOT_ON = (31, 138, 112)
DOT_OFF = (229, 224, 213)

RED = (192, 57, 43)
AMBER = (217, 154, 0)
GREEN = (31, 138, 112)
GOLD = (184, 134, 47)
# 원본 램프 유지: 0~4 빨강 / 5~6 앰버 / 7~8 초록 / 9~10 골드
ACCENT = [RED]*5 + [AMBER]*2 + [GREEN]*2 + [GOLD]*2

NOTO = 'C:/Windows/Fonts/NotoSansKR-VF.ttf'
EMOJI = 'C:/Windows/Fonts/seguiemj.ttf'

def noto(size, weight='Bold'):
    f = ImageFont.truetype(NOTO, size)
    f.set_variation_by_name(weight)
    return f

def fit_font(text, target, weight='Bold', axis='h', lo=10, hi=460):
    """ink 높이(또는 너비)가 target이 되도록 폰트 크기를 이분 탐색"""
    probe = Image.new('RGB', (10, 10))
    d = ImageDraw.Draw(probe)
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        f = noto(mid, weight)
        bb = d.textbbox((0, 0), text, font=f)
        v = (bb[3]-bb[1]) if axis == 'h' else (bb[2]-bb[0])
        if v <= target:
            best = mid; lo = mid + 1
        else:
            hi = mid - 1
    return noto(best, weight)

def ink_bbox(draw, xy, text, font, **kw):
    return draw.textbbox(xy, text, font=font, **kw)

def emoji_img(ch, box):
    """이모지를 그려 ink만 크롭한 뒤 box(px) 정사각에 맞춰 축소"""
    canvas = Image.new('RGBA', (400, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((40, 40), ch, font=ImageFont.truetype(EMOJI, 137), embedded_color=True)
    bb = canvas.getbbox()
    im = canvas.crop(bb)
    scale = box / max(im.size)
    return im.resize((max(1, int(im.width*scale)), max(1, int(im.height*scale))), Image.LANCZOS)

def rounded(draw, box, r, **kw):
    draw.rounded_rectangle(box, radius=r, **kw)

def make_card(score, level, out_path):
    img = Image.new('RGB', (W, H), WHITE)
    d = ImageDraw.Draw(img)
    accent = ACCENT[score]

    # 상단 바
    d.rectangle([0, 0, W, 14], fill=BAR)

    # 좌상단 병아리 + 필
    chick = emoji_img('\U0001F423', 58)
    img.paste(chick, (38, 44), chick)
    pill_f = noto(30, 'Bold')
    label = '부린이 테스트'
    tw = d.textbbox((0, 0), label, font=pill_f)
    pw = (tw[2]-tw[0]) + 64
    rounded(d, [114, 46, 114+pw, 100], 27, fill=PILL)
    d.text((114+pw/2, 73), label, font=pill_f, fill=WHITE, anchor='mm')

    # 우상단 스탬프 (기울어진 라운드 사각형)
    st_f = noto(44, 'Bold')
    sb = d.textbbox((0, 0), level['stamp'], font=st_f)
    sw, sh = (sb[2]-sb[0]) + 64, 86
    stamp = Image.new('RGBA', (sw+24, sh+24), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle([12, 12, 12+sw, 12+sh], radius=12, outline=accent, width=4)
    sd.text((12+sw/2, 12+sh/2), level['stamp'], font=st_f, fill=accent, anchor='mm')
    stamp = stamp.rotate(-8, resample=Image.BICUBIC, expand=True)
    img.paste(stamp, (620 - stamp.width//2, 103 - stamp.height//2), stamp)

    # 큰 이모지
    em = emoji_img(level['emoji'], 190)
    img.paste(em, (588 - em.width//2, 306 - em.height//2), em)

    # 점수 + /10
    s_txt = str(score)
    s_f = fit_font(s_txt, 248)
    sb = d.textbbox((0, 0), s_txt, font=s_f)
    sx = 180 - (sb[2]-sb[0])/2 - sb[0]
    sy = 475 - sb[3]
    d.text((sx, sy), s_txt, font=s_f, fill=accent)
    s_right = sx + sb[2]

    o_f = fit_font('/10', 138, axis='w')
    ob = d.textbbox((0, 0), '/10', font=o_f)
    d.text((s_right + 26 - ob[0], 448 - ob[3]), '/10', font=o_f, fill=GRAY)

    # 진행 점 10개
    for i in range(10):
        cx = 220 + 40*i
        c = DOT_ON if i < score else DOT_OFF
        d.ellipse([cx-13.5, 524-13.5, cx+13.5, 524+13.5], fill=c)

    # 도발 문구 2줄 (좌우 여백 60px 확보 — 넘치면 즉시 실패)
    t_f = noto(62, 'Bold')
    for i, line in enumerate(level['taunt2']):
        lb = d.textbbox((400, 610 + i*68), line, font=t_f, anchor='mm')
        assert lb[0] >= 60 and lb[2] <= W-60, 'taunt line overflows: %r (%d..%d)' % (line, lb[0], lb[2])
        d.text((400, 610 + i*68), line, font=t_f, fill=INK, anchor='mm')

    # 푸터
    f_f = noto(23, 'Medium')
    d.text((400, 754), '10문항 2지선다 · 3분 · aptweather.co.kr', font=f_f, fill=FOOT, anchor='mm')

    img.save(out_path, 'PNG', optimize=True)


LEVELS = [
    # score 0
    dict(stamp='태아', emoji='\U0001F95A', taunt2=['아직 엄마 뱃속에', '계시네요…']),
    dict(stamp='태아', emoji='\U0001F95A', taunt2=['아직 엄마 뱃속에', '계시네요…']),
    dict(stamp='신생아', emoji='\U0001F476', taunt2=['전세 계약서만 보면', '울음부터 나오죠']),
    dict(stamp='어린이집', emoji='\U0001F9F8', taunt2=['등기부등본이', '아직 그림책 같죠?']),
    dict(stamp='유치원', emoji='\U0001F392', taunt2=['LTV랑 DSR,', '아직 헷갈리시죠?']),
    dict(stamp='초등학생', emoji='✏️', taunt2=['용어는 외웠는데', '실전은 아직이에요']),
    dict(stamp='중학생', emoji='\U0001F4D0', taunt2=['임장은 이제', '다녀보셨나요?']),
    dict(stamp='고등학생', emoji='\U0001F4D7', taunt2=['제도는 다 아시네요', '이제 실전만 남았어요']),
    dict(stamp='대학생', emoji='\U0001F4DA', taunt2=['계약서 앞에서', '안 떨리겠는데요?']),
    dict(stamp='대학원생', emoji='\U0001F52C', taunt2=['이쯤 되면…', '다주택자세요?']),
    dict(stamp='교수님', emoji='\U0001F393', taunt2=['혹시… 부동산학', '강의하세요?']),
]

if __name__ == '__main__':
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    for s in range(11):
        make_card(s, LEVELS[s], os.path.join(outdir, 'beginner-%d.png' % s))
    print('rendered 11 cards ->', outdir)

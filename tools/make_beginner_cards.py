# -*- coding: utf-8 -*-
"""부린이 테스트 점수별 공유 카드 11장 (800x800) — 부동산 여정 (달걀 → 봉황).

문구는 index.html의 BLV[score]와 1:1로 대응한다. 둘 중 하나를 고치면 반드시 같이 고칠 것.

아트 소스:
  art_raw/raw-<score>.{png,webp,jpg,jpeg} 가 있으면 그 그림을 배경 제거(단색 배경 flood-fill)
  후 카드 히어로 자리에 합성한다. 없는 레벨은 v3 스타일(이모지 없이 큰 점수 숫자)로 대체한다 —
  '그림 대기중' 같은 플레이스홀더는 배포용으로 쓰지 않는다.

  그림을 새로 구하면 art_raw/raw-<score>.png 로 넣고 이 스크립트를 다시 실행하면
  그 레벨만 실사 아트로 자동 교체된다.

사용:  python tools/make_beginner_cards.py
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

# 10단 연속 램프 (0~5 붉은 계열 = 아직 어린이 / 6에서 초록 점프 / 10은 금)
RAMP = [
    (178, 59, 46), (178, 59, 46), (192, 57, 43), (207, 91, 42), (217, 130, 0),
    (217, 163, 0), (106, 168, 79), (61, 154, 99), (31, 138, 112), (20, 119, 111),
    (184, 134, 47),
]

NOTO = 'C:/Windows/Fonts/NotoSansKR-VF.ttf'

# (LV배지, 이름, 도발 문구 2줄) — index.html BLV[score]의 lv/g/taunt와 대응
LEVELS = [
    ('LV1', '무주택 달걀', ['아직 껍데기 속', '무주택입니다']),
    ('LV1', '부화 임박', ['곧 세상 밖으로', '나올 참입니다']),
    ('LV2', '갓 깬 삐약이', ['전세 계약서가', '아직 무섭죠?']),
    ('LV3', '솜털 병아리', ['용어는 외웠는데', '실전은 아직이죠']),
    ('LV4', '첫 발품 영계', ['임장은 이제', '다녀보셨나요?']),
    ('LV5', '알 낳는 암탉', ['슬슬 감이', '잡히시죠?']),
    ('LV6', '목청 좋은 장닭', ['이제 아무도', '못 말리겠는데요?']),
    ('LV7', '내 집 마련', ['드디어 첫 둥지', '축하합니다!']),
    ('LV8', '다주택자', ['한 채로는', '성에 안 차죠?']),
    ('LV9', '부동산 거물', ['시장이 손안에', '들어왔네요']),
    ('LV10', '부동산 봉황', ['금은보화 위에', '앉으셨네요']),
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


def find_art(art_dir, score):
    for ext in ('png', 'webp', 'jpg', 'jpeg', 'png.webp'):
        p = os.path.join(art_dir, 'raw-%d.%s' % (score, ext))
        if os.path.exists(p):
            return p
    return None


def _largest_component(opaque):
    """opaque: 2D bool ndarray. 가장 큰 4연결 성분만 True로 남긴 마스크를 반환.
    (점선 테두리·드롭섀도우처럼 배경 flood-fill 뒤에도 남는 얇은 조각을 걸러낸다.)"""
    import numpy as np
    from collections import deque
    H, W = opaque.shape
    labels = np.zeros((H, W), dtype=np.int32)
    visited = np.zeros((H, W), dtype=bool)
    cur = 0
    sizes = [0]
    for y in range(H):
        row = opaque[y]
        for x in range(W):
            if row[x] and not visited[y, x]:
                cur += 1
                q = deque([(y, x)])
                visited[y, x] = True
                size = 0
                while q:
                    cy, cx = q.popleft()
                    labels[cy, cx] = cur
                    size += 1
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and opaque[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            q.append((ny, nx))
                sizes.append(size)
    if cur == 0:
        return opaque
    biggest = int(np.argmax(sizes))
    return labels == biggest


def cutout(path, thresh=48):
    """배경 제거 + 내용만 트림.
    이미 알파 채널이 있는 소스(사전 가공된 PNG)는 그대로 크롭만 한다.
    그 외에는 가장자리 flood-fill로 배경을 지운 뒤, 점선 테두리·드롭섀도우 같은
    잔여 조각을 떨어내기 위해 가장 큰 연결 성분(피사체)만 남긴다."""
    import numpy as np
    src = Image.open(path)
    if src.mode == 'RGBA':
        alpha = src.getchannel('A')
        if alpha.getextrema()[0] < 250:
            bbox = src.getbbox()
            return src.crop(bbox) if bbox else src

    im = src.convert('RGB')
    w, h = im.size
    key = (255, 0, 255)
    seeds = [(1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2),
             (w // 2, 1), (w // 2, h - 2), (1, h // 2), (w - 2, h // 2)]
    for sd in seeds:
        ImageDraw.floodfill(im, sd, key, thresh=thresh)

    arr = np.array(im)
    opaque = ~np.all(arr == np.array(key), axis=2)
    keep = _largest_component(opaque)

    px = im.load()
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    op = out.load()
    for y in range(h):
        for x in range(w):
            if keep[y, x]:
                c = px[x, y]
                op[x, y] = (c[0], c[1], c[2], 255)
    bbox = out.getbbox()
    return out.crop(bbox) if bbox else out


def place_art(card, art, box):
    bx0, by0, bx1, by1 = box
    bw, bh = bx1 - bx0, by1 - by0
    s = min(bw / art.width, bh / art.height)
    nw, nh = int(art.width * s), int(art.height * s)
    art2 = art.resize((nw, nh), Image.LANCZOS)
    card.alpha_composite(art2, (bx0 + (bw - nw) // 2, by0 + (bh - nh) // 2))


def make_card(score, art_dir, out_path):
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
    d.text((60, 86), '부린이 테스트', font=noto(27), fill=INK, anchor='lm')
    bf, sf = noto(30), noto(19, 'Medium')
    bw = d.textbbox((0, 0), lv, font=bf)[2] + d.textbbox((0, 0), '/ 10', font=sf)[2] + 20
    bx1 = W - M - 34
    d.rounded_rectangle([bx1 - bw - 28, 66, bx1, 108], 21, fill=accent)
    d.text((bx1 - bw - 14, 88), lv, font=bf, fill=CARD, anchor='lm')
    d.text((bx1 - 14, 89), '/ 10', font=sf, fill=CARD, anchor='rm')

    art_path = find_art(art_dir, score)
    if art_path:
        place_art(img, cutout(art_path), (110, 128, W - 110, 468))
        score_y = 494
    else:
        # v3 폴백: 이모지 없이 점수 숫자가 히어로
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
        score_y = None

    if score_y:
        d.text((W // 2, score_y), '점수 %d/10' % score, font=noto(23, 'Medium'), fill=MUTED, anchor='mm')

    # 레벨 미터 10칸
    lvl = max(1, score)
    gap, bh = 9, 12
    x0 = M + 46
    bw2 = ((W - 2 * x0) - gap * 9) / 10
    meter_y = 522 if art_path else 470
    for i in range(10):
        x = x0 + i * (bw2 + gap)
        d.rounded_rectangle([x, meter_y, x + bw2, meter_y + bh], 6, fill=accent if i < lvl else METER_OFF)

    name_y = meter_y + 46
    d.text((W // 2, name_y), name, font=noto(44), fill=accent, anchor='mm')

    taunt_y0 = name_y + (74 if art_path else 86)
    line_gap = 58 if art_path else 74
    tf = noto(48 if art_path else 60)
    for i, line in enumerate(taunt2):
        y = taunt_y0 + i * line_gap
        bb = d.textbbox((W // 2, y), line, font=tf, anchor='mm')
        assert bb[0] >= M + 24 and bb[2] <= W - M - 24, 'taunt overflows: %r' % line
        d.text((W // 2, y), line, font=tf, fill=INK, anchor='mm')

    footer_line_y = taunt_y0 + (len(taunt2) - 1) * line_gap + (44 if art_path else 52)
    footer_line_y = min(footer_line_y, 732)
    d.line([320, footer_line_y, 480, footer_line_y], fill=LINE, width=2)
    d.text((W // 2, footer_line_y + 26), 'aptweather.co.kr', font=noto(25), fill=INK, anchor='mm')

    img.convert('RGB').save(out_path, 'PNG', optimize=True)
    return art_path is not None


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    art_dir = os.path.join(root, 'art_raw')
    share = os.path.join(root, 'share')
    os.makedirs(share, exist_ok=True)
    real = []
    for s in range(11):
        if make_card(s, art_dir, os.path.join(share, 'beginner-%d.png' % s)):
            real.append(s)
    print('11 cards written -> %s (real art: %s)' % (share, real))

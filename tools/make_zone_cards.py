# -*- coding: utf-8 -*-
"""지역 OG 카드 — share/zone-<지역>.png (1200x630), 지역 하나당 한 장.

카카오톡·SNS에 지역 페이지를 공유했을 때 뜨는 미리보기다. 이게 없으면 20장이
전부 같은 이미지 하나를 공유해서, 누가 "서울 공급 분석"을 단톡방에 올려도
미리보기엔 주간 지도만 떴다 — 우리 동네 얘기라는 신호가 0이었다.

**숫자를 일부러 넣지 않는다.** 순부족 세대수도, 등급 라벨도 안 넣는다:
  - 카카오톡은 OG 이미지를 한 번 크롤링하면 수일~수주 캐시한다. 숫자를
    박으면 데이터가 갱신된 뒤에도 카톡방엔 옛 숫자가 계속 떠 있고,
    지역마다 캐시를 일일이 깨는 건 비현실적이다.
  - 모델이 실제로 크게 움직였다. 2026-07~08 사이 지역 체계가 생활권 44곳
    → 시도 20곳으로 바뀌었고, 미래 공급 기준도 인허가 4년 → 착공 3년으로
    갈아엎였다. 그때마다 숫자 카드를 다시 뿌렸다면 캐시 때문에 옛 숫자가
    남았을 것이다.
그래서 카드에는 안 바뀌는 것만 담는다 — 지역명과 이 서비스가 답하는 질문.
숫자는 링크를 눌러 페이지에서 보면 되고, OG의 역할은 "어느 지역 얘기인지"
알리는 데까지다. 덕분에 주간·월간 갱신 때 재생성할 필요가 없다.
(지역 구성이 바뀔 때만 다시 돌린다. 모델이 안정된 뒤 숫자판을 원하면
 og:image에 ?v=<데이터기준일>을 붙여 캐시를 강제로 깨는 장치가 함께 필요하다.)

지역 목록은 zone/ 디렉토리에서 읽는다. ADV.sido를 읽지 않으므로 공급 모델이
어떻게 바뀌든 이 생성기는 영향받지 않는다.

사용:  python tools/make_zone_cards.py
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

W, H = 1200, 630

# make_og_cards.py와 동일 토큰 (쿨 계열). 브랜드 카드가 먹색 상단바를 쓰므로
# 존 카드도 먹색으로 맞춘다 — 그린 바는 퀴즈 카드 몫이다.
PAPER = (244, 246, 245)
INK   = (19, 30, 36)
RED   = (192, 57, 43)
MUTED = (94, 111, 116)
LINE  = (196, 206, 201)
WHITE = (255, 255, 255)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, 'fonts') if os.path.exists(os.path.join(ROOT, 'fonts')) \
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
FONT_FILES = {'Bold': 'Pretendard-Bold.subset.ttf', 'Medium': 'Pretendard-Medium.subset.ttf'}

OUT_DIR = os.path.join(ROOT, 'share')

# 칩은 '시도'라고 못 박지 않는다 — 목록에 전국·수도권·지방 같은 집계도 섞여 있다.
CHIP = '아공맵 지역 리포트'
SUB = '필요한 집 vs 들어올 집'
# 2026-08-06 재편 반영: 미래 공급을 인허가가 아니라 착공 실적으로 센다.
FOOT = '준공·착공 실적으로 본 아파트 공급'


def font(size, weight='Bold'):
    return ImageFont.truetype(os.path.join(FONT_DIR, FONT_FILES[weight]), size)


def fit_width(text, target, weight='Bold', hi=140, lo=40):
    """target 픽셀 폭에 들어가는 가장 큰 폰트. 존 이름은 2~6자로 길이 편차가
    커서(예: '서울권' vs '군산익산권') 고정 크기로는 균형이 안 맞는다."""
    pr = ImageDraw.Draw(Image.new('RGB', (4, 4)))
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        bb = pr.textbbox((0, 0), text, font=font(mid, weight))
        if bb[2] - bb[0] <= target:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return font(best, weight)


def zone_names():
    """zone/ 디렉토리에서 존 목록을 읽는다. 데이터 모델에 의존하지 않으려고
    calc() 대신 파일시스템을 본다."""
    zdir = os.path.join(ROOT, 'zone')
    names = []
    for d in sorted(os.listdir(zdir)):
        p = os.path.join(zdir, d)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, 'index.html')):
            names.append(d)
    return names


def make(name):
    img = Image.new('RGBA', (W, H), PAPER + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 13], fill=INK)

    MX = 64

    # 우측 모래시계 — 브랜드 카드(og-brand)와 같은 아이콘을 써서 계열을 맞춘다.
    # draw_icon은 PAPER 배경의 RGB를 돌려주므로 alpha_composite가 아니라
    # paste로 붙인다(배경색이 같아 이음매가 안 보인다).
    # 실패해도 카드 자체는 나와야 하지만, 조용히 삼키면 텅 빈 카드가 45장
    # 나오고도 모르므로 경고는 남긴다.
    icon_left = W - MX
    try:
        from make_app_icon import draw_icon
        glass = draw_icon(300, 0.94)
        gx, gy = W - MX - glass.width, 186
        img.paste(glass, (gx, gy))
        icon_left = gx
    except Exception as e:
        sys.stderr.write('WARN: 모래시계 아이콘 생략 (%s: %s)\n' % (type(e).__name__, e))

    # 칩
    cf = font(28, 'Bold')
    cbb = d.textbbox((0, 0), CHIP, font=cf)
    cw, ch = cbb[2] - cbb[0], cbb[3] - cbb[1]
    px, py = 22, 13
    d.rounded_rectangle([MX, 66, MX + cw + px * 2, 66 + ch + py * 2], radius=6, fill=INK)
    d.text((MX + px - cbb[0], 66 + py - cbb[1]), CHIP, font=cf, fill=WHITE)

    # 지역명 — 아이콘 왼쪽까지만 쓰고, 그 폭에 맞춰 크기를 잡는다.
    tw = max(320, icon_left - 40 - MX)
    hf = fit_width(name, tw, hi=140)
    hbb = d.textbbox((0, 0), name, font=hf)
    y1 = 176
    d.text((MX - hbb[0], y1 - hbb[1]), name, font=hf, fill=INK)
    name_bottom = y1 + (hbb[3] - hbb[1])

    # 부제
    sf = font(38, 'Medium')
    d.text((MX, name_bottom + 30), SUB, font=sf, fill=MUTED)

    # 하단 구분선 + 푸터
    fy = 548
    d.line([MX, fy, W - MX, fy], fill=LINE, width=2)
    d.text((MX, fy + 24), FOOT, font=font(24, 'Medium'), fill=MUTED)
    dom = 'agongmap.co.kr'
    df = font(26, 'Bold')
    dbb = d.textbbox((0, 0), dom, font=df)
    d.text((W - MX - (dbb[2] - dbb[0]), fy + 22), dom, font=df, fill=RED)

    out = os.path.join(OUT_DIR, 'zone-%s.png' % name)
    img.convert('RGB').save(out, 'PNG', optimize=True)
    return out


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    names = zone_names()
    if not names:
        print('zone/ 에 생활권 디렉토리가 없다 — make_zone_pages.py를 먼저 실행할 것')
        return 1
    for n in names:
        make(n)
    print('생활권 OG 카드 %d장 생성 → share/zone-*.png' % len(names))
    return 0


if __name__ == '__main__':
    sys.exit(main())

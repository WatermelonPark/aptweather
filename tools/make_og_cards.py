# -*- coding: utf-8 -*-
"""퀴즈 3종 OG 카드 (1200x630) — 카카오톡·트위터 공유 미리보기.

og-test.png(부린이)·og-investor.png·og-redev.png 세 장을 같은 템플릿으로 찍는다.
톤은 랜딩 페이지(/burini-test/ 등)의 쿨 토큰과 1:1로 맞춘다:
  ink #131e24 / paper #f4f6f5 / green #1a6b54 / red #c0392b / muted #5e6f74 / line #c4cec9

이모지는 Segoe UI Emoji(컬러)로 렌더한다 — 원본 og-test.png의 병아리와 동일 서체다.
문구는 각 랜딩의 h1/부제와 대응한다. 랜딩을 고치면 이 문구도 같이 볼 것.

사용:  python tools/make_og_cards.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630

# 랜딩 페이지 :root 토큰과 동일 (쿨 계열)
PAPER = (244, 246, 245)   # --paper #f4f6f5
INK   = (19, 30, 36)      # --ink   #131e24
RED   = (192, 57, 43)     # 상승/훅 라인 #c0392b
GREEN = (26, 107, 84)     # --green #1a6b54
MUTED = (94, 111, 116)    # --muted #5e6f74
LINE  = (196, 206, 201)   # --line  #c4cec9
WHITE = (255, 255, 255)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, 'fonts') if os.path.exists(os.path.join(ROOT, 'fonts')) \
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
FONT_FILES = {'Bold': 'Pretendard-Bold.subset.ttf', 'Medium': 'Pretendard-Medium.subset.ttf'}
EMOJI_FONT = 'C:/Windows/Fonts/seguiemj.ttf'

# (출력파일, 칩, h1 1줄(먹색), h1 2줄(빨강·훅), 부제, 푸터 좌측, 이모지)
CARDS = [
    ('og-test.png', '부린이 테스트',
     '내 부동산 감각,', '몇 점일까?',
     '10문항 2지선다 · 3분 · 즉시 채점·해설',
     '내집마련 전 필수 체크 · 국가기관 데이터 기반', '🐣'),
    ('og-investor.png', '투자자 테스트',
     '통념을 뒤집을', '준비가 됐나?',
     '10문항 2지선다 · 3분 · 즉시 채점·해설',
     '규제·금리·수급의 진짜 게임 · 국가기관 데이터 기반', '🦅'),
    ('og-redev.png', '재건축·재개발 테스트',
     '이 재건축,', '사업성 있을까?',
     '10문항 2지선다 · 3분 · 즉시 채점·해설',
     '대지지분·용적률·조합원 수 · 국가기관 데이터 기반', '🏗️'),
]


def font(size, weight='Bold'):
    return ImageFont.truetype(os.path.join(FONT_DIR, FONT_FILES[weight]), size)


def emoji_font(size):
    return ImageFont.truetype(EMOJI_FONT, size)


def fit_width(text, target, weight='Bold', hi=96, lo=28):
    """target 픽셀 폭에 들어가는 가장 큰 폰트."""
    pr = ImageDraw.Draw(Image.new('RGB', (4, 4)))
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        bb = pr.textbbox((0, 0), text, font=font(mid, weight))
        if bb[2] - bb[0] <= target:
            best = mid; lo = mid + 1
        else:
            hi = mid - 1
    return font(best, weight)


def draw_emoji(img, ch, box):
    """box(=(x0,y0,x1,y1)) 안에 컬러 이모지를 중앙 배치. Segoe는 고정 비트맵이라
    큰 사이즈로 렌더 후 리샘플해 선명도를 확보한다."""
    bx0, by0, bx1, by1 = box
    bw, bh = bx1 - bx0, by1 - by0
    render_px = 240  # Segoe 컬러 글리프의 실제 비트맵 크기
    tile = Image.new('RGBA', (render_px + 40, render_px + 40), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    ef = emoji_font(render_px)
    td.text((20, 20), ch, font=ef, embedded_color=True)
    bb = tile.getbbox()
    if bb:
        tile = tile.crop(bb)
    s = min(bw / tile.width, bh / tile.height)
    nw, nh = max(1, int(tile.width * s)), max(1, int(tile.height * s))
    tile = tile.resize((nw, nh), Image.LANCZOS)
    img.alpha_composite(tile, (bx0 + (bw - nw) // 2, by0 + (bh - nh) // 2))


def make(out, chip, h1a, h1b, sub, foot, emoji):
    img = Image.new('RGBA', (W, H), PAPER + (255,))
    d = ImageDraw.Draw(img)

    # 상단 그린 바
    d.rectangle([0, 0, W, 13], fill=GREEN)

    MX = 64  # 좌우 여백

    # 이모지 (우측). 텍스트가 침범하지 않도록 먼저 영역을 잡는다.
    draw_emoji(img, emoji, (852, 150, 1136, 400))

    # 칩 (그린 알약)
    cf = font(28, 'Bold')
    cbb = d.textbbox((0, 0), chip, font=cf)
    cw, ch = cbb[2] - cbb[0], cbb[3] - cbb[1]
    px, py = 22, 13
    d.rounded_rectangle([MX, 66, MX + cw + px * 2, 66 + ch + py * 2], radius=6, fill=GREEN)
    d.text((MX + px - cbb[0], 66 + py - cbb[1]), chip, font=cf, fill=WHITE)

    # 헤드라인 2줄 — 텍스트 폭을 이모지 왼쪽(~x=820)까지로 제한
    tw = 820 - MX
    hf = fit_width(max([h1a, h1b], key=len), tw, hi=88)
    asc, desc = hf.getmetrics()
    lh = asc + desc
    y1 = 168
    d.text((MX, y1), h1a, font=hf, fill=INK)
    d.text((MX, y1 + int(lh * 1.06)), h1b, font=hf, fill=RED)

    # 부제
    sf = font(34, 'Medium')
    sy = y1 + int(lh * 1.06) + lh + 26
    d.text((MX, sy), sub, font=sf, fill=MUTED)

    # 하단 구분선 + 푸터
    fy = 548
    d.line([MX, fy, W - MX, fy], fill=LINE, width=2)
    d.text((MX, fy + 24), foot, font=font(24, 'Medium'), fill=MUTED)
    dom = 'agongmap.co.kr'
    df = font(26, 'Bold')
    dbb = d.textbbox((0, 0), dom, font=df)
    d.text((W - MX - (dbb[2] - dbb[0]), fy + 22), dom, font=df, fill=RED)

    img.convert('RGB').save(os.path.join(ROOT, out), 'PNG', optimize=True)
    return out


if __name__ == '__main__':
    for c in CARDS:
        print('written ->', make(*c))

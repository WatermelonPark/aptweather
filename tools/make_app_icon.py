# -*- coding: utf-8 -*-
"""앱 아이콘·파비콘·PWA 아이콘 생성 — art_raw/raw-1(부화 병아리, FLUX 아트) 기반.

(구버전은 PIL로 병아리를 직접 그렸으나, 카드 아트와 톤을 맞추기 위해
 공유 카드와 같은 원본 그림에서 배경을 제거해 합성하는 방식으로 교체함)

산출물:
  app_icon.png           512  파비콘 + apple-touch-icon (피사체 크게)
  icons/icon-192.png     192  PWA any
  icons/icon-512.png     512  PWA any
  icons/maskable-192.png 192  PWA maskable (안전영역: 중앙 80% 원 안에 피사체)
  icons/maskable-512.png 512  PWA maskable

사용: python tools/make_app_icon.py
"""
import os, sys
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from make_beginner_cards import cutout, find_art  # noqa: E402

BG = (246, 244, 238, 255)   # 사이트 종이색 #f6f4ee (manifest background_color와 동일)
RED = (169, 50, 38)         # 시세 지도 상승색 #a93226
BLUE = (26, 82, 118)        # 시세 지도 하락색 #1a5276
NEUTRAL = (208, 202, 188)
# 4x4 그리드에서 색이 들어가는 타일 위치 (행, 열) — 시세 지도 축소판 느낌
TILE_PAT = {(0, 1): RED, (1, 2): RED, (2, 0): BLUE, (3, 2): BLUE, (1, 0): RED, (2, 3): BLUE}


def blend(col, alpha):
    """BG 위에 col을 alpha(0~255)만큼 얹은 결과색 — RGBA 캔버스는 PIL이 반투명
    블렌딩을 안 해주므로(직접 대입됨) 미리 섞은 불투명 색을 쓴다."""
    a = alpha / 255
    return tuple(round(b * (1 - a) + c * a) for b, c in zip(BG[:3], col))


def tile_bg(size):
    """아공맵 정체성: 시세 지도풍 타일 그리드를 은은하게 깐 배경 (병아리가 주인공)."""
    im = Image.new('RGBA', (size, size), BG)
    d = ImageDraw.Draw(im)
    n = 4
    gap = max(2, round(size * 0.02))
    cell = (size - gap * (n + 1)) // n
    radius = max(3, round(cell * 0.17))
    for r in range(n):
        for c in range(n):
            x0 = gap + c * (cell + gap)
            y0 = gap + r * (cell + gap)
            col = TILE_PAT.get((r, c))
            fill = blend(col, 70) if col else blend(NEUTRAL, 40)
            d.rounded_rectangle([x0, y0, x0 + cell, y0 + cell], radius=radius, fill=fill)
    return im


def compose(subject, size, fill_ratio):
    """타일 배경 캔버스 중앙에 피사체를 fill_ratio 크기로 합성."""
    canvas = tile_bg(size)
    w, h = subject.size
    scale = size * fill_ratio / max(w, h)
    sub = subject.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    canvas.alpha_composite(sub, ((size - sub.width) // 2, (size - sub.height) // 2))
    return canvas.convert('RGB')


def main():
    raw = find_art(os.path.join(ROOT, 'art_raw'), 1)
    assert raw, 'art_raw/raw-1.* 없음'
    subject = cutout(raw)
    os.makedirs(os.path.join(ROOT, 'icons'), exist_ok=True)
    jobs = [
        ('app_icon.png', 512, 0.94),
        (os.path.join('icons', 'icon-192.png'), 192, 0.88),
        (os.path.join('icons', 'icon-512.png'), 512, 0.88),
        (os.path.join('icons', 'maskable-192.png'), 192, 0.66),
        (os.path.join('icons', 'maskable-512.png'), 512, 0.66),
    ]
    for rel, size, ratio in jobs:
        compose(subject, size, ratio).save(os.path.join(ROOT, rel), 'PNG')
        print('wrote', rel)


if __name__ == '__main__':
    main()

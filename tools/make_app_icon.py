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
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from make_beginner_cards import cutout, find_art  # noqa: E402

BG = (246, 244, 238, 255)   # 사이트 종이색 #f6f4ee (manifest background_color와 동일)


def compose(subject, size, fill_ratio):
    """정사각 캔버스(BG) 중앙에 피사체를 fill_ratio 크기로 합성."""
    canvas = Image.new('RGBA', (size, size), BG)
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

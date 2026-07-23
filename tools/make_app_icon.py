# -*- coding: utf-8 -*-
"""앱 아이콘·파비콘·PWA 아이콘 생성 — 아공맵 시그니처 '발산 막대'(공급 과부족).

서비스 정체성 그대로를 아이콘화한다: 생활권별 아파트 공급 과부족을 0선(척추)에서
좌우로 뻗는 막대로. 부족=빨강·오른쪽(#c0392b), 과잉/충분=파랑·왼쪽(#3a7bd5).
쿨 토큰·플랫 디자인으로 OG 카드와 톤을 맞춘다. (구 병아리 아이콘 생성기는
tools/make_app_icon_chick.py.bak 로 백업)

산출물:
  app_icon.png           512  파비콘 + apple-touch-icon (차트 크게, iOS가 스퀘어클 마스킹)
  icons/icon-192.png     192  PWA any
  icons/icon-512.png     512  PWA any
  icons/maskable-192.png 192  PWA maskable (안전영역: 중앙 원 안에 차트)
  icons/maskable-512.png 512  PWA maskable

사용: python tools/make_app_icon.py
"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAPER = (244, 246, 245)   # --paper #f4f6f5 (랜딩·OG 카드와 동일 쿨 토큰)
RED   = (192, 57, 43)     # 부족 #c0392b (오른쪽)
RED2  = (169, 50, 38)     # 절벽 #a93226 (최심 부족)
BLUE  = (58, 123, 213)    # 충분/과잉 #3a7bd5 (왼쪽)
BLUE2 = (26, 82, 118)     # 과잉 심화 #1a5276 (최대 과잉)
SPINE = (19, 30, 36)      # --ink #131e24 (0선 척추)

# 0선에서 좌우로 뻗는 막대 — 부호(+오른쪽/부족, -왼쪽/과잉)와 길이(half 대비 비율).
# 위에서 아래로: 최심 부족 → 균형 근처 → 최대 과잉 (사이트 순위 지도와 같은 방향).
BARS = [
    ( 0.98, RED2),
    ( 0.70, RED),
    ( 0.42, RED),
    ( 0.16, RED),
    (-0.36, BLUE),
    (-0.66, BLUE),
    (-0.92, BLUE2),
]


def draw_icon(size, fill_ratio):
    img = Image.new('RGB', (size, size), PAPER)
    d = ImageDraw.Draw(img)

    A = size * fill_ratio          # 차트가 차지하는 정사각 한 변
    cx = size / 2                   # 0선(중앙)
    half = A / 2                    # 막대 최대 길이

    n = len(BARS)
    bar_h = A / (n + (n - 1) * 0.58)
    gap = bar_h * 0.58
    total = n * bar_h + (n - 1) * gap
    y = (size - total) / 2
    r = bar_h * 0.42                # 막대 둥근 정도

    # 0선 척추 (막대 아래에 깔려 막대 사이 틈으로 드러난다)
    sw = max(2, round(size * 0.015))
    d.rounded_rectangle([cx - sw / 2, y - bar_h * 0.35,
                         cx + sw / 2, y + total + bar_h * 0.35],
                        radius=sw / 2, fill=SPINE)

    for frac, col in BARS:
        length = frac * half
        x0, x1 = (cx, cx + length) if length >= 0 else (cx + length, cx)
        d.rounded_rectangle([x0, y, x1, y + bar_h], radius=r, fill=col)
        y += bar_h + gap

    return img


def main():
    os.makedirs(os.path.join(ROOT, 'icons'), exist_ok=True)
    jobs = [
        ('app_icon.png', 512, 0.80),
        (os.path.join('icons', 'icon-192.png'), 192, 0.76),
        (os.path.join('icons', 'icon-512.png'), 512, 0.76),
        (os.path.join('icons', 'maskable-192.png'), 192, 0.60),
        (os.path.join('icons', 'maskable-512.png'), 512, 0.60),
    ]
    for rel, size, ratio in jobs:
        draw_icon(size, ratio).save(os.path.join(ROOT, rel), 'PNG', optimize=True)
        print('wrote', rel)


if __name__ == '__main__':
    main()

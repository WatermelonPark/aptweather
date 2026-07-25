# -*- coding: utf-8 -*-
"""앱 아이콘·파비콘·PWA 아이콘 생성 — 아공맵 '사이클 모래시계'.

빨강/파랑 막대 그래프 모티프를 모래시계 실루엣으로: 가로 막대를 중앙 0축에
대칭으로 쌓되 위·아래는 넓고 가운데(목)에서 좁아진다. 위=빨강(과열/상승),
아래=파랑(침체/하락), 잘록한 목 = 사이클 전환점. '집값은 돌고 돈다'.

**파비콘은 SVG(벡터)가 정본** — 어떤 크기서도 선명. PNG는 PWA/apple-touch
폴백용으로 같은 도형을 고해상 래스터로 생성. 작은 크기 가독성 위해 막대는
반쪽당 4개로 굵게.

산출물:
  favicon.svg            벡터 파비콘(정본, index.html이 우선 참조)
  app_icon.png           512  apple-touch-icon + PNG 폴백
  icons/icon-192.png     192  PWA any
  icons/icon-512.png     512  PWA any
  icons/maskable-192.png 192  PWA maskable
  icons/maskable-512.png 512  PWA maskable

사용: python tools/make_app_icon.py
"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAPER = (244, 246, 245)   # --paper #f4f6f5
RED_BASE = (166, 47, 35)  # 위 판쪽 최고조
RED_NECK = (202, 72, 56)  # 목쪽 선명 빨강
BLU_NECK = (66, 133, 220) # 목쪽 선명 파랑
BLU_BASE = (23, 76, 110)  # 아래 판쪽 바닥
FRAME    = (26, 38, 45)   # 모래시계 위·아래 판

N_HALF = 4                # 반쪽당 막대 수(굵게 → 작은 크기서도 또렷)
NECK   = 0.18             # 목 최소 폭(half 대비)
BASE   = 1.0             # 판쪽 최대 폭
WIDTH_RATIO = 0.80        # 최대폭/높이
CAP_RATIO = 0.052         # 판 두께 / 높이
GAP_RATIO = 0.20          # 막대 간격 / 막대 높이


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _hex(c):
    return '#%02x%02x%02x' % c


def _bars():
    """(중심대비 폭비율 half, RGB) 리스트, 위(빨강)→아래(파랑)."""
    out = []
    for i in range(N_HALF):                     # 위: 판→목
        t = i / (N_HALF - 1)
        out.append((BASE + (NECK - BASE) * t, _lerp(RED_BASE, RED_NECK, t)))
    for i in range(N_HALF):                     # 아래: 목→판
        t = i / (N_HALF - 1)
        out.append((NECK + (BASE - NECK) * t, _lerp(BLU_NECK, BLU_BASE, t)))
    return out


def _geometry(size, fill_ratio):
    H = size * fill_ratio
    halfW = size * fill_ratio * WIDTH_RATIO / 2
    cx = cy = size / 2
    top, bot = cy - H / 2, cy + H / 2
    cap = max(2, size * CAP_RATIO * fill_ratio)
    inner_top, inner_bot = top + cap, bot - cap
    n = N_HALF * 2
    bar_h = (inner_bot - inner_top) / (n + (n - 1) * GAP_RATIO)
    gap = bar_h * GAP_RATIO
    return dict(cx=cx, halfW=halfW, top=top, bot=bot, cap=cap,
                inner_top=inner_top, bar_h=bar_h, gap=gap, r=bar_h * 0.4)


def draw_icon(size, fill_ratio):
    img = Image.new('RGB', (size, size), PAPER)
    d = ImageDraw.Draw(img)
    g = _geometry(size, fill_ratio)
    cx, halfW, cap = g['cx'], g['halfW'], g['cap']
    d.rounded_rectangle([cx - halfW, g['top'], cx + halfW, g['top'] + cap],
                        radius=cap / 2, fill=FRAME)
    d.rounded_rectangle([cx - halfW, g['bot'] - cap, cx + halfW, g['bot']],
                        radius=cap / 2, fill=FRAME)
    y = g['inner_top']
    for frac, col in _bars():
        w = max(frac * halfW, g['bar_h'] * 0.55)
        rr = min(g['r'], w)
        d.rounded_rectangle([cx - w, y, cx + w, y + g['bar_h']], radius=rr, fill=col)
        y += g['bar_h'] + g['gap']
    return img


def build_svg(size=64, fill_ratio=0.86, rounded_bg=True):
    g = _geometry(size, fill_ratio)
    cx, halfW, cap = g['cx'], g['halfW'], g['cap']
    el = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">' % (size, size)]
    if rounded_bg:
        el.append('<rect width="%d" height="%d" rx="%.1f" fill="%s"/>'
                  % (size, size, size * 0.16, _hex(PAPER)))
    def rr(x0, y0, x1, y1, rad, col):
        el.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="%.2f" fill="%s"/>'
                  % (x0, y0, x1 - x0, y1 - y0, rad, _hex(col)))
    rr(cx - halfW, g['top'], cx + halfW, g['top'] + cap, cap / 2, FRAME)
    rr(cx - halfW, g['bot'] - cap, cx + halfW, g['bot'], cap / 2, FRAME)
    y = g['inner_top']
    for frac, col in _bars():
        w = max(frac * halfW, g['bar_h'] * 0.55)
        rad = min(g['r'], w)
        rr(cx - w, y, cx + w, y + g['bar_h'], rad, col)
        y += g['bar_h'] + g['gap']
    el.append('</svg>')
    return '\n'.join(el)


def main():
    import io
    os.makedirs(os.path.join(ROOT, 'icons'), exist_ok=True)
    with io.open(os.path.join(ROOT, 'favicon.svg'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(build_svg())
    print('wrote favicon.svg')
    jobs = [
        ('app_icon.png', 512, 0.86),
        ('app_icon_128.png', 128, 0.86),   # 카카오 링크/프로필 소(권장 128px)
        ('app_icon_640.png', 640, 0.86),   # 카카오 채널 이미지(권장 640x640)
        (os.path.join('icons', 'icon-192.png'), 192, 0.84),
        (os.path.join('icons', 'icon-512.png'), 512, 0.84),
        (os.path.join('icons', 'maskable-192.png'), 192, 0.64),
        (os.path.join('icons', 'maskable-512.png'), 512, 0.64),
    ]
    for rel, size, ratio in jobs:
        draw_icon(size, ratio).save(os.path.join(ROOT, rel), 'PNG', optimize=True)
        print('wrote', rel)


if __name__ == '__main__':
    main()

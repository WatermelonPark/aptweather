# -*- coding: utf-8 -*-
"""aptweather 앱 아이콘 — 알에서 깨는 부린이 병아리.

이모지 폰트 글리프를 굽지 않고 직접 그린다 (재배포 라이선스 회피 + 작은 크기에서 선명).
4배 크기로 그린 뒤 축소해 안티에일리어싱을 얻는다.

사용:  python tools/make_app_icon.py
출력:  app_icon.png, icons/icon-{192,512}.png, icons/maskable-{192,512}.png
"""
import os
from PIL import Image, ImageDraw

S = 4                      # 슈퍼샘플 배율
BASE = 512
NAVY = (22, 32, 58)
BODY = (245, 195, 68)
BODY_DK = (226, 170, 44)
BEAK = (240, 135, 46)
SHELL = (246, 244, 238)
SHELL_DK = (219, 213, 199)
EYE = (22, 32, 58)


def s(v):
    """좌표를 슈퍼샘플 배율로 (튜플은 튜플로 유지 — PIL이 좌표 타입을 가린다)"""
    if isinstance(v, tuple):
        return tuple(s(x) for x in v)
    if isinstance(v, list):
        return [s(x) for x in v]
    return v * S


def zigzag(x0, x1, y, teeth, height, down=False):
    """x0..x1 구간의 톱니 모서리 점들 (깨진 껍질)"""
    pts = []
    step = (x1 - x0) / teeth
    for i in range(teeth):
        a = x0 + i * step
        pts.append((a, y))
        pts.append((a + step / 2, y + height if down else y - height))
    pts.append((x1, y))
    return pts


def draw_chick(size=BASE, inset=1.0):
    """정사각 아이콘 한 장. inset<1 이면 내용을 중앙으로 축소(maskable 안전영역)."""
    W = size * S
    img = Image.new('RGB', (W, W), NAVY)

    # 내용은 512 좌표계로 그린 뒤 통째로 축소·중앙 정렬
    layer = Image.new('RGBA', (BASE * S, BASE * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # --- 몸통 (껍질보다 먼저: 아래쪽은 컵에 가려진다) ---
    d.ellipse(s([126, 108, 386, 368]), fill=BODY)

    # --- 눈 ---
    for cx in (218, 294):
        d.ellipse(s([cx - 16, 198, cx + 16, 230]), fill=EYE)
        d.ellipse(s([cx + 2, 205, cx + 11, 214]), fill=(255, 255, 255))

    # --- 부리 ---
    d.polygon(s([(230, 252), (282, 252), (256, 284)]), fill=BEAK)
    d.polygon(s([(237, 268), (275, 268), (256, 284)]), fill=(214, 108, 32))

    # --- 아래 껍질 컵 (직사각 + 둥근 바닥, 위 모서리는 톱니) ---
    d.rectangle(s([130, 336, 382, 400]), fill=SHELL)
    d.ellipse(s([130, 350, 382, 452]), fill=SHELL)
    d.polygon(s(zigzag(130, 382, 336, 7, 34) + [(382, 362), (130, 362)]), fill=SHELL)

    # --- 머리 위 껍질 조각 (기울여 얹는다) ---
    cw, chh = 156, 96
    cap = Image.new('RGBA', s((cw, chh)), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cap)
    cd.chord(s([4, 0, cw - 4, 124]), 180, 360, fill=SHELL)
    cd.polygon(s(zigzag(4, cw - 4, 60, 5, 28, down=True) + [(cw - 4, 30), (4, 30)]), fill=SHELL)
    cap = cap.rotate(14, resample=Image.BICUBIC, expand=True)
    layer.alpha_composite(cap, (s(256) - cap.width // 2, s(122) - cap.height // 2))

    if inset != 1.0:
        n = int(BASE * S * inset)
        layer = layer.resize((n, n), Image.LANCZOS)
        off = (BASE * S - n) // 2
        pad = Image.new('RGBA', (BASE * S, BASE * S), (0, 0, 0, 0))
        pad.alpha_composite(layer, (off, off))
        layer = pad

    if W != BASE * S:
        layer = layer.resize((W, W), Image.LANCZOS)

    img.paste(layer, (0, 0), layer)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(root, 'icons'), exist_ok=True)

    draw_chick(512).save(os.path.join(root, 'app_icon.png'), optimize=True)
    draw_chick(512).save(os.path.join(root, 'icons', 'icon-512.png'), optimize=True)
    draw_chick(192).save(os.path.join(root, 'icons', 'icon-192.png'), optimize=True)
    # maskable: 원형 크롭에 잘리지 않도록 내용을 72%로
    draw_chick(512, inset=0.72).save(os.path.join(root, 'icons', 'maskable-512.png'), optimize=True)
    draw_chick(192, inset=0.72).save(os.path.join(root, 'icons', 'maskable-192.png'), optimize=True)
    print('icons written')

# -*- coding: utf-8 -*-
"""카카오톡 채널 홈 배경 이미지 생성 (720x940, 카카오 권장 사이즈).

프로필(app_icon_640.png)과 같은 '사이클 모래시계' 도형을 재사용해 톤을 맞춘다.
카카오 채널홈은 하단부가 프로필/버튼 패널에 가려지는 경우가 많아, 핵심 그래픽과
문구를 화면 상단~중단에 배치하고 하단은 여백으로 비운다.

사용: python tools/make_kakao_bg.py
"""
import os
import sys
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_app_icon as ICON  # noqa: E402  (모래시계 도형 재사용)

sys.path.insert(0, os.path.join(ROOT, 'tools'))
from make_beginner_cards import noto  # noqa: E402  (번들 Pretendard)

W, H = 720, 940
PAPER = ICON.PAPER          # (244,246,245) — 아이콘과 동일 톤
INK = (19, 30, 36)          # --ink
INK2 = (76, 95, 102)        # --ink2


def build():
    img = Image.new('RGB', (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # 큰 모래시계(정사각 도형을 상단~중단에 얹는다)
    hg_size = 460
    hg = ICON.draw_icon(hg_size, 0.86)
    hg_x = (W - hg_size) // 2
    hg_y = 96
    img.paste(hg, (hg_x, hg_y))

    # 카피: 워드마크 + 태그라인
    wm_font = noto(46, 'Bold')
    wm = '아공맵'
    wb = d.textbbox((0, 0), wm, font=wm_font)
    d.text(((W - (wb[2] - wb[0])) / 2, hg_y + hg_size + 34), wm,
           font=wm_font, fill=INK)

    tag_font = noto(24, 'Medium')
    tag = '공급을 보면 집값이 보입니다'
    tb = d.textbbox((0, 0), tag, font=tag_font)
    d.text(((W - (tb[2] - tb[0])) / 2, hg_y + hg_size + 34 + (wb[3] - wb[1]) + 18),
           tag, font=tag_font, fill=INK2)

    sub_font = noto(17, 'Medium')
    sub = '전국 아파트 주간·월간 시세 지도'
    sb = d.textbbox((0, 0), sub, font=sub_font)
    d.text(((W - (sb[2] - sb[0])) / 2,
            hg_y + hg_size + 34 + (wb[3] - wb[1]) + 18 + (tb[3] - tb[1]) + 12),
           sub, font=sub_font, fill=INK2)

    return img


def main():
    out = os.path.join(ROOT, 'kakao_bg_720x940.png')
    build().save(out, 'PNG', optimize=True)
    print('wrote', out)


if __name__ == '__main__':
    main()

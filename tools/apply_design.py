# -*- coding: utf-8 -*-
"""자체 CSS를 가진 독립 페이지에 디자인 시스템을 적용한다.

app.css를 공유하지 않는 페이지들(404·burini-test·privacy 등)이 각자 옛 규칙을
들고 있어 감사에서 걸렸다. 페이지마다 손으로 고치면 또 어긋나므로 규칙을
코드로 박아 일괄 적용한다.

사용: python tools/apply_design.py 404.html privacy/index.html ...
"""
import io, os, re, sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FONT_LINK = ('<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>\n'
             '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard'
             '@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">')

# app.css와 동일한 값. 페이지마다 다르면 같은 브랜드가 다른 색을 낸다.
TOKENS = {'--ink': '#131e24', '--ink2': '#4c5f66', '--paper': '#f4f6f5',
          '--paper2': '#e9edeb', '--muted': '#5e6f74', '--line': '#c4cec9'}

DISPLAY = {'h1', 'h2', '.big', '.hero h1'}
TOUCH = ('button', 'input', 'select', '.cta', '.btn', 'a.cta', '.nav-btn')


def cool(h):
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    L = 0.299*r + 0.587*g + 0.114*b
    d = 50.0 * (255.0 - L) / 255.0
    return '%02x%02x%02x' % tuple(max(0, min(255, int(round(x))))
                                  for x in (L - 0.4*d, L + 0.6*d, L + 0.1*d))


def is_warm(h):
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    ch = max(r, g, b) - min(r, g, b)
    L = 0.299*r + 0.587*g + 0.114*b
    return ch <= 32 and (g - b) >= (r - g) and r > b + 4 and 40 <= L <= 254


def apply(path):
    s = io.open(path, encoding='utf-8').read()
    before = s
    log = []

    # 1) 폰트 — 링크가 없으면 font-family 선언은 아무 일도 하지 않는다
    if 'pretendardvariable' not in s.lower():
        m = re.search(r'<meta name="viewport"[^>]*>', s)
        if m:
            s = s.replace(m.group(0), m.group(0) + '\n' + FONT_LINK, 1)
            log.append('폰트 링크')
    if 'Pretendard Variable' not in s:
        s = re.sub(r"font-family:\s*'Pretendard'", "font-family:'Pretendard Variable','Pretendard'", s)
        if 'Pretendard Variable' not in s:   # 아예 선언이 없던 페이지
            s = re.sub(r'(body\s*\{)',
                       r"\1font-family:'Pretendard Variable','Pretendard',-apple-system,"
                       r"'Apple SD Gothic Neo','Malgun Gothic',sans-serif;", s, count=1)
        log.append('폰트 스택')

    # 2) 웨이트 배급 — 표제만 700, 나머지 600
    def fw(mo):
        sel, body = mo.group(1), mo.group(2)
        key = re.sub(r'\s+', ' ', sel.strip())
        return sel + '{' + re.sub(r'font-weight:\s*(?:800|900|700)',
                                  'font-weight:' + ('700' if key in DISPLAY else '600'), body) + '}'
    s2 = re.sub(r'([^{};]+)\{([^{}]*font-weight:\s*(?:800|900|700)[^{}]*)\}', fw, s)
    if s2 != s: log.append('웨이트')
    s = s2

    # <b>는 규칙이 없으면 bolder가 부모에 얹혀 900으로 계산된다(정적 검사로 안 잡힘)
    if not re.search(r'\bb\s*,\s*strong\b|\bstrong\s*,\s*b\b', s):
        s = re.sub(r'(<style[^>]*>)', r'\1b,strong{font-weight:600}', s, count=1)
        log.append('b,strong')

    # 3) 한글에 해로운 조판
    n = len(re.findall(r'letter-spacing:\s*\.(?:0[5-9]|[1-9]\d*)em', s))
    if n:
        s = re.sub(r'\s*letter-spacing:\s*\.(?:0[5-9]|[1-9]\d*)em;?', '', s)
        log.append('자간×%d' % n)
    if 'text-transform:uppercase' in s:
        s = re.sub(r'\s*text-transform:\s*uppercase;?', '', s)
        log.append('uppercase')

    # 4) radius 두 값 — 누르는 것만 3px
    def rad(mo):
        sel, body = mo.group(1), mo.group(2)
        key = re.sub(r'\s+', ' ', sel.strip())
        touch = any(t in key for t in TOUCH)
        return sel + '{' + re.sub(r'border-radius:[^;}]+',
                                  'border-radius:' + ('3px' if touch else '0'), body) + '}'
    s2 = re.sub(r'([^{};]+)\{([^{}]*border-radius:[^{}]*)\}', rad, s)
    if s2 != s: log.append('radius')
    s = s2

    # 5) 색 — 토큰 일치 · 금색 폐기 · 웜 뉴트럴 쿨 전환
    for k, v in TOKENS.items():
        s = re.sub(re.escape(k) + r':\s*#[0-9a-fA-F]{3,6}', k + ':' + v, s)
    s = s.replace('var(--accent)', 'var(--ink)')
    s = s.replace('var(--gold-ink)', 'var(--muted)').replace('var(--gold)', 'var(--ink2)')
    s = re.sub(r'--(?:accent|gold|gold-ink):\s*#[0-9a-fA-F]{3,6};?', '', s)
    warm = [h for h in {x.lower() for x in re.findall(r'#([0-9a-fA-F]{6})\b', s)} if is_warm(h)]
    for h in warm:
        s = re.sub('#' + h, '#' + cool(h), s, flags=re.I)
    if warm: log.append('웜색%d종' % len(warm))

    # 6) 표 헤더 — th,td 묶음 우측 정렬이면 헤더만 가운데로
    if re.search(r'\bth\s*,\s*td\b[^{]*\{[^{}]*text-align:\s*right', s) \
       and not re.search(r'thead\s+th[^{]*\{[^{}]*text-align', s):
        s = re.sub(r'(<style[^>]*>)', r'\1thead th{text-align:center}thead th:first-child{text-align:left}',
                   s, count=1)
        log.append('표헤더')

    if s != before:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    return log


def main():
    targets = sys.argv[1:]
    if not targets:
        print('usage: python tools/apply_design.py <html> [<html> ...]')
        return
    os.chdir(ROOT)
    for t in targets:
        if not os.path.exists(t):
            print('%-26s 없음' % t)
            continue
        log = apply(t)
        print('%-26s %s' % (t, ' · '.join(log) if log else '변경 없음'))


if __name__ == '__main__':
    main()

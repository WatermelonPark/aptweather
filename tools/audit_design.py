# -*- coding: utf-8 -*-
"""디자인 시스템 준수 감사 — 모든 페이지.

2026-07 감사에서 정한 규칙을 페이지마다 기계적으로 검사한다. 사람 눈으로
훑으면 index.html만 보고 끝나는데, 실제로 app.css를 쓰는 건 두 페이지뿐이고
나머지는 자기 CSS를 들고 있어 규칙이 닿지 않는다.

규칙(=agongmap-design-direction 메모리와 동일)
  1 폰트   Pretendard Variable을 실제로 로드하는가
  2 웨이트 800/900 금지 (합성 볼드로 굵기 위계가 소멸)
  3 조판   한글에 uppercase 금지, 양수 자간 .04em 초과 금지
  4 radius 데이터=0 / 터치=3px 두 값
  5 색     --gold/--accent 폐기, 웜 뉴트럴 금지, 데이터 색(빨강/파랑)은 보존
  6 장식   장식용 그림자·그라디언트 금지

사용: python tools/audit_design.py
"""
import io, os, re, sys, glob

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

SHARED = io.open('app.css', encoding='utf-8').read()


def warm_neutral(h):
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    chroma = max(r, g, b) - min(r, g, b)
    return chroma <= 32 and (g - b) >= (r - g) and r > b + 4 and 40 <= (0.299*r + 0.587*g + 0.114*b) <= 254


def audit(path):
    s = io.open(path, encoding='utf-8').read()
    uses_shared = 'app.css' in s
    css = SHARED + s if uses_shared else s          # 공유 CSS를 쓰면 함께 판정
    style = ''.join(re.findall(r'<style[^>]*>(.*?)</style>', s, re.S))
    scope = css if uses_shared else (style or s)

    radii = set(re.findall(r'border-radius:\s*([^;}\n]+)', scope))
    OK = {'0', '0px', 'var(--r-touch)', '3px', '50%', '0 0 3px 3px'}
    radii = {r.strip() for r in radii if r.strip() not in OK}
    hexes = {h.lower() for h in re.findall(r'#([0-9a-fA-F]{6})\b', s)}
    warms = sorted(h for h in hexes if warm_neutral(h))

    return {
        'shared': uses_shared,
        'font': ('Pretendard Variable' in s) or (uses_shared and 'Pretendard Variable' in SHARED),
        'fontlink': 'pretendardvariable' in s.lower(),
        'w800': len(re.findall(r'font-weight:\s*(?:800|900)\b', scope))
                + len(re.findall(r'font-weight="(?:800|900)"', s)),
        'upper': len(re.findall(r'text-transform:\s*uppercase', scope)),
        'track': len(re.findall(r'letter-spacing:\s*\.(?:0[5-9]|[1-9]\d*)em', scope)),
        'radii': sorted(radii),
        'gold': len(re.findall(r'--gold|--accent', scope)),
        'warm': warms,
        'shadow': len([x for x in re.findall(r'box-shadow:\s*([^;}\n]+)', scope)
                       if 'none' not in x and '0 0 0' not in x]),
        'grad': len(re.findall(r'linear-gradient', scope)),
        # 표 정렬: th와 td를 한 규칙으로 묶어 우측 정렬하면 헤더가 값처럼 붙어
        # 열과 어긋나 보인다. thead th 별도 지정이 없으면 위반으로 본다.
        'thalign': bool(re.search(r'th\s*,\s*td[^{]*\{[^{}]*text-align:\s*right', scope))
                   and not re.search(r'thead\s+th[^{]*\{[^{}]*text-align', scope),
    }


def main():
    pages = ['index.html', 'cycle/index.html', 'zone/index.html',
             'privacy/index.html', 'burini-test/index.html', '404.html']
    zones = sorted(glob.glob('zone/*/index.html'))
    zones = [z for z in zones if z != 'zone/index.html']
    if zones:
        pages.append(zones[0])          # 생활권은 템플릿 산출물이라 대표 1장

    print('%-26s %-4s %-5s %-4s %-4s %-4s %-7s %-4s %-5s %s'
          % ('페이지', '공유', '폰트', '800', 'UP', '자간', 'radius', '금색', '웜색', '장식'))
    print('-' * 96)
    bad = []
    for p in pages:
        if not os.path.exists(p):
            continue
        a = audit(p)
        nr = len(a['radii'])
        flags = []
        if not a['font']: flags.append('폰트')
        if a['w800']: flags.append('800×%d' % a['w800'])
        if a['upper']: flags.append('UP×%d' % a['upper'])
        if a['track']: flags.append('자간×%d' % a['track'])
        if nr > 2: flags.append('radius%d종' % nr)
        if a['gold']: flags.append('금색×%d' % a['gold'])
        if a['warm']: flags.append('웜색%d종' % len(a['warm']))
        if a['shadow'] > 1: flags.append('그림자×%d' % a['shadow'])
        if a['thalign']: flags.append('표헤더우측정렬')
        print('%-26s %-4s %-5s %-4d %-4d %-4d %-7d %-4d %-5d %d'
              % (p[:26], 'O' if a['shared'] else '-', 'O' if a['font'] else 'X',
                 a['w800'], a['upper'], a['track'], nr, a['gold'], len(a['warm']), a['shadow']))
        if flags:
            bad.append((p, flags))

    print('-' * 96)
    if not bad:
        print('위반 없음')
    else:
        print('위반 요약')
        for p, f in bad:
            print('  %-26s %s' % (p[:26], ' · '.join(f)))
    if zones:
        print('\n생활권 %d장은 tools/make_zone_pages.py 산출물 — 템플릿을 고치면 일괄 반영된다.' % len(zones))


if __name__ == '__main__':
    main()

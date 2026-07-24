# -*- coding: utf-8 -*-
"""이중 구현 정합성 검사 — index.html scCalc  vs  make_zone_pages.py calc().

아공맵 스코어는 두 곳에 각각 구현돼 있다:
  · index.html  `scCalc()`        — 홈 순위표·생활권 지도 타일
  · tools/make_zone_pages.py `calc()` — /zone/ 생활권 리포트

한쪽만 고치면 같은 지표가 화면마다 다른 값으로 나온다.
2026-07-20에 실제로 발생 — scCalc에만 dA 정규화(×12/H)가 남아 홈이 2.4배로 표시됐다.

이 스크립트는 Node로 scCalc를 실제 실행해 calc()와 생활권별로 대조한다.
불일치가 있으면 종료코드 1. 배치·배포 전에 돌릴 것.

사용: python tools/check_dual_calc.py
"""
import io, os, re, sys, json, subprocess, tempfile

# cp949 콘솔에서도 요약 출력(— 등)이 죽지 않도록(split_data.py와 동일 처리).
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import make_zone_pages as M

TOL = 1.0          # 세대 단위 허용 오차 (부동소수 반올림)


def js_side():
    """index.html에서 scCalc 관련 코드를 떼어내 Node로 실행."""
    html = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()

    def grab(pat, name):
        m = re.search(pat, html, re.S)
        if not m:
            raise SystemExit('index.html에서 %s 를 찾지 못했다 — 구조가 바뀌었는지 확인할 것' % name)
        return m.group(0)

    # scCalc는 외부 헬퍼(runningShortage·_qkey·_conf·ANCHOR)에 의존한다. HUB 러닝재고
    # 재작성으로 생긴 이 함수들을 함께 떼오지 않으면, activate=true일 때 scCalc가
    # runningShortage를 부르며 ReferenceError로 죽어 미러 검증 자체가 크래시한다.
    fn = grab(r'function scCalc\(\)\{.*?\n\}', 'scCalc')
    qkey = grab(r'function _qkey\(i\)\{[^}]*\}', '_qkey')
    conf = grab(r'function _conf\(k\)\{[^}]*\}', '_conf')
    anchor = grab(r'var ANCHOR=[^;\n]*;', 'ANCHOR')
    rsh = grab(r'function runningShortage\([^)]*\)\{.*?\n\}', 'runningShortage')
    data = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()

    src = """
%s
%s
%s
%s
%s
%s
const out = scCalc().map(z => ({z: z.z, dA: z.dA, dB: z.dB, dC: z.dC, tot: z.tot}));
console.log(JSON.stringify(out));
""" % (data, qkey, conf, anchor, rsh, fn)
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(src)
        path = f.name
    try:
        # encoding 명시 필수 — 생략하면 Windows에서 cp949로 읽다가 한글에 깨진다
        r = subprocess.run(['node', path], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=120)
        if r.returncode != 0:
            raise SystemExit('scCalc 실행 실패:\n' + r.stderr[:600])
        return {x['z']: x for x in json.loads(r.stdout)}
    finally:
        os.unlink(path)


def main():
    adv, sts = M.load()
    py = {r['z']['z']: r for r in M.calc(adv, sts)}
    js = js_side()

    only_py = sorted(set(py) - set(js))
    only_js = sorted(set(js) - set(py))
    bad = []
    for z in sorted(set(py) & set(js)):
        for k in ('dA', 'dB', 'dC', 'tot'):
            a, b = py[z][k], js[z][k]
            if abs(a - b) > TOL:
                bad.append((z, k, a, b))

    print('생활권 — calc() %d곳 · scCalc %d곳 · 공통 %d곳'
          % (len(py), len(js), len(set(py) & set(js))))
    if only_py:
        print('  ⚠️ calc()에만 있음:', ', '.join(only_py))
    if only_js:
        print('  ⚠️ scCalc에만 있음:', ', '.join(only_js))

    if bad:
        print()
        print('❌ 불일치 %d건 (같은 지표가 화면마다 다르게 나온다)' % len(bad))
        print('%-11s %5s %14s %14s %10s' % ('생활권', '항목', 'calc()/zone', 'scCalc/홈', '배율'))
        for z, k, a, b in bad[:20]:
            print('%-11s %5s %14s %14s %10s' % (
                z, k, format(int(a), ','), format(int(b), ','),
                ('%.2f' % (b / a)) if a else '-'))
        if len(bad) > 20:
            print('  ... 외 %d건' % (len(bad) - 20))
        return 1

    print('✅ 두 구현이 모든 생활권에서 일치한다 (dA·dB·dC·tot)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

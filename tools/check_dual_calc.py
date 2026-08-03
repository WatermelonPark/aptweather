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


def js_side(data_file='data.js'):
    """index.html에서 scCalc 관련 코드를 떼어내 Node로 실행.

    data_file: 어떤 데이터로 돌릴지. 기본은 data.js지만, **브라우저가 실제로 받는 건
    data-core.js**다(split_data가 홈이 쓰는 조각만 추린 것). 둘 다 돌려 비교하면
    'scCalc에 새 의존을 추가하고 split_data의 CORE_ADV/CORE_STATS에 넣는 걸 잊은'
    경우를 잡는다 — 그러면 라이브 홈만 조용히 폴백으로 떨어진다(2026-08-04 감사).
    """
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
    # 과거 재고 창(분기). 함수 밖 상수라 여기서 같이 떼와야 ReferenceError가 안 난다.
    cap = grab(r'var BACKLOG_WINDOW=[^;\n]*;', 'BACKLOG_WINDOW')
    sgrade = grab(r'var GRADE_CUTS=.*?\nfunction scGrade\([^)]*\)\{.*?\n\}', 'scGrade')
    rsh = grab(r'function runningShortage\([^)]*\)\{.*?\n\}', 'runningShortage')
    # 정렬(zoneOrder)과 판정 문장(mzHeadline)도 이중구현이다 — 여기서 안 떼오면
    # 대조할 수 없고, 대조하지 않으면 조용히 갈라진다(2026-08-04 감사에서 실제로
    # 순위는 44곳 중 38곳, 문구는 8곳이 갈라져 있었다).
    gorder = grab(r'var GORDER=\[[^\]]*\];', 'GORDER')
    zorder = grab(r'function zoneOrder\(rows\)\{.*?\n\}', 'zoneOrder')
    slab = grab(r'const MZ_SLAB=\[[^\]]*\];', 'MZ_SLAB')
    mzh = grab(r'function mzHeadline\([^)]*\)\{.*?\n\}', 'mzHeadline')
    data = io.open(os.path.join(ROOT, data_file), encoding='utf-8').read()
    # data-core.js는 `const ADV=...` 형태라 그대로 붙여도 되지만, window 전역을
    # 건드리는 꼬리(window.__DATA_CORE__)가 있어 Node에서 죽는다 — 무해화한다.
    if data_file != 'data.js':
        data = 'var window={};\n' + data

    src = """
%s
%s
%s
%s
%s
%s
%s
%s
%s
%s
%s
%s
const rows = scCalc();
const order = zoneOrder(rows).map(z => z.z);
const out = rows.map(z => ({z: z.z, dA: z.dA, dB: z.dB, dC: z.dC, tot: z.tot, need4: z.need4,
                            gk: z.gr.k, seq: z.seq || [],
                            desc: mzHeadline(z.seq || [], z.gr.desc, z.gr.k)}));
console.log(JSON.stringify({rows: out, order: order}));
""" % (data, qkey, conf, anchor, cap, sgrade, gorder, zorder, rsh, fn, slab, mzh)
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(src)
        path = f.name
    try:
        # encoding 명시 필수 — 생략하면 Windows에서 cp949로 읽다가 한글에 깨진다
        r = subprocess.run(['node', path], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=120)
        if r.returncode != 0:
            raise SystemExit('scCalc 실행 실패(%s):\n%s' % (data_file, r.stderr[:600]))
        d = json.loads(r.stdout)
        return {x['z']: x for x in d['rows']}, d['order']
    finally:
        os.unlink(path)


def main():
    adv, sts = M.load()
    rows = M.calc(adv, sts)
    py = {r['z']['z']: r for r in rows}
    py_order = [r['z']['z'] for r in M.zone_order(rows)]
    js, js_order = js_side()

    only_py = sorted(set(py) - set(js))
    only_js = sorted(set(js) - set(py))
    bad = []
    for z in sorted(set(py) & set(js)):
        for k in ('dA', 'dB', 'dC', 'tot', 'need4'):
            a, b = py[z][k], js[z][k]
            if abs(a - b) > TOL:
                bad.append((z, k, a, b))
        if py[z]['gr']['k'] != js[z]['gk']:
            bad.append((z, 'grade', py[z]['gr']['k'], js[z]['gk']))
        # 5칸 재고 궤적 — 존 페이지 타임라인과 홈 카드 바가 같은 값을 그려야 한다.
        pseq = py[z].get('seq') or []
        jseq = js[z].get('seq') or []
        if len(pseq) != len(jseq) or any(abs(a - b) > TOL for a, b in zip(pseq, jseq)):
            bad.append((z, 'seq', pseq, jseq))
        # 판정 문장 — hero_line(Python) ↔ mzHeadline(JS)
        pd = M.hero_line(pseq, py[z]['gr'])
        if pd != js[z].get('desc'):
            bad.append((z, 'desc', pd, js[z].get('desc')))
    # 나열 순서 — 존 페이지 'N위'와 홈 순위가 같은 잣대여야 한다.
    if py_order != js_order:
        diff = [i + 1 for i, (a, b) in enumerate(zip(py_order, js_order)) if a != b]
        bad.append(('(전체)', 'order', '%d자리 어긋남 %s' % (len(diff), diff[:6]), ''))

    if only_py:
        bad.append(('(전체)', 'zones', 'calc()에만 있음: ' + ', '.join(only_py), ''))
    if only_js:
        bad.append(('(전체)', 'zones', 'scCalc에만 있음: ' + ', '.join(only_js), ''))

    # ── 브라우저가 실제로 받는 데이터로도 같은 결과가 나오는가 ──────────────
    # 위 대조는 data.js로 돌았다. 홈은 data-core.js만 받는다(split_data가 추린 것).
    # scCalc에 새 의존을 넣고 CORE_ADV/CORE_STATS에 추가하는 걸 잊으면, 여기서만
    # 폴백으로 떨어져 라이브 홈이 조용히 다른 값을 낸다.
    core_path = os.path.join(ROOT, 'data-core.js')
    if os.path.exists(core_path):
        try:
            jsc, _ = js_side('data-core.js')
        except SystemExit as e:
            bad.append(('(전체)', 'core', 'data-core.js로 scCalc 실행 실패: %s' % e, ''))
            jsc = None
        if jsc is not None:
            for z in sorted(set(js) & set(jsc)):
                for k in ('tot', 'need4'):
                    if abs(js[z][k] - jsc[z][k]) > TOL:
                        bad.append((z, 'core:' + k, js[z][k], jsc[z][k]))
                if js[z]['gk'] != jsc[z]['gk']:
                    bad.append((z, 'core:grade', js[z]['gk'], jsc[z]['gk']))
            miss = sorted(set(js) - set(jsc))
            if miss:
                bad.append(('(전체)', 'core', 'data-core.js에서 사라진 존: %s' % ', '.join(miss[:5]), ''))

    print('생활권 — calc() %d곳 · scCalc %d곳 · 공통 %d곳'
          % (len(py), len(js), len(set(py) & set(js))))

    if bad:
        print()
        print('❌ 불일치 %d건 (같은 지표가 화면마다 다르게 나온다)' % len(bad))
        print('%-11s %-10s %s' % ('생활권', '항목', 'calc()/zone  vs  scCalc/홈'))
        for z, k, a, b in bad[:20]:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                mul = ('  (배율 %.2f)' % (b / a)) if a else ''
                print('%-11s %-10s %s  vs  %s%s'
                      % (z, k, format(int(a), ','), format(int(b), ','), mul))
            else:
                print('%-11s %-10s %s  vs  %s' % (z, k, a, b))
        if len(bad) > 20:
            print('  ... 외 %d건' % (len(bad) - 20))
        return 1

    print('✅ 두 구현이 모든 생활권에서 일치한다'
          ' (dA·dB·dC·tot·need4·grade·seq·판정문·나열순서, data-core.js 포함)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

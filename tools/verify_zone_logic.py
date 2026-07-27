# -*- coding: utf-8 -*-
"""기준표 논리를 생활권 단위로 실증한다.

검증할 주장
  A. 공급이 부족한 생활권일수록 가격이 더 오른다 (공급이 알파이자 오메가)
  B. 전세가 매매를 선행한다 (공급 부족 → 전세 ↑ → 매매 ↑)

데이터: data.js의 ADV.weekly.sgg(R-ONE, 156주 = 3년)를 그대로 읽는다.
과거엔 12주뿐이라 KOSIS 3년치를 따로 받았지만, 2026-07-28 시군구 시계열
확장으로 재조회가 필요 없어졌다.

⚠️ 이 표의 DT는 지수가 아니라 **이미 주간 변동률(%)**이다(UNIT_NM='%').
   지수로 착각해 b/a−1을 하면 −1000% 같은 값이 나온다. 누적은 복리로 합치고,
   시차상관은 차분 없이 원계열을 그대로 쓴다.

실행: python tools/verify_zone_logic.py
"""
import io, os, re, sys, json, statistics

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
os.chdir(ROOT)

# 키 주입 (값은 출력하지 않는다)
kf = os.path.expanduser('~/.aptweather_keys.bat')
if os.path.exists(kf):
    for m in re.finditer(r'set\s+(\w+)=(.*)', io.open(kf, encoding='utf-8', errors='replace').read()):
        os.environ.setdefault(m.group(1), m.group(2).strip())
os.environ.pop('BUTTONDOWN_API_KEY', None)

import update_adv_data as U  # noqa: E402

WEEKS = 156          # 3년
LAGS = range(0, 13)  # 전세→매매 선행 검사 구간(주)


def load_zones():
    src = io.open('data.js', encoding='utf-8').read()
    adv = json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S).group(1))
    return adv['livezone']['zones']


def fetch_sgg(metric):
    """시군구 주간 변동률(%) → {주차: {코드: 값}}.
    KOSIS 재조회를 버리고 data.js의 ADV.weekly.sgg를 읽는다(2026-07-28) —
    시군구 시계열이 156주로 확장돼("최근 12주만" 전제가 낡음) 원천 재조회가
    불필요해졌고, KOSIS 주간 폴백 헬퍼도 같은 날 제거됐다. R-ONE 값도 KOSIS와
    동일하게 '이미 주간 변동률(%)'이다."""
    src = io.open('data.js', encoding='utf-8').read()
    adv = json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S).group(1))
    sgg = adv['weekly']['sgg']
    return {r['p']: {c: v for c, v in zip(sgg['codes'], r[metric]) if v is not None}
            for r in sgg['rows']}


def code_name_map():
    """코드→시군구명. index.html의 SGG_QNAME('서울 강남구'·'성남 분당구')에서
    마지막 토큰만 취하면 KOSIS C1_NM('강남구'·'분당구')과 같은 꼴이 된다.
    (SGG_QNAME은 프론트 상수라 백엔드 모듈엔 없다 — data.js처럼 정규식으로 읽는다.)"""
    src = io.open('index.html', encoding='utf-8').read()
    qn = json.loads(re.search(r'const SGG_QNAME=(\{.*?\});', src, re.S).group(1))
    return {c: n.split()[-1] for c, n in qn.items()}


def norm(n):
    """KOSIS는 '양산'·'제주', 생활권 데이터는 '평택시'·'천안시'로 접미사가 다르다."""
    return re.sub(r'(시|군|구)$', '', (n or '').strip())


def to_zone_series(sgg_rows, c2n, zones):
    """시군구 지수를 생활권으로 묶는다. 가중치는 그 생활권 안에서의 입주예정 세대수."""
    zseries = {}
    for z in zones:
        members = {norm(n): v for n, v in (z.get('sgg') or [])}
        if not members:
            continue
        tot = sum(members.values()) or 1
        s = {}
        for wk, vals in sgg_rows.items():
            acc, wsum = 0.0, 0
            for code, v in vals.items():
                nm = norm(c2n.get(code, ''))
                if nm in members:
                    acc += v * members[nm]
                    wsum += members[nm]
            if wsum >= tot * 0.5:        # 절반 이상 잡힐 때만 (누락 지역 왜곡 방지)
                s[wk] = acc / wsum
        if len(s) >= 60:
            zseries[z['z']] = s
    return zseries


def cum_change(series, weeks):
    """주간 변동률(%)을 복리로 합쳐 누적 변동률(%)을 낸다."""
    ks = sorted(series)[-weeks:]
    if len(ks) < weeks * 0.8:
        return None
    acc = 1.0
    for k in ks:
        acc *= (1 + series[k] / 100.0)
    return (acc - 1) * 100


def corr(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = (sum((x - mx) ** 2 for x in xs) ** .5) * (sum((y - my) ** 2 for y in ys) ** .5)
    return num / dx if dx else None


def main():
    zones = load_zones()
    print('생활권 %d곳 · data.js에서 시군구 주간 변동률(R-ONE) 로드 중...' % (len(zones), WEEKS))
    c2n = code_name_map()
    ma = fetch_sgg('ma')
    je = fetch_sgg('je')
    print('  수집 완료: 매매 %d주 · 전세 %d주 · 시군구 코드 %d개'
          % (len(ma), len(je), len(c2n)))

    zma = to_zone_series(ma, c2n, zones)
    zje = to_zone_series(je, c2n, zones)
    print('  생활권으로 묶인 곳: 매매 %d · 전세 %d' % (len(zma), len(zje)))

    # ── 주장 A: 공급 강도 vs 이후 가격 ──────────────────────────
    print('\n[A] 공급이 부족한 생활권일수록 가격이 더 올랐나')
    rows = []
    for z in zones:
        nm = z['z']
        if nm not in zma:
            continue
        inten = z.get('inten')
        chg = cum_change(zma[nm], 52)
        if inten is None or chg is None:
            continue
        rows.append((nm, inten, chg))
    if len(rows) >= 5:
        xs = [r[1] for r in rows]
        ys = [r[2] for r in rows]
        c = corr(xs, ys)
        print('  표본 %d곳 · 공급강도(만명당 예정세대) vs 최근 1년 매매변동률' % len(rows))
        print('  상관계수 r = %+.3f' % c)
        print('  기준표 논리대로면 음수(공급 많을수록 덜 오름)여야 한다 → %s'
              % ('부합' if c < -0.1 else ('반대' if c > 0.1 else '무관계에 가까움')))
        rows.sort(key=lambda r: r[1])
        print('  공급 적은 5곳: ' + ', '.join('%s(%.0f→%+.2f%%)' % (n, i, c2) for n, i, c2 in rows[:5]))
        print('  공급 많은 5곳: ' + ', '.join('%s(%.0f→%+.2f%%)' % (n, i, c2) for n, i, c2 in rows[-5:]))
    else:
        print('  표본 부족(%d곳) — 판단 불가' % len(rows))

    # ── 주장 B: 전세가 매매를 선행하는가 ───────────────────────
    print('\n[B] 전세가 매매를 선행하는가 (생활권별 시차상관)')
    best = []
    for nm in sorted(set(zma) & set(zje)):
        m, j = zma[nm], zje[nm]
        ks = sorted(set(m) & set(j))
        if len(ks) < 80:
            continue
        dm = [m[k] for k in ks]      # 이미 주간 변동률 — 차분하지 않는다
        dj = [j[k] for k in ks]
        scores = []
        for lag in LAGS:
            if lag >= len(dm) - 20:
                break
            c = corr(dj[:len(dj) - lag] if lag else dj, dm[lag:])
            if c is not None:
                scores.append((c, lag))
        if scores:
            c, lag = max(scores)
            best.append((nm, lag, c))
    if best:
        lags = [b[1] for b in best]
        print('  표본 %d곳 · 전세 변동이 매매 변동을 가장 잘 설명하는 시차' % len(best))
        print('  중앙값 %d주 · 평균 %.1f주' % (statistics.median(lags), sum(lags) / len(lags)))
        lead = sum(1 for l in lags if l > 0)
        print('  전세가 앞선 곳 %d / %d (%.0f%%)' % (lead, len(lags), lead / len(lags) * 100))
        best.sort(key=lambda b: -b[2])
        print('  상관 높은 5곳: ' + ', '.join('%s(%d주,r=%.2f)' % b for b in best[:5]))
    else:
        print('  표본 부족 — 판단 불가')


if __name__ == '__main__':
    main()

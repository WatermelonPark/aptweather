# -*- coding: utf-8 -*-
"""생활권별 공급 리포트 페이지 생성 — /zone/<생활권>/index.html

index.html의 ADV(livezone·occupancy·permits·bubble)와 STATS(전세가율·주택멸실)를 읽어
아공맵 점수 산출 근거를 서술형으로 풀어쓴 정적 페이지를 생활권 수만큼 만든다.
홈의 요약 카드가 "무슨 말인지 모르겠다"는 문제를 풀고, 검색 유입(SEO) 창구가 된다.

사용:  python tools/make_zone_pages.py         # 생성 + sitemap 갱신
"""
import io, os, re, json, sys, datetime
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'index.html')
SITE = 'https://www.agongmap.co.kr'
H_MAX = 8  # 앞으로 최대 8분기 — 실제로는 데이터가 있는 미래 분기 수만 사용
LB = 12  # 과거 누적 3년(12분기) — 부족은 재고처럼 쌓이므로 1년으로는 부족
W = (0.55, 0.35, 0.10)


def load():
    t = io.open(INDEX, encoding='utf-8').read()
    adv = json.loads(re.search(r'/\*ADV_DATA_START\*/const ADV=(\{.*?\});\s*/\*ADV_DATA_END\*/', t, re.S).group(1))
    sts = json.loads(re.search(r'/\*STATS_DATA_START\*/const STATS=(\{.*?\});\s*/\*STATS_DATA_END\*/', t, re.S).group(1))
    return adv, sts


def last_of(series, key):
    s = (series or {}).get(key)
    if not s:
        return 0
    for v in reversed(s):
        if v is not None:
            return v
    return 0


def calc(adv, sts):
    """홈 renderScoreSec(scCalc)와 동일한 산식으로 생활권별 누적 순부족을 계산."""
    LZ, O, P, B = adv['livezone'], adv['occupancy'], adv['permits'], adv.get('bubble') or {}
    J = (sts.get('전세가율') or {}).get('series') or {}
    DM = (sts.get('주택멸실') or {}).get('series') or {}
    SP = LZ.get('sidopop') or {}
    act = [r for r in O['rows'] if not r.get('e')]
    ph = P['rows'][-2:]
    today = datetime.date.today()
    cur_q = today.year * 4 + (today.month - 1) // 3        # 현재 분기 인덱스
    def qi(k):
        m = re.match(r'^(\d{4})Q([1-4])$', k)
        return int(m.group(1)) * 4 + int(m.group(2)) - 1 if m else None
    # 전역 미래 분기 창 — 모든 생활권이 같은 창을 써야 절대량 비교가 성립
    allq = {k for zz in LZ['zones'] for k in (zz.get('byq') or {})}
    FUTQ = sorted([k for k in allq if qi(k) is not None and qi(k) > cur_q], key=qi)[:H_MAX]
    HQ = max(1, len(FUTQ))
    def fut_supply(zz):
        b = zz.get('byq') or {}
        return sum(b.get(k, 0) for k in FUTQ), HQ
    out = []
    for z in LZ['zones']:
        ps = '수도권' if z['region'] == '수도권' else (z.get('psido') or '수도권')
        if ps not in O['regions']:
            continue
        oi = O['regions'].index(ps)
        band = (O.get('band') or {}).get(ps)
        refq = (O.get('ref') or {}).get(ps) or (sum(band) / 2 if band else None)
        if not refq:
            continue
        share = min(1.0, z['pop'] / (SP.get(ps) or z['pop'] or 1))
        dY = last_of(DM, ps); dQ = dY / 4.0
        fsup, H = fut_supply(z)
        need = refq * H * share
        dA = need - fsup
        n4 = [r['v'][oi] for r in act[-LB:] if r['v'][oi] is not None]
        dB = (refq * len(n4) - (sum(n4) - dQ * len(n4))) * share if n4 else 0
        dC = 0; pv = None; plo = None
        if ps in P['regions']:
            pi = P['regions'].index(ps)
            vals = [r['v'][pi] for r in ph]
            if all(v is not None for v in vals):
                pv = sum(vals); plo = P['ref'][ps][0]
                dC = (plo - (pv - dY)) * share
        tot = W[0] * dA + W[1] * dC + W[2] * dB
        flag = None; lo = hi = None
        cv = (B.get('conv') or {}).get(ps)
        jr = last_of(J, ps) or None
        loan = (B.get('loan') or {}).get('v')
        if cv and jr and loan:
            lo = jr / 100.0 * cv; hi = lo * 2
            flag = 'warn' if loan >= hi else ('watch' if loan <= lo else None)
        out.append(dict(z=z, ps=ps, share=share, need=need, dA=dA, dB=dB, dC=dC, tot=tot, fsup=fsup, fq=H,
                        flag=flag, lo=lo, hi=hi, loan=loan, pv=pv, plo=plo, dY=dY, refq=refq, band=band))
    out.sort(key=lambda r: -r['tot'])
    return out


def make_capital(rows):
    """수도권 16개 생활권을 하나로 합친 unit — 홈 순위표와 같은 기준."""
    caps = [r for r in rows if r['z']['region'] == '수도권']
    if not caps:
        return None
    agg = dict(caps[0])
    q0s = [c['z'].get('q0') for c in caps if c['z'].get('q0')]
    q1s = [c['z'].get('q1') for c in caps if c['z'].get('q1')]
    agg['z'] = {'z': '수도권', 'region': '수도권',
                'pop': sum(c['z']['pop'] for c in caps),
                'supply': sum(c['z']['supply'] for c in caps),
                'sgg': [], 'q0': min(q0s) if q0s else '', 'q1': max(q1s) if q1s else '',
                'span': 1 if q0s else 0}
    for k in ('need', 'dA', 'dB', 'dC', 'tot', 'fsup'):
        agg[k] = sum(c[k] for c in caps)
    agg['fq'] = max(c['fq'] for c in caps)
    agg['share'] = sum(c['share'] for c in caps)
    agg['ps'] = '수도권'
    agg['subs'] = sorted(caps, key=lambda c: -c['tot'])
    return agg


def tier(v):
    if v >= 30000: return ('공급 절벽', '#a93226')
    if v >= 5000:  return ('공급 부족', '#c0392b')
    if v >= -2000: return ('수급 균형', '#6f6a5c')
    return ('공급 과잉', '#1a5276')


def num(v):
    return '{:,}'.format(int(round(v)))


def signed(v):
    """화면 표기는 부호 반전 — 부족을 음수로."""
    d = -v
    s = '−' if d < 0 else '+'
    a = abs(d)
    return s + ('{:,}'.format(int(round(a))))


CSS = """:root{--ink:#16203a;--ink2:#3b4569;--paper:#f6f4ee;--accent:#3d4a8a;--muted:#6f6a5c;--line:#dad5c9}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--paper);color:var(--ink);word-break:keep-all;overflow-wrap:break-word;
 font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
 line-height:1.75;-webkit-font-smoothing:antialiased}
.wrap{max-width:620px;margin:0 auto;padding:0 22px}
header{padding:44px 0 28px;text-align:center}
.chip{display:inline-block;font-size:12.5px;font-weight:800;letter-spacing:.08em;color:#fff;
 background:var(--accent);padding:5px 14px;border-radius:20px;margin-bottom:14px}
h1{font-size:clamp(25px,5.6vw,34px);font-weight:800;letter-spacing:-.02em;line-height:1.28;margin-bottom:12px}
.lead{font-size:15.5px;color:var(--ink2)}
.big{font-size:clamp(34px,9vw,48px);font-weight:800;letter-spacing:-.02em;margin:6px 0 2px}
.bigsub{font-size:13.5px;color:var(--muted)}
section{padding:30px 0;border-top:1px solid var(--line)}
h2{font-size:19.5px;font-weight:800;margin-bottom:12px}
p{font-size:15px;color:var(--ink2);margin-bottom:11px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:11px}
.card b{display:block;font-size:15px;color:var(--ink);margin-bottom:5px}
.card span{font-size:13.5px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:14px;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}
thead th{background:#f1eee6;font-size:12.5px;color:var(--muted)}
tbody tr:last-child td{border-bottom:0}
.num{font-variant-numeric:tabular-nums;font-weight:700}
.cta{display:block;max-width:400px;margin:22px auto 0;text-align:center;text-decoration:none;
 background:var(--ink);color:#fff;font-size:16.5px;font-weight:800;padding:15px 22px;border-radius:14px}
.zlist{display:flex;flex-wrap:wrap;gap:7px;margin-top:6px}
.zlist a{font-size:12.5px;font-weight:700;text-decoration:none;color:var(--ink2);background:#fff;
 border:1px solid var(--line);border-radius:9px;padding:5px 9px}
.note{font-size:12.5px;color:var(--muted);line-height:1.8}
footer{padding:26px 0 40px;text-align:center;font-size:12.5px;color:var(--muted);border-top:1px solid var(--line)}
footer a{color:var(--muted)}
.disc{font-size:12px;color:var(--muted);line-height:1.75;margin-top:14px}
@media(max-width:560px){
 table,tbody,tr,td{display:block;width:100%}
 thead{display:none}
 tr{border-bottom:1px solid var(--line);padding:13px 14px}
 tbody tr:last-child{border-bottom:0}
 td{border:0;padding:3px 0;text-align:left;display:flex;justify-content:space-between;align-items:baseline;gap:12px}
 td.lbl{display:block;font-weight:800;color:var(--ink);font-size:14.5px;margin-bottom:7px}
 td.lbl .note{display:block;font-weight:400;margin-top:2px}
 td[data-l]::before{content:attr(data-l);font-size:12.5px;color:var(--muted);font-weight:700;flex:none}
}"""


def build_page(r, allrows, prd, today):
    z = r['z']; nm = z['z']; ps = r['ps']
    tname, tcol = tier(r['tot'])
    lack = r['tot'] > 0
    disp = signed(r['tot'])
    sgg = z.get('sgg') or []
    subs = r.get('subs') or []
    if subs:
        members = '%d개 생활권 · 인구 %s명 · 향후 2년 입주예정 %s세대' % (len(subs), num(z['pop']), num(z['supply']))
        sublist = ('<div class="zlist" style="margin-top:9px">' +
                   ''.join('<a href="/zone/%s/">%s %s</a>' % (c['z']['z'], c['z']['z'], signed(c['tot']))
                           for c in subs) + '</div>')
        sgg_names = [c['z']['z'] for c in subs]
    else:
        members = ' · '.join('%s %s세대' % (s[0], num(s[1])) for s in sgg) if sgg else '입주예정 단지 없음'
        sublist = ''
        sgg_names = [s[0] for s in sgg]
    # 서술
    head_line = ('%s은 앞으로 아파트가 <b>모자랄</b> 쪽입니다.' % nm) if lack else \
                ('%s은 앞으로 아파트가 <b>남을</b> 쪽입니다.' % nm)
    if subs:
        ranktxt = '수도권 %d개 생활권 합계' % len(subs)
    else:
        rk = [i for i, x in enumerate(allrows, 1) if x['z']['z'] == nm]
        ranktxt = ('생활권 %d곳 중 %d위' % (len(allrows), rk[0])) if rk else ''
    span = ('%s~%s' % (z.get('q0'), z.get('q1'))) if z.get('span') else '예정 없음'

    rows_html = ''.join([
        '<tr><td class="lbl">앞으로 ' + str(r['fq']) + '분기, 입주 예정<br><span class="note">생활권 실측 · 가중 0.55</span></td>'
        '<td class="num" data-l="적정">%s</td><td class="num" data-l="실제">%s</td><td class="num" data-l="부족분" style="color:%s">%s</td></tr>' % (
            num(r['need']), num(r['fsup']), '#a93226' if r['dA'] > 0 else '#1a5276', signed(r['dA'])),
        '<tr><td class="lbl">인허가 — 3~4년 뒤 입주<br><span class="note">시도 배분 추정 · 가중 0.35</span></td>'
        '<td class="num" data-l="적정">%s</td><td class="num" data-l="실제">%s</td><td class="num" data-l="부족분" style="color:%s">%s</td></tr>' % (
            num(r['plo'] * r['share']) if r['plo'] else '·',
            num((r['pv'] - r['dY']) * r['share']) if r['pv'] is not None else '·',
            '#a93226' if r['dC'] > 0 else '#1a5276', signed(r['dC'])),
        '<tr><td class="lbl">최근 3년, 입주 실적<br><span class="note">시도 배분 추정 · 가중 0.10</span></td>'
        '<td class="num" data-l="적정">%s</td><td class="num" data-l="실제">·</td><td class="num" data-l="부족분" style="color:%s">%s</td></tr>' % (
            num(r['refq'] * LB * r['share']),
            '#a93226' if r['dB'] > 0 else '#1a5276', signed(r['dB'])),
    ])

    flag_html = ''
    if r['flag'] == 'watch':
        flag_html = ('<section><div class="wrap"><h2>★ 저평가 신호가 함께 켜져 있습니다</h2>'
            '<p>%s의 주택담보대출 금리(<b>%.2f%%</b>)가 임대수익으로 계산한 매수신호선(<b>%.1f%%</b>)보다 낮습니다. '
            '전세를 끼고 보유할 때 <b>임대수익이 이자 부담을 덮는 구간</b>이라는 뜻입니다. '
            '공급이 모자란 상태에서 이 신호가 같이 켜지면, 보유 비용 부담이 적은 채로 공급 부족을 기다릴 수 있는 조건이 됩니다.</p></div></section>'
            % (ps, r['loan'], r['lo']))
    elif r['flag'] == 'warn':
        flag_html = ('<section><div class="wrap"><h2>⚠ 보유 부담 주의</h2>'
            '<p>%s의 주택담보대출 금리(<b>%.2f%%</b>)가 임대수익 대비 위험선(<b>%.1f%%</b>)을 넘었습니다. '
            '과거 2008년·2022년 급락기가 이 조건에서 시작됐습니다. 공급이 모자라더라도 <b>보유 비용이 수익을 잠식</b>하는 구간이라 '
            '단기 진입에는 신중할 필요가 있습니다.</p></div></section>' % (ps, r['loan'], r['hi']))

    navsrc = [x for x in allrows if x['z']['region'] != '수도권']
    nav = '<a href="/zone/수도권/">수도권</a>' if nm != '수도권' else ''
    nav += ''.join('<a href="/zone/%s/">%s</a>' % (x['z']['z'], x['z']['z'])
                   for x in navsrc if x['z']['z'] != nm)

    title = '%s 아파트 공급 분석 — 입주예정·인허가로 본 %s | 아공맵' % (nm, tname)
    desc = ('%s의 아파트 공급은 적정물량 대비 %s세대(%s). 향후 2년 입주예정 %s세대, 구성: %s. '
            '한국부동산원·국토교통부 통계로 매주 자동 갱신.' % (
                nm, disp, tname, num(z['supply']), ', '.join(sgg_names[:3]) or '—'))

    ld = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": '%s 아파트 공급 분석' % nm,
        "description": desc,
        "datePublished": today, "dateModified": today,
        "author": {"@type": "Organization", "name": "아공맵"},
        "publisher": {"@type": "Organization", "name": "아공맵"},
        "mainEntityOfPage": '%s/zone/%s/' % (SITE, quote(nm)),
        "about": {"@type": "Place", "name": nm},
    }

    return """<!DOCTYPE html>
<html lang="ko">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-3FJNG6G1F3"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-3FJNG6G1F3');</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<link rel="canonical" href="%(site)s/zone/%(enc)s/">
<link rel="icon" type="image/png" href="/app_icon.png">
<meta name="theme-color" content="#16203a">
<meta property="og:type" content="article">
<meta property="og:title" content="%(nm)s 아파트 공급 분석 — %(tname)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(site)s/zone/%(enc)s/">
<meta property="og:image" content="%(site)s/og-brand.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">%(ld)s</script>
<style>%(css)s</style>
</head>
<body>

<header><div class="wrap">
  <div class="chip">아공맵 생활권 리포트</div>
  <h1>%(nm)s 아파트,<br>앞으로 얼마나 부족할까</h1>
  <div class="big" style="color:%(tcol)s">%(disp)s세대</div>
  <div class="bigsub">적정 공급량 대비 누적 순부족 · <b style="color:%(tcol)s">%(tname)s</b> · %(ranktxt)s · 기준 %(prd)s</div>
</div></header>

<section><div class="wrap">
  <h2>한 줄 요약</h2>
  <p>%(head)s 앞으로 %(fq)d개 분기 동안 이 지역에 필요한 아파트는 약 <b>%(need)s세대</b>인데, 실제로 입주가 예정된 물량은 <b>%(sup)s세대</b>입니다.
  여기에 3~4년 뒤 입주로 이어질 인허가와 최근 3년간 실제 입주량까지 더해 계산한 결과가 <b style="color:%(tcol)s">%(disp)s세대</b>입니다.</p>
  <p class="note">숫자가 <b>음수(−)</b>면 그만큼 <b>모자란다</b>는 뜻이고, 양수(+)면 남는다는 뜻입니다. 모자랄수록 가격에는 상승 압력으로, 남을수록 하락 압력으로 작용합니다.</p>
</div></section>

<section><div class="wrap">
  <h2>이 생활권은 어디를 묶은 건가</h2>
  <p>행정구역이 아니라 <b>실제로 하나의 주택시장처럼 움직이는 범위</b>로 묶었습니다. 같은 도(道)라도 통근권이 다르면 집값도 따로 움직이기 때문입니다.
  예를 들어 목포와 광양은 같은 전남이지만 직선거리 100km가 넘는 별개 시장입니다.</p>
  <div class="card"><b>%(nm)s 구성</b><span>%(members)s</span></div>%(sublist)s
  <p class="note">입주예정 물량은 단지별 주소를 시군구로 분류해 이 생활권 몫만 집계한 <b>실측치</b>입니다. 예정 시기는 %(span)s입니다.</p>
</div></section>

<section><div class="wrap">
  <h2>어떻게 계산했나</h2>
  <p>공급이 충분한지는 <b>적정물량</b>과 비교해야 알 수 있습니다. 적정물량은 과거 이 지역에서 가격이 하락에서 상승으로(또는 그 반대로) 돌아섰던 시점의 입주물량을 실측해 잡은 기준선입니다.</p>
  <table>
    <thead><tr><th>구간</th><th>적정</th><th>실제</th><th>부족분</th></tr></thead>
    <tbody>%(rows)s</tbody>
  </table>
  <p class="note" style="margin-top:10px">과거를 <b>3년</b>으로 보는 이유는 부족이 재고처럼 쌓이기 때문입니다 — 몇 해 모자랐던 지역은 한 해 물량이 몰려도 그 부족이 메워지지 않습니다. 모두 <b>멸실(철거)을 뺀 순공급</b> 기준입니다. %(dYtxt)s
  인허가와 최근 실적은 시군구 단위 통계가 존재하지 않아 <b>소속 시도(%(ps)s) 값을 인구 비중(%(sharep).1f%%)으로 배분한 추정치</b>입니다 —
  이 지역에 실제로 인허가가 몰렸는지까지는 알 수 없다는 한계가 있습니다. 반면 향후 2년 입주예정은 단지 주소 기반 실측이라 가장 정확합니다.</p>
</div></section>

%(flag)s

<section><div class="wrap">
  <h2>이 숫자를 어떻게 읽나</h2>
  <div class="card"><b>공급은 3년 전에 결정된다</b><span>오늘 인허가받은 아파트는 3년쯤 뒤에 입주합니다. 즉 지금 보이는 입주예정 물량은 이미 확정된 미래이고, 바꿀 수 없습니다.</span></div>
  <div class="card"><b>부족이 곧 상승은 아니다</b><span>공급 부족은 가격을 밀어올리는 힘이지만, 금리·규제·수요 같은 다른 힘과 함께 작동합니다. 이 지표는 그중 <b>공급</b> 한 축만 정확히 보여줍니다.</span></div>
  <div class="card"><b>절대량으로 비교한다</b><span>인구 대비 비율이 아니라 세대수 절대량이라, 시장이 큰 곳일수록 부족 규모도 크게 잡힙니다. 작은 지역의 가뭄은 순위에서 희석될 수 있습니다.</span></div>
  <a class="cta" href="/#score">전국 생활권 순위 보기 →</a>
</div></section>

<section><div class="wrap">
  <h2>다른 생활권</h2>
  <div class="zlist">%(nav)s</div>
</div></section>

<footer><div class="wrap">
  <a href="/">agongmap.co.kr</a> · 자료: 한국부동산원 입주예정물량 · 국토교통부 주택건설실적 · 행정안전부 주민등록인구 · 한국은행
  <div class="disc">본 페이지는 공개된 국가통계를 가공한 정보 제공 목적의 자료이며, 특정 부동산의 매수·매도를 권유하거나 투자 수익을 보장하지 않습니다. 투자 판단과 그 결과는 이용자 본인에게 귀속됩니다.</div>
</div></footer>

</body>
</html>""" % dict(
        title=title, desc=desc, site=SITE, nm=nm, enc=quote(nm), tname=tname, tcol=tcol, disp=disp,
        ranktxt=ranktxt, prd=prd, fq=r['fq'], head=head_line, need=num(r['need']), sup=num(r['fsup']),
        members=members, sublist=sublist, span=span, rows=rows_html, ps=ps, sharep=r['share'] * 100,
        dYtxt=('이 시도의 최근 멸실은 연 %s호입니다.' % num(r['dY'])) if r['dY'] else '',
        flag=flag_html, nav=nav, ld=json.dumps(ld, ensure_ascii=False),
        css=CSS)


def update_sitemap(names, today):
    p = os.path.join(ROOT, 'sitemap.xml')
    x = io.open(p, encoding='utf-8').read()
    x = re.sub(r'\s*<url>\s*<loc>[^<]*/zone/[^<]*</loc>.*?</url>', '', x, flags=re.S)
    block = ''.join(
        '\n  <url>\n    <loc>%s/zone/%s/</loc>\n    <lastmod>%s</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>' % (SITE, quote(n), today)
        for n in names)
    x = x.replace('</urlset>', block + '\n</urlset>')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(x)


def main():
    adv, sts = load()
    rows = calc(adv, sts)
    prd = adv['livezone'].get('prd', '')
    today = datetime.date.today().isoformat()
    outdir = os.path.join(ROOT, 'zone')
    # 옛 페이지 정리(생활권 구성이 바뀌었을 수 있음)
    if os.path.isdir(outdir):
        for d in os.listdir(outdir):
            fp = os.path.join(outdir, d, 'index.html')
            if os.path.exists(fp):
                os.remove(fp)
            if os.path.isdir(os.path.join(outdir, d)) and not os.listdir(os.path.join(outdir, d)):
                os.rmdir(os.path.join(outdir, d))
    cap = make_capital(rows)
    pages = list(rows) + ([cap] if cap else [])
    names = []
    for r in pages:
        nm = r['z']['z']
        d = os.path.join(outdir, nm)
        os.makedirs(d, exist_ok=True)
        io.open(os.path.join(d, 'index.html'), 'w', encoding='utf-8', newline='\n').write(
            build_page(r, rows, prd, today))
        names.append(nm)
    update_sitemap(names, today)
    print('zone pages: %d개 생성 → /zone/ · sitemap 갱신' % len(names))


if __name__ == '__main__':
    main()

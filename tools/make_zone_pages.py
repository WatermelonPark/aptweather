# -*- coding: utf-8 -*-
"""생활권별 공급 리포트 페이지 생성 — /zone/<생활권>/index.html

data.js의 ADV(livezone·occupancy·permits·bubble)와 STATS(전세가율·주택멸실)를 읽어
아공맵 점수 산출 근거를 서술형으로 풀어쓴 정적 페이지를 생활권 수만큼 만든다.
홈의 요약 카드가 "무슨 말인지 모르겠다"는 문제를 풀고, 검색 유입(SEO) 창구가 된다.

사용:  python tools/make_zone_pages.py         # 생성 + sitemap 갱신
"""
import io, os, re, json, sys, datetime
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data.js')
SITE = 'https://www.agongmap.co.kr'
H_MAX = 8  # 앞으로 최대 8분기 — 실제로는 데이터가 있는 미래 분기 수만 사용
LB = 12  # 과거 누적 3년(12분기) — 부족은 재고처럼 쌓이므로 1년으로는 부족
W = (0.55, 0.35, 0.10)


def load():
    t = io.open(DATA, encoding='utf-8').read()
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
        # 입주예정 물량 0은 '자료 없음'이 아니라 그냥 0이다(2026-07-19 사용자 확정).
        # odcloud는 물량이 없는 지역의 행을 아예 보내지 않으므로 '단지 없음 = 물량 0'이고,
        # 원자료 자체의 건강성은 update_adv_data의 가드 1(생활권 급감 감지)이 따로 지킨다.
        # 진주권 실측(2026-07-19): 2027-12까지 입주 0세대, 다음은 2028-06 840세대로
        # 원자료 시야(2026-01~2027-12) 밖. 즉 결측이 아니라 실제 공급 가뭄이다.
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
 line-height:1.75;-webkit-font-smoothing:antialiased;padding-bottom:66px}
.bottomnav{position:fixed;bottom:0;left:0;right:0;height:62px;background:var(--ink);
 display:flex;justify-content:center;z-index:100;box-shadow:0 -4px 18px rgba(22,32,58,.28)}
.nav-btn{flex:1;max-width:220px;display:flex;flex-direction:column;align-items:center;
 justify-content:center;gap:3px;color:#97a0b8;font-size:11.5px;font-weight:700;text-decoration:none}
.nav-btn svg{display:block}
.nav-btn:hover{color:#fff}
.nav-btn:focus-visible{outline:2px solid #fff;outline-offset:-3px}
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
.subsbox{background:#fff;border:1.5px solid var(--line);border-radius:14px;padding:16px 18px}
.subsbox b{display:block;font-size:15px;color:var(--ink);margin-bottom:4px}
.subsbox p{font-size:12.5px;color:var(--muted);margin:4px 0 10px;line-height:1.5}
.subsbox form{display:flex;gap:8px;flex-wrap:wrap}
.subsbox input{flex:1;min-width:180px;font-family:inherit;font-size:14px;padding:10px 12px;
  border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink2)}
.subsbox button{font-family:inherit;font-size:14px;font-weight:800;padding:10px 18px;border-radius:10px;
  border:1px solid var(--ink);background:var(--ink);color:#fff;cursor:pointer}
.subsbox .consent{font-size:11.5px;line-height:1.55;margin:8px 0 0}
.subsbox .subs-msg{display:block;font-size:12.5px;color:var(--muted);margin-top:8px}
.cta{display:block;max-width:400px;margin:22px auto 0;text-align:center;text-decoration:none;
 background:var(--ink);color:#fff;font-size:16.5px;font-weight:800;padding:15px 22px;border-radius:14px}
.cta.sub{background:#fff;color:var(--ink);border:1.5px solid var(--ink);font-size:15px;padding:13px 20px}
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
        flag_html = ('<section><div class="wrap"><h2>★ 실거주라면 검토해볼 구간입니다</h2>'
            '<p>%s의 임대수익률(전세가율 × 전월세전환율 = 연 <b>%.1f%%</b>)이 주택담보대출 금리 <b>%.2f%%</b>보다 높습니다. '
            '쉽게 말해 <b>이 지역은 대출 이자가 월세보다 쌉니다.</b></p>'
            '<p>어차피 어딘가에는 살아야 합니다. 전세든 월세든 주거비는 나가는데, 같은 집에 월세로 사는 비용보다 '
            '갚아야 할 이자가 적다면 <b>실거주 목적의 매수를 검토해볼 만한 조건</b>입니다. '
            '여기에 공급까지 모자란 상태라면, 기다리는 동안의 보유 부담도 그만큼 가볍습니다.</p>'
            '<p class="note">다만 <b>이자만 비교한 값</b>입니다. 원금 상환, 취득세·재산세·수선비 같은 보유 비용, '
            'LTV·DSR 대출 한도, 그리고 집값이 내릴 가능성은 각자 따로 따져야 합니다.</p></div></section>'
            % (ps, r['lo'], r['loan']))
    elif r['flag'] == 'warn':
        flag_html = ('<section><div class="wrap"><h2>⚠ 보유 부담이 큰 구간입니다</h2>'
            '<p>%s의 주택담보대출 금리(<b>%.2f%%</b>)가 임대수익률의 두 배(위험선 <b>%.1f%%</b>)를 넘었습니다. '
            '대출로 사서 보유하면 <b>이자가 월세로 받을 수 있는 돈의 두 배를 넘는다</b>는 뜻입니다. '
            '과거 2008년·2022년 급락기가 이 조건에서 시작됐습니다. 공급이 모자라더라도 보유 비용이 수익을 잠식하는 구간이라 '
            '진입 시점은 신중히 볼 필요가 있습니다.</p></div></section>' % (ps, r['loan'], r['hi']))

    # 예전에는 수도권 소속 생활권을 네비에서 통째로 뺐다. 그 결과 서울권·인천권 등
    # 16장이 인바운드 링크 1개짜리 고아가 됐다 — 검색 수요가 가장 큰 페이지들이
    # 링크 자산을 가장 적게 받는 역전이었다.
    nav = '<a href="/zone/"><b>전체 생활권</b></a>'
    nav += '<a href="/zone/수도권/">수도권</a>' if nm != '수도권' else ''
    nav += ''.join('<a href="/zone/%s/">%s</a>' % (x['z']['z'], x['z']['z'])
                   for x in allrows if x['z']['z'] != nm)

    title = '%s 아파트 공급 분석 — 입주예정·인허가로 본 %s | 아공맵' % (nm, tname)
    # sgg가 비면 '구성: —'가 그대로 메타 설명에 나갔다. odcloud는 물량이 없는
    # 지역의 행을 보내지 않으므로, 빈 sgg는 '입주예정 단지가 없다'는 뜻이다.
    comp = ('구성: %s. ' % ', '.join(sgg_names[:3])) if sgg_names else '예정 단지 없음. '
    desc = ('%s의 아파트 공급은 적정물량 대비 %s세대(%s). 향후 2년 입주예정 %s세대, %s'
            '한국부동산원·국토교통부 통계로 매주 자동 갱신.' % (
                nm, disp, tname, num(z['supply']), comp))

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
  <h1>%(h1)s</h1>
  <div class="big" style="color:%(tcol)s">%(disp)s세대</div>
  <div class="bigsub">적정 공급량 대비 누적 순부족 · <b style="color:%(tcol)s">%(tname)s</b> · %(ranktxt)s · 기준 %(prd)s</div>
</div></header>

<section><div class="wrap">
  <h2>한 줄 요약</h2>
  <p>%(head)s %(supsent)s
  %(calcsent)s</p>
  %(legend)s
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
  <p class="note">공급이 어떻게 가격으로 이어지는지는 사이클 리포트에서 6개 고리로 나눠 검증했습니다 — 공급 부족이 전세를 올리고, 전세가 매매를 밀어올리고, 새 공급이 다시 전세를 누르는 과정입니다.</p>
  <a class="cta" href="/cycle/">사이클 리포트 읽기 →</a>
</div></section>

<section><div class="wrap">
  <div class="subsbox">
    <b>📬 %(nm)s 공급 수치가 갱신되면 메일로 받기</b>
    <p>한국부동산원 주간·월간 통계와 입주물량이 갱신되는 날에만 보냅니다. 광고 메일이 아닙니다.</p>
    <form onsubmit="return zsubs(this)">
      <input type="email" name="email" required placeholder="이메일 주소" autocomplete="email">
      <button type="submit">알림 받기</button>
    </form>
    <span class="subs-msg" id="subs-msg"></span>
    <p class="consent">구독하면 <b>이메일 주소</b>를 통계 갱신 알림 발송에 이용하며, 구독 해지 시 즉시 파기합니다.
      발송은 미국 소재 Buttondown을 통해 이뤄집니다(국외 이전). 메일 하단 수신거부 링크로 언제든 즉시 해지할 수 있습니다.
      자세한 내용은 <a href="/privacy/">개인정보처리방침</a>을 확인하세요.</p>
  </div>
</div></section>

<section><div class="wrap">
  <h2>다른 생활권</h2>
  <div class="zlist">%(nav)s</div>
  <a class="cta sub" href="/#score">전국 생활권 순위 한눈에 보기 →</a>
</div></section>

<footer><div class="wrap">
  <a href="/">agongmap.co.kr</a> · 자료: 한국부동산원 입주예정물량 · 국토교통부 주택건설실적 · 행정안전부 주민등록인구 · 한국은행
  <div class="disc">본 페이지는 공개된 국가통계를 가공한 정보 제공 목적의 자료이며, 특정 부동산의 매수·매도를 권유하거나 투자 수익을 보장하지 않습니다. 투자 판단과 그 결과는 이용자 본인에게 귀속됩니다.</div>
</div></footer>

<nav class="bottomnav">
  <a class="nav-btn" href="/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3 11l9-8 9 8M5 10v10h14V10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>홈</span></a>
  <a class="nav-btn" href="/#test"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="7.4" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="7.4" cy="12" r="1.7" fill="currentColor"/><circle cx="16.6" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/></svg><span>퀴즈</span></a>
  <a class="nav-btn" href="/#stats"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span>통계</span></a>
  <a class="nav-btn" href="/cycle/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M20.3 3.7v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>리포트</span></a>
</nav>

<script>
function zsubs(f){
  var email=f.email.value.trim(); if(!email)return false;
  var m=document.getElementById('subs-msg');
  var fd=new FormData(); fd.append('email',email);
  fetch('https://buttondown.com/api/emails/embed-subscribe/aptweather',{method:'POST',mode:'no-cors',body:fd})
    .then(function(){ m.textContent='확인 메일을 보냈습니다. 메일함에서 구독을 완료해주세요!'; f.reset();
      try{if(typeof gtag==='function')gtag('event','subscribe',{channel:'email',page:'zone'});}catch(e){} })
    .catch(function(){ m.textContent='잠시 후 다시 시도해주세요.'; });
  return false;
}
</script>

</body>
</html>""" % dict(
        title=title, desc=desc, site=SITE, nm=nm, enc=quote(nm), tname=tname, tcol=tcol, disp=disp,
        ranktxt=ranktxt, prd=prd, fq=r['fq'], head=head_line, need=num(r['need']), sup=num(r['fsup']),
        calcsent=('여기에 3~4년 뒤 입주로 이어질 인허가와 최근 3년간 실제 입주량까지 더해 계산한 결과가 '
                  '<b style="color:%s">%s세대</b>입니다.' % (tcol, disp)),
        legend=('<p class="note">숫자가 <b>음수(−)</b>면 그만큼 <b>모자란다</b>는 뜻이고, 양수(+)면 남는다는 뜻입니다. '
                '모자랄수록 가격에는 상승 압력으로, 남을수록 하락 압력으로 작용합니다.</p>'),
        h1=('%s 아파트,<br>앞으로 얼마나 부족할까' % nm),
        supsent=('앞으로 %d개 분기 동안 이 지역에 필요한 아파트는 약 <b>%s세대</b>인데, '
                 '실제로 입주가 예정된 물량은 <b>%s세대</b>입니다.' % (
                     r['fq'], num(r['need']), num(r['fsup']))),
        members=members, sublist=sublist, span=span, rows=rows_html, ps=ps, sharep=r['share'] * 100,
        dYtxt=('이 시도의 최근 멸실은 연 %s호입니다.' % num(r['dY'])) if r['dY'] else '',
        flag=flag_html, nav=nav, ld=json.dumps(ld, ensure_ascii=False),
        css=CSS)


DATE_RE = re.compile(r'"date(?:Published|Modified)": "(\d{4}-\d{2}-\d{2})"')


def strip_dates(html):
    """날짜만 지운 본문 — '내용이 실제로 바뀌었나'의 판정 기준."""
    return DATE_RE.sub('"date": "-"', html or '')


def read_old(path):
    try:
        return io.open(path, encoding='utf-8').read()
    except IOError:
        return ''


def keep_dates(new_html, old_html, today):
    """내용이 같으면 옛 날짜를 그대로 둔다. (반환: html, lastmod, 변경여부)

    이 배치는 매일 돈다. 예전에는 today를 무조건 심어서, 데이터가 하나도
    안 바뀐 날에도 37장과 sitemap의 lastmod가 날짜만 바뀐 채 커밋됐다.
    검색엔진에 '매일 갱신'이라 신고하면서 내용은 그대로면 신선도 신호의
    신뢰도가 깎이고, 최초 발행일이어야 할 datePublished마저 매일 리셋됐다.
    """
    if not old_html or strip_dates(new_html) != strip_dates(old_html):
        return new_html, today, True
    olds = DATE_RE.findall(old_html)
    if len(olds) < 2:
        return new_html, today, True
    pub, mod = olds[0], olds[1]
    out = new_html.replace('"datePublished": "%s"' % today, '"datePublished": "%s"' % pub, 1)
    out = out.replace('"dateModified": "%s"' % today, '"dateModified": "%s"' % mod, 1)
    return out, mod, False


HUB_TPL = u"""<!DOCTYPE html>
<html lang="ko">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-3FJNG6G1F3"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
gtag('js',new Date());gtag('config','G-3FJNG6G1F3');</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>전국 생활권 아파트 공급 순위 %(n)d곳 — 입주예정·인허가로 본 부족·과잉 | 아공맵</title>
<meta name="description" content="전국 %(n)d개 생활권의 아파트 공급을 적정물량과 비교해 누적 순부족 순으로 정렬했습니다. 공급 절벽부터 공급 과잉까지 한눈에. 기준 %(prd)s.">
<link rel="canonical" href="%(site)s/zone/">
<link rel="icon" type="image/png" href="/app_icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#16203a">
<meta property="og:type" content="website">
<meta property="og:title" content="전국 생활권 아파트 공급 순위 %(n)d곳">
<meta property="og:description" content="적정물량 대비 누적 순부족 순. 공급 절벽부터 과잉까지.">
<meta property="og:url" content="%(site)s/zone/">
<meta property="og:image" content="%(site)s/og-brand.png">
<script type="application/ld+json">
%(ld)s
</script>
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<style>
:root{--ink:#16203a;--paper:#f4f6f5;--line:#e2dbc9;--muted:#6f6a5c;--body:#3a352b}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--body);word-break:keep-all;padding-bottom:78px;
 font-family:'Pretendard Variable','Pretendard',-apple-system,'Malgun Gothic',sans-serif;line-height:1.7}
.wrap{max-width:660px;margin:0 auto;padding:0 20px}
header{padding:46px 0 26px;border-bottom:1px solid var(--line)}
h1{font-size:clamp(23px,5.4vw,31px);color:var(--ink);letter-spacing:-.02em;line-height:1.32}
.lead{color:var(--muted);font-size:14.5px;margin-top:10px}
section{padding:26px 0;border-bottom:1px solid var(--line)}
h2{font-size:18px;color:var(--ink);margin-bottom:6px}
p{font-size:14.5px;margin:8px 0}
table{width:100%%;border-collapse:collapse;font-size:14.5px;margin-top:12px}
th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line)}
th{font-size:12px;letter-spacing:.04em;color:var(--muted);white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.rk{color:var(--muted);width:2.2em;text-align:right;font-variant-numeric:tabular-nums}
a.z{color:var(--ink);text-decoration:none;font-weight:700}
a.z:hover{text-decoration:underline}
.tag{font-size:11.5px;padding:2px 7px;border-radius:99px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.bottomnav{position:fixed;bottom:0;left:0;right:0;height:62px;background:var(--ink);
 display:flex;justify-content:center;z-index:100}
.nav-btn{flex:1;max-width:220px;display:flex;flex-direction:column;align-items:center;
 justify-content:center;gap:3px;color:#97a0b8;font-size:11.5px;font-weight:700;text-decoration:none}
.nav-btn svg{display:block}
footer{padding:24px 0 40px;color:var(--muted);font-size:12.5px}
footer a{color:var(--muted)}
</style>
</head>
<body>
<header><div class="wrap">
  <h1>전국 생활권 아파트 공급 순위</h1>
  <p class="lead">%(n)d개 생활권을 적정물량 대비 <b>누적 순부족</b>이 큰 순으로 정렬했습니다.
    양수는 공급이 모자란 곳, 음수는 남는 곳입니다. 기준 %(prd)s.</p>
</div></header>

<section><div class="wrap">
  <h2>순위표</h2>
  <p>생활권 이름을 누르면 그 지역의 분기별 입주예정·인허가·적정물량 비교를 볼 수 있습니다.</p>
  <table>
    <thead><tr><th>#</th><th>생활권</th><th class="num">누적 순부족</th><th>판정</th></tr></thead>
    <tbody>
%(rows)s
    </tbody>
  </table>
</div></section>

<section><div class="wrap">
  <h2>이 숫자는 무엇인가</h2>
  <p><b>누적 순부족</b>은 앞으로 들어올 아파트가 그 지역에 필요한 양보다 얼마나 모자라는지를 세대수로 나타낸 값입니다.
    향후 2년 입주예정, 인허가(3~4년 뒤 공급), 최근 1년 실적을 가중 합산합니다.</p>
  <p>공급이 모자란다고 값이 반드시 오르는 것도, 남는다고 반드시 내리는 것도 아닙니다.
    공급은 사이클을 움직이는 여러 힘 가운데 하나이며, 금리·전세가율·심리가 함께 작용합니다.
    <a href="/cycle/">사이클이 어떻게 도는지 보기 →</a></p>
</div></section>

<footer><div class="wrap">
  <a href="/">agongmap.co.kr</a> · 자료: 한국부동산원 입주예정물량 · 국토교통부 주택건설실적 · 행정안전부 주민등록인구<br>
  <a href="/privacy/">개인정보처리방침</a> · 본 자료는 공공 데이터를 가공한 참고 자료이며 투자자문이 아닙니다.
</div></footer>

<nav class="bottomnav">
  <a class="nav-btn" href="/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3 11l9-8 9 8M5 10v10h14V10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>홈</span></a>
  <a class="nav-btn" href="/#test"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="7.4" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="7.4" cy="12" r="1.7" fill="currentColor"/><circle cx="16.6" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/></svg><span>퀴즈</span></a>
  <a class="nav-btn" href="/#stats"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>통계</span></a>
  <a class="nav-btn" href="/cycle/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M20.3 3.7v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>리포트</span></a>
</nav>

<script>
if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('/sw.js').catch(function(){});});}
</script>
</body>
</html>
"""


def build_hub(pages, prd, today):
    """전 생활권을 한 페이지에 모은 허브.

    존재 이유는 링크다. 홈의 생활권 타일은 JS 런타임 생성이라 정적 HTML에
    /zone/ 링크가 하나도 없었고, 37장의 사실상 유일한 발견 경로가 sitemap이었다.
    sitemap은 발견은 시켜주지만 링크 가치를 전달하지 않는다.
    """
    # 입주예정 0은 '자료 없음'이 아니라 그냥 0이다(3c897f7 확정). 전부 순위에 넣는다.
    live = sorted(pages, key=lambda r: -r['tot'])
    rows = []
    for i, r in enumerate(live):
        nm = r['z']['z']
        tname, tcol = tier(r['tot'])
        rows.append(
            '      <tr><td class="rk">%d</td><td><a class="z" href="/zone/%s/">%s</a></td>'
            '<td class="num" style="color:%s">%s</td><td><span class="tag">%s</span></td></tr>'
            % (i + 1, nm, nm, tcol, signed(r['tot']), tname))
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "Article",
        "headline": "전국 생활권 아파트 공급 순위",
        "description": "전국 %d개 생활권의 아파트 공급을 적정물량과 비교해 누적 순부족 순으로 정렬." % len(live),
        "datePublished": today, "dateModified": today,
        "author": {"@type": "Organization", "name": "아공맵"},
        "publisher": {"@type": "Organization", "name": "아공맵"},
        "mainEntityOfPage": '%s/zone/' % SITE,
    }, ensure_ascii=False, indent=2)
    return HUB_TPL % dict(n=len(live), prd=prd, site=SITE, ld=ld,
                          rows='\n'.join(rows))


def update_sitemap(names, lastmods):
    p = os.path.join(ROOT, 'sitemap.xml')
    x = io.open(p, encoding='utf-8').read()
    x = re.sub(r'\s*<url>\s*<loc>[^<]*/zone/[^<]*</loc>.*?</url>', '', x, flags=re.S)
    x = re.sub(r'\s*<url>\s*<loc>[^<]*/zone/</loc>.*?</url>', '', x, flags=re.S)
    newest = max(lastmods.values()) if lastmods else ''
    block = ('\n  <url>\n    <loc>%s/zone/</loc>\n    <lastmod>%s</lastmod>\n'
             '    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>'
             % (SITE, newest))
    block += ''.join(
        '\n  <url>\n    <loc>%s/zone/%s/</loc>\n    <lastmod>%s</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>'
        % (SITE, quote(n), lastmods.get(n, ''))
        for n in names)
    x = x.replace('</urlset>', block + '\n</urlset>')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(x)


def main():
    adv, sts = load()
    rows = calc(adv, sts)
    prd = adv['livezone'].get('prd', '')
    today = datetime.date.today().isoformat()
    outdir = os.path.join(ROOT, 'zone')
    # ⚠️ 삭제 전에 읽어야 한다 — 날짜 유지 판정에 옛 내용이 필요하다.
    old_pages = {}
    if os.path.isdir(outdir):
        for d in os.listdir(outdir):
            fp = os.path.join(outdir, d, 'index.html')
            if os.path.exists(fp):
                old_pages[d] = read_old(fp)
    old_hub = read_old(os.path.join(outdir, 'index.html'))
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
    names, lastmods, nchanged = [], {}, 0
    for r in pages:
        nm = r['z']['z']
        d = os.path.join(outdir, nm)
        os.makedirs(d, exist_ok=True)
        html, lm, ch = keep_dates(build_page(r, rows, prd, today), old_pages.get(nm, ''), today)
        io.open(os.path.join(d, 'index.html'), 'w', encoding='utf-8', newline='\n').write(html)
        names.append(nm)
        lastmods[nm] = lm
        nchanged += 1 if ch else 0
    hub, _, _ = keep_dates(build_hub(pages, prd, today), old_hub, today)
    io.open(os.path.join(outdir, 'index.html'), 'w', encoding='utf-8', newline='\n').write(hub)
    update_sitemap(names, lastmods)
    print('zone pages: %d개 + 허브 1개 생성 (내용 변경 %d개) → /zone/ · sitemap 갱신'
          % (len(names), nchanged))


if __name__ == '__main__':
    main()

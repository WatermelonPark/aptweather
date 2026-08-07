# -*- coding: utf-8 -*-
"""지표별 정적 랜딩 페이지 생성기 — /jeonse-ratio/(전세가율), /moveins/(입주물량).

zone 페이지와 같은 모델: 배치가 실데이터를 표·요약 문장으로 구워 넣은 완결
페이지를 재생성한다. 빈 차트 껍데기(thin content)가 아니라 JS 없이도 내용이
온전해야 검색엔진이 지표 페이지로 인정한다. 대상 지표는 검색 수요가 실재하는
것만 — 기본통계 전 계열을 페이지로 찍으면 얇은 유사 페이지 무더기가 된다
(2026-07-29 사용자 합의: 전세가율·입주물량 2종만).

결정성: 본문 날짜는 전부 데이터 시점에서 유도한다(오늘 날짜 금지).
데이터가 안 바뀐 실행은 바이트 동일 출력 → git diff 없음 → 커밋 없음.
(옛 make_zone_pages가 keep_dates로 배운 것과 같은 교훈, 여기선 애초에 오늘을 안 쓴다)

실행: python tools/make_indicator_pages.py   # 생성 + sitemap 갱신
"""
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'https://www.agongmap.co.kr'
PUBLISHED = '2026-07-29'   # 페이지 최초 공개일(고정)

SIDO17 = ['서울', '경기', '인천', '부산', '대구', '광주', '대전', '울산', '세종',
          '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']


def load():
    s = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    adv = json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', s, re.S).group(1))
    c = io.open(os.path.join(ROOT, 'data-core.js'), encoding='utf-8').read()
    sts = json.loads(re.search(
        r'const STATS=(\{.*?\});\nwindow\.__DATA_CORE__', c, re.S).group(1))
    return adv, sts


def num(v):
    return format(int(round(v)), ',')


def updown(a, b, tol=0.03):
    """방향어는 반드시 데이터로 판정한다.

    ⚠️ 2026-08-01 실사고: '줄어든다'를 본문에 박아뒀는데 데이터가 105,950 →
    115,411(증가)로 바뀌어 라이브에 정반대 문장이 걸렸다. 매주 재생성되는
    페이지에 방향·비교 단정어를 하드코딩하면 언젠가 반드시 뒤집힌다.
    변화폭이 tol(기본 3%) 안이면 '거의 그대로'로 — 1% 차이를 '늘어난다'고
    쓰면 그것도 과장이다."""
    if not a or not b:
        return '이어진다'
    if abs(b - a) <= abs(a) * tol:
        return '거의 그대로다'
    return '늘어난다' if b > a else '줄어든다'


def ga(w):
    """주격 조사 — 받침 있으면 '이', 없으면 '가' (전남이/경기가)."""
    c = ord(w[-1])
    return w + ('이' if 0xAC00 <= c <= 0xD7A3 and (c - 0xAC00) % 28 else '가')


def neun(w):
    """보조사 — 받침 있으면 '은', 없으면 '는' (세종은/제주는)."""
    c = ord(w[-1])
    return w + ('은' if 0xAC00 <= c <= 0xD7A3 and (c - 0xAC00) % 28 else '는')


# ---- 공통 템플릿 ----------------------------------------------------------
# zone 페이지와 같은 뼈대·팔레트. CSS 인라인(자기완결) — app.css에 묶지 않는 건
# zone 페이지와 같은 이유(페이지 단독 캐시·앱 셸과 수명 분리).
SHELL = """<!DOCTYPE html>
<html lang="ko">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-3FJNG6G1F3"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-3FJNG6G1F3');</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css" media="print" onload="this.media='all'">
<noscript><link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css"></noscript>
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<link rel="canonical" href="__URL__">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" href="/app_icon.png">
<meta name="theme-color" content="#16203a">
<meta property="og:type" content="article">
<meta property="og:title" content="__OGTITLE__">
<meta property="og:description" content="__DESC__">
<meta property="og:url" content="__URL__">
<meta property="og:image" content="https://www.agongmap.co.kr/og-brand.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">__LD__</script>
<style>
:root{--ink:#131e24;--ink2:#4c5f66;--paper:#f4f6f5;--paper2:#e9edeb;--muted:#5e6f74;--line:#c4cec9;--up:#b23b2e;--dn:#2f6db3}
*{margin:0;padding:0;box-sizing:border-box}
b,strong{font-weight:600}
body{background:var(--paper);color:var(--ink);word-break:keep-all;overflow-wrap:break-word;
 font-family:'Pretendard Variable','Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
 line-height:1.75;-webkit-font-smoothing:antialiased;padding-bottom:66px}
.wrap{max-width:620px;margin:0 auto;padding:0 22px}
header{padding:44px 0 24px;text-align:center}
.chip{display:inline-block;font-size:12.5px;font-weight:600;color:#fff;background:var(--ink);padding:5px 14px;margin-bottom:14px}
h1{font-size:clamp(25px,5.6vw,34px);font-weight:700;letter-spacing:-.02em;line-height:1.28;margin-bottom:12px}
.lead{font-size:15.5px;color:var(--ink2)}
.big{font-size:clamp(34px,9vw,48px);font-weight:700;letter-spacing:-.02em;margin:6px 0 2px}
.bigsub{font-size:13.5px;color:var(--muted)}
section{padding:20px 0}
h2{font-size:20px;font-weight:700;letter-spacing:-.02em;margin-bottom:10px}
p{margin-bottom:12px;font-size:15px}
p:last-child{margin-bottom:0}
.note{font-size:13px;color:var(--muted);line-height:1.6;margin-top:8px}
.tbl-wrap{overflow-x:auto;margin:6px 0 2px}
table{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}
th{font-size:12.5px;font-weight:600;color:var(--muted);text-align:right;padding:7px 8px;border-bottom:1.5px solid var(--ink);white-space:nowrap;cursor:pointer;user-select:none}
th:first-child,td:first-child{text-align:left}
td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
tr.agg td{background:var(--paper2);font-weight:600}
.up{color:var(--up)}.dn{color:var(--dn)}.mut{color:var(--muted)}
.links{display:grid;gap:10px;margin-top:6px}
.links a{display:block;background:#fff;border:1px solid var(--line);padding:13px 16px;text-decoration:none;color:var(--ink);font-weight:600;font-size:14.5px}
.links a span{display:block;font-weight:400;font-size:13px;color:var(--muted);margin-top:2px}
.links a:hover{border-color:var(--ink)}
footer{padding:28px 0 40px;font-size:13px;color:var(--muted);text-align:center}
footer a{color:var(--ink)}
.disc{margin-top:10px;font-size:11.5px;line-height:1.6;color:#8a9599}
.bottomnav{position:fixed;bottom:0;left:0;right:0;height:62px;background:var(--ink);display:flex;justify-content:center;z-index:100;box-shadow:0 -4px 18px rgba(22,32,58,.28)}
.nav-btn{flex:1;max-width:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;color:#97a0b8;font-size:11.5px;font-weight:600;text-decoration:none}
.nav-btn svg{display:block}
.nav-btn:hover{color:#fff}
.nav-btn:focus-visible{outline:2px solid #fff;outline-offset:-3px}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>
</head>
<body>
__BODY__
<footer><div class="wrap">
  <b>아공맵</b> — 아파트 · 공급량 · 투자지도<br>
  <a href="/">agongmap.co.kr</a> · 자료: __SRC__
  <div class="disc">공공 데이터를 가공한 참고 자료이며 투자자문이 아닙니다. 투자 판단과 책임은 이용자에게 있습니다.</div>
</div></footer>

<nav class="bottomnav">
  <a class="nav-btn" href="/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3 11l9-8 9 8M5 10v10h14V10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>홈</span></a>
  <a class="nav-btn" href="/#test"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="7.4" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="7.4" cy="12" r="1.7" fill="currentColor"/><circle cx="16.6" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/></svg><span>퀴즈</span></a>
  <a class="nav-btn" href="/#stats"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span>통계</span></a>
  <a class="nav-btn" href="/cycle/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M20.3 3.7v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>리포트</span></a>
</nav>

<script>
(function(){
  var t=document.getElementById('utable'); if(!t) return;
  var tb=t.tBodies[0], ths=t.tHead.rows[0].cells, cur=-1, dir=1;
  function val(row,k,isNum){
    var s=row.cells[k].textContent.trim();
    return isNum ? (parseFloat(s.replace(/[^0-9.-]/g,''))||-1e9) : s;
  }
  Array.prototype.forEach.call(ths, function(h,i){
    h.addEventListener('click', function(){
      var isNum=h.hasAttribute('data-num');
      dir=(cur===i)?-dir:-1; cur=i;
      var rows=Array.prototype.slice.call(tb.rows).filter(function(r){return !r.classList.contains('agg')});
      var aggs=Array.prototype.slice.call(tb.rows).filter(function(r){return r.classList.contains('agg')});
      rows.sort(function(a,b){var x=val(a,i,isNum),y=val(b,i,isNum);return (x<y?-1:x>y?1:0)*dir;});
      aggs.concat(rows).forEach(function(r){tb.appendChild(r);});
    });
  });
})();
</script>
</body>
</html>
"""


def fill(shell, **kw):
    out = shell
    for k, v in kw.items():
        out = out.replace('__' + k.upper() + '__', v)
    return out


def not_before_pub(iso):
    """dateModified가 datePublished보다 과거가 되지 않게 막는다.
    두 페이지의 lastmod는 '마지막 실적 분기'에서 오는데(데이터가 안 바뀌면
    안 움직이게 하려는 의도), 그 분기가 페이지 공개일보다 앞서면
    '2026-07-29 발행 · 2026-06-01 수정'이라는 불가능한 조합이 나간다
    (2026-08-07 감사에서 실제로 그 상태였다)."""
    return max(iso, PUBLISHED)


def ld_pack(headline, desc, url, crumb_name, modified):
    modified = not_before_pub(modified)
    return json.dumps([{
        "@context": "https://schema.org", "@type": "Article",
        "headline": headline,
        "description": desc,
        "datePublished": PUBLISHED, "dateModified": modified,
        "author": {"@type": "Organization", "name": "아공맵"},
        "publisher": {"@type": "Organization", "name": "아공맵"},
        "mainEntityOfPage": url,
    }, {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "아공맵", "item": SITE + '/'},
            {"@type": "ListItem", "position": 2, "name": crumb_name},
        ],
    }], ensure_ascii=False, indent=2)


# ---- 전세가율 (/jeonse-ratio/) --------------------------------------------
def build_jeonse(sts):
    j = sts['전세가율']
    dates, ser = j['dates'], j['series']
    li = len(dates) - 1
    prd = dates[li]                       # '2026.05'
    prd_iso = prd.replace('.', '-') + '-01'

    def at(name, i):
        v = (ser.get(name) or [None])[i] if name in ser else None
        return v

    aggs = ['전국', '수도권', '지방']
    rows, vals = [], []
    for name in aggs + SIDO17:
        cur, ago = at(name, li), at(name, li - 12)
        if cur is None:
            continue
        d = None if ago is None else round(cur - ago, 1)
        if name in SIDO17:
            vals.append((name, cur, d))
        rows.append((name, cur, ago, d))
    # 시도는 현재값 내림차순, 집계 3행은 상단 고정
    body_rows = [r for r in rows if r[0] in aggs] + \
        sorted([r for r in rows if r[0] not in aggs], key=lambda r: -r[1])

    def cell_d(d):
        if d is None:
            return '<td class="mut">·</td>'
        cls = 'up' if d > 0 else 'dn' if d < 0 else 'mut'
        return '<td class="%s">%+.1f%%p</td>' % (cls, d)

    trs = []
    for name, cur, ago, d in body_rows:
        trs.append('<tr%s><td>%s</td><td>%.1f%%</td><td>%s</td>%s</tr>' % (
            ' class="agg"' if name in aggs else '', name, cur,
            '·' if ago is None else '%.1f%%' % ago, cell_d(d)))

    nat = at('전국', li)
    nat_d = round(nat - at('전국', li - 12), 1)
    hi = max(vals, key=lambda v: v[1])
    lo = min(vals, key=lambda v: v[1])
    up_most = max([v for v in vals if v[2] is not None], key=lambda v: v[2])

    title = '전세가율이란 — 전국·시도별 아파트 전세가율 현황 %s | 아공맵' % prd
    desc = ('전세가율은 매매가 대비 전세가 비율. %s 기준 전국 아파트 전세가율은 %.1f%%로 1년 전보다 %+.1f%%p. '
            '%s %.1f%%로 가장 높고 %s %.1f%%. 시도별 현황과 사이클 신호로서의 의미를 데이터로 정리했다.'
            ) % (prd, nat, nat_d, ga(hi[0]), hi[1], neun(lo[0]), lo[1])
    url = SITE + '/jeonse-ratio/'

    body = """<header class="wrap">
  <div class="chip">지표 해설</div>
  <h1>전세가율 — 매매가 대비 전세가,<br>실수요의 체온계</h1>
  <div class="big">%(nat).1f%%</div>
  <div class="bigsub">전국 아파트 전세가율 · %(prd)s 기준 · 1년 전 대비 %(natd)+.1f%%p</div>
</header>

<section class="wrap">
  <h2>전세가율이란</h2>
  <p><strong>전세가율 = 전세가 ÷ 매매가 × 100.</strong> 매매가 10억 아파트의 전세가 6억이면 전세가율 60%%다.</p>
  <p>전세가에는 시세차익 기대가 없다 — 세입자는 오를 것 같다고 전세금을 더 내지 않는다. 그래서 전세가는 <strong>거주 가치의 순수한 값</strong>이고, 전세가율은 매매가에 낀 기대(프리미엄)가 얼마나 되는지를 보여준다. 전세가율이 낮을수록 매매가에 미래 기대가 많이 반영된 것이고, 높을수록 가격이 실거주 가치에 붙어 있는 것이다.</p>
</section>

<section class="wrap">
  <h2>시도별 현황 (%(prd)s)</h2>
  <div class="tbl-wrap"><table id="utable">
    <thead><tr><th>지역</th><th data-num>전세가율</th><th data-num>1년 전</th><th data-num>변화</th></tr></thead>
    <tbody>
%(trs)s
    </tbody>
  </table></div>
  <div class="note">표두를 누르면 정렬. 자료: KOSIS·한국부동산원 「매매가격 대비 전세가격비」, 매월 갱신.</div>
</section>

<section class="wrap">
  <h2>지금 표에서 읽히는 것</h2>
  <p>가장 높은 곳은 <strong>%(hi)s %(hiv).1f%%</strong>, 가장 낮은 곳은 <strong>%(lo)s %(lov).1f%%</strong>다. 서울처럼 전세가율이 낮은 시장은 매매가가 거주 가치보다 기대에 기대어 있다는 뜻이고(투자성 시장), 전세가율이 높은 지방 시장은 가격이 실수요에 붙어 있어 갭이 작다(실거주성 시장).</p>
  <p>1년 새 가장 크게 오른 곳은 <strong>%(upm)s(%(upmd)+.1f%%p)</strong>. 전세가율 상승은 사이클에서 중요한 신호다 — <strong>공급이 부족하면 전세가 먼저 오르고, 전세가율이 차오르면 매매를 밀어 올린다.</strong> 갭투자 비용이 줄어드는 지점이기도 하다. 이 연결고리는 20년 국가 통계로 검증해 리포트에 정리해 뒀다.</p>
</section>

<section class="wrap">
  <h2>더 보기</h2>
  <div class="links">
    <a href="/#stats-adv-bubble">버블밴드<span>전세가율로 계산한 지역별 고평가·저평가 밴드</span></a>
    <a href="/#stats-basic">기본통계 차트<span>전세가율 2012년부터 월별 추이를 지역별로</span></a>
    <a href="/moveins/">아파트 입주물량<span>전세가율을 움직이는 원인 — 시도별 입주 예정</span></a>
    <a href="/zone/">시도별 공급 분석<span>17개 시도를 부족·과잉 등급으로</span></a>
    <a href="/cycle/">아파트 사이클 리포트<span>전세가율이 매매를 미는 고리, 데이터 검증</span></a>
  </div>
</section>
""" % dict(nat=nat, natd=nat_d, prd=prd, trs='\n'.join(trs),
           hi=hi[0], hiv=hi[1], lo=lo[0], lov=lo[1], upm=up_most[0], upmd=up_most[2])

    html = fill(SHELL, title=title, ogtitle='전세가율 — 전국 %.1f%%, 시도별 현황' % nat,
                desc=desc, url=url, body=body,
                ld=ld_pack('전세가율 — 전국·시도별 현황과 의미', desc, url, '전세가율', prd_iso),
                src='KOSIS 한국부동산원 매매가격 대비 전세가격비')
    return html, not_before_pub(prd_iso)


# ---- 입주물량 (/moveins/) --------------------------------------------------
def build_moveins(adv):
    o = adv['occupancy']
    regs, rows = o['regions'], o['rows']
    # ⚠️ o['ref']는 '분기' 수요 기준선이다(통계탭 occCls가 분기값과 직접 비교,
    # UI 문구도 '분기 수요 기준선'). 연간 표에서는 반드시 ×4로 환산할 것 —
    # 안 하면 수도권이 '과잉 224%'로 나와 사이트 전체 서사와 정반대가 된다.
    ref = {k: (v * 4 if v else None) for k, v in o['ref'].items()}
    idx = {r: i for i, r in enumerate(regs)}
    last_act = [r['p'] for r in rows if not r.get('e')][-1]     # 마지막 실적 분기 '2026Q2'
    # ⚠️ 분기를 버리지 말 것. prd=last_act[:4]로 연도만 남기면 '.' 분기가 영영
    # 거짓이 되어 mod_iso가 그 해 1월 1일로 굳는다 — /moveins/의 dateModified가
    # datePublished보다 과거가 되고(불가능한 조합) sitemap lastmod가 1년 내내
    # 안 움직였다(2026-08-07 감사). 분기의 마지막 달 1일로 찍는다.
    prd = last_act
    m = re.match(r'^(\d{4})Q([1-4])$', prd)
    if m:
        mod_iso = '%s-%02d-01' % (m.group(1), int(m.group(2)) * 3)
    elif '.' in prd:
        mod_iso = prd.replace('.', '-') + '-01'
    else:
        mod_iso = prd[:4] + '-01-01'
    years = ['2025', '2026', '2027']

    def ytot(name, y):
        i = idx[name]
        vs = [r['v'][i] for r in rows if r['p'].startswith(y) and r['v'][i] is not None]
        return sum(vs) if vs else None

    def pct_cell(t, rf):
        if t is None or not rf:
            return '<td class="mut">·</td>'
        p = t / rf * 100
        # ⚠️ 이 값은 '적정 대비 얼마나 채웠나'(충족률)다. 39%에 ' 부족'을 붙이면
        # '39% 모자라다'로 읽히는데 실제로는 61% 모자란 것이다(2026-08-07 감사).
        cls = 'up' if p < 70 else 'dn' if p > 130 else 'mut'
        return '<td class="%s">%d%% 충족</td>' % (cls, round(p))

    # ⚠️ regs에는 전국·수도권·지방 집계 3종이 섞여 있다. 그대로 정렬하면 '시도별'
    # 표에 전국·지방이 시도인 척 들어가 이중계상된다(2026-08-07 감사).
    # 수도권만 맨 위 집계행으로 두고 나머지 집계는 뺀다.
    order = ['수도권', '서울', '경기', '인천'] + sorted(
        [r for r in SIDO17 if r not in ('서울', '경기', '인천')],
        key=lambda r: -(ytot(r, '2026') or 0))
    trs = []
    for name in order:
        t = {y: ytot(name, y) for y in years}
        rf = ref.get(name)
        trs.append('<tr%s><td>%s</td>%s<td>%s</td>%s</tr>' % (
            ' class="agg"' if name == '수도권' else '', name,
            ''.join('<td>%s</td>' % ('·' if t[y] is None else num(t[y])) for y in years),
            '·' if not rf else num(rf), pct_cell(t['2026'], rf)))

    nat26 = sum(ytot(r, '2026') or 0 for r in SIDO17)
    nat27 = sum(ytot(r, '2027') or 0 for r in SIDO17)
    sudo = {y: ytot('수도권', y) for y in years}
    shorts = sorted([(r, (ytot(r, '2026') or 0) / ref[r] * 100)
                     for r in SIDO17 if ref.get(r)], key=lambda x: x[1])
    lo1, hi1 = shorts[0], shorts[-1]

    title = '아파트 입주물량 — 2026·2027 전국 시도별 입주 예정 | 아공맵'
    desc = ('아파트 입주물량은 준공(사용승인) 뒤 실제로 입주가 시작되는 물량. 2026년 전국 %s세대, '
            '2027년 %s세대 예정. 수도권은 %s→%s세대. 적정수요와 비교한 시도별 부족·과잉과 '
            '전세·매매에 미치는 영향을 정리했다.') % (
        num(nat26), num(nat27), num(sudo['2026'] or 0), num(sudo['2027'] or 0))
    url = SITE + '/moveins/'

    body = """<header class="wrap">
  <div class="chip">지표 해설</div>
  <h1>아파트 입주물량 —<br>공급이 시장에 도착하는 순간</h1>
  <div class="big">%(nat26)s</div>
  <div class="bigsub">2026년 전국 입주물량(실적+예정, 세대) · 2027년 %(nat27)s세대</div>
</header>

<section class="wrap">
  <h2>입주물량이란</h2>
  <p><strong>준공(사용승인)을 마치고 실제 입주가 시작되는 아파트 물량</strong>이다. 인허가·착공이 '공급 예고'라면 입주는 <strong>공급의 도착</strong>이다 — 열쇠를 받은 집주인과 세입자가 시장에 실물로 등장한다.</p>
  <p>입주가 몰리면 가장 먼저 눌리는 건 매매가 아니라 <strong>전세</strong>다. 잔금을 치르려는 집주인들이 전세를 한꺼번에 내놓기 때문이다. 반대로 입주 절벽이 오면 전세부터 마르고, 전세가율이 차오르며 매매를 민다. 그래서 입주물량은 아파트 사이클의 타이밍을 읽는 핵심 지표다.</p>
</section>

<section class="wrap">
  <h2>시도별 연간 입주물량 (세대)</h2>
  <div class="tbl-wrap"><table id="utable">
    <thead><tr><th>지역</th><th data-num>2025</th><th data-num>2026</th><th data-num>2027</th><th data-num>적정수요/년</th><th data-num>2026 충족률</th></tr></thead>
    <tbody>
%(trs)s
    </tbody>
  </table></div>
  <div class="note">표두를 누르면 정렬. %(lastact)s까지 준공 실적, 이후는 <b>착공 실적을 3년 뒤로 밀어</b> 추정한 값입니다(전환율 0.958). 적정수요는 가격이 하락에서 상승으로 돌아선 시점의 입주물량을 실측해 잡은 분기 기준선을 연환산(×4)한 고정 상수이며, 서울·경기·인천과 세종·제주는 추정치입니다. 자료: 국토교통부 주택건설실적(준공·착공), 매주 갱신.</div>
</section>

<section class="wrap">
  <h2>지금 표에서 읽히는 것</h2>
  <p>2026년 적정수요를 가장 덜 채운 곳은 <strong>%(lo1)s(%(lo1p)d%% 충족)</strong>, 가장 많이 채운 곳은 <strong>%(hi1)s(%(hi1p)d%% 충족)</strong>다. 공급이 적정선의 70%%를 밑돌면 전세부터 조여드는 구간, 130%%를 넘으면 입주장이 전세를 누르는 구간으로 본다.</p>
  <p>수도권은 2026년 %(sudo26)s세대에서 2027년 %(sudo27)s세대로 %(sudodir)s. 시도 안에서도 시군구별로 사정이 갈리므로, 이 수치는 시장의 방향을 보는 값이지 개별 단지의 사정을 말해 주지 않는다.</p>
</section>

<section class="wrap">
  <h2>더 보기</h2>
  <div class="links">
    <a href="/#stats-adv-occ">입주물량 차트<span>분기별 추이를 적정수요와 견줘 지역별로</span></a>
    <a href="/zone/">시도별 공급 분석<span>17개 시도의 부족·과잉을 등급으로</span></a>
    <a href="/jeonse-ratio/">전세가율<span>입주물량이 움직이는 결과 — 시도별 현황</span></a>
    <a href="/cycle/">아파트 사이클 리포트<span>입주 → 전세 → 매매로 이어지는 고리, 데이터 검증</span></a>
  </div>
</section>
""" % dict(nat26=num(nat26), nat27=num(nat27), trs='\n'.join(trs),
           lastact=last_act.replace('Q', '년 ') + '분기',
           lo1=lo1[0], lo1p=round(lo1[1]), hi1=hi1[0], hi1p=round(hi1[1]),
           sudo26=num(sudo['2026'] or 0), sudo27=num(sudo['2027'] or 0),
           sudodir=updown(sudo['2026'], sudo['2027']))

    html = fill(SHELL, title=title,
                ogtitle='아파트 입주물량 — 2026년 전국 %s세대' % num(nat26),
                desc=desc, url=url, body=body,
                ld=ld_pack('아파트 입주물량 — 시도별 입주 예정과 의미', desc, url, '입주물량', mod_iso),
                src='국토교통부 주택건설실적(준공·착공)')
    return html, not_before_pub(mod_iso)


# ---- sitemap ---------------------------------------------------------------
def update_sitemap(entries):
    """entries: [(path('/moveins/'), lastmod_iso)] — 있으면 lastmod 갱신, 없으면 추가."""
    p = os.path.join(ROOT, 'sitemap.xml')
    x = io.open(p, encoding='utf-8').read()
    for path, lm in entries:
        loc = SITE + path
        pat = r'(<loc>%s</loc>\s*<lastmod>)[^<]*(</lastmod>)' % re.escape(loc)
        if re.search(pat, x):
            x = re.sub(pat, r'\g<1>%s\g<2>' % lm, x)
        else:
            block = ('\n  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>\n'
                     '    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>'
                     % (loc, lm))
            x = x.replace('</urlset>', block + '\n</urlset>')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(x)


def main():
    adv, sts = load()
    out = []
    for sub, (html, lm) in (
            ('jeonse-ratio', build_jeonse(sts)),
            ('moveins', build_moveins(adv))):
        d = os.path.join(ROOT, sub)
        os.makedirs(d, exist_ok=True)
        io.open(os.path.join(d, 'index.html'), 'w', encoding='utf-8', newline='\n').write(html)
        out.append(('/%s/' % sub, lm))
    update_sitemap(out)
    print('indicator pages: %s' % ', '.join('%s(%s)' % e for e in out))


if __name__ == '__main__':
    main()

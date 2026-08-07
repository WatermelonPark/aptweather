# -*- coding: utf-8 -*-
"""시도 20곳의 공급 상세 페이지와 허브를 만든다.

옛 make_zone_pages.py(생활권 31곳·시군구 페이지·건축HUB 단지 목록)를 대체한다.
지역이 국토부 통계와 같은 단위가 되면서 안분·풀 재배선·단지 수집이 통째로
필요 없어졌고, 페이지도 그만큼 단순해졌다(50KB → 10KB대).

점수는 계산하지 않는다 — tools/sido_zones.py가 빌드 시점에 계산해 ADV.sido로
싣고, 여기서는 그걸 읽어 그리기만 한다. 홈(index.html)도 같은 값을 읽으므로
두 화면이 갈릴 수 없다(옛 이중구현 미러와 그 감시 도구가 사라진 이유).

사용: python tools/make_sido_pages.py
"""
import datetime
import io
import json
import math
import os
import re
import shutil
import sys
import urllib.parse

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sido_zones as SZ                                            # noqa: E402

SITE = 'https://www.agongmap.co.kr'
OUT = os.path.join(ROOT, 'zone')
GA = 'G-3FJNG6G1F3'
# 표 시작. 홈 통합표(index.html TB_FROM = 2017.01)와 같은 지점이어야 한다 —
# 두 화면이 같은 지역을 다른 구간으로 그리면 숫자를 맞춰보는 사람이 어긋난 걸 본다.
TABLE_FROM = SZ.qidx(2017, 1)

GRADE_TXT = {
    'g4': ('매우 부족', '#a93226', '앞으로 3년, 필요한 집이 크게 모자랍니다'),
    'g3': ('부족', '#c0392b', '공급이 수요를 못 따라갑니다'),
    'g2': ('다소 부족', '#b9770e', '부족하지만 심하진 않습니다'),
    'g1': ('균형', '#5e6f74', '필요한 만큼 들어오고 있습니다'),
    'g0': ('공급 여유', '#1a5276', '입주가 몰려 있어 세입자·매수자에게 유리한 시기가 옵니다'),
}
# 집계 3종은 '지역'이 아니라 묶음이라 설명이 달라야 한다
AGG_NOTE = {
    '전국': '전국 17개 시도를 합친 값입니다.',
    '수도권': '서울·경기·인천을 합친 값입니다. 적정물량 50,000호는 기준표 그대로이고, '
              '서울·경기·인천 개별 값은 이를 세대수 비중으로 나눈 추정치입니다.',
    '지방': '수도권을 뺀 14개 시도를 합친 값입니다.',
}


DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')


def read_old(path):
    try:
        return io.open(path, encoding='utf-8').read()
    except IOError:
        return None


def keep_dates(new_html, old_html, today):
    """내용이 같고 날짜만 다르면 **옛 페이지를 그대로** 돌려준다.

    ⚠️ 이게 없으면 데이터가 안 바뀐 날에도 21장과 sitemap의 lastmod가 날짜만
    달라진 채 매일 커밋된다(옛 make_zone_pages가 같은 이유로 갖고 있던 장치인데
    2026-08-06 재편 때 빠뜨렸다). 검색엔진에도 '매일 전부 갱신'이라는 틀린 신호가
    간다. 페이지 안의 YYYY-MM-DD는 datePublished·dateModified 둘뿐이라 날짜만
    가려내고 비교하면 된다.

    돌려주는 값: (채택할 HTML, 그 페이지의 lastmod, 내용이 실제로 바뀌었나)

    ⚠️ 세 번째 값이 필요하다. lastmod == today로 '바뀌었나'를 판정하면, 옛 날짜가
    마침 오늘일 때(같은 날 두 번 생성) 안 바뀐 페이지도 바뀐 것으로 센다.
    """
    if not old_html:
        return new_html, today, True
    if DATE_RE.sub('@', new_html) == DATE_RE.sub('@', old_html):
        m = re.search(r'"dateModified":\s*"(\d{4}-\d{2}-\d{2})"', old_html)
        return old_html, (m.group(1) if m else today), False
    # ⚠️ 내용이 바뀌어도 **최초 발행일은 물려받는다**. 안 그러면 갱신 회차마다
    # datePublished가 오늘로 다시 찍혀, 8월에 색인된 페이지가 9월에 '어제 처음
    # 발행됨, 수정 이력 없음'이라고 선언한다(2026-08-07 감사).
    pub = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})"', old_html)
    if pub:
        new_html = new_html.replace('"datePublished": "%s"' % today,
                                    '"datePublished": "%s"' % pub.group(1), 1)
    return new_html, today, True


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def rnd(v):
    """JS Math.round와 같은 half-up. 파이썬 기본 round()는 은행가 반올림이라
    비율이 정확히 x.5인 칸에서 홈(Math.round)과 1%p 어긋났다 — 1,000칸 중 7칸
    (부산 25Q2 88.5%: zone 88% vs 홈 89%, 2026-08-08 감사)."""
    return int(math.floor(float(v) + 0.5))


def num(v):
    return format(rnd(v), ',')


def disp_tot(row, H):
    """화면에 찍는 누적 순부족. ADV의 tot는 반올림 전 값들로 계산돼서, 카드에 찍은
    정수 셋(적정·공급·재고)으로 검산하면 1~2세대가 남는다. 허브 목록과 상세 카드가
    **같은 정수**를 쓰도록 여기서 한 번만 만든다(2026-08-08 감사에서 4곳이 갈렸다)."""
    return rnd(row['ref']) * H - rnd(row['fut']) - rnd(row['inow'])


def signed(v):
    """부족은 −, 과잉은 + 로 보여준다(홈 표기와 같은 부호 규칙)."""
    d = -v
    return ('−' if d < 0 else '+') + num(abs(d))


def load():
    src = io.open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    adv = json.loads(re.search(
        r'/\*ADV_DATA_START\*/\s*const ADV=(\{.*?\});?\s*/\*ADV_DATA_END\*/', src, re.S).group(1))
    stats = json.loads(re.search(
        r'const STATS\s*=\s*(\{.*?\});?\s*(?:/\*|const |$)', src, re.S).group(1))
    return adv, stats


def price_quarters(adv):
    """{분기 인덱스: {지역: [매매, 전세, 월세]}} — 월별 변동률을 분기로 합친다.

    ⚠️ 자료가 하나도 없는 지역·분기는 **키를 만들지 않고**, 항목별로도 값이 없으면
    None으로 남긴다. 예전엔 모든 지역에 [0,0,0]을 먼저 깔아 놔서 지수가 결측인 곳이
    '+0.0%'(완전 보합)로 인쇄됐다 — 광주·전남은 2025-05~2026-06 14개월이 통째로
    결측인데 최근 4분기가 전부 보합으로 보였다(2026-08-07 감사).
    """
    mo = (adv.get('monthly') or {})
    regs = mo.get('regions') or []
    out = {}
    for r in mo.get('rows') or []:
        y, m = int(r['p'][:4]), int(r['p'][5:7])
        i = SZ.qidx(y, (m - 1) // 3 + 1)
        cur = out.setdefault(i, {})
        for k, reg in enumerate(regs):
            for f, n in (('ma', 0), ('je', 1), ('wo', 2)):
                v = (r.get(f) or [None] * len(regs))[k]
                if v is None:
                    continue
                a = cur.get(reg)
                if a is None:
                    a = cur[reg] = [None, None, None]
                a[n] = (a[n] or 0) + v
    return out

def series(stats, z, calc):
    """지역 하나의 분기별 공급 — (분기 인덱스, 값, 미래 여부) 목록."""
    L = SZ.qidx(int(calc['L'][:4]), int(calc['L'][5:]))
    dn = SZ.quarterly(stats, '준공', z)
    st = SZ.quarterly(stats, '착공', z)
    rows = []
    for i in range(TABLE_FROM, L + calc['H'] + 1):
        if i <= L:
            rows.append((i, dn.get(i, 0), False))
        else:
            # ⚠️ 여기서 반올림하지 않는다. 홈(index.html)은 raw에서 세대수와 %를
            # 각각 반올림하는데, 여기서 먼저 굳히면 경남 27Q2가 1349.822 → 1350 →
            # 22.5% → 23%가 되어 홈의 22%와 갈린다(2026-08-08 감사, 1,000칸 중 1칸).
            rows.append((i, st.get(i - calc['lead'], 0) * calc['conv'], True))
    return rows


def head(z, desc, title, url=None, crumb=None):
    """⚠️ url을 안 넘기면 z를 지역명으로 보고 /zone/{z}/ 를 만든다. 허브처럼
    z 자리에 제목을 넘기는 곳은 반드시 url을 주어야 한다 — 안 그러면 canonical·
    og:url·JSON-LD가 존재하지 않는 /zone/시도별%20공급/ 을 가리킨다(2026-08-07 감사)."""
    u = url or (SITE + '/zone/' + urllib.parse.quote(z) + '/')
    ld = [
        {"@context": "https://schema.org", "@type": "Article", "headline": title,
         "description": desc,
         "datePublished": datetime.date.today().isoformat(),
         "dateModified": datetime.date.today().isoformat(),
         "author": {"@type": "Organization", "name": "아공맵"},
         "publisher": {"@type": "Organization", "name": "아공맵"},
         "mainEntityOfPage": u,
         "about": {"@type": "Place", "name": z}},
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "아공맵", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "시도 공급 분석", "item": SITE + "/zone/"}]
            + ([] if crumb is False else
               [{"@type": "ListItem", "position": 3, "name": z, "item": u}])},
    ]
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=%(ga)s"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','%(ga)s');</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css" media="print" onload="this.media='all'">
<noscript><link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css"></noscript>
<title>%(title)s | 아공맵</title>
<meta name="description" content="%(desc)s">
<link rel="canonical" href="%(url)s">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" href="/app_icon.png">
<meta name="theme-color" content="#16203a">
<meta property="og:type" content="article">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(url)s">
<meta property="og:image" content="%(site)s/share/weekly-map.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">%(ld)s</script>
<link rel="stylesheet" href="/app.css">
</head>
<body>
''' % {'ga': GA, 'title': esc(title), 'desc': esc(desc), 'url': u, 'site': SITE,
       'ld': json.dumps(ld, ensure_ascii=False)}


FOOT = '''<footer><div class="wrap">
  <b>아공맵</b> — 아파트 · 공급량 · 투자지도<br>
  <a href="/">agongmap.co.kr</a> · <a href="/about/">아공맵 소개</a> · 자료: 국토교통부 주택건설실적(준공·착공) · 한국부동산원 아파트 실거래가격지수
  <div class="disc">공공 데이터를 가공한 참고 자료이며 투자자문이 아닙니다. 투자 판단과 책임은 이용자에게 있습니다.</div>
</div></footer>

<nav class="bottomnav">
  <a class="nav-btn" href="/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3 11l9-8 9 8M5 10v10h14V10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>홈</span></a>
  <a class="nav-btn" href="/#test"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="7.4" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="7.4" cy="12" r="1.7" fill="currentColor"/><circle cx="16.6" cy="12" r="4.4" fill="none" stroke="currentColor" stroke-width="2"/></svg><span>퀴즈</span></a>
  <a class="nav-btn" href="/#stats"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span>통계</span></a>
  <a class="nav-btn" href="/cycle/"><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M20.3 3.7v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>리포트</span></a>
</nav>
</body>
</html>
'''


def tint(v, scale):
    """홈 표와 같은 색 규칙 — 0.00일 때만 무색, 아니면 최소 0.13은 물든다."""
    if v is None or v == 0:
        return 'transparent'
    a = (0.13 + 0.87 * min(1.0, abs(v) / float(scale))) * 0.8
    return ('rgba(198,58,48,%.3f)' if v > 0 else 'rgba(38,110,180,%.3f)') % a


def build_page(z, calc, stats, pq, others):
    row = [x for x in calc['zones'] if x['z'] == z][0]
    lab, color, gdesc = GRADE_TXT[row['grade']]
    rows = series(stats, z, calc)
    L = SZ.qidx(int(calc['L'][:4]), int(calc['L'][5:]))
    fut = [r for r in rows if r[2]]
    yrs = calc['H'] / 4.0
    # ⚠️ 카드 세 개는 **서로 검산이 되어야 한다**. 예전엔 '앞으로 3년 공급'만 분기별
    # 반올림의 합(fut_sum)이라 ADV.sido의 fut과 1~2세대 어긋났고, 같은 페이지의
    # '어떻게 계산했나' 산식으로 검산하면 20곳 중 12곳이 안 맞았다(2026-08-08 감사).
    # 표시할 정수로 먼저 고정하고, 누적 순부족은 그 정수들로 계산한다.
    d_ref, d_fut, d_inow = rnd(row['ref']), rnd(row['fut']), rnd(row['inow'])
    d_tot = disp_tot(row, calc['H'])
    fut_sum = d_fut

    desc = ('%s의 아파트 공급은 적정물량 대비 %s세대(%s). 앞으로 %.0f년 착공 기준 공급 %s세대, '
            '분기 적정물량 %s호. 국토교통부 준공·착공 실적으로 매주 자동 갱신.'
            % (z, signed(d_tot), lab, yrs, num(d_fut), num(d_ref)))
    title = '%s 아파트 공급 분석 — %s' % (z, lab)

    h = [head(z, desc, title)]
    h.append('<header class="zhead"><div class="wrap">'
             '<nav class="crumb"><a href="/">아공맵</a> › <a href="/zone/">시도 공급 분석</a> › <b>%s</b></nav>'
             '<h1>%s 아파트 공급</h1>'
             '<p class="zlead"><span class="sc-tier %s">%s</span> %s</p>'
             % (esc(z), esc(z), row['grade'], esc(lab), esc(gdesc)))
    if row.get('uwarn'):
        # 미분양은 순위 산식에 안 들어간다(결과값이라 이중계상). 다만 판정과
        # 어긋나면 그 사실을 숨기지 않는다 — 제주가 '매우 부족'인데 미분양이
        # 적정물량의 2.4배인 건 읽는 사람이 알아야 한다(2026-08-07).
        h.append('<p class="zwarn">⚠ 부족으로 나오지만 <b>미분양이 %s호</b> 쌓여 '
                 '있습니다(분기 적정물량의 %.1f배). 지을 데가 없어서가 아니라 '
                 '안 팔려서 안 짓는 것일 수 있습니다.</p>'
                 % (num(row['unsold']), row['um']))
    if z in AGG_NOTE:
        h.append('<p class="znote">%s</p>' % esc(AGG_NOTE[z]))
    elif row['est']:
        h.append('<p class="znote">적정물량 %s호는 기준표에 없어 추정한 값입니다. '
                 '%s</p>' % (num(row['ref']),
                             '수도권 기준을 세대수 비중으로 나눴습니다.' if z in ('서울', '경기', '인천')
                             else '다른 시도의 세대당 원단위로 환산했습니다.'))
    h.append('</div></header>')

    # ── 핵심 수치 ──
    h.append('<section><div class="wrap"><h2>숫자로 보면</h2><div class="zgrid">')
    for k, v, note in (
        # ⚠️ 부호를 뒤집지 않는다. tot는 '양수=부족'인데 signed()로 −를 붙이면
        # 바로 아래 '어떻게 계산했나'의 산식(필요량 − 지어질 물량 − 재고)으로
        # 검산했을 때 부호가 반대가 된다(2026-08-07 감사).
        ('누적 순부족', ('%s세대 부족' % num(d_tot)) if d_tot >= 0
         else ('%s세대 여유' % num(-d_tot)),
         '앞으로 %.0f년 필요량에서 이미 쌓인 재고와 지어질 물량을 뺀 값' % yrs),
        ('지난 4년 재고', signed(-d_inow) + '세대',
         '준공에서 멸실과 적정물량을 뺀 누적. −는 그만큼 모자랐다는 뜻'),
        ('앞으로 %.0f년 공급' % yrs, num(fut_sum) + '세대',
         '이미 착공한 물량을 3년 뒤로 밀어 추정'),
        ('분기 적정물량', num(d_ref) + '호',
         '가격이 하락에서 상승으로 돌아선 시점의 입주물량 실측 기준선'),
        ('미분양', (num(row['unsold']) + '호') if row.get('unsold') is not None else '–',
         ('%s 기준 · 분기 적정물량의 %.2f배' % (calc.get('unsold_prd') or '', row['um']))
         if row.get('um') is not None else '자료 없음'),
    ):
        h.append('<div class="zcell"><b>%s</b><span>%s</span><i>%s</i></div>' % (k, v, note))
    h.append('</div></section>')

    # ── 기간별 표 ──
    h.append('<section><div class="wrap"><h2>%s의 분기별 공급</h2>'
             '<p class="zsub">칸 색은 실적 구간에서는 가격 변동(매매·전세·월세), '
             '미래 구간에서는 적정물량 대비 모자란 정도입니다.</p>'
             '<div class="ztb-scroll"><table class="ztb">'
             '<thead><tr><th>기간</th><th>공급</th><th>적정 대비</th>'
             '<th>매매</th><th>전세</th><th>월세</th></tr></thead><tbody>' % esc(z))
    first_fut = True
    for i, v, isfut in rows:
        cls = ''
        if isfut and first_fut:
            cls = ' class="znow"'; first_fut = False
        pct = rnd(v / float(row['ref']) * 100) if row['ref'] else 0
        gap = (1 - v / float(row['ref'])) if row['ref'] else None
        p = (pq.get(i) or {}).get(z)
        if isfut:
            cells = ('<td style="background:%s">%d%%</td>' % (tint(gap, 1), pct)
                     + '<td colspan="3" class="zfut">착공 기준 추정</td>')
        else:
            cells = ('<td>%d%%</td>' % pct) + ''.join(
                '<td style="background:%s">%s</td>'
                % (tint((p[n] if p else None), 2),
                   ('%+.1f%%' % p[n]) if (p and p[n] is not None) else '–')
                for n in (0, 1, 2))
        h.append('<tr%s><td>%s</td><td>%s</td>%s</tr>'
                 % (cls, SZ.qlabel(i), num(v), cells))
    h.append('</tbody></table></div>'
             '<p class="zsub">굵은 줄 아래 %d분기가 미래입니다. 0은 그 분기에 실제로 없었다는 뜻입니다'
             '(굵은 줄 위는 준공, 아래는 착공).</p>'
             '</div></section>' % calc['H'])

    # ── 산출 방법 ──
    h.append('<section><div class="wrap"><h2>어떻게 계산했나</h2>'
             '<p>칸의 숫자는 그 분기에 <b>준공된</b> 아파트 세대수입니다(국토교통부 주택건설 준공실적). '
             '아직 오지 않은 분기는 <b>착공 실적을 3년 뒤로 밀어</b> 추정했습니다 — '
             '착공한 것의 96%%가 3년 뒤 준공되는 게 15년치 실측입니다. '
             '인허가는 쓰지 않습니다. 삽을 안 뜬 계획이 섞여 실제보다 1.3~1.7배 부풀기 때문입니다.</p>'
             '<p>누적 순부족은 <b>앞으로 %d분기 필요량 − 지어질 물량 − 지난 16분기에 쌓인 재고</b>입니다. '
             '재고에서는 멸실(철거)을 뺐지만 <b>앞으로 헐릴 집은 빼지 않았습니다</b> — '
             '재건축 시기를 미리 알 방법이 없어서입니다. 그만큼 부족이 덜 잡힙니다.</p>'
             '<p><b>미분양</b>은 지금 안 팔리고 남은 집입니다(한국부동산원). '
             '순위 계산에는 넣지 않습니다 — 결과값이라 공급에서 빼면 이중으로 세고 부호도 반대가 됩니다. '
             '판정을 읽는 맥락으로만 씁니다.</p>'
             '<p>공급 기준이며 가격 예측이 아닙니다. 금리가 크게 움직이면 공급 신호는 가격에 묻힙니다.</p>'
             '</div></section>' % calc['H'])

    # ── 다른 지역 ──
    h.append('<section><div class="wrap"><h2>다른 지역</h2><div class="zlinks">')
    for o in others:
        if o['z'] == z:
            continue
        h.append('<a href="/zone/%s/"><b>%s</b><span class="sc-tier %s">%s</span></a>'
                 % (urllib.parse.quote(o['z']), esc(o['z']), o['grade'], GRADE_TXT[o['grade']][0]))
    h.append('</div><p class="zsub" style="margin-top:14px">'
             '<a href="/">← 전국 공급 표로 돌아가기</a></p></div></section>')
    h.append(FOOT)
    return ''.join(h)


def build_hub(calc):
    agg = [z for z in calc['zones'] if z['agg']]
    sido = SZ.zone_order(calc['zones'])
    desc = ('전국 17개 시도의 아파트 공급을 적정물량과 견줘 정리했습니다. '
            '실적은 국토교통부 준공, 앞으로 %d분기는 착공 실적 기준. 기준 %s.'
            % (calc['H'], calc['L']))
    h = [head('시도별 공급', desc, '시도별 아파트 공급 분석',
              url=SITE + '/zone/', crumb=False)]
    h.append('<header class="zhead"><div class="wrap">'
             '<nav class="crumb"><a href="/">아공맵</a> › <b>시도 공급 분석</b></nav>'
             '<h1>시도별 아파트 공급</h1>'
             '<p class="zlead">%s</p></div></header>' % esc(desc))
    h.append('<section><div class="wrap"><h2>전국·수도권·지방</h2><div class="zlinks">')
    for o in agg:
        h.append('<a href="/zone/%s/"><b>%s</b><span class="sc-tier %s">%s</span></a>'
                 % (urllib.parse.quote(o['z']), esc(o['z']), o['grade'], GRADE_TXT[o['grade']][0]))
    h.append('</div><h2>17개 시도</h2>'
             '<div class="tb-seg zsort" id="sido-sort" role="group" aria-label="정렬 기준">'
             '<button type="button" class="on" aria-pressed="true" data-s="g">등급순</button>'
             '<button type="button" aria-pressed="false" data-s="a">세대수순</button></div>'
             # ⚠️ 정렬은 순부족(tot) 내림차순이다. 공급 여유 등급은 tot가 음수라
             # '세대수가 많은 순'이라고 쓰면 반대로 읽힌다 — 여유가 가장 큰 충남이
             # 맨 아래에 온다(2026-08-07 감사). 부호를 포함해 정확히 쓴다.
             '<p class="zsub" id="sido-note">등급순입니다. 같은 등급 안에서는 '
             '모자란 세대수가 큰 순(공급 여유 등급에서는 여유가 적은 순).</p>'
             '<div class="zlinks" id="sido-list">')
    for o in sido:
        h.append('<a href="/zone/%s/" data-gi="%d" data-tot="%d"><b>%s</b>'
                 '<span class="sc-tier %s">%s</span><i>%s세대</i></a>'
                 % (urllib.parse.quote(o['z']), SZ.GRADE_KEYS.index(o['grade']),
                    disp_tot(o, calc['H']),
                    esc(o['z']), o['grade'], GRADE_TXT[o['grade']][0],
                    signed(disp_tot(o, calc['H']))))
    h.append('</div></div></section>')
    h.append('<script>(function(){'
             'var w=document.getElementById("sido-list"),seg=document.getElementById("sido-sort"),'
             'note=document.getElementById("sido-note");'
             'if(!w||!seg)return;'
             'var g=function(e,k){return +e.getAttribute(k)};'
             'seg.addEventListener("click",function(ev){'
             'var b=ev.target.closest("button");if(!b)return;var s=b.getAttribute("data-s");'
             'Array.prototype.forEach.call(seg.children,function(x){'
             'var on=x===b;x.classList.toggle("on",on);x.setAttribute("aria-pressed",on?"true":"false")});'
             'var a=Array.prototype.slice.call(w.children);'
             'a.sort(s==="a"?function(x,y){return g(y,"data-tot")-g(x,"data-tot")}'
             ':function(x,y){return g(x,"data-gi")-g(y,"data-gi")||g(y,"data-tot")-g(x,"data-tot")});'
             'a.forEach(function(el){w.appendChild(el)});'
             'if(note)note.textContent=s==="a"'
             '?"모자란 세대수가 큰 순입니다(공급 여유 등급은 여유가 적은 순). 등급은 필요량 대비 비율이라 순서가 다릅니다."'
             ':"등급순입니다. 같은 등급 안에서는 모자란 세대수가 큰 순(공급 여유 등급에서는 여유가 적은 순).";'
             '});})();</script>')
    h.append(FOOT)
    return ''.join(h)


HOME_STAMP = os.path.join(ROOT, 'tools', 'data', '.home_stamp')


def _home_lastmod(today):
    """홈·/weekly/의 lastmod. data-core.js 내용이 바뀐 날만 오늘로 민다.

    두 페이지는 data-core.js(ADV.weekly.sgg 최신 주차, ADV.sido)를 그려서 만든다.
    파일 해시를 도장으로 남겨, 내용이 같은 날은 옛 날짜를 유지한다.
    """
    import hashlib
    try:
        h = hashlib.sha1(io.open(os.path.join(ROOT, 'data-core.js'), 'rb').read()).hexdigest()[:16]
    except IOError:
        return today
    prev = ''
    try:
        prev = io.open(HOME_STAMP, encoding='utf-8').read().strip()
    except IOError:
        pass
    old_h, _, old_d = prev.partition(' ')
    if old_h == h and old_d:
        return old_d
    try:
        os.makedirs(os.path.dirname(HOME_STAMP), exist_ok=True)
        io.open(HOME_STAMP, 'w', encoding='utf-8').write('%s %s' % (h, today))
    except IOError:
        pass
    return today


def update_sitemap(names, lastmods, hub_lastmod, home_lastmod):
    """/zone/ 항목을 통째로 갈아 끼운다.

    옛 생활권 31곳 URL이 남아 있으면 색인에 404가 쌓인다 — 먼저 전부 지우고
    새 20곳만 넣는다(리다이렉트는 두지 않기로 함, 2026-08-06 사용자 결정).

    ⚠️ lastmod는 **페이지별로 실제 내용이 바뀐 날**이다. 오늘 날짜를 일괄로 박으면
    안 바뀐 날에도 21줄이 매일 달라져 커밋되고, 검색엔진엔 '매일 전부 갱신'이라는
    틀린 신호가 간다. home_lastmod는 한 장이라도 바뀐 날에만 넘어온다(아니면 None).
    """
    p = os.path.join(ROOT, 'sitemap.xml')
    x = io.open(p, encoding='utf-8').read()
    x = re.sub(r'\s*<url>\s*<loc>[^<]*/zone/[^<]*</loc>.*?</url>', '', x, flags=re.S)
    if home_lastmod:
        for loc in ('%s/' % SITE, '%s/weekly/' % SITE):
            x = re.sub(r'(<loc>%s</loc>\s*<lastmod>)[^<]*(</lastmod>)' % re.escape(loc),
                       r'\g<1>%s\g<2>' % home_lastmod, x)
    block = ('\n  <url>\n    <loc>%s/zone/</loc>\n    <lastmod>%s</lastmod>\n'
             '    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>'
             % (SITE, hub_lastmod))
    block += ''.join(
        '\n  <url>\n    <loc>%s/zone/%s/</loc>\n    <lastmod>%s</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>'
        % (SITE, urllib.parse.quote(n), lastmods[n]) for n in names)
    x = x.replace('</urlset>', block + '\n</urlset>')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(x)


def main():
    adv, stats = load()
    calc = adv.get('sido')
    assert calc and calc.get('zones'), 'ADV.sido가 없다 — update_adv_data.py --seed-sido 먼저'
    # ⚠️ 점수(ADV.sido)와 표(STATS)가 같은 시점이어야 한다. sido 가드가 옛 점수를
    # 보존한 회차에 STATS만 새로 들어오면, 한 페이지 안에 옛 등급과 새 표가 섞여
    # 스스로 모순된 페이지가 구워진다(2026-08-07 감사).
    _live = SZ.calc(stats)
    if _live['L'] != calc['L'] or _live['H'] != calc['H']:
        raise SystemExit('ABORT: ADV.sido(실적~%s, %d분기)와 STATS(실적~%s, %d분기)의 '
                         '시점이 다르다 — --seed-sido로 점수를 먼저 맞출 것.'
                         % (calc['L'], calc['H'], _live['L'], _live['H']))
    # ⚠️ L·H는 '전국' 시리즈에서만 나온다. 지역명 개편 등으로 **일부 시도만** 결측이
    # 되면 L·H는 그대로라 위 게이트를 통과하는데, 그 상태로 구우면 등급 카드는 옛
    # 점수(24,297세대 부족)인데 분기 표는 전 칸 0인 자가당착 페이지가 나온다
    # (2026-08-07 감사에서 울산으로 재현). 지역 구성까지 같은지 본다.
    # ⚠️ H는 착공 끝 − 준공 끝 + 리드타임이라, 두 시리즈가 같은 분기에서 끝나야
    # H == lead가 된다. 한쪽만 늦게 들어온 회차(부분 수집)에는 H가 13이 되고
    # 등급이 3곳까지 조용히 바뀌는데 테스트·게이트가 전부 통과한다(2026-08-08 감사).
    # 실측상 두 계열은 같은 표의 두 열이라 늘 함께 도착한다 — 어긋나면 수집 사고다.
    if _live['H'] != _live['lead']:
        raise SystemExit('ABORT: 준공(~%s)과 착공(~%s)의 끝 분기가 달라 H=%d다(정상 %d) — '
                         '한쪽만 수집된 회차로 보인다. 데이터를 먼저 맞출 것.'
                         % (_live['L'], _live['S'], _live['H'], _live['lead']))
    if _live.get('missing'):
        raise SystemExit('ABORT: STATS 준공·착공에서 %d곳이 결측이다(%s) — 데이터를 '
                         '먼저 복구할 것.' % (len(_live['missing']), ', '.join(_live['missing'])))
    if {z['z'] for z in _live['zones']} != {z['z'] for z in calc['zones']}:
        raise SystemExit('ABORT: ADV.sido의 지역 구성(%d곳)과 STATS로 다시 센 구성(%d곳)이 '
                         '다르다 — --seed-sido로 점수를 먼저 맞출 것.'
                         % (len(calc['zones']), len(_live['zones'])))
    pq = price_quarters(adv)
    names = [z['z'] for z in calc['zones']]

    # 옛 생활권 디렉터리 정리. 이름이 통째로 바뀌었으므로 남겨두면 stale 페이지가
    # 색인에 그대로 남는다(리다이렉트도 두지 않기로 함 — 2026-08-06 사용자 결정).
    gone = []
    if os.path.isdir(OUT):
        for d in os.listdir(OUT):
            p = os.path.join(OUT, d)
            if os.path.isdir(p) and d not in names:
                shutil.rmtree(p); gone.append(d)
    os.makedirs(OUT, exist_ok=True)

    today = datetime.date.today().isoformat()
    lastmods, changed = {}, 0
    for z in names:
        d = os.path.join(OUT, z)
        os.makedirs(d, exist_ok=True)
        fp = os.path.join(d, 'index.html')
        html, lm, ch = keep_dates(build_page(z, calc, stats, pq, calc['zones']),
                                  read_old(fp), today)
        if ch:
            changed += 1
        lastmods[z] = lm
        io.open(fp, 'w', encoding='utf-8', newline='\n').write(html)
    hub_fp = os.path.join(OUT, 'index.html')
    hub, hub_lm, hub_ch = keep_dates(build_hub(calc), read_old(hub_fp), today)
    io.open(hub_fp, 'w', encoding='utf-8', newline='\n').write(hub)
    # ⚠️ 홈·/weekly/ lastmod를 zone 변경에만 묶으면 안 된다. 주간 회차가 새로 들어온
    # 날 홈 히어로 지도와 /weekly/ 지도는 실제로 바뀌는데 zone 20장은 분기 준공·착공만
    # 읽으므로 changed=0이 되고, 두 페이지 lastmod가 영영 안 움직인다(2026-08-07 감사).
    # data-core.js의 내용 해시로 판정한다 — 그게 두 페이지의 실제 입력이다.
    home_lm = _home_lastmod(today)
    update_sitemap(names, lastmods, hub_lm, home_lm)

    print('지역 페이지 %d개 + 허브 (실적~%s, 미래 %d분기) — 내용 변경 %d개'
          % (len(names), calc['L'], calc['H'], changed))
    if gone:
        print('옛 생활권 디렉터리 %d개 삭제: %s' % (len(gone), ', '.join(sorted(gone))))
    return 0


if __name__ == '__main__':
    sys.exit(main())

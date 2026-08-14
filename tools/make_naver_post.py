# -*- coding: utf-8 -*-
"""네이버 블로그 초안 생성 — drafts/naver-<주차>.html

네이버 블로그는 개인 블로그용 글쓰기 API가 없어 완전 자동화가 불가능하다.
그래서 '붙여넣기만 하면 되는 초안'을 매주 만들어 두는 반자동 방식을 쓴다.

만들어지는 초안 2건:
  ① 주간 시세 + 아공맵 해설  — 속보성, 매주 내용이 바뀐다
  ② 지역 심층 리포트         — 매주 한 곳씩 순회(모두 돌면 처음부터)

사용법:
  python tools/make_naver_post.py      # drafts/naver-<주차>.html 생성
  브라우저로 열고 → [복사] 버튼 → 스마트에디터에 붙여넣기 → 이미지 끌어놓기 → 발행

drafts/ 는 .gitignore 대상이다(사이트에 공개될 초안이 아니라 로컬 작업물).

⚠️ 이 생성기는 **사이트와 같은 말을 해야 한다.** 블로그가 사이트에 없는 산식을
설명하면, "계산법을 전부 공개한다"는 아공맵의 신뢰 근거가 그 자리에서 무너진다.
그래서 지평·등급 라벨·지역 수를 문자로 박지 않고 sido_zones의 상수를 읽는다.
2026-08-06 시도 재편(생활권 44곳 → 시도 20곳, 인허가 4년 → 착공 3년)으로 한 번
전면 재작성했다. 다음에 모델이 바뀌면 '설명 구조'가 그대로인지부터 확인할 것.
"""
import io, os, re, sys, json, datetime
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_sido_pages as M  # noqa: E402  (load 재사용)
import sido_zones as SZ      # noqa: E402  (zone_order·GRADE_LABS·상수)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'drafts')
STATE = os.path.join(OUT, '.rotation.json')
SITE = 'https://www.agongmap.co.kr'


def num(n):
    return format(int(round(n)), ',')


def pct(v):
    """-0.004 가 '-0.00%'로 찍히는 것(음수 0) 방지."""
    if v is None:
        return '—'
    return '0.00%' if abs(v) < 0.005 else '%+.2f%%' % v


def kdate(p):
    """'2026-07-13' -> '7월 13일' (블로그 본문에 ISO 날짜는 어색하다)."""
    y, m, d = p.split('-')
    return '%d월 %d일' % (int(m), int(d))


def iga(w):
    """이/가 조사. 옛 지역명은 전부 '권'으로 끝나 '이' 고정이 맞았지만,
    시도명은 제주·경기처럼 받침 없는 이름이 있다('제주이' 오류, 2026-08-14 실측)."""
    c = ord(w[-1])
    return '이' if 0xAC00 <= c <= 0xD7A3 and (c - 0xAC00) % 28 else '가'


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


# ---------------------------------------------------------------- 순회 상태
# 검색 수요가 실증된 지역을 앞에 세운다(2026-08-14 네이버 키워드도구 실측).
# 우리 주제(미분양·입주물량·공급·시세·전망) 월간 검색량 합계:
#   대구 6,580 · 부산 4,540 · 서울 3,200 · 경기 1,455 · 세종 1,390
#   광주 410 · 울산 35 · 인천 25 · 나머지 9개 시도 0
# 대구·부산이 압도적인 건 미분양이 실제로 심각해서다 — 그 지역 미분양 검색이
# 월 1천~3천이고, 우리는 그 수치와 "미분양이 쌓여 착공이 멈췄다"는 해석을
# 함께 갖고 있다. 순부족 절대값 순서로 돌면 이 지역들이 한참 뒤로 밀린다.
PRIORITY = ('서울', '대구', '부산', '경기', '세종', '광주')


def pick_zone(rows):
    """아직 안 다룬 지역 중 하나를 고른다 — PRIORITY 먼저, 그다음 |순부족| 순.

    한 바퀴 돌면 초기화. 주차 번호로 나머지 연산을 하면 데이터가 바뀔 때
    같은 곳이 연달아 걸릴 수 있어, 다룬 목록을 파일로 남기는 쪽을 택했다.
    ⚠️ 2026-08-06 재편으로 지역 이름이 전부 바뀌었다(생활권 → 시도). 옛 순회
    기록이 남아 있으면 없는 이름만 가리키므로, 현재 목록에 없는 이름은 버린다.
    """
    names = {r['z'] for r in rows}
    done = []
    if os.path.exists(STATE):
        try:
            done = json.load(io.open(STATE, encoding='utf-8')).get('done', [])
        except Exception:
            done = []
    done = [d for d in done if d in names]

    def rank(r):
        # PRIORITY에 있으면 그 순서대로 앞에, 없으면 순부족 큰 순으로 뒤에
        try:
            return (0, PRIORITY.index(r['z']), 0)
        except ValueError:
            return (1, 0, -abs(r['tot']))
    pool = sorted(rows, key=rank)
    rest = [r for r in pool if r['z'] not in done]
    if not rest:                      # 한 바퀴 완주 → 처음부터
        done, rest = [], pool
    pick = rest[0]
    done.append(pick['z'])
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    io.open(STATE, 'w', encoding='utf-8').write(
        json.dumps({'done': done}, ensure_ascii=False))
    return pick, len(done), len(pool)


# ---------------------------------------------------------- 로테이션·해석 자리
# 해석은 기계가 못 쓴다. 이 자리를 비워 둔 채 발행하면 시세 숫자만 나열한 글이
# 되어 블로그 톤(분석)에서 떨어진다. 눈에 띄라고 대괄호로 남긴다.
INTERP_PLACEHOLDER = (
    '[이번 주 데이터에서 눈에 띈 것을 2~4문장으로. 위 표의 숫자를 다시 읊지 말고 '
    '왜 그런지, 무엇을 시사하는지 쓸 것. 예: 특정 지역만 튀는 이유, 매매-전세 '
    '방향이 갈리는 곳, 몇 주째 이어지는 흐름.]')

# ⑤ 더 보기 — 4주에 걸쳐 사이트의 다른 코너를 하나씩 소개한다.
MORE_ROTATION = [
    dict(h='이번 주 시세를 지도로 보려면',
         desc='187개 시군구와 서울 25개 구의 매매·전세 변동률을 지도 한 장으로 볼 수 있습니다. 상승은 빨강, 하락은 파랑입니다.',
         path='/weekly/', label='주간 시세 지도 보기'),
    dict(h='우리 동네 공급은 어떤가',
         desc='시도별로 앞으로 3년간 들어올 물량과 필요한 양을 비교한 리포트가 있습니다. 지역을 골라 들어가 보세요.',
         path='/zone/', label='전국 시도 공급 순위'),
    dict(h='집값은 왜 도는가',
         desc='공급 → 전세 → 매매 → 다시 공급으로 이어지는 순환의 6개 고리를, 15개 시도 20년 데이터로 검증한 리포트입니다.',
         path='/cycle/', label='「집값은 돌고 돈다」 읽기'),
    dict(h='내 부동산 감각은 몇 점일까',
         desc='10문항 3분이면 끝나는 테스트입니다. 문항마다 국가 통계에 근거한 해설이 붙습니다.',
         path='/burini-test/', label='부린이 테스트 풀어보기'),
]


def rot_index(p):
    """발표주차 기준 4주 로테이션 인덱스. 날짜에서 뽑으므로 상태 파일이 필요 없고,
    주간 발행을 건너뛰어도 순서가 어긋나지 않는다."""
    y, m, d = (int(x) for x in p.split('-'))
    return (datetime.date(y, m, d).isocalendar()[1] - 1) % 4


def _series_last(sts, key, region='전국'):
    """(최신값, 직전값, 기준월) — 데이터가 없으면 (None, None, None)."""
    d = sts.get(key) or {}
    s = (d.get('series') or {}).get(region) or []
    dates = d.get('dates') or []
    vals = [v for v in s if v is not None]
    if len(vals) < 2 or not dates:
        return None, None, None
    return vals[-1], vals[-2], dates[len(s) - 1] if len(dates) >= len(s) else dates[-1]


def extra_section(adv, sts, rot):
    """④ 이번 주의 다른 지표 — 4주 로테이션. 데이터가 없으면 섹션째 생략한다."""
    if rot == 0:
        cur, prv, when = _series_last(sts, '전세가율')
        if cur is None:
            return ''
        mv = '올랐습니다' if cur > prv else ('내렸습니다' if cur < prv else '보합입니다')
        return ('<h3>이번 주의 지표 — 전세가율</h3>'
                '<p>전국 전세가율은 <b>%.1f%%</b>입니다(%s 기준, 전월 %.1f%%에서 %s). '
                '매매가 대비 전세가의 비율로, 높아질수록 사는 값과 빌리는 값의 차이가 '
                '좁아져 매매 전환 압력이 커집니다.</p>' % (cur, when, prv, mv))
    if rot == 1:
        cur, prv, when = _series_last(sts, '미분양')
        if cur is None:
            return ''
        diff = cur - prv
        mv = ('%s호 늘었습니다' % num(diff)) if diff > 0 else (
             ('%s호 줄었습니다' % num(-diff)) if diff < 0 else '변동이 없습니다')
        return ('<h3>이번 주의 지표 — 미분양</h3>'
                '<p>전국 미분양은 <b>%s호</b>입니다(%s 기준, 전월 대비 %s). '
                '미분양은 공급이 수요를 넘어선 흔적이라, 쌓이면 그 지역 분양가와 '
                '입주장 전세가에 먼저 반영됩니다.</p>' % (num(cur), when, mv))
    if rot == 2:
        B = adv.get('bubble') or {}
        conv = (B.get('conv') or {}).get('전국')
        loan = (B.get('loan') or {}).get('v')
        if conv is None or loan is None:
            return ''
        gap = conv - loan
        judge = ('월세로 사는 비용이 대출 이자보다 비싼 상태' if gap > 0
                 else '대출 이자가 월세보다 비싼 상태')
        return ('<h3>이번 주의 지표 — 월세수익률 vs 대출금리</h3>'
                '<p>전국 월세수익률(전세가율 × 전월세전환율)은 연 <b>%.2f%%</b>, '
                '주택담보대출 금리는 <b>%.2f%%</b>입니다. 지금은 %s입니다. '
                '어차피 어딘가에는 살아야 하므로, 이 차이는 실거주 매수를 '
                '검토할지 판단하는 출발점이 됩니다.</p>' % (conv, loan, judge))
    # ⚠️ ADV.aged30은 쓰지 않는다 — 2026-08-06 시도 재편 전의 생활권 키('서울권',
    # '경기남부권' …)가 그대로 남아 있어서, 사이트엔 없는 지역명이 블로그로 나간다
    # (2026-08-11 실측으로 확인). STATS['노후주택30년']이 시도 키로 살아 있다.
    N = sts.get('노후주택30년') or {}
    ser = N.get('series') or {}
    dates = N.get('dates') or []
    pairs = []
    for k, v in ser.items():
        if k in SZ.AGG:          # 전국·수도권·지방 집계는 순위에서 뺀다
            continue
        vals = [x for x in (v or []) if x is not None]
        if vals:
            pairs.append((k, vals[-1]))
    if not pairs:
        return ''
    tops = sorted(pairs, key=lambda x: -x[1])[:3]
    return ('<h3>이번 주의 지표 — 30년 넘은 아파트</h3>'
            '<p>준공 30년이 지난 아파트가 가장 많은 곳은 %s입니다(%s년 기준). '
            '노후 재고는 재건축·재개발 압력이자 앞으로 헐릴 집이기도 해서, '
            '많이 쌓인 지역일수록 실제 공급이 통계보다 빠듯해질 수 있습니다.</p>'
            % (' · '.join('<b>%s %s호</b>' % (esc(k), num(v)) for k, v in tops),
               (dates[-1] if dates else '')))


# ---------------------------------------------------------------- 초안 ①
def draft_weekly(adv, sts, rows):
    W = adv['weekly']
    p = W['rows'][-1]['p']
    rot = rot_index(p)
    extra_html = extra_section(adv, sts, rot)
    more = MORE_ROTATION[rot]
    reg, last = W['regions'], W['rows'][-1]
    prev = W['rows'][-2] if len(W['rows']) > 1 else None
    val = dict(zip(reg, zip(last['ma'], last['je'])))

    def g(name, i=0):
        return val.get(name, (None, None))[i]

    seoul = g('서울'), g('서울', 1)
    nat = g('전국'), g('전국', 1)

    # 시도만 추려 상승·하락 정렬(전국·수도권·지방 같은 집계 항목 제외)
    AGG = {'전국', '수도권', '지방'}
    sido = [(k, v[0]) for k, v in val.items() if k not in AGG and v[0] is not None]
    up = sorted(sido, key=lambda x: -x[1])[:3]
    dn = sorted(sido, key=lambda x: x[1])[:3]

    # 서울 구별
    gu = []
    S = W.get('seoul') or {}
    if S.get('rows'):
        sr = S['rows'][-1]
        gu = sorted(zip(S['regions'], sr['ma']), key=lambda x: -(x[1] or -9))[:3]

    ymd = p.split('-')
    # 검색어를 맨 앞에 둔다. 2026-08-14 네이버 검색 실측에서 이 자리를 차지한
    # 블로그 글이 '한국부동산원 주간동향｜8월 1주 전국 아파트 시세 분석' 형태였고,
    # 웹문서 1위도 부동산원 공식 '주간아파트가격동향'이다. 출처명이 검색어로
    # 같이 쓰인다는 뜻이라, 본문에만 있던 '한국부동산원'을 제목으로 끌어올렸다.
    title = '주간 아파트 시세 %s년 %s월 %s주 | 한국부동산원 기준, 서울 %s 전국 %s' % (
        ymd[0], int(ymd[1]), (int(ymd[2]) - 1) // 7 + 1, pct(seoul[0]), pct(nat[0]))

    # 아공맵 상위 — 사이트 표준 순서를 그대로 쓴다.
    # ⚠️ tot(절대 세대수)만으로 정렬하면 안 된다. 등급은 '필요량 대비 비율'로 매기므로
    # 덩치 큰 곳이 1위인데 판정은 '균형'으로 찍히는 모순이 난다(2026-08-02 실측).
    # SZ.zone_order()가 홈·허브·지역 페이지가 공유하는 유일한 순서이고,
    # 집계 3종(전국·수도권·지방)은 그 안에서 이미 빠진다.
    units = SZ.zone_order(rows)
    top = units[:5]
    sido_count = len(units)         # 개별 시도 수(집계 제외)

    rowsHtml = ''
    for k in ['전국', '수도권', '서울', '경기', '인천', '부산', '대구', '대전', '광주', '울산']:
        if k not in val:
            continue
        m, j = val[k]
        if m is None:
            continue
        rowsHtml += ('<tr><td>%s</td><td style="text-align:right">%s</td>'
                     '<td style="text-align:right">%s</td></tr>') % (k, pct(m), pct(j))

    # 순위·판정만 싣는다(세대수 제외). 판정 라벨은 하드코딩하지 않고 GRADE_LABS를
    # 읽는다 — 등급 체계가 바뀌어도 초안이 따라간다.
    topHtml = ''
    for i, r in enumerate(top, 1):
        topHtml += ('<tr><td>%d위</td><td>%s</td><td>%s</td></tr>'
                    % (i, esc(r['z']), SZ.GRADE_LABS[r['grade']]))

    lead = ('한국부동산원이 발표한 <b>%s 기준</b> 주간 아파트 가격 동향입니다. '
            '전국 매매가는 전주 대비 <b>%s</b>, 서울은 <b>%s</b> 움직였습니다.'
            ) % (kdate(p), pct(nat[0]), pct(seoul[0]))

    body = []
    body.append('<p>%s</p>' % lead)
    body.append('<h3>주요 지역 변동률</h3>')
    body.append('<p>전주 대비 아파트 매매·전세 변동률입니다.</p>')
    body.append('<table border="1" cellspacing="0" cellpadding="6"><thead>'
                '<tr><th>지역</th><th>매매</th><th>전세</th></tr></thead>'
                '<tbody>%s</tbody></table>' % rowsHtml)
    body.append('<p>이번 주 가장 많이 오른 곳은 %s입니다. 반대로 %s는 내렸습니다.</p>' % (
        ' · '.join('<b>%s %s</b>' % (k, pct(v)) for k, v in up),
        ' · '.join('%s %s' % (k, pct(v)) for k, v in dn)))
    if gu:
        body.append('<p>서울 안에서는 %s 순으로 올랐습니다.</p>' %
                    ' · '.join('<b>%s %s</b>' % (k, pct(v)) for k, v in gu))
    body.append('<p>[여기에 시세 지도 이미지를 넣어 주세요]</p>')

    # ── ② 해석 자리. 기계가 채울 수 없는 부분이라 비워 두고, 재료(위 표·순위)만
    # 앞에 깔아 둔다. 블로그 이웃들이 기대하는 건 숫자 나열이 아니라 해석이므로
    # 이 자리를 비운 채 발행하면 안 된다.
    body.append('<h3>이번 주 눈에 띈 것</h3>')
    body.append('<p>%s</p>' % INTERP_PLACEHOLDER)

    # ── ③ 공급. 절대 세대수는 싣지 않는다 — 공급 모델이 갱신되면 숫자가 움직이는데
    # 블로그 글은 박제되기 때문이다. 순위와 등급은 훨씬 덜 흔들린다.
    body.append('<h3>공급으로 보면 어떤가 — 아공맵</h3>')
    body.append('<p>주간 시세가 지금의 온도라면, 공급은 앞으로의 방향입니다. '
                '착공한 아파트가 입주까지 <b>%d년</b>쯤 걸리기 때문에, '
                '앞으로 %d년의 공급은 이미 삽을 뜬 현장으로 정해져 있습니다.</p>'
                % (SZ.LEAD_Q // 4, SZ.LEAD_Q // 4))
    body.append('<p>전국 <b>%d개 시도</b>를 각자의 적정 공급량과 견줘, 재고가 얼마나 '
                '쌓였는지 본 순위입니다. 순위는 세대수 절대량이 아니라 '
                '<b>필요량 대비 부족 비율</b>로 매깁니다.</p>' % sido_count)
    body.append('<table border="1" cellspacing="0" cellpadding="6"><thead>'
                '<tr><th>순위</th><th>지역</th><th>판정</th></tr></thead>'
                '<tbody>%s</tbody></table>' % topHtml)
    lead_z = top[0]
    body.append('<p><b>%s</b>%s 가장 모자란 곳으로 나왔습니다.</p>'
                % (esc(lead_z['z']), iga(lead_z['z'])))
    # 1위가 미분양 경고를 달고 있으면 '가격을 밀어올린다'고 쓰면 안 된다.
    # 사이트 지역 페이지는 같은 자리에서 정반대를 경고하고 있다(제주: 부족 1위인데
    # 미분양이 분기 적정물량의 2.4배). 블로그만 반대로 말하면 신뢰가 무너진다
    # — 우리가 파는 게 계산법의 투명성이기 때문이다(2026-08-14 사용자 지적).
    if lead_z.get('uwarn'):
        body.append('<p>⚠ %s</p>' % M.unsold_warn(lead_z))
    else:
        body.append('<p>공급 부족이 곧 가격 상승을 뜻하지는 않지만, '
                    '금리·수요와 함께 가격을 밀어올리는 힘 가운데 하나입니다.</p>')

    # ── ④ 다른 지표(4주 로테이션). 매주 같은 각도만 보여주면 사이트의 폭이 안 드러난다.
    if extra_html:
        body.append(extra_html)

    # ── ⑤ 더 보기(4주 로테이션). 매번 같은 링크를 붙이면 무시당하므로 4주에 걸쳐
    # 사이트의 다른 코너를 하나씩 소개한다.
    body.append('<h3>%s</h3>' % more['h'])
    body.append('<p>%s<br>👉 <a href="%s%s%s">%s</a></p>' % (
        more['desc'], SITE, more['path'],
        '?utm_source=naver_blog&amp;utm_medium=social&amp;utm_campaign=weekly',
        more['label']))
    body.append('<p><i>※ 이 글은 한국부동산원·국토교통부·KOSIS·한국은행 공개 데이터를 '
                '가공한 것으로, 특정 지역의 매수·매도를 권유하지 않습니다.</i></p>')

    tags = ['아파트시세', '주간아파트시세', '부동산시세', '집값전망', '서울아파트',
            '아파트매매', '전세시세', '부동산데이터', '아파트공급', '입주물량',
            '내집마련', '부동산공부', '아공맵']
    return dict(title=title, body='\n'.join(body), tags=tags, kw='주간 아파트 시세',
                img=r'share\weekly-map.png', imgnote='본문의 [여기에 시세 지도] 자리')


# ---------------------------------------------------------------- 초안 ②
def draft_zone(adv, r, seq, total, total_zones):
    nm = r['z']
    t = r['tot']
    lack = t >= 0
    # '과잉하다'는 동사가 아니라 '얼마나 과잉할까'가 안 된다. 부족/과잉을
    # 대칭 서술어(모자라다/남다)로 갈라 쓴다.
    ask = '모자랄까' if lack else '남을까'
    state = '모자란' if lack else '남아도는'
    yrs = SZ.LEAD_Q // 4

    # '수급'은 우리가 쓰는 말이지 검색되는 말이 아니다. 2026-08-14 실측에서
    # 이 주제의 상위 글은 전부 '연도 + 지역 + 아파트 공급물량 + 전망' 형태였다
    # (1위 '2026년 부산 아파트 공급물량과 향후 부동산 시장 전망은').
    # '입주물량'이 검색량은 더 크지만 그건 분양 확정분을 뜻하는 말이라,
    # 착공 실적으로 추정하는 우리 숫자에 붙이면 기대와 다른 글이 된다.
    yr = (adv.get('weekly', {}).get('rows') or [{}])[-1].get('p', '')[:4]
    title = '%s%s 아파트 공급물량 전망 | 앞으로 %d년 얼마나 %s' % (
        (yr + '년 ') if yr else '', nm, yrs, ask)

    body = []
    body.append('<p>전국 <b>%d개 시도</b>의 아파트 수급을 같은 기준으로 보고 있습니다. '
                '이번에는 <b>%s</b> 차례입니다.</p>' % (total_zones, esc(nm)))
    body.append('<p>시도 단위로 보는 이유가 있습니다. 국토교통부 통계가 시도 경계로 '
                '나오기 때문에, 화면의 숫자를 원자료와 그대로 맞춰볼 수 있습니다. '
                '대신 시도 안에서도 시군구별 사정은 갈립니다.</p>')

    body.append('<h3>결론부터</h3>')
    body.append('<p>이 지역의 적정 공급량과 견주면, %s은 현재 '
                '<b>%s세대가 %s</b> 상태입니다. 판정은 <b>%s</b>입니다.</p>' % (
                    esc(nm), num(abs(t)), state, SZ.GRADE_LABS[r['grade']]))

    # ⚠️ 2026-08-06 시도 재편 반영. 폐기된 것: 3구간 가중평균(55/35/10),
    # 인허가 기반 미래 공급, 생활권 단위. 지금은 착공 실적을 LEAD_Q만큼 미래로
    # 밀어 미래 공급을 세고, 과거는 준공-멸실-적정을 재고처럼 굴린다.
    # 사이트 지역 페이지의 '어떻게 계산했나'와 같은 말을 해야 한다.
    body.append('<h3>어떻게 계산했나</h3>')
    body.append('<p><b>적정물량</b>은 인구로 나눈 추정치가 아닙니다. 과거 이 지역의 '
                '가격이 하락에서 상승으로 방향을 바꾼 시점의 입주물량을 실측해 잡은 '
                '기준선입니다. 그만큼 들어오면 시장이 돌아섰다는 뜻이니까요.</p>')
    body.append('<p>앞으로의 공급은 <b>인허가가 아니라 착공</b>으로 셉니다. 인허가는 '
                '삽을 안 뜬 계획이 섞여 실제보다 1.3~1.7배 부풀기 때문입니다. '
                '실제로 2028년 입주예정으로 잡히던 물량 가운데 착공이 하나도 없는 '
                '경우가 있었습니다. 착공한 현장이 입주까지 <b>%d년</b>쯤 걸리므로, '
                '그만큼 미래로 밀어 앞으로 %d년 몫을 셉니다.</p>' % (yrs, yrs))
    body.append('<p>과거는 <b>준공(입주 완료)</b>에서 철거(멸실)를 빼고 적정선과 '
                '견줍니다. 덜 들어온 분기는 부족분이 남고 더 들어온 분기는 그 부족분을 '
                '메웁니다. 이렇게 <b>재고처럼 굴린 누적치</b>가 순부족입니다.</p>')
    body.append('<p>부족을 재고로 보는 이유가 있습니다. 오랫동안 모자랐던 지역은 '
                '1년치 물량이 한꺼번에 쏟아져도 그동안 밀린 몫까지 다 메우지는 '
                '못하기 때문입니다.</p>')

    # 미분양은 순위 산식에 넣지 않는다(결과값이라 부호가 반대·이중계상). 다만
    # "부족하다는데 미분양이 쌓였다"는 오해가 크므로 표시용으로 덧붙인다.
    # 부족 판정 + 미분양 과다가 겹치는 곳이 실제로 있다(대구: 미분양이 쌓여
    # 착공이 멈춘 결과라 앞으로 지을 게 없다는 뜻).
    if r.get('unsold'):
        body.append('<h3>미분양은 어떤가</h3>')
        if r.get('uwarn'):
            body.append('<p>%s의 미분양은 <b>%s호</b>로 적정 물량 대비 높은 편입니다. '
                        '부족 판정과 어긋나 보이지만 모순이 아닙니다 — 미분양이 쌓이면 '
                        '건설사가 착공을 멈추고, 그래서 <b>앞으로 지을 물량이 줄어듭니다.</b> '
                        '지금 남는 것과 3년 뒤 모자라는 것은 다른 이야기입니다.</p>'
                        % (esc(nm), num(r['unsold'])))
        else:
            body.append('<p>%s의 미분양은 <b>%s호</b>입니다. 미분양은 공급이 수요를 '
                        '넘어선 흔적이라, 쌓이면 분양가와 입주장 전세가에 먼저 '
                        '반영됩니다.</p>' % (esc(nm), num(r['unsold'])))

    body.append('<h3>이 숫자의 한계</h3>')
    body.append('<p><b>앞으로 헐릴 집은 빼지 않았습니다.</b> 지난 몫에서는 철거(멸실)를 '
                '반영했지만, 앞으로 %d년 몫에는 넣지 않았습니다. 재건축이 언제 얼마나 '
                '진행될지 미리 알 방법이 없어서입니다. 그만큼 이 지표는 부족을 '
                '<b>덜</b> 잡습니다 — 노후 아파트가 많은 지역일수록 그렇습니다.</p>' % yrs)
    # ⚠️ est(적정물량 추정치) 안내는 넣지 않는다. "값이 좀 부정확할 수 있다"는
    # 방법론 얘기라 화면에 싣지 않기로 한 사용자 결정(2026-08-08)이 있고, 실제로
    # 사이트엔 est 문구도 * 표시도 없다. 블로그만 "사이트에 * 표시가 있다"고 하면
    # 독자가 없는 걸 찾게 된다(2026-08-13 실측으로 확인).
    # 대신 사이트가 실제로 공시하는 것 — "이 지역은 지표 자체를 다르게 읽어야
    # 한다"는 모델 한계 — 는 그대로 옮긴다. 판정을 곧이곧대로 인용하면 안 되는
    # 지역이 있다는 사실은 블로그에서도 숨기면 안 된다.
    # 정본은 make_sido_pages.MODEL_LIMIT_NOTE 하나다 — 여기 사본을 두면 사이트가
    # 문구를 고쳤을 때 블로그만 옛말을 하게 된다. '⚠ ' 접두는 화면용 기호라 뗀다.
    limit = (getattr(M, 'MODEL_LIMIT_NOTE', {}) or {}).get(nm)
    if limit:
        body.append('<p><b>덧붙임</b> — %s</p>' % esc(limit.lstrip('⚠ ')))
    body.append('<p>그리고 <b>가격을 맞히는 지표가 아닙니다.</b> 금리가 크게 움직인 시기엔 '
                '공급의 영향이 거의 보이지 않았습니다. 공급은 가격을 밀어올리는 '
                '여러 힘 가운데 하나일 뿐입니다.</p>')
    body.append('<p>끝으로 화면의 세대수는 <b>절대량</b>이고 등급·순위는 <b>필요량 대비 '
                '비율</b>로 매깁니다. 그래서 세대수가 큰 곳이 순위에서는 뒤일 수 있습니다.</p>')

    body.append('<p>%s의 분기별 물량과 산출 근거 전체는 아래에서 볼 수 있습니다.<br>'
                '👉 <a href="%s/zone/%s/?utm_source=naver_blog&amp;utm_medium=social&amp;utm_campaign=zone_deep">%s 공급 리포트</a></p>'
                % (esc(nm), SITE, quote(nm), esc(nm)))
    body.append('<p><i>※ 한국부동산원·국토교통부·KOSIS·한국은행 공개 데이터를 '
                '가공한 것으로, 특정 지역의 매수·매도를 권유하지 않습니다.</i></p>')

    tags = [nm, nm + '아파트', nm + '부동산', '아파트공급', '입주물량', '아파트착공',
            '부동산데이터', '집값전망', '내집마련', '부동산공부', '아공맵']
    return dict(title=title, body='\n'.join(body), tags=tags, img=None,
                kw='%s 아파트 공급물량' % nm,
                imgnote='이미지 없음 — 필요하면 사이트 리포트 화면을 캡처해 넣으세요',
                seq='%d / %d번째 지역' % (seq, total))


# ---------------------------------------------------------------- 렌더
CSS = """
body{font:15px/1.7 -apple-system,'Segoe UI','Malgun Gothic',sans-serif;
  max-width:820px;margin:0 auto;padding:24px 18px 80px;color:#1d2330;background:#f6f4ee}
h1{font-size:21px;margin:0 0 4px}
.hint{color:#6f6a5c;font-size:13.5px;margin:0 0 24px}
.draft{background:#fff;border:1px solid #dad5c9;border-radius:10px;
  padding:18px;margin:0 0 22px}
.draft>h2{font-size:16px;margin:0 0 14px;padding-bottom:10px;
  border-bottom:2px solid #3d4a8a;color:#3d4a8a}
.field{margin:0 0 16px}
.lab{display:flex;align-items:center;gap:8px;margin:0 0 6px}
.lab b{font-size:12.5px;color:#3d4a8a}
button{font:600 12px/1 inherit;padding:5px 11px;border:1px solid #3d4a8a;
  background:#3d4a8a;color:#fff;border-radius:6px;cursor:pointer}
button.done{background:#1f8a70;border-color:#1f8a70}
.box{border:1px solid #dad5c9;border-radius:7px;padding:12px 14px;background:#fcfbf8;overflow-x:auto}
.box.t{font-weight:700}
.box.g{color:#3d4a8a;font-size:13.5px}
.box table{border-collapse:collapse;margin:10px 0}
.box th,.box td{border:1px solid #cfc9b8;padding:5px 9px;font-size:14px}
.box th{background:#f1eee6}
.box h3{font-size:15.5px;margin:18px 0 6px}
.note{background:#fff8e6;border-left:3px solid #dca214;padding:9px 12px;
  font-size:13px;margin:10px 0 0;border-radius:0 6px 6px 0}
code{background:#f1eee6;padding:1px 5px;border-radius:4px;font-size:12.5px}
.rival{background:#f4f7f4;border:1px solid #d8e2d8;border-radius:6px;
  padding:10px 13px;margin:0 0 12px;font-size:13px}
.rival ol{margin:7px 0 6px;padding-left:20px}
.rival li{margin:3px 0;line-height:1.45}
.src{color:#7b8a7b;font-size:12px}
"""

JS = """
// 클립보드에 '의미'만 싣는다.
//
// 두 가지를 한꺼번에 푼다(둘 다 2026-08-14 사용자 실측):
//  ① 붙여넣으면 문단이 줄줄이 붙는다 — 에디터가 <p> 사이 CSS 여백을 안 가져온다.
//     여백은 스타일이라 살아남지 못하므로, 빈 문단을 실제 노드로 끼운다.
//  ② 붙여넣으면 전부 볼드로 나온다 — 소스는 굵지 않다(실측 font-weight 400).
//     범위 선택 후 execCommand로 복사하면 Chrome이 계산된 스타일을 전부
//     인라인으로 박아 넣고, 스마트에디터가 그 뭉치를 제 방식대로 해석한다.
//     그래서 DOM을 복사시키지 않고 우리가 만든 HTML 문자열을 직접 쓴다.
//     class·id는 지운다(페이지 겉치레). td의 text-align은 우리가 쓴 것이라 남긴다.
function payload(el){
  var c=el.cloneNode(true);
  c.querySelectorAll('*').forEach(function(n){
    n.removeAttribute('class'); n.removeAttribute('id');
  });
  var kids=Array.prototype.slice.call(c.children);
  kids.forEach(function(k,i){
    if(i<kids.length-1){
      var gap=document.createElement('p');
      gap.appendChild(document.createElement('br'));
      c.insertBefore(gap,k.nextSibling);
    }
  });
  c.removeAttribute('class'); c.removeAttribute('id');
  c.style.position='fixed'; c.style.left='-9999px'; c.style.top='0';
  document.body.appendChild(c);
  // innerText는 문서에 붙어 있어야 나온다. 끼워 넣은 빈 문단 탓에 평문 쪽은
  // 빈 줄이 과하게 잡히므로 두 줄로 줄인다(html을 못 받는 편집기용 폴백).
  var out={html:c.innerHTML, text:c.innerText.replace(/\\n{3,}/g,'\\n\\n')};
  document.body.removeChild(c);
  return out;
}
function legacy(el){                              // 클립보드 API가 막힌 경우만
  var r=document.createRange(); r.selectNodeContents(el);
  var s=window.getSelection(); s.removeAllRanges(); s.addRange(r);
  try{document.execCommand('copy');}catch(e){}
  s.removeAllRanges();
}
document.querySelectorAll('button[data-t]').forEach(function(b){
  b.onclick=function(){
    var el=document.getElementById(b.dataset.t);
    var ok=function(){
      b.textContent='\\uBCF5\\uC0AC\\uB428'; b.className='done';
      setTimeout(function(){b.textContent='\\uBCF5\\uC0AC';b.className='';},1500);
    };
    var p=payload(el);
    if(navigator.clipboard&&window.ClipboardItem){
      navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([p.html],{type:'text/html'}),
        'text/plain': new Blob([p.text],{type:'text/plain'})
      })]).then(ok,function(){legacy(el);ok();});
    } else { legacy(el); ok(); }
  };
});
"""


def rivals(keyword, n=5):
    """그 키워드로 지금 상위에 있는 블로그 글 제목을 가져온다.

    제목을 다듬는 순간에 정작 경쟁 글이 안 보인다는 게 지금까지의 병목이었다.
    브라우저를 따로 열어 검색하고 초안으로 돌아오는 왕복이 매주 반복된다.
    같은 화면에 붙여두면 (1) 어떤 각도가 이미 점령됐는지, (2) 우리 제목이
    상위 글과 너무 닮지 않았는지(유사문서)를 한눈에 본다.

    키가 없거나 네트워크가 막히면 조용히 건너뛴다 — 부가 정보 때문에
    초안 생성 자체가 실패하면 주객이 전도된다.
    """
    try:
        import naver_serp as NS
        d = NS._get('blog', keyword, display=n)
        return [(NS._clean(it.get('title', '')), NS._clean(it.get('bloggername', '')))
                for it in (d.get('items') or [])]
    except Exception:
        return None


def rival_panel(keyword):
    rows = rivals(keyword)
    if rows is None:
        return ('<p class="note">🔍 <b>%s</b> 경쟁 글을 못 불러왔습니다. '
                'NAVER_CLIENT_ID/SECRET 환경변수를 확인하세요 '
                '(없어도 초안 자체는 정상입니다).</p>' % esc(keyword))
    if not rows:
        return '<p class="note">🔍 <b>%s</b> 상위 결과 없음.</p>' % esc(keyword)
    li = ''.join('<li>%s <span class="src">%s</span></li>' % (esc(t), esc(b))
                 for t, b in rows)
    return ('<div class="rival"><b>🔍 지금 “%s” 상위 글</b>'
            '<ol>%s</ol>'
            '<span class="src">제목이 이 중 하나와 닮았다면 바꾸세요 — '
            '유사문서로 묶이면 둘 다 손해입니다.</span></div>' % (esc(keyword), li))


def field(lab, tid, html, cls=''):
    return ('<div class="field"><div class="lab"><b>%s</b>'
            '<button data-t="%s">복사</button></div>'
            '<div class="box %s" id="%s">%s</div></div>') % (lab, tid, cls, tid, html)


def render(p, d1, d2):
    S = []
    S.append('<!doctype html><html lang="ko"><meta charset="utf-8">')
    S.append('<title>네이버 블로그 초안 — %s</title>' % p)
    S.append('<style>%s</style>' % CSS)
    S.append('<h1>네이버 블로그 초안 — %s 기준</h1>' % p)
    S.append('<p class="hint">[복사] → 스마트에디터에 붙여넣기 → 이미지 끌어놓기 → 발행. '
             '표·굵은 글씨는 붙여넣을 때 그대로 살아납니다.</p>')

    for i, (head, d) in enumerate([('① 주간 시세 + 아공맵 해설', d1),
                                   ('② 지역 심층 — %s' % d2.get('seq', ''), d2)], 1):
        S.append('<section class="draft"><h2>%s</h2>' % head)
        S.append(rival_panel(d['kw']))
        S.append(field('제목', 't%d' % i, esc(d['title']), 't'))
        S.append(field('본문', 'b%d' % i, d['body']))
        S.append(field('태그 (붙여넣고 쉼표로 구분)', 'g%d' % i,
                       ', '.join(d['tags']), 'g'))
        if d['img']:
            S.append('<p class="note">📎 이미지 <code>%s</code> 를 %s에 끌어다 '
                     '놓으세요. 네이버는 외부 이미지 주소를 그대로 쓰지 않으므로 '
                     '파일을 직접 올려야 합니다.</p>' % (d['img'], d['imgnote']))
        else:
            S.append('<p class="note">📎 %s</p>' % d['imgnote'])
        S.append('</section>')

    S.append('<p class="hint">같은 내용을 사이트·인스타와 똑같이 올리면 네이버가 '
             '유사문서로 볼 수 있습니다. 첫 두세 문장만이라도 직접 고쳐 쓰면 '
             '안전합니다.</p>')
    S.append('<script>%s</script></html>' % JS)
    return '\n'.join(S)


def main():
    adv, sts = M.load()
    # 점수는 배치가 구워 ADV.sido에 실어 둔 것을 그대로 읽는다 — 사이트 화면과
    # 같은 값을 써야 하므로 여기서 다시 계산하지 않는다.
    calc = (adv or {}).get('sido')
    if not calc or not calc.get('zones'):
        raise SystemExit('ADV.sido가 없다 — 배치(update_adv_data.py --seed-sido)를 먼저 돌릴 것')
    rows = calc['zones']
    p = adv['weekly']['rows'][-1]['p']

    d1 = draft_weekly(adv, sts, rows)
    # 심층은 개별 시도만 순회한다(집계 3종 제외).
    pool = SZ.zone_order(rows)
    pick, seq, total = pick_zone(pool)
    d2 = draft_zone(adv, pick, seq, total, len(pool))

    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    path = os.path.join(OUT, 'naver-%s.html' % p)

    # 손댄 초안은 덮지 않는다. drafts/는 gitignore라 덮어쓰면 되돌릴 데가 없다
    # (2026-08-14에 실제로 날렸다 — 트랜스크립트에서 겨우 건졌다).
    # 판별은 해석 자리 표시자의 유무로 한다. 그게 사라졌다면 사람이 채운 것이다.
    if os.path.exists(path) and '--force' not in sys.argv:
        old = io.open(path, encoding='utf-8').read()
        if INTERP_PLACEHOLDER[:20] not in old:
            alt = path[:-5] + '.new.html'
            io.open(alt, 'w', encoding='utf-8', newline='\n').write(render(p, d1, d2))
            print('⚠ %s 는 이미 손댄 흔적이 있어 그대로 뒀다.' % os.path.basename(path))
            print('  새 초안은 %s 에 썼다. 비교 후 필요한 것만 옮길 것.'
                  % os.path.relpath(alt, ROOT))
            print('  덮어쓰려면 --force.')
            return 0

    io.open(path, 'w', encoding='utf-8', newline='\n').write(render(p, d1, d2))
    print('네이버 초안 생성: %s' % os.path.relpath(path, ROOT))
    print('  ① %s' % d1['title'])
    print('  ② %s  (%s)' % (d2['title'], d2['seq']))

    # 바로 연다. 터미널의 경로를 손으로 찾아 여는 왕복이 매주 반복될 이유가 없다.
    # 배치에서 부르는 도구가 아니라 사람이 발행 직전에 돌리는 도구다.
    if '--no-open' not in sys.argv:
        try:
            import webbrowser
            webbrowser.open('file:///' + path.replace('\\', '/'))
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

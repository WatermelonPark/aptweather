# -*- coding: utf-8 -*-
"""네이버 블로그 초안 생성 — drafts/naver-<주차>.html

네이버 블로그는 개인 블로그용 글쓰기 API가 없어 완전 자동화가 불가능하다.
그래서 '붙여넣기만 하면 되는 초안'을 매주 만들어 두는 반자동 방식을 쓴다.

만들어지는 초안 2건:
  ① 주간 시세 + 아공맵 해설  — 속보성, 매주 내용이 바뀐다
  ② 생활권 심층 리포트       — 매주 한 곳씩 순회(모두 돌면 처음부터)

사용법:
  python tools/make_naver_post.py      # drafts/naver-<주차>.html 생성
  브라우저로 열고 → [복사] 버튼 → 스마트에디터에 붙여넣기 → 이미지 끌어놓기 → 발행

drafts/ 는 .gitignore 대상이다(사이트에 공개될 초안이 아니라 로컬 작업물).
"""
import io, os, re, sys, json, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_zone_pages as Z  # noqa: E402  (load/calc/make_capital 재사용)

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


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


# ---------------------------------------------------------------- 순회 상태
def pick_zone(rows):
    """아직 안 다룬 생활권 중 |누적 부족·과잉|이 가장 큰 곳을 고른다.

    한 바퀴 돌면 초기화. 주차 번호로 나머지 연산을 하면 데이터가 바뀔 때
    같은 곳이 연달아 걸릴 수 있어, 다룬 목록을 파일로 남기는 쪽을 택했다.
    """
    done = []
    if os.path.exists(STATE):
        try:
            done = json.load(io.open(STATE, encoding='utf-8')).get('done', [])
        except Exception:
            done = []
    pool = sorted(rows, key=lambda r: -abs(r['tot']))
    rest = [r for r in pool if r['z']['z'] not in done]
    if not rest:                      # 한 바퀴 완주 → 처음부터
        done, rest = [], pool
    pick = rest[0]
    done.append(pick['z']['z'])
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
         desc='생활권별로 앞으로 4년간 들어올 물량과 필요한 양을 비교한 리포트가 있습니다. 지역을 골라 들어가 보세요.',
         path='/zone/', label='전국 생활권 공급 순위'),
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
    A = adv.get('aged30') or {}
    zmap = A.get('z') or {}
    if not zmap:
        return ''
    tops = sorted(zmap.items(), key=lambda x: -x[1])[:3]
    return ('<h3>이번 주의 지표 — 30년 넘은 아파트</h3>'
            '<p>준공 30년이 지난 아파트가 가장 많은 곳은 %s입니다(%s년 기준). '
            '노후 재고는 재건축·재개발 압력이자 앞으로 헐릴 집이기도 해서, '
            '많이 쌓인 지역일수록 실제 공급이 통계보다 빠듯해질 수 있습니다.</p>'
            % (' · '.join('<b>%s %s세대</b>' % (k, num(v)) for k, v in tops),
               A.get('yr', '')))


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
    title = '%s년 %s월 %s주 아파트 시세 | 서울 %s, 전국 %s' % (
        ymd[0], int(ymd[1]), (int(ymd[2]) - 1) // 7 + 1, pct(seoul[0]), pct(nat[0]))

    # 아공맵 상위 — 홈과 같은 범위(수도권 통합)에 사이트 표준 순서를 그대로 쓴다.
    # ⚠️ tot(절대 세대수)만으로 정렬하면 안 된다. 등급은 '필요량 대비 비율'로 매기므로
    # 덩치 큰 수도권이 1위인데 판정은 '균형'으로 찍히는 모순이 난다(2026-08-02 실측).
    # zone_order()가 홈·허브·존 페이지가 공유하는 유일한 순서다.
    cap = Z.make_capital(rows)
    units = Z.zone_order([cap] + [r for r in rows if r['z']['region'] != '수도권'])
    top = units[:5]
    zone_count = len(rows)          # 개별 생활권 수(허브 표기와 동일)
    unit_count = len(units)         # 수도권을 하나로 묶었을 때의 단위 수

    rowsHtml = ''
    for k in ['전국', '수도권', '서울', '경기', '인천', '부산', '대구', '대전', '광주', '울산']:
        if k not in val:
            continue
        m, j = val[k]
        if m is None:
            continue
        rowsHtml += ('<tr><td>%s</td><td style="text-align:right">%s</td>'
                     '<td style="text-align:right">%s</td></tr>') % (k, pct(m), pct(j))

    # 순위·판정만 싣는다(세대수 제외). 판정 라벨은 하드코딩하지 않고 grade()가
    # 돌려준 것을 그대로 쓴다 — 등급 체계가 바뀌어도 초안이 따라간다.
    topHtml = ''
    for i, r in enumerate(top, 1):
        topHtml += ('<tr><td>%d위</td><td>%s</td><td>%s</td></tr>'
                    % (i, r['z']['z'], r['gr']['label']))

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
                '지금 짓고 있는 아파트는 3년쯤 뒤에 입주하기 때문에, '
                '앞으로 4년의 공급은 이미 상당 부분 정해져 있습니다.</p>')
    body.append('<p>전국을 하나의 주택시장처럼 움직이는 <b>생활권 %d곳</b>으로 나눈 뒤, '
                '그 지역의 적정 공급량과 견줘 재고가 얼마나 쌓였는지 본 순위입니다. '
                '(수도권은 한 덩어리로 묶어 %d개 단위로 봅니다. 순위는 세대수 절대량이 '
                '아니라 <b>필요량 대비 부족 비율</b>로 매깁니다.)</p>'
                % (zone_count, unit_count))
    body.append('<table border="1" cellspacing="0" cellpadding="6"><thead>'
                '<tr><th>순위</th><th>생활권</th><th>판정</th></tr></thead>'
                '<tbody>%s</tbody></table>' % topHtml)
    lead_z = top[0]
    body.append('<p><b>%s</b>이 가장 모자란 곳으로 나왔습니다. '
                '공급 부족이 곧 가격 상승을 뜻하지는 않지만, '
                '금리·수요와 함께 가격을 밀어올리는 힘 가운데 하나입니다.</p>'
                % lead_z['z']['z'])

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
    return dict(title=title, body='\n'.join(body), tags=tags,
                img=r'share\weekly-map.png', imgnote='본문의 [여기에 시세 지도] 자리')


# ---------------------------------------------------------------- 초안 ②
def draft_zone(adv, r, seq, total, total_zones):
    z = r['z']
    nm = z['z']
    t = r['tot']
    lack = t >= 0
    # '과잉하다'는 동사가 아니라 '얼마나 과잉할까'가 안 된다. 부족/과잉을
    # 대칭 서술어(모자라다/남다)로 갈라 쓴다.
    ask = '모자랄까' if lack else '남을까'
    state = '모자란' if lack else '남아도는'
    short = '부족' if lack else '과잉'
    # sgg = [[시군구, 입주예정 물량]] — 물량이 0인 시군구는 아예 빠지므로
    # '생활권 구성 목록'이 아니다(목포권엔 무안·영암이 없음). 물량 분포로만 쓴다.
    sgg = [(s[0], s[1]) for s in (z.get('sgg') or [])
           if isinstance(s, (list, tuple)) and len(s) >= 2]

    title = '%s 아파트, 앞으로 얼마나 %s | 준공·입주예정으로 본 수급' % (nm, ask)

    body = []
    body.append('<p>전국을 통근·생활 단위 <b>생활권 %d곳</b>으로 나눠 '
                '아파트 수급을 보고 있습니다. 이번에는 <b>%s</b> 차례입니다.</p>'
                % (total_zones, nm))

    body.append('<p>생활권은 행정구역이 아니라 실제로 출퇴근하고 생활하는 범위로 '
                '묶은 단위입니다. 같은 도라도 차로 두 시간 걸리는 곳은 사실상 '
                '다른 주택시장이기 때문입니다.</p>')
    if sgg:
        top5 = sgg[:5]
        body.append('<h3>입주 물량은 어디에 몰리나</h3>')
        body.append('<p>앞으로 입주가 예정된 <b>%s세대</b>를 시군구별로 보면 '
                    '%s%s.%s</p>' % (
                        num(z.get('supply', 0)),
                        ' · '.join('<b>%s %s세대</b>' % (esc(a), num(b)) for a, b in top5),
                        # 한 곳뿐이면 '순입니다'가 어색하다(순서랄 게 없음)
                        '입니다' if len(top5) == 1 else ' 순입니다',
                        (' (물량이 잡힌 %d곳 중 상위 %d곳)' % (len(sgg), len(top5)))
                        if len(sgg) > len(top5) else ''))

    body.append('<h3>결론부터</h3>')
    body.append('<p>이 지역의 적정 공급량과 견주면, %s은 현재 '
                '<b>%s세대가 %s</b> 상태입니다. 판정은 <b>%s</b>입니다.</p>' % (
                    nm, num(abs(t)), state, r['gr']['label']))

    # ⚠️ 2026-08-02 모델 확정(activate) 반영. 예전의 3구간 가중평균(55/35/10)·
    # 인허가 35% 반영·"앞으로 5분기"는 전부 폐기됐다. 지금은 준공/준공예정 실측을
    # 재고처럼 굴리는 러닝재고 방식이다. 사이트 존 페이지의 '어떻게 계산했나'와
    # 같은 내용을 말해야 한다 — 블로그와 사이트가 다른 산식을 설명하면 신뢰가 깨진다.
    body.append('<h3>어떻게 계산했나</h3>')
    body.append('<p><b>적정물량</b>은 인구로 나눈 추정치가 아닙니다. 과거 이 지역의 '
                '가격이 하락에서 상승으로 방향을 바꾼 시점의 입주물량을 실측해 잡은 '
                '기준선입니다. 그만큼 들어오면 시장이 돌아섰다는 뜻이니까요.</p>')
    body.append('<p>여기에 실제 <b>준공(입주 완료)</b>과 <b>준공예정</b> 물량을 견줍니다. '
                '적정선보다 덜 들어온 해는 부족분이 남고, 더 들어온 해는 그 부족분을 '
                '메웁니다. 이렇게 <b>재고처럼 굴린 누적치</b>가 순부족입니다. '
                '앞으로는 %d분기(%d년) 몫까지 함께 봅니다.</p>' % (
                    Z.FUT_HORIZON, Z.FUT_HORIZON // 4))
    body.append('<p>부족을 재고로 보는 이유가 있습니다. 오랫동안 모자랐던 지역은 '
                '1년치 물량이 한꺼번에 쏟아져도 그동안 밀린 몫까지 다 메우지는 '
                '못하기 때문입니다.</p>')

    if r['flag'] == 'watch':
        body.append('<h3>실거주라면 눈여겨볼 조건</h3>')
        body.append('<p>%s의 임대수익률(전세가율 × 전월세전환율)은 연 <b>%.1f%%</b>로, '
                    '주택담보대출 금리 <b>%.2f%%</b>보다 높습니다. '
                    '쉽게 말해 <b>대출 이자가 이 지역 월세보다 쌉니다.</b></p>' % (
                        r['ps'], r['lo'], r['loan']))
        body.append('<p>어차피 어딘가에는 살아야 합니다. 전세든 월세든 주거비는 '
                    '나가는데, 같은 집에 월세로 사는 비용보다 갚아야 할 이자가 적다면 '
                    '실거주 목적의 매수를 검토해볼 만한 조건입니다.</p>')
        body.append('<p>다만 <b>이자만 비교한 값</b>입니다. 원금 상환, 취득세·재산세·'
                    '수선비 같은 보유 비용, LTV·DSR 한도, 그리고 집값이 내릴 '
                    '가능성은 각자 따로 따져야 합니다.</p>')
    elif r['flag'] == 'warn':
        body.append('<h3>보유 부담은 큰 편</h3>')
        body.append('<p>주택담보대출 금리 <b>%.2f%%</b>가 임대수익률의 두 배(위험선 '
                    '<b>%.1f%%</b>)를 넘었습니다. 대출로 사서 보유하면 이자가 월세로 '
                    '받을 수 있는 돈의 두 배를 넘는다는 뜻입니다. 공급이 모자라더라도 '
                    '진입 시점은 신중히 볼 필요가 있습니다.</p>' % (r['loan'], r['hi']))

    body.append('<h3>이 숫자의 한계</h3>')
    body.append('<p><b>앞으로 헐릴 집은 빼지 않았습니다.</b> 지난 몫에서는 철거(멸실)를 '
                '반영했지만, 앞으로 4년 몫에는 넣지 않았습니다. 재건축이 언제 얼마나 '
                '진행될지 미리 알 방법이 없어서입니다. 그만큼 이 지표는 부족을 '
                '<b>덜</b> 잡습니다 — 노후 아파트가 많은 지역일수록 그렇습니다.</p>')
    body.append('<p>또 <b>가격을 맞히는 지표가 아닙니다.</b> 금리가 크게 움직인 시기엔 '
                '공급의 영향이 거의 보이지 않았습니다. 공급은 가격을 밀어올리는 '
                '여러 힘 가운데 하나일 뿐입니다.</p>')
    body.append('<p>끝으로 화면의 세대수는 <b>절대량</b>이고 등급·순위는 <b>필요량 대비 '
                '비율</b>로 매깁니다. 그래서 세대수가 큰 곳이 순위에서는 뒤일 수 있습니다.</p>')

    body.append('<p>%s의 분기별 물량과 산출 근거 전체는 아래에서 볼 수 있습니다.<br>'
                '👉 <a href="%s/zone/%s/?utm_source=naver_blog&amp;utm_medium=social&amp;utm_campaign=zone_deep">%s 생활권 리포트</a></p>' % (
                    nm, SITE, nm, nm))
    body.append('<p><i>※ 한국부동산원·국토교통부·KOSIS·한국은행 공개 데이터를 '
                '가공한 것으로, 특정 지역의 매수·매도를 권유하지 않습니다.</i></p>')

    tags = [nm, nm.replace('권', '') + '아파트', '아파트공급', '입주물량', '아파트인허가',
            '부동산데이터', '집값전망', '내집마련', '부동산공부', '아공맵']
    return dict(title=title, body='\n'.join(body), tags=tags, img=None,
                imgnote='이미지 없음 — 필요하면 사이트 리포트 화면을 캡처해 넣으세요',
                seq='%d / %d번째 생활권' % (seq, total))


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
"""

JS = """
document.querySelectorAll('button[data-t]').forEach(function(b){
  b.onclick=function(){
    var el=document.getElementById(b.dataset.t);
    var r=document.createRange(); r.selectNodeContents(el);
    var s=window.getSelection(); s.removeAllRanges(); s.addRange(r);
    try{document.execCommand('copy');}catch(e){}
    s.removeAllRanges();
    b.textContent='\\uBCF5\\uC0AC\\uB428'; b.className='done';
    setTimeout(function(){b.textContent='\\uBCF5\\uC0AC';b.className='';},1500);
  };
});
"""


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
                                   ('② 생활권 심층 — %s' % d2.get('seq', ''), d2)], 1):
        S.append('<section class="draft"><h2>%s</h2>' % head)
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
    adv, sts = Z.load()
    rows = Z.calc(adv, sts)
    p = adv['weekly']['rows'][-1]['p']

    d1 = draft_weekly(adv, sts, rows)
    pool = [r for r in rows
            if r['z']['region'] != '수도권' or r['z']['z'] == '서울권']
    pick, seq, total = pick_zone(pool)
    d2 = draft_zone(adv, pick, seq, total, len(rows))

    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    path = os.path.join(OUT, 'naver-%s.html' % p)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(render(p, d1, d2))
    print('네이버 초안 생성: %s' % os.path.relpath(path, ROOT))
    print('  ① %s' % d1['title'])
    print('  ② %s  (%s)' % (d2['title'], d2['seq']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
